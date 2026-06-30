#!/bin/zsh
cd "$(dirname "$0")/.."

RUNTIME_DIR="$HOME/dianjin-automation-runtime"
LOG_DIR="$RUNTIME_DIR/outputs/dianjin_automation/logs"
mkdir -p "$LOG_DIR"

LATEST="$(ls -t "$LOG_DIR"/*.log 2>/dev/null | head -1)"
if [[ -z "$LATEST" ]]; then
  echo "还没有自动化运行日志。"
else
  echo "最新日志：$LATEST"
  echo
  tail -120 "$LATEST"
fi

echo
read -r "?按回车关闭窗口..."
