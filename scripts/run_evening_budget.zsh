#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${BUDGET_MODE:-commit}"
LIMIT="${BUDGET_LIMIT:-all}"

exec /bin/zsh "$ROOT/scripts/run_current_budget.zsh" --period 晚餐 --mode "$MODE" --limit "$LIMIT"
