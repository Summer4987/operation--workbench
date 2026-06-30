#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$ROOT/config/direct_meituan_accounts.json"
ACCOUNT_ID="direct_chaoyangmen"
OPEN_ALL_PAGES=0
PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all-pages)
      OPEN_ALL_PAGES=1
      shift
      ;;
    --account)
      ACCOUNT_ID="$2"
      shift 2
      ;;
    -*)
      echo "未知参数：$1" >&2
      exit 2
      ;;
    *)
      ACCOUNT_ID="$1"
      shift
      ;;
  esac
done

if [[ ! -f "$CONFIG" ]]; then
  echo "缺少直营美团账号配置：$CONFIG" >&2
  exit 2
fi

read_config() {
  "$PYTHON_BIN" - "$CONFIG" "$ACCOUNT_ID" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
account_id = sys.argv[2]
payload = json.loads(config_path.read_text(encoding="utf-8"))
accounts = payload.get("accounts") or []
account = next((item for item in accounts if item.get("id") == account_id), None)
if not account:
    known = ", ".join(item.get("id", "") for item in accounts)
    raise SystemExit(f"没有找到账号 {account_id}。已配置：{known}")
pages = account.get("pages") or {}
urls = [pages.get(key, "") for key in ["home", "daily_report", "reviews", "promo_balance"]]
print(account.get("name", account_id))
print(Path(account.get("profile_dir", "")).expanduser())
print(account.get("debug_port", ""))
for url in urls:
    if url:
        print(url)
PY
}

config_lines=("${(@f)$(read_config)}")
ACCOUNT_NAME="${config_lines[1]}"
PROFILE_DIR="${config_lines[2]}"
DEBUG_PORT="${config_lines[3]}"
if (( OPEN_ALL_PAGES )); then
  URLS=("${config_lines[@]:3}")
else
  URLS=("${config_lines[4]}")
fi

mkdir -p "$PROFILE_DIR"

echo "正在打开直营美团账号：$ACCOUNT_NAME"
echo "登录态目录：$PROFILE_DIR"
echo "动作类型：只打开页面，不下载、不采集、不保存预算。"
if (( OPEN_ALL_PAGES )); then
  echo "打开范围：全部检查页。"
else
  echo "打开范围：首页（减少多标签和验证码触发）。如需全量检查，请加 --all-pages。"
fi
if [[ -n "$DEBUG_PORT" ]]; then
  echo "本地调试端口：$DEBUG_PORT"
fi

chrome_args=(
  --user-data-dir="$PROFILE_DIR"
  --profile-directory=Default
  --no-first-run
  --no-default-browser-check
  --new-window
)

if [[ -n "$DEBUG_PORT" ]]; then
  chrome_args+=(--remote-debugging-port="$DEBUG_PORT")
fi

open -na "Google Chrome" --args \
  "${chrome_args[@]}" \
  "${URLS[@]}"

echo ""
echo "已打开页面，请在 Mac mini 上人工确认："
echo "1. 美团后台首页无需重新登录。"
echo "2. 默认不再一次打开多个业务页，避免旧标签堆积和验证码风险。"
echo "3. 如需检查报表/评价/推广页，运行：scripts/open_direct_meituan_account.zsh $ACCOUNT_ID --all-pages"
