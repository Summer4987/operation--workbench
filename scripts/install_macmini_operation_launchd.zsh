#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LAUNCHD_LOG_DIR="$HOME/Library/Logs/xiong-operation/launchd"
SCRIPT_DIR="$HOME/Library/Scripts/xiong-operation"
SECRETS_FILE="$HOME/Library/Application Support/xiong-operation/secrets.env"
mkdir -p "$LAUNCH_DIR" "$LAUNCHD_LOG_DIR" "$ROOT/morning-ops/logs" "$SCRIPT_DIR"

chmod u+rwX,go+rX "$ROOT/morning-ops/上午运营一键采集.command" \
  "$ROOT/morning-ops/我已处理验证码继续.command" \
  "$ROOT/morning-ops/run_morning_ops_if_10am.command" \
  "$ROOT/scripts/run_realtime_order_income.zsh" \
  "$ROOT/scripts/run_evening_budget.zsh" \
  "$ROOT/scripts/run_current_budget.zsh" \
  "$ROOT/scripts/upload_store_inspection_evidence.zsh" \
  "$ROOT/安装实时单量收入采集.command"

cat > "$SCRIPT_DIR/run_realtime_order_income.zsh" <<EOF
#!/bin/zsh
set -uo pipefail

ROOT="${ROOT}"
LOG_DIR="\$HOME/Library/Logs/xiong-operation/realtime_order_income"
mkdir -p "\$LOG_DIR"

PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "\$PYTHON" ]; then
  PYTHON="\$ROOT/business-report-dashboard/.venv/bin/python"
fi
if [ ! -x "\$PYTHON" ]; then
  PYTHON="python3"
fi
export PYTHONPATH="\$ROOT/business-report-dashboard/.venv/lib/python3.12/site-packages\${PYTHONPATH:+:\$PYTHONPATH}"

LOG_FILE="\$LOG_DIR/\$(date +%F).log"
TASK_ID="ops.realtime_order_income"
TASK_STEP="初始化"
TASK_STATE_FINALIZED="false"
FINAL_RC=0

run_with_timeout() {
  local seconds="\$1"
  shift
  "\$@" &
  local child_pid=\$!
  (
    sleep "\$seconds"
    if kill -0 "\$child_pid" 2>/dev/null; then
      echo "步骤超时：\${seconds}s，已终止：\$*"
      pkill -TERM -P "\$child_pid" 2>/dev/null || true
      kill -TERM "\$child_pid" 2>/dev/null || true
      sleep 2
      pkill -KILL -P "\$child_pid" 2>/dev/null || true
      kill -KILL "\$child_pid" 2>/dev/null || true
    fi
  ) &
  local watchdog_pid=\$!
  local exit_status=0
  wait "\$child_pid" || exit_status=\$?
  kill "\$watchdog_pid" 2>/dev/null || true
  wait "\$watchdog_pid" 2>/dev/null || true
  return "\$exit_status"
}

record_task_run() {
  run_with_timeout "\${TASK_STATE_WRITE_TIMEOUT_SECONDS:-10}" "\$PYTHON" "\$ROOT/scripts/record_task_run.py" "\$@" || true
}

latest_failure_message() {
  REALTIME_ROOT="\$ROOT" "\$PYTHON" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["REALTIME_ROOT"]) / "outputs" / "realtime_order_income" / "last_failed.json"
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("实时单量收入采集失败，已保留上一份成功数据。")
    raise SystemExit

summary = payload.get("summary") or {}
parts = [
    f"实时单量收入采集失败：已采集 {summary.get('platform_store_count', 0)} 个平台门店",
    f"缺失 {summary.get('missing_count', 0)} 个",
]
errors = [str(item) for item in payload.get("errors") or [] if item]
if errors:
    parts.append("；".join(errors[:2]))
parts.append("已拒绝覆盖 latest.json，保留上一份成功数据。")
print("，".join(parts))
PY
}

run_followup_step() {
  local step="\$1"
  local seconds="\$2"
  shift 2
  TASK_STEP="\$step"
  record_task_run "\$TASK_ID" running --message "\$TASK_STEP" --step "\$TASK_STEP" --log-path "\$LOG_FILE"
  if run_with_timeout "\$seconds" "\$@"; then
    return 0
  fi
  local rc=\$?
  FINAL_RC="\$rc"
  record_task_run "\$TASK_ID" failed --message "实时单量收入采集后续步骤失败：\${TASK_STEP}。" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode "\$rc"
  return "\$rc"
}

finish_task_state() {
  local rc="\$?"
  if [[ "\$TASK_STATE_FINALIZED" == "true" ]]; then
    return
  fi
  if [[ "\$rc" -eq 0 && "\$FINAL_RC" -eq 0 ]]; then
    record_task_run "\$TASK_ID" success --message "实时单量收入采集完成。" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode 0
  else
    local final_rc="\$rc"
    if [[ "\$FINAL_RC" -ne 0 ]]; then
      final_rc="\$FINAL_RC"
    fi
    record_task_run "\$TASK_ID" failed --message "\$(latest_failure_message)" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode "\$final_rc"
  fi
}
trap finish_task_state EXIT

platform_route_interface() {
  /sbin/route get "\$1" 2>/dev/null | /usr/bin/awk '/interface:/{print \$2; exit}'
}

if [[ "\${ALLOW_VPN_PLATFORM_ROUTE:-0}" != "1" ]]; then
  MEITUAN_IF="\$(platform_route_interface e.waimai.meituan.com || true)"
  ELEME_IF="\$(platform_route_interface melody.shop.ele.me || true)"
  if [[ "\$MEITUAN_IF" == utun* || "\$ELEME_IF" == utun* ]]; then
    {
      echo
      echo "[\$(date '+%F %T')] 实时单量收入采集未执行：检测到平台后台正在走 VPN 隧道。"
      echo "美团路由接口：\${MEITUAN_IF:-unknown}"
      echo "饿了么路由接口：\${ELEME_IF:-unknown}"
      echo "请关闭 VPN，或把 e.waimai.meituan.com、waimaieapp.meituan.com、melody.shop.ele.me 加入直连规则后重跑。"
    } >> "\$LOG_FILE" 2>&1
    TASK_STEP="平台路由检查"
    FINAL_RC=12
    record_task_run "\$TASK_ID" failed --message "实时单量收入采集未执行：检测到平台后台正在走 VPN 隧道。" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode 12 --failure-type "network_route"
    exit 12
  fi
fi

{
  echo
  echo "[\$(date '+%F %T')] 实时单量收入采集开始"
  run_with_timeout "\${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "\$PYTHON" "\$ROOT/scripts/cleanup_chrome_tabs.py" || true
  record_task_run "\$TASK_ID" running --message "实时单量收入采集开始。" --step "\$TASK_STEP" --log-path "\$LOG_FILE"
  TASK_STEP="采集平台实时单量"
  record_task_run "\$TASK_ID" running --message "\$TASK_STEP" --step "\$TASK_STEP" --log-path "\$LOG_FILE"
  if run_with_timeout "\${REALTIME_COLLECT_TIMEOUT_SECONDS:-300}" "\$PYTHON" "\$ROOT/scripts/realtime_order_income.py"; then
    COLLECT_RC=0
  else
    COLLECT_RC=\$?
    FINAL_RC="\$COLLECT_RC"
    record_task_run "\$TASK_ID" failed --message "\$(latest_failure_message)" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode "\$COLLECT_RC"
  fi
  TASK_STEP="清理浏览器标签页"
  run_with_timeout "\${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "\$PYTHON" "\$ROOT/scripts/cleanup_chrome_tabs.py" || true
  run_followup_step "生成实时采集状态" "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_realtime_collection_status.py" || true
  run_followup_step "生成任务健康状态" "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_task_health.py" || true
  run_followup_step "生成工作台数据" "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_workbench_data.py" || true
  run_followup_step "发布工作台云端数据" "\${REALTIME_DEPLOY_TIMEOUT_SECONDS:-180}" /bin/zsh "\$HOME/Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh" || true
  if [[ "\$COLLECT_RC" -eq 0 && "\$FINAL_RC" -eq 0 ]]; then
    record_task_run "\$TASK_ID" success --message "实时单量收入采集完成。" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode 0
  else
    record_task_run "\$TASK_ID" failed --message "\$(latest_failure_message)" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode "\$FINAL_RC"
  fi
  run_with_timeout "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_task_health.py" || true
  run_with_timeout "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_workbench_data.py" || true
  TASK_STATE_FINALIZED="true"
  if [[ "\$FINAL_RC" -eq 0 ]]; then
    echo "[\$(date '+%F %T')] 实时单量收入采集完成"
  else
    echo "[\$(date '+%F %T')] 实时单量收入采集失败，已生成失败状态并保留上一份成功数据"
  fi
} >> "\$LOG_FILE" 2>&1

exit "\$FINAL_RC"
EOF
chmod +x "$SCRIPT_DIR/run_realtime_order_income.zsh"

cat > "$SCRIPT_DIR/deploy_workbench_to_cloud.zsh" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
SERVER="\${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="\${OPERATION_CLOUD_REMOTE_DIR:-/var/www/html/operation-workbench}"
PUBLIC_URL="\${OPERATION_CLOUD_PUBLIC_URL:-http://139.155.148.169/operation-workbench/}"
DEPLOY_MODE="\${OPERATION_CLOUD_DEPLOY_MODE:-ui-data}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
IDENTITY_FILE="\${OPERATION_CLOUD_IDENTITY_FILE:-\$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "\$IDENTITY_FILE" ]]; then
  SSH_OPTS+=(-i "\$IDENTITY_FILE")
fi
PYTHON="\$ROOT/business-report-dashboard/.venv/bin/python"
if [ ! -x "\$PYTHON" ]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "\$PYTHON" ]; then
  PYTHON="python3"
fi

cd "\$ROOT"

"\$PYTHON" scripts/sync_promo_budget_overrides.py
"\$PYTHON" scripts/build_workbench_data.py
STAGE_DIR="\$HOME/Library/Application Support/xiong-operation/deploy"
mkdir -p "\$STAGE_DIR/data"
"\$PYTHON" - <<'PY'
from pathlib import Path

root = Path("${ROOT}")
stage = Path.home() / "Library" / "Application Support" / "xiong-operation" / "deploy"
(stage / "data").mkdir(parents=True, exist_ok=True)

def copy_bytes(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)

for name in ("index.html", "workbench.css", "workbench.js", "workbench-data.js"):
    copy_bytes(root / name, stage / name)
copy_bytes(root / "data" / "realtime-history.json", stage / "data" / "realtime-history.json")
for name in ("index.html", "workbench.css", "workbench.js", "workbench-data.js"):
    (stage / name).chmod(0o644)
(stage / "data" / "realtime-history.json").chmod(0o644)
PY

ssh "\${SSH_OPTS[@]}" "\$SERVER" "sudo mkdir -p '\$REMOTE_DIR' && sudo chown -R \\\$(whoami):\\\$(whoami) '\$REMOTE_DIR' && chmod -R u+rwX '\$REMOTE_DIR'"

if [[ "\$DEPLOY_MODE" == "full" ]]; then
  rsync -az --delete \
    -e "ssh \${SSH_OPTS[*]}" \
    index.html workbench.css workbench.js workbench-data.js PROJECT_TREE.md \
    "\$SERVER:\$REMOTE_DIR/"

  ssh "\${SSH_OPTS[@]}" "\$SERVER" "mkdir -p '\$REMOTE_DIR/business-report-dashboard/data'"
  rsync -az --delete \
    -e "ssh \${SSH_OPTS[*]}" \
    business-report-dashboard/dashboard/ \
    "\$SERVER:\$REMOTE_DIR/business-report-dashboard/"
  rsync -az -e "ssh \${SSH_OPTS[*]}" business-report-dashboard/data/latest.json business-report-dashboard/data/unified_daily.csv business-report-dashboard/data/unified_reviews.csv "\$SERVER:\$REMOTE_DIR/business-report-dashboard/data/"

  rsync -az --delete \
    -e "ssh \${SSH_OPTS[*]}" \
    store-inspection/index.html store-inspection/meituan-budget.html store-inspection/styles.css store-inspection/app.js store-inspection/latest.json store-inspection/latest-data.js \
    store-inspection/budget-editor.html \
    "\$SERVER:\$REMOTE_DIR/store-inspection/"

  rsync -az --delete \
    -e "ssh \${SSH_OPTS[*]}" \
    dianjin-prototype/index.html dianjin-prototype/styles.css dianjin-prototype/app.js dianjin-prototype/logic.js dianjin-prototype/rules.js dianjin-prototype/current_state.js dianjin-prototype/execution_preview.js \
    "\$SERVER:\$REMOTE_DIR/dianjin-prototype/"

  ssh "\${SSH_OPTS[@]}" "\$SERVER" "mkdir -p '\$REMOTE_DIR/outputs/promo_budget_preview'"
  rsync -az -e "ssh \${SSH_OPTS[*]}" outputs/promo_budget_preview/latest.json outputs/promo_budget_preview/latest-data.js "\$SERVER:\$REMOTE_DIR/outputs/promo_budget_preview/"
elif [[ "\$DEPLOY_MODE" == "data-only" ]]; then
  ssh "\${SSH_OPTS[@]}" "\$SERVER" "mkdir -p '\$REMOTE_DIR/data'"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh \${SSH_OPTS[*]}" \
    "\$STAGE_DIR/workbench-data.js" \
    "\$SERVER:\$REMOTE_DIR/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh \${SSH_OPTS[*]}" \
    "\$STAGE_DIR/data/realtime-history.json" \
    "\$SERVER:\$REMOTE_DIR/data/"
  echo "已按 data-only 模式发布，仅更新 workbench-data.js 和 data/realtime-history.json，未同步页面布局文件。"
else
  ssh "\${SSH_OPTS[@]}" "\$SERVER" "mkdir -p '\$REMOTE_DIR/data' '\$REMOTE_DIR/business-report-dashboard/data'"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh \${SSH_OPTS[*]}" \
    "\$STAGE_DIR/index.html" \
    "\$STAGE_DIR/workbench.css" \
    "\$STAGE_DIR/workbench.js" \
    "\$STAGE_DIR/workbench-data.js" \
    "\$SERVER:\$REMOTE_DIR/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh \${SSH_OPTS[*]}" \
    "\$STAGE_DIR/data/realtime-history.json" \
    "\$SERVER:\$REMOTE_DIR/data/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh \${SSH_OPTS[*]}" \
    business-report-dashboard/data/latest.json business-report-dashboard/data/unified_daily.csv business-report-dashboard/data/unified_reviews.csv \
    "\$SERVER:\$REMOTE_DIR/business-report-dashboard/data/"
  rsync -az --delete --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh \${SSH_OPTS[*]}" \
    business-report-dashboard/dashboard/ \
    "\$SERVER:\$REMOTE_DIR/business-report-dashboard/"
  echo "已按 ui-data 模式发布，更新首页 UI、workbench-data.js、实时数据和加盟店日报。"
fi

ssh "\${SSH_OPTS[@]}" "\$SERVER" "find '\$REMOTE_DIR' -type d -exec chmod 755 {} + && find '\$REMOTE_DIR' -type f -exec chmod 644 {} +"

echo "运营总看板已发布：\$PUBLIC_URL"
EOF
chmod +x "$SCRIPT_DIR/deploy_workbench_to_cloud.zsh"

cat > "$SCRIPT_DIR/run_morning_ops.zsh" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
SECRETS_FILE="${SECRETS_FILE}"
cd "\$ROOT"
if [ -r "\$SECRETS_FILE" ]; then
  set -a
  source "\$SECRETS_FILE"
  set +a
fi
LOG_DIR="\$HOME/Library/Logs/xiong-operation/morning"
mkdir -p "\$LOG_DIR"
export MORNING_OPS_LOG_DIR="\$LOG_DIR"
export AI_BUSINESS_CENTER_ENV="production"

now_hhmm="\$(date +%H%M)"
if [ "\$now_hhmm" -lt 800 ] || [ "\$now_hhmm" -gt 1050 ]; then
  echo "[\$(date '+%F %T')] 跳过：当前不在 08:00-10:50 窗口内。" >> "\$LOG_DIR/scheduler.log"
  exit 0
fi

run_with_timeout() {
  local seconds="\$1"
  shift
  "\$@" &
  local child_pid=\$!
  (
    sleep "\$seconds"
    if kill -0 "\$child_pid" 2>/dev/null; then
      echo "[\$(date '+%F %T')] 步骤超时：\${seconds}s，已终止：\$*"
      kill -TERM "\$child_pid" 2>/dev/null || true
      sleep 2
      kill -KILL "\$child_pid" 2>/dev/null || true
    fi
  ) &
  local watchdog_pid=\$!
  local exit_status=0
  wait "\$child_pid" || exit_status=\$?
  kill "\$watchdog_pid" 2>/dev/null || true
  wait "\$watchdog_pid" 2>/dev/null || true
  return "\$exit_status"
}

PYTHON=""
for candidate in \
  "\$ROOT/business-report-dashboard/.venv/bin/python" \
  "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
  "python3"
do
  if command -v "\$candidate" >/dev/null 2>&1 || [ -x "\$candidate" ]; then
    if run_with_timeout "\${MORNING_OPS_PYTHON_PREFLIGHT_TIMEOUT_SECONDS:-30}" "\$candidate" -c "import sys; print(sys.executable)" >> "\$LOG_DIR/scheduler.log" 2>&1; then
      PYTHON="\$candidate"
      break
    fi
    echo "[\$(date '+%F %T')] Python 预检失败，尝试下一个解释器：\$candidate" >> "\$LOG_DIR/scheduler.log"
  fi
done
if [ -z "\$PYTHON" ]; then
  echo "[\$(date '+%F %T')] 未找到可用 Python，上午运营采集停止。" >> "\$LOG_DIR/scheduler.log"
  exit 127
fi

echo "[\$(date '+%F %T')] 开始上午运营采集。" >> "\$LOG_DIR/scheduler.log"
run_with_timeout "\${MORNING_OPS_TOTAL_TIMEOUT_SECONDS:-7200}" "\$PYTHON" "\$ROOT/morning-ops/run_morning_ops.py" >> "\$LOG_DIR/scheduler.log" 2>&1
echo "[\$(date '+%F %T')] 上午运营采集结束。" >> "\$LOG_DIR/scheduler.log"
EOF
chmod +x "$SCRIPT_DIR/run_morning_ops.zsh"

/bin/cp "$ROOT/scripts/run_current_budget.zsh" "$SCRIPT_DIR/run_current_budget.zsh"
/bin/cp "$ROOT/scripts/run_eleme_automation.zsh" "$SCRIPT_DIR/run_eleme_automation.zsh"
/bin/cp "$ROOT/scripts/run_evening_budget.zsh" "$SCRIPT_DIR/run_evening_budget_entry.zsh"
chmod u+rwX,go+rX \
  "$SCRIPT_DIR/run_current_budget.zsh" \
  "$SCRIPT_DIR/run_eleme_automation.zsh" \
  "$SCRIPT_DIR/run_evening_budget_entry.zsh"

NODE_RUNTIME_ROOT="$HOME/Library/Application Support/xiong-operation/node-runtime"
mkdir -p \
  "$NODE_RUNTIME_ROOT/scripts" \
  "$NODE_RUNTIME_ROOT/dianjin-prototype" \
  "$NODE_RUNTIME_ROOT/config" \
  "$NODE_RUNTIME_ROOT/outputs/promo_budget_preview"
/bin/cp "$ROOT/scripts/build_promo_budget_preview.mjs" "$NODE_RUNTIME_ROOT/scripts/build_promo_budget_preview.mjs"
/bin/cp "$ROOT/scripts/promo_budget_resolver.mjs" "$NODE_RUNTIME_ROOT/scripts/promo_budget_resolver.mjs"
/bin/cp "$ROOT/dianjin-prototype/rules.js" "$NODE_RUNTIME_ROOT/dianjin-prototype/rules.js"
/bin/cp "$ROOT/dianjin-prototype/logic.js" "$NODE_RUNTIME_ROOT/dianjin-prototype/logic.js"
/bin/cp "$ROOT/config/promo_budget_overrides.json" "$NODE_RUNTIME_ROOT/config/promo_budget_overrides.json"
/bin/cp "$ROOT/config/direct_meituan_accounts.json" "$NODE_RUNTIME_ROOT/config/direct_meituan_accounts.json"

cat > "$SCRIPT_DIR/run_evening_budget.zsh" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
SECRETS_FILE="${SECRETS_FILE}"
RUNNER="${SCRIPT_DIR}/run_evening_budget_entry.zsh"
CURRENT_RUNNER="${SCRIPT_DIR}/run_current_budget.zsh"
ELEME_RUNNER="${SCRIPT_DIR}/run_eleme_automation.zsh"
DEPLOY_RUNNER="${SCRIPT_DIR}/deploy_workbench_to_cloud.zsh"
LOG_DIR="\$HOME/Library/Logs/xiong-operation/evening_budget"
mkdir -p "\$LOG_DIR"
LOG_FILE="\$LOG_DIR/\$(date +%F).log"
if [ -r "\$SECRETS_FILE" ]; then
  set -a
  source "\$SECRETS_FILE"
  set +a
fi

{
  echo
  echo "[\$(date '+%F %T')] 晚间预算初始化开始"
  if [ ! -r "\$RUNNER" ]; then
    echo "触发失败：预算入口不可读：\$RUNNER"
    exit 127
  fi
  cd "\$ROOT"
  OPERATION_ROOT="\$ROOT" \
  CURRENT_BUDGET_RUNNER="\$CURRENT_RUNNER" \
  ELEME_AUTOMATION_RUNNER="\$ELEME_RUNNER" \
  WORKBENCH_DEPLOY_RUNNER="\$DEPLOY_RUNNER" \
  /bin/zsh "\$RUNNER"
  echo "[\$(date '+%F %T')] 晚间预算初始化完成"
} >> "\$LOG_FILE" 2>&1
EOF
chmod +x "$SCRIPT_DIR/run_evening_budget.zsh"

write_plist() {
  local label="$1"
  local hour="$2"
  local minute="$3"
  local runner="$4"
  local _workdir="$5"
  local plist="$LAUNCH_DIR/${label}.plist"

  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>/bin/zsh '${runner}'</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${hour}</integer>
    <key>Minute</key>
    <integer>${minute}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LAUNCHD_LOG_DIR}/${label}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LAUNCHD_LOG_DIR}/${label}.err.log</string>
</dict>
</plist>
EOF

  /bin/launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$plist"
  /bin/launchctl enable "gui/$(id -u)/${label}" >/dev/null 2>&1 || true
  echo "已安装：${label} -> ${hour}:${minute}"
}

write_realtime_plist() {
  local label="com.summer.operation.realtime-order-income"
  local runner="$SCRIPT_DIR/run_realtime_order_income.zsh"
  local plist="$LAUNCH_DIR/${label}.plist"

  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>/bin/zsh '${runner}'</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>19</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>${LAUNCHD_LOG_DIR}/${label}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LAUNCHD_LOG_DIR}/${label}.err.log</string>
</dict>
</plist>
EOF

  /bin/launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "gui/$(id -u)" "$plist"
  /bin/launchctl enable "gui/$(id -u)/${label}" >/dev/null 2>&1 || true
  echo "已安装：${label} -> 实时采集 10:30-20:00"
}

for old_label in \
  com.xiong.daily-report \
  com.summer.store-inspection.promo-balance \
  com.summer.dianjin.eleme.1030 \
  com.summer.dianjin.eleme.1040 \
  com.summer.dianjin.eleme.1050 \
  com.summer.dianjin.eleme.1100 \
  com.summer.dianjin.eleme.1130 \
  com.summer.dianjin.eleme.1730 \
  com.summer.dianjin.eleme.1630 \
  com.summer.morning-ops \
  com.summer.operation.morning \
  com.summer.operation.lunch-budget \
  com.summer.operation.evening \
  com.summer.operation.inventory-sync \
  com.summer.operation.realtime-order-income
do
  /bin/launchctl bootout "gui/$(id -u)" "$LAUNCH_DIR/${old_label}.plist" >/dev/null 2>&1 || true
  rm -f "$LAUNCH_DIR/${old_label}.plist"
done

write_plist "com.summer.operation.morning" 8 0 "$SCRIPT_DIR/run_morning_ops.zsh" "$ROOT"
write_realtime_plist
write_plist "com.summer.operation.evening" 16 30 "$SCRIPT_DIR/run_evening_budget.zsh" "$ROOT"

echo
echo "Mac mini 定时任务已安装。"
echo "上午：每天 8:00 一键运营，采集完成后立即提交午餐推广预算"
echo "实时：每天 10:30-13:00 每半小时、13:00-17:00 每小时、17:00-20:00 每半小时"
echo "库存：已改为云端主流程，不再安装 10:10 本地同步"
echo "晚间：每天 16:30 推广预算真实提交"
echo "launchd 日志目录：$LAUNCHD_LOG_DIR"
