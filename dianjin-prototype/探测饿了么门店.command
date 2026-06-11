#!/bin/zsh
cd "$(dirname "$0")/.."

STORE="${1:-金融街店}"

PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

"$PYTHON" business-report-dashboard/chrome_cdp_reports.py start-chrome
/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/eleme_dianjin_adapter.mjs probe-store --store "$STORE"

echo
echo "门店探测文件已生成到 outputs/dianjin_automation。默认探测门店：$STORE"
read -r "?按回车关闭窗口..."
