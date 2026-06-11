#!/bin/zsh
cd "$(dirname "$0")/.."

PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

"$PYTHON" business-report-dashboard/chrome_cdp_reports.py start-chrome
/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/eleme_dianjin_adapter.mjs probe-page

echo
echo "页面探测文件已生成到 outputs/dianjin_automation。"
read -r "?按回车关闭窗口..."
