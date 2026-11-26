#!/bin/zsh
# 安装每天 14:30（午晚高峰之间的空闲时段）的美团登录到期检查。只在 Mac mini 生产主机运行。
set -euo pipefail
ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LABEL="com.summer.operation.meituan-login-expiry"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/xiong-operation/meituan-login-expiry"
mkdir -p "$LOG_DIR"
PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
/usr/bin/python3 - "$PLIST" "$LABEL" "$PYTHON" "$ROOT" "$LOG_DIR" <<'PY'
import plistlib, sys
plist, label, python, root, log = sys.argv[1:]
plistlib.dump({"Label": label, "ProgramArguments": [python, f"{root}/scripts/meituan_login_expiry.py"],
               "WorkingDirectory": root, "StartCalendarInterval": {"Hour": 14, "Minute": 30},
               "EnvironmentVariables": {"TZ": "Asia/Shanghai", "PYTHONNOUSERSITE": "1"},
               "StandardOutPath": f"{log}/stdout.log", "StandardErrorPath": f"{log}/stderr.log"}, open(plist, "wb"))
PY
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "已安装：每天 14:30 检查美团登录到期（$LABEL）"
