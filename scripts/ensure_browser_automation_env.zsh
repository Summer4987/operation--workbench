#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
REPORT_DIR="$ROOT/business-report-dashboard"
BASE_PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$BASE_PYTHON" ]]; then
  BASE_PYTHON="python3"
fi

cd "$REPORT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  "$BASE_PYTHON" -m venv --system-site-packages .venv
fi

PYTHON="$REPORT_DIR/.venv/bin/python"

if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import playwright
PY
then
  "$PYTHON" -m pip install -r requirements.txt
fi

"$PYTHON" - <<'PY'
from playwright.sync_api import sync_playwright
print("browser automation env ok")
PY
