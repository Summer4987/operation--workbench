#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

exec /bin/zsh "$ROOT/scripts/run_current_budget.zsh" --period 晚餐
