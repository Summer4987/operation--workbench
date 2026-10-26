#!/bin/zsh
set -euo pipefail
SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ROOT="${OPERATION_BUDGET_RUNTIME_ROOT:-$HOME/Library/Application Support/xiong-operation/node-runtime}"
if [[ "${1:-}" == --trial-code-only ]]; then
  for relative in scripts/build_promo_budget_preview.mjs scripts/fleet-budget-trial.mjs; do
    /bin/mkdir -p "$RUNTIME_ROOT/${relative:h}"
    /bin/cp "$SOURCE_ROOT/$relative" "$RUNTIME_ROOT/$relative"
  done
  echo "一天测试预算代码已安装；现有规则、云端预算配置与运行数据保留：$RUNTIME_ROOT"
  exit 0
fi
# Called from the GitHub main checkout on Mac mini; installs only Node budget
# assets, without reloading launchd or executing platform actions.
for relative in \
  scripts/build_promo_budget_preview.mjs \
  scripts/promo_budget_resolver.mjs \
  scripts/fleet-budget-trial.mjs \
  dianjin-prototype/rules.js \
  dianjin-prototype/logic.js \
  config/promo_budget_overrides.json \
  config/promo_budget_temporary.json \
  config/promo_budget_task_controls.json \
  config/direct_meituan_accounts.json; do
  /bin/mkdir -p "$RUNTIME_ROOT/${relative:h}"
  /bin/cp "$SOURCE_ROOT/$relative" "$RUNTIME_ROOT/$relative"
done
/bin/mkdir -p "$RUNTIME_ROOT/outputs/promo_budget_preview"
echo "推广预算 runtime 已安装：$RUNTIME_ROOT"
