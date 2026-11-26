#!/bin/zsh
# Mac mini：每天 13:00（午餐）和 20:10（晚餐）发送美团 + 淘宝闪购推广时段汇总到通知助手。
set -euo pipefail
ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.summer.operation.promo-period-summary"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/xiong-operation/promo-period-summary"
mkdir -p "$LOG_DIR"
/usr/bin/python3 - "$PLIST" "$LABEL" "$ROOT/business-report-dashboard/.venv/bin/python" "$ROOT" "$LOG_DIR" <<'PY'
import plistlib, sys
plist, label, python, root, log = sys.argv[1:]
plistlib.dump({"Label": label, "ProgramArguments": [python, f"{root}/scripts/promo_period_summary.py", "--period", "auto"],
               "WorkingDirectory": root, "StartCalendarInterval": [{"Hour": 13, "Minute": 0}, {"Hour": 20, "Minute": 10}],
               "EnvironmentVariables": {"TZ": "Asia/Shanghai", "PYTHONNOUSERSITE": "1"},
               "StandardOutPath": f"{log}/stdout.log", "StandardErrorPath": f"{log}/stderr.log"}, open(plist, "wb"))
PY
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "已安装：每天 13:00、20:10 推广时段汇总（$LABEL）"
