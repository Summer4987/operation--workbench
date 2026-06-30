#!/bin/zsh
cd "$(dirname "$0")/.."
/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/export_ele_rules_to_json.mjs
echo
echo "规则数据已刷新。可以重新打开 dianjin-prototype/index.html 查看。"
read -r "?按回车关闭窗口..."
