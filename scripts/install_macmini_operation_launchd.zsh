#!/bin/zsh
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${OPERATION_RUNTIME_ROOT:-${OPERATION_ROOT:-$SOURCE_ROOT}}"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LAUNCHD_LOG_DIR="$HOME/Library/Logs/xiong-operation/launchd"
SCRIPT_DIR="$HOME/Library/Scripts/xiong-operation"
SECRETS_FILE="$HOME/Library/Application Support/xiong-operation/secrets.env"
mkdir -p "$LAUNCH_DIR" "$LAUNCHD_LOG_DIR" "$ROOT/morning-ops/logs" "$SCRIPT_DIR"

# The production runtime is isolated from the Git checkout. Keep the local,
# untracked notification credentials available there so scheduled jobs can
# deliver their results after every reinstall or runtime refresh.
if [ -r "$SOURCE_ROOT/config/ops_notify.json" ]; then
  mkdir -p "$ROOT/config"
  if [[ "$SOURCE_ROOT/config/ops_notify.json" != "$ROOT/config/ops_notify.json" ]]; then
    /bin/cp "$SOURCE_ROOT/config/ops_notify.json" "$ROOT/config/ops_notify.json"
  fi
  /bin/chmod 600 "$ROOT/config/ops_notify.json"
fi

chmod u+rwX,go+rX "$SOURCE_ROOT/morning-ops/上午运营一键采集.command" \
  "$SOURCE_ROOT/morning-ops/我已处理验证码继续.command" \
  "$SOURCE_ROOT/morning-ops/run_morning_ops_if_10am.command" \
  "$SOURCE_ROOT/scripts/run_realtime_order_income.zsh" \
  "$SOURCE_ROOT/scripts/ensure_browser_automation_env.zsh" \
  "$SOURCE_ROOT/scripts/run_evening_budget.zsh" \
  "$SOURCE_ROOT/scripts/run_current_budget.zsh" \
  "$SOURCE_ROOT/scripts/upload_store_inspection_evidence.zsh" \
  "$SOURCE_ROOT/安装实时单量收入采集.command"

cat > "$SCRIPT_DIR/run_realtime_order_income.zsh" <<EOF
#!/bin/zsh
set -uo pipefail

ROOT="${ROOT}"
cd "\$ROOT"
LOG_DIR="\$HOME/Library/Logs/xiong-operation/realtime_order_income"
mkdir -p "\$LOG_DIR"

PYTHON="\$ROOT/business-report-dashboard/.venv/bin/python"
if [ ! -x "\$PYTHON" ]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "\$PYTHON" ]; then
  PYTHON="python3"
fi
export PYTHONUNBUFFERED=1
export PYTHONNOUSERSITE=1
export AI_BUSINESS_CENTER_ENV="production"
export PYTHONPATH="\$ROOT/business-report-dashboard/.venv/lib/python3.12/site-packages\${PYTHONPATH:+:\$PYTHONPATH}"

LOG_FILE="\$LOG_DIR/\$(date +%F).log"
TASK_ID="ops.realtime_order_income"
TASK_STEP="初始化"
TASK_STATE_FINALIZED="false"
FINAL_RC=0
NOTIFY_RUNNER="\$ROOT/scripts/ops_notify.py"

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

python_has_playwright() {
  "\$PYTHON" - <<'PY' >/dev/null 2>&1
import playwright  # noqa: F401
PY
}

ensure_browser_env() {
  local ensure_script="\$ROOT/scripts/ensure_browser_automation_env.zsh"
  if [[ ! -f "\$ensure_script" || ! -x "\$ensure_script" ]]; then
    return 0
  fi
  run_with_timeout "\${REALTIME_DEPENDENCY_CHECK_TIMEOUT_SECONDS:-240}" env OPERATION_ROOT="\$ROOT" /bin/zsh "\$ensure_script"
  local rc=\$?
  if [[ "\$rc" -eq 0 ]]; then
    PYTHON="\$ROOT/business-report-dashboard/.venv/bin/python"
    export PYTHONPATH="\$ROOT/business-report-dashboard/.venv/lib/python3.12/site-packages\${PYTHONPATH:+:\$PYTHONPATH}"
    return 0
  fi
  if python_has_playwright; then
    echo "浏览器自动化依赖检查脚本失败，已用当前 Python 直接确认 Playwright 可用，继续采集。"
    return 0
  fi
  FINAL_RC="\$rc"
  TASK_STEP="浏览器自动化依赖检查"
  record_task_run "\$TASK_ID" failed --message "实时单量收入采集未执行：浏览器自动化环境不可用，Playwright 安装或导入失败。" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode "\$rc" --failure-type "dependency_missing"
  TASK_STATE_FINALIZED="true"
  return "\$rc"
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
else:
    missing = payload.get("missing") or []
    if missing:
        stores = []
        for item in missing[:4]:
            if isinstance(item, dict):
                stores.append(f"{item.get('platform') or '未知平台'}{item.get('store') or ''}")
        if stores:
            parts.append("缺失门店：" + "、".join(stores))
parts.append("已拒绝覆盖 latest.json，保留上一份成功数据。")
print("，".join(parts))
PY
}

notify_realtime_failure_once() {
  local failure_message="\$1"
  local notify_dir="\$ROOT/outputs/realtime_order_income"
  local signature_file="\$notify_dir/last_notify_signature.txt"
  mkdir -p "\$notify_dir"
  local signature=""
  signature="\$(printf "%s" "\$failure_message" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print \$1}')"
  if [[ -f "\$signature_file" && "\$(cat "\$signature_file" 2>/dev/null)" == "\$signature" ]]; then
    echo "实时单量收入采集失败通知已发送过，跳过重复推送。"
    return 0
  fi
  local action="请在 Mac mini 的 Chrome 里查看对应平台页面后，再补跑实时单量采集。"
  if [[ "\$failure_message" == *"登录"* || "\$failure_message" == *"验证码"* || "\$failure_message" == *"身份核实"* || "\$failure_message" == *"滑块"* ]]; then
    action="请在 Mac mini 的 Chrome 里恢复平台登录/验证码后，再补跑实时单量采集。"
  elif [[ "\$failure_message" == *"全部门店"* || "\$failure_message" == *"单店上下文"* ]]; then
    action="请在 Mac mini 的美团后台确认已切到连锁/全部门店视图；如果页面已正常，可直接补跑实时单量采集。"
  fi
  local notice="【实时单量采集失败】\${failure_message} \${action}"
  if run_with_timeout "\${REALTIME_NOTIFY_TIMEOUT_SECONDS:-15}" "\$PYTHON" "\$NOTIFY_RUNNER" "\$notice"; then
    printf "%s" "\$signature" > "\$signature_file"
  else
    echo "实时单量收入采集失败通知发送失败。"
  fi
}

run_followup_step() {
  local step="\$1"
  local seconds="\$2"
  shift 2
  TASK_STEP="\$step"
  record_task_run "\$TASK_ID" running --message "\$TASK_STEP" --step "\$TASK_STEP" --log-path "\$LOG_FILE"
  run_with_timeout "\$seconds" "\$@"
  local rc=\$?
  if [[ "\$rc" -eq 0 ]]; then
    return 0
  fi
  if [[ "\$FINAL_RC" -eq 0 ]]; then
    FINAL_RC="\$rc"
  fi
  record_task_run "\$TASK_ID" failed --message "实时单量收入采集后续步骤失败：\${TASK_STEP}。" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode "\$rc"
  return "\$rc"
}

refresh_final_workbench_state() {
  TASK_STEP="刷新最终工作台状态"
  run_with_timeout "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_realtime_collection_status.py" || true
  run_with_timeout "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_task_health.py" || true
  run_with_timeout "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_workbench_data.py" || true
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
  ensure_browser_env || exit "\$FINAL_RC"
  run_with_timeout "\${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "\$PYTHON" "\$ROOT/scripts/cleanup_chrome_tabs.py" || true
  record_task_run "\$TASK_ID" running --message "实时单量收入采集开始。" --step "\$TASK_STEP" --log-path "\$LOG_FILE"
  TASK_STEP="采集平台实时单量"
  record_task_run "\$TASK_ID" running --message "\$TASK_STEP" --step "\$TASK_STEP" --log-path "\$LOG_FILE"
  COLLECT_RC=0
  run_with_timeout "\${REALTIME_COLLECT_TIMEOUT_SECONDS:-300}" "\$PYTHON" "\$ROOT/scripts/realtime_order_income.py" || COLLECT_RC=\$?
  if [[ "\$COLLECT_RC" -ne 0 && "\${REALTIME_COLLECT_RETRY_ATTEMPTS:-1}" -gt 0 ]]; then
    echo "首次实时采集未通过完整性校验，清理浏览器标签页后自动重试一次。"
    run_with_timeout "\${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "\$PYTHON" "\$ROOT/scripts/cleanup_chrome_tabs.py" || true
    sleep "\${REALTIME_COLLECT_RETRY_DELAY_SECONDS:-5}"
    COLLECT_RC=0
    run_with_timeout "\${REALTIME_COLLECT_TIMEOUT_SECONDS:-300}" "\$PYTHON" "\$ROOT/scripts/realtime_order_income.py" || COLLECT_RC=\$?
  fi
  if [[ "\$COLLECT_RC" -ne 0 ]]; then
    FINAL_RC="\$COLLECT_RC"
    failure_message="\$(latest_failure_message)"
    record_task_run "\$TASK_ID" failed --message "\$failure_message" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode "\$COLLECT_RC"
    notify_realtime_failure_once "\$failure_message"
  fi
  TASK_STEP="清理浏览器标签页"
  run_with_timeout "\${CHROME_TAB_CLEANUP_TIMEOUT_SECONDS:-20}" "\$PYTHON" "\$ROOT/scripts/cleanup_chrome_tabs.py" || true
  run_followup_step "生成实时采集状态" "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_realtime_collection_status.py" || true
  run_followup_step "生成任务健康状态" "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_task_health.py" || true
  run_followup_step "生成工作台数据" "\${REALTIME_BUILD_TIMEOUT_SECONDS:-120}" "\$PYTHON" "\$ROOT/scripts/build_workbench_data.py" || true
  run_followup_step "发布工作台云端数据" "\${REALTIME_DEPLOY_TIMEOUT_SECONDS:-180}" env OPERATION_ROOT="\$ROOT" OPERATION_CLOUD_DEPLOY_MODE=data-only /bin/zsh "\$HOME/Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh" || true
  if [[ "\$COLLECT_RC" -eq 0 && "\$FINAL_RC" -eq 0 ]]; then
    record_task_run "\$TASK_ID" success --message "实时单量收入采集完成。" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode 0
  else
    record_task_run "\$TASK_ID" failed --message "\$(latest_failure_message)" --step "\$TASK_STEP" --log-path "\$LOG_FILE" --returncode "\$FINAL_RC"
  fi
  refresh_final_workbench_state
  run_with_timeout "\${REALTIME_DEPLOY_TIMEOUT_SECONDS:-180}" env OPERATION_ROOT="\$ROOT" OPERATION_CLOUD_DEPLOY_MODE=data-only /bin/zsh "\$HOME/Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh" || true
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
/bin/cp "$SOURCE_ROOT/scripts/deploy_workbench_to_cloud.zsh" "$SCRIPT_DIR/deploy_workbench_to_cloud.zsh"
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
export PYTHONUNBUFFERED=1
export PYTHONNOUSERSITE=1

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

record_morning_task() {
  "\$PYTHON" "\$ROOT/scripts/record_task_run.py" ops.morning_collection "\$@" --log-path "\$LOG_DIR/scheduler.log" || true
}

run_finalize_step() {
  local label="\$1"
  local seconds="\$2"
  shift 2
  echo "[\$(date '+%F %T')] 上午运营收尾补偿：\$label" >> "\$LOG_DIR/scheduler.log"
  run_with_timeout "\$seconds" "\$@" >> "\$LOG_DIR/scheduler.log" 2>&1
}

run_finalize_payload() {
  local deploy_runner="\$HOME/Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh"
  if [ ! -x "\$deploy_runner" ]; then
    deploy_runner="\$ROOT/scripts/deploy_workbench_to_cloud.zsh"
  fi
  run_finalize_step "刷新上午采集状态" "\${MORNING_OPS_FINALIZE_STEP_TIMEOUT_SECONDS:-180}" "\$PYTHON" "\$ROOT/scripts/build_morning_collection_status.py" || return "\$?"
  run_finalize_step "刷新任务健康状态" "\${MORNING_OPS_FINALIZE_STEP_TIMEOUT_SECONDS:-180}" "\$PYTHON" "\$ROOT/scripts/build_task_health.py" || return "\$?"
  run_finalize_step "重建运营总看板数据" "\${MORNING_OPS_FINALIZE_STEP_TIMEOUT_SECONDS:-240}" "\$PYTHON" "\$ROOT/scripts/build_workbench_data.py" || return "\$?"
  run_finalize_step "发布运营总看板 data-only" "\${MORNING_OPS_FINALIZE_DEPLOY_TIMEOUT_SECONDS:-240}" env OPERATION_ROOT="\$ROOT" OPERATION_CLOUD_DEPLOY_MODE=data-only /bin/zsh "\$deploy_runner" || return "\$?"
}

run_timeout_finalize() {
  local original_rc="\$1"
  local finalize_rc=0
  record_morning_task running --message "上午运营主流程超时或被终止，开始轻量收尾补偿。" --step "收尾补偿发布"
  if run_finalize_payload; then
    record_morning_task success --message "上午运营主流程超时或被终止，轻量收尾补偿已完成；未重跑预算、订货或平台提交。" --step "收尾补偿发布" --returncode 0
    run_finalize_payload || finalize_rc="\$?"
  else
    finalize_rc="\$?"
  fi
  if [[ "\$finalize_rc" -ne 0 ]]; then
    record_morning_task failed --message "上午运营主流程超时或被终止，轻量收尾补偿也失败，退出码：\$finalize_rc。" --step "收尾补偿发布" --returncode "\$finalize_rc" --failure-type "publish_failed"
    return "\$finalize_rc"
  fi
  echo "[\$(date '+%F %T')] 上午运营轻量收尾补偿完成，原退出码：\$original_rc" >> "\$LOG_DIR/scheduler.log"
  return 0
}

PYTHON="\$ROOT/business-report-dashboard/.venv/bin/python"
if [ ! -x "\$PYTHON" ]; then
  echo "[\$(date '+%F %T')] 未找到业务 Python venv：\$PYTHON，上午运营采集停止。" >> "\$LOG_DIR/scheduler.log"
  "/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" "\$ROOT/scripts/record_task_run.py" ops.morning_collection failed --message "上午运营未执行：缺少业务 Python venv。" --step "Python 环境检查" --log-path "\$LOG_DIR/scheduler.log" --returncode 127 --failure-type "execution_failed" || true
  exit 127
fi
set +e
run_with_timeout "\${MORNING_OPS_PYTHON_PREFLIGHT_TIMEOUT_SECONDS:-20}" "\$PYTHON" -c "import sys; import playwright; print(sys.executable)" >> "\$LOG_DIR/scheduler.log" 2>&1
rc="\$?"
set -e
if [[ "\$rc" -ne 0 ]]; then
  echo "[\$(date '+%F %T')] 业务 Python 预检失败，上午运营采集停止：\$PYTHON" >> "\$LOG_DIR/scheduler.log"
  "\$PYTHON" "\$ROOT/scripts/record_task_run.py" ops.morning_collection failed --message "上午运营未执行：业务 Python/Playwright 预检失败。" --step "Python 环境检查" --log-path "\$LOG_DIR/scheduler.log" --returncode "\$rc" --failure-type "execution_failed" || true
  exit "\$rc"
fi

echo "[\$(date '+%F %T')] 开始上午运营采集。" >> "\$LOG_DIR/scheduler.log"
set +e
run_with_timeout "\${MORNING_OPS_TOTAL_TIMEOUT_SECONDS:-5400}" "\$PYTHON" "\$ROOT/morning-ops/run_morning_ops.py" >> "\$LOG_DIR/scheduler.log" 2>&1
rc="\$?"
set -e
if [[ "\$rc" -ne 0 ]]; then
  echo "[\$(date '+%F %T')] 上午运营采集异常结束，退出码：\$rc" >> "\$LOG_DIR/scheduler.log"
  if [[ "\$rc" -eq 124 || "\$rc" -eq 143 ]]; then
    record_morning_task failed --message "上午运营一键采集超时或被终止，退出码：\$rc；开始轻量收尾补偿。" --step "launchd 包装器" --returncode "\$rc" --failure-type "timeout"
    if run_timeout_finalize "\$rc"; then
      rc=0
    fi
  else
    record_morning_task failed --message "上午运营一键采集异常结束，退出码：\$rc。" --step "launchd 包装器" --returncode "\$rc"
  fi
fi
echo "[\$(date '+%F %T')] 上午运营采集结束。" >> "\$LOG_DIR/scheduler.log"
exit "\$rc"
EOF
chmod +x "$SCRIPT_DIR/run_morning_ops.zsh"

/bin/cp "$SOURCE_ROOT/scripts/run_current_budget.zsh" "$SCRIPT_DIR/run_current_budget.zsh"
/bin/cp "$SOURCE_ROOT/scripts/run_eleme_automation.zsh" "$SCRIPT_DIR/run_eleme_automation.zsh"
/bin/cp "$SOURCE_ROOT/scripts/ensure_eleme_headquarters_context.py" "$SCRIPT_DIR/ensure_eleme_headquarters_context.py"
/bin/cp "$SOURCE_ROOT/scripts/run_evening_budget.zsh" "$SCRIPT_DIR/run_evening_budget_entry.zsh"
chmod u+rwX,go+rX \
  "$SCRIPT_DIR/run_current_budget.zsh" \
  "$SCRIPT_DIR/run_eleme_automation.zsh" \
  "$SCRIPT_DIR/ensure_eleme_headquarters_context.py" \
  "$SCRIPT_DIR/run_evening_budget_entry.zsh"

NODE_RUNTIME_ROOT="$HOME/Library/Application Support/xiong-operation/node-runtime"
mkdir -p \
  "$NODE_RUNTIME_ROOT/scripts" \
  "$NODE_RUNTIME_ROOT/dianjin-prototype" \
  "$NODE_RUNTIME_ROOT/config" \
  "$NODE_RUNTIME_ROOT/outputs/promo_budget_preview"
/bin/cp "$SOURCE_ROOT/scripts/build_promo_budget_preview.mjs" "$NODE_RUNTIME_ROOT/scripts/build_promo_budget_preview.mjs"
/bin/cp "$SOURCE_ROOT/scripts/promo_budget_resolver.mjs" "$NODE_RUNTIME_ROOT/scripts/promo_budget_resolver.mjs"
/bin/cp "$SOURCE_ROOT/dianjin-prototype/rules.js" "$NODE_RUNTIME_ROOT/dianjin-prototype/rules.js"
/bin/cp "$SOURCE_ROOT/dianjin-prototype/logic.js" "$NODE_RUNTIME_ROOT/dianjin-prototype/logic.js"
/bin/cp "$SOURCE_ROOT/config/promo_budget_overrides.json" "$NODE_RUNTIME_ROOT/config/promo_budget_overrides.json"
/bin/cp "$SOURCE_ROOT/config/direct_meituan_accounts.json" "$NODE_RUNTIME_ROOT/config/direct_meituan_accounts.json"

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
export AI_BUSINESS_CENTER_ENV="production"

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

cat > "$SCRIPT_DIR/run_inventory_warning_daily.zsh" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
SECRETS_FILE="${SECRETS_FILE}"
PYTHON="\$ROOT/business-report-dashboard/.venv/bin/python"
if [[ ! -x "\$PYTHON" ]]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [[ -r "\$SECRETS_FILE" ]]; then
  set -a
  source "\$SECRETS_FILE"
  set +a
fi
cd "\$ROOT"
"\$PYTHON" scripts/send_inventory_warning_daily.py
EOF
chmod +x "$SCRIPT_DIR/run_inventory_warning_daily.zsh"

cat > "$SCRIPT_DIR/run_daily_order_wechat_delivery.zsh" <<EOF
#!/bin/zsh
set -uo pipefail

ROOT="${ROOT}"
SECRETS_FILE="${SECRETS_FILE}"
PYTHON="\$ROOT/business-report-dashboard/.venv/bin/python"
if [[ ! -x "\$PYTHON" ]]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [[ ! -x "\$PYTHON" ]]; then
  PYTHON="python3"
fi
if [[ -r "\$SECRETS_FILE" ]]; then
  set -a
  source "\$SECRETS_FILE"
  set +a
fi

cd "\$ROOT"
LOG_DIR="\$HOME/Library/Logs/xiong-operation/daily_order_wechat_delivery"
mkdir -p "\$LOG_DIR"
LOG_FILE="\$LOG_DIR/\$(date +%F).log"
TARGET="\${DAILY_ORDER_WECHAT_TARGET:-熊小小牛排饭-易代仓仓储配送群}"
OUTPUT_DIR="\${DAILY_ORDER_WECHAT_OUTPUT_DIR:-\$HOME/Desktop/库存管理/出库记录}"
STATE_PATH="\${DAILY_ORDER_WECHAT_STATE_PATH:-\$HOME/HermesPrivate/state/daily_order_hermes_delivery.json}"
DELIVERY_LOG_DIR="\${DAILY_ORDER_WECHAT_LOG_DIR:-\$HOME/HermesPrivate/logs/daily_order_hermes_delivery}"
LATEST="\${DAILY_ORDER_WECHAT_LATEST:-20}"
SENDER_BIN="\${DAILY_ORDER_WECHAT_GUI_BIN:-\$ROOT/inventory-board/scripts/wechat_gui_sender.py}"

{
  echo
  echo "[\$(date '+%F %T')] 日配订单微信群自动投递开始"
  echo "目标群：\$TARGET"
  echo "兜底目录：\$OUTPUT_DIR"
  "\$PYTHON" "\$ROOT/inventory-board/scripts/deliver_order_outputs_with_hermes.py" \
    --sender wechat-gui \
    --wechat-gui-bin "\$SENDER_BIN" \
    --target "\$TARGET" \
    --output-dir "\$OUTPUT_DIR" \
    --state-path "\$STATE_PATH" \
    --log-dir "\$DELIVERY_LOG_DIR" \
    --latest "\$LATEST" \
    --json
  rc=\$?
  if [[ "\$rc" -eq 0 ]]; then
    echo "[\$(date '+%F %T')] 日配订单微信群自动投递完成"
    exit 0
  fi
  echo "[\$(date '+%F %T')] 日配订单微信群自动投递失败，退出码：\$rc"
  if [[ -x "\$PYTHON" && -f "\$ROOT/scripts/ops_notify.py" ]]; then
    "\$PYTHON" "\$ROOT/scripts/ops_notify.py" "【日配订单微信群自动发送失败】
目标群：\$TARGET
兜底目录：\$OUTPUT_DIR
发送日志：\$DELIVERY_LOG_DIR
运行日志：\$LOG_FILE
处理方式：打开 Mac mini 上的兜底目录，手动把未发送的 Excel 发到微信群；系统下次检查会继续重试，成功后才会标记已发送。" || true
  fi
  exit "\$rc"
} >> "\$LOG_FILE" 2>&1
EOF
chmod +x "$SCRIPT_DIR/run_daily_order_wechat_delivery.zsh"

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

write_daily_order_wechat_delivery_plist() {
  local label="com.summer.operation.daily-order-wechat-delivery"
  local runner="$SCRIPT_DIR/run_daily_order_wechat_delivery.zsh"
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
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
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
  echo "已安装：${label} -> 日配订单微信群投递 09:00-20:00 每半小时"
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
  com.summer.operation.inventory-warning-daily \
  com.summer.operation.daily-order-wechat-delivery \
  com.summer.operation.realtime-order-income
do
  /bin/launchctl bootout "gui/$(id -u)" "$LAUNCH_DIR/${old_label}.plist" >/dev/null 2>&1 || true
  rm -f "$LAUNCH_DIR/${old_label}.plist"
done

write_plist "com.summer.operation.morning" 8 0 "$SCRIPT_DIR/run_morning_ops.zsh" "$ROOT"
write_realtime_plist
write_daily_order_wechat_delivery_plist
write_plist "com.summer.operation.inventory-warning-daily" 16 0 "$SCRIPT_DIR/run_inventory_warning_daily.zsh" "$ROOT"
write_plist "com.summer.operation.evening" 16 30 "$SCRIPT_DIR/run_evening_budget.zsh" "$ROOT"

echo
echo "Mac mini 定时任务已安装。"
echo "上午：每天 8:00 一键运营，采集完成后立即提交午餐推广预算"
echo "实时：每天 10:30-13:00 每半小时、13:00-17:00 每小时、17:00-20:00 每半小时"
echo "日配订单微信群：每天 09:00-20:00 每半小时检查最近 20 个订单，失败文件留在 ~/Desktop/库存管理/出库记录"
echo "库存：已改为云端主流程，不再安装 10:10 本地同步"
echo "库存预警：每天 16:00 单独汇总推送一次"
echo "晚间：每天 16:30 推广预算真实提交"
echo "launchd 日志目录：$LAUNCHD_LOG_DIR"
