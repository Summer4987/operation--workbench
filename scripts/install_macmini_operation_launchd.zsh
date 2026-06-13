#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$ROOT/outputs/launchd_logs"
SCRIPT_DIR="$HOME/Library/Scripts/xiong-operation"
mkdir -p "$LAUNCH_DIR" "$LOG_DIR" "$ROOT/morning-ops/logs" "$SCRIPT_DIR"

chmod +x "$ROOT/morning-ops/上午运营一键采集.command" \
  "$ROOT/morning-ops/我已处理验证码继续.command" \
  "$ROOT/morning-ops/run_morning_ops_if_10am.command" \
  "$ROOT/scripts/run_realtime_order_income.zsh" \
  "$ROOT/scripts/run_evening_budget.zsh" \
  "$ROOT/scripts/run_current_budget.zsh" \
  "$ROOT/安装实时单量收入采集.command"

cat > "$SCRIPT_DIR/run_realtime_order_income.zsh" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
exec /bin/zsh "\$ROOT/scripts/run_realtime_order_income.zsh"
EOF
chmod +x "$SCRIPT_DIR/run_realtime_order_income.zsh"

cat > "$SCRIPT_DIR/deploy_workbench_to_cloud.zsh" <<EOF
#!/bin/zsh
set -euo pipefail

ROOT="${ROOT}"
SERVER="\${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="\${OPERATION_CLOUD_REMOTE_DIR:-/var/www/html/operation-workbench}"
PUBLIC_URL="\${OPERATION_CLOUD_PUBLIC_URL:-http://139.155.148.169/operation-workbench/}"
DEPLOY_MODE="\${OPERATION_CLOUD_DEPLOY_MODE:-data-only}"
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
import shutil

root = Path("${ROOT}")
stage = Path.home() / "Library" / "Application Support" / "xiong-operation" / "deploy"
(stage / "data").mkdir(parents=True, exist_ok=True)
shutil.copy2(root / "workbench-data.js", stage / "workbench-data.js")
shutil.copy2(root / "data" / "realtime-history.json", stage / "data" / "realtime-history.json")
PY

ssh "\${SSH_OPTS[@]}" "\$SERVER" "sudo mkdir -p '\$REMOTE_DIR' && sudo chown -R \\\$(whoami):\\\$(whoami) '\$REMOTE_DIR' && chmod -R u+rwX '\$REMOTE_DIR'"

if [[ "\$DEPLOY_MODE" == "full" ]]; then
  rsync -az --delete \
    -e "ssh \${SSH_OPTS[*]}" \
    index.html workbench.css workbench.js workbench-data.js PROJECT_TREE.md \
    "\$SERVER:\$REMOTE_DIR/"

  ssh "\${SSH_OPTS[@]}" "\$SERVER" "mkdir -p '\$REMOTE_DIR/business-report-dashboard/data'"
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
else
  ssh "\${SSH_OPTS[@]}" "\$SERVER" "mkdir -p '\$REMOTE_DIR/data'"
  rsync -az \
    -e "ssh \${SSH_OPTS[*]}" \
    "\$STAGE_DIR/workbench-data.js" \
    "\$SERVER:\$REMOTE_DIR/"
  rsync -az \
    -e "ssh \${SSH_OPTS[*]}" \
    "\$STAGE_DIR/data/realtime-history.json" \
    "\$SERVER:\$REMOTE_DIR/data/"
  echo "已按 data-only 模式发布，仅更新 workbench-data.js 和 data/realtime-history.json，未同步页面布局文件。"
fi

ssh "\${SSH_OPTS[@]}" "\$SERVER" "find '\$REMOTE_DIR' -type d -exec chmod 755 {} + && find '\$REMOTE_DIR' -type f -exec chmod 644 {} +"

echo "运营总看板已发布：\$PUBLIC_URL"
EOF
chmod +x "$SCRIPT_DIR/deploy_workbench_to_cloud.zsh"

write_plist() {
  local label="$1"
  local hour="$2"
  local minute="$3"
  local runner="$4"
  local workdir="$5"
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
    <string>cd '${workdir}' &amp;&amp; /bin/zsh '${runner}'</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${workdir}</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${hour}</integer>
    <key>Minute</key>
    <integer>${minute}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/${label}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/${label}.err.log</string>
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
  <string>${ROOT}</string>
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
  <string>${LOG_DIR}/${label}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/${label}.err.log</string>
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
  com.summer.morning-ops \
  com.summer.operation.morning \
  com.summer.operation.evening \
  com.summer.operation.inventory-sync \
  com.summer.operation.realtime-order-income
do
  /bin/launchctl bootout "gui/$(id -u)" "$LAUNCH_DIR/${old_label}.plist" >/dev/null 2>&1 || true
  rm -f "$LAUNCH_DIR/${old_label}.plist"
done

write_plist "com.summer.operation.morning" 9 30 "$ROOT/morning-ops/run_morning_ops_if_10am.command" "$ROOT/morning-ops"
write_realtime_plist
write_plist "com.summer.operation.evening" 17 30 "$ROOT/scripts/run_evening_budget.zsh" "$ROOT"

echo
echo "Mac mini 定时任务已安装。"
echo "上午：每天 9:30 一键运营"
echo "实时：每天 10:30-13:00 每半小时、13:00-17:00 每小时、17:00-20:00 每半小时"
echo "库存：已改为云端主流程，不再安装 10:10 本地同步"
echo "晚间：每天 17:30 推广预算真实提交"
echo "日志目录：$LOG_DIR"
