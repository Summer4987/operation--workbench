#!/bin/zsh
cd "$(dirname "$0")/.."
/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/eleme_dianjin_adapter.mjs dry-run
echo
echo "试运行文件已生成到 outputs/dianjin_automation。"
read -r "?按回车关闭窗口..."
