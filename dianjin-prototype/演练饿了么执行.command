#!/bin/zsh
cd "$(dirname "$0")/.."

NODE="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"

echo "本脚本只做执行演练：会打开弹窗并填目标值，但不会点击确定保存。"
echo

"$NODE" scripts/eleme_dianjin_adapter.mjs execute-preview --file outputs/dianjin_automation/execution_preview_1040.json --limit 1

echo
echo "执行演练结果已保存到 outputs/dianjin_automation/"
read -r "?按回车关闭窗口..."
