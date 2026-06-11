#!/bin/zsh
cd "$(dirname "$0")/.."

NODE="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"

"$NODE" scripts/eleme_dianjin_adapter.mjs probe-store --store 金融街店
"$NODE" scripts/eleme_dianjin_adapter.mjs probe-store --store 金融街店 --page 2
"$NODE" scripts/eleme_dianjin_adapter.mjs analyze-state-combined --time 10:40 --output outputs/dianjin_automation/current_state_1040_all.json
"$NODE" scripts/export_current_state_for_ui.mjs outputs/dianjin_automation/current_state_1040_all.json
"$NODE" scripts/build_execution_preview.mjs outputs/dianjin_automation/current_state_1040_all.json --time 10:40

echo
echo "当前状态分析已保存：outputs/dianjin_automation/current_state_1040_all.json"
echo "页面状态数据已刷新：dianjin-prototype/current_state.js"
echo "执行预览已生成：outputs/dianjin_automation/execution_preview_1040.json"
echo "执行预览表格已生成：outputs/dianjin_automation/execution_preview_1040.csv"
read -r "?按回车关闭窗口..."
