#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${BUDGET_MODE:-commit}"
LIMIT="${BUDGET_LIMIT:-all}"
CURRENT_RUNNER="${CURRENT_BUDGET_RUNNER:-$ROOT/scripts/run_current_budget.zsh}"

exec /bin/zsh "$CURRENT_RUNNER" --period 晚餐 --mode "$MODE" --limit "$LIMIT"
