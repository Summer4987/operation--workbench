#!/bin/zsh
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

HOST="${MACMINI_REMOTE_HOST:-macmini-remote}"
ROOT="${MACMINI_REMOTE_ROOT:-$HOME/Documents/operation-workbench-clean}"
NOTIFY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --root)
      ROOT="$2"
      shift 2
      ;;
    --notify)
      NOTIFY=1
      shift
      ;;
    *)
      echo "用法：/bin/zsh scripts/macmini_remote_health_check.zsh [--host macmini-remote] [--root ~/Documents/operation-workbench-clean] [--notify]" >&2
      exit 2
      ;;
  esac
done

ROOT_ESCAPED="${ROOT}"
TMP_OUTPUT="$(mktemp -t macmini-remote-health.XXXXXX)"

{
  echo "== Mac mini 远程维护体检 =="
  echo "入口：${HOST}"
  echo "时间：$(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo

  ssh -o BatchMode=yes -o ConnectTimeout=12 "$HOST" "ROOT='${ROOT_ESCAPED}' /bin/zsh -s" <<'REMOTE'
set -euo pipefail
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

section() {
  echo
  echo "== $1 =="
}

section "主机与网络"
hostname
whoami
date
echo "局域网 IP：$(ipconfig getifaddr en0 2>/dev/null || true)"
echo "外网探测：$(curl -sS --max-time 5 https://ifconfig.me 2>/dev/null || echo unavailable)"

section "电源设置"
pmset -g custom | awk '/AC Power:/,/Battery Power:/' | sed -n '1,40p'

section "反向 SSH 隧道"
if launchctl print "gui/$(id -u)/com.summer.macmini.reverse-ssh-tunnel" >/dev/null 2>&1; then
  echo "launchd：已加载"
else
  echo "launchd：未加载"
fi
if pgrep -af "127.0.0.1:22022:localhost:22" >/dev/null 2>&1; then
  echo "进程：运行中"
else
  echo "进程：未运行"
fi
tail -20 "$HOME/Library/Logs/macmini_reverse_ssh_tunnel.err.log" 2>/dev/null || true

section "生产仓库"
if [[ -d "$ROOT/.git" ]]; then
  cd "$ROOT"
  echo "目录：$ROOT"
  git status --short --branch
  echo "HEAD：$(git rev-parse --short HEAD)"
  echo "分支：$(git rev-parse --abbrev-ref HEAD)"
else
  echo "未找到生产仓库：$ROOT"
fi

section "launchd 生产任务"
for label in \
  com.summer.operation.morning \
  com.summer.operation.realtime-order-income \
  com.summer.operation.evening \
  com.summer.operation.promo-balance-refresh \
  com.summer.operation.agent-task-notifier \
  com.summer.operation.ai-center-guardian
do
  if launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
    state="$(launchctl print "gui/$(id -u)/${label}" 2>/dev/null | awk -F'= ' '/state =/ {print $2; exit}')"
    code="$(launchctl print "gui/$(id -u)/${label}" 2>/dev/null | awk -F'= ' '/last exit code =/ {print $2; exit}')"
    echo "${label}: loaded state=${state:-unknown} last_exit=${code:-unknown}"
  else
    echo "${label}: missing"
  fi
done

section "Chrome 与 CDP"
if pgrep -af "Google Chrome" >/dev/null 2>&1; then
  echo "Chrome：运行中"
else
  echo "Chrome：未运行"
fi
if curl -sS --max-time 3 http://127.0.0.1:9222/json/version >/tmp/macmini-cdp-version.json 2>/dev/null; then
  echo "CDP 9222：可访问"
  cat /tmp/macmini-cdp-version.json
else
  echo "CDP 9222：不可访问"
fi

section "最近任务状态"
if [[ -d "$ROOT" ]]; then
  cd "$ROOT"
  for path in \
    outputs/task_runs/latest.json \
    outputs/agent_mobile_status/latest.json \
    outputs/morning_collection_status/latest.json \
    outputs/daily_focus_status/latest.json \
    store-inspection/meituan-cdp-latest.json \
    data/realtime-history.json
  do
    if [[ -f "$path" ]]; then
      echo "--- $path"
      /usr/bin/python3 - <<PY 2>/dev/null || /usr/bin/head -40 "$path"
import json
from pathlib import Path
p = Path("$path")
data = json.loads(p.read_text(encoding="utf-8"))
print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
PY
    fi
  done
fi

section "磁盘"
/bin/df -h "$HOME" | /usr/bin/sed -n '1,3p'
REMOTE
} | tee "$TMP_OUTPUT"

if (( NOTIFY )); then
  python3 "$(cd "$(dirname "$0")/.." && pwd)/scripts/ops_notify.py" < "$TMP_OUTPUT" || true
fi

echo
echo "体检输出：$TMP_OUTPUT"
