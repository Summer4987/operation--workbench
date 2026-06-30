#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${CAINIAO_CAPTURE_PYTHON:-python3}"
ADB="${ANDROID_ADB_BIN:-$HOME/Library/Android/sdk/platform-tools/adb}"
DETAILS="${CAINIAO_MAX_DETAILS:-12}"
SCROLL_PAGES="${CAINIAO_SCROLL_PAGES:-1}"
STAMP="$(date +%Y%m%d-%H%M%S)"
EVIDENCE_DIR="$ROOT/outputs/cainiao_logistics/scheduled-$STAMP"

export ANDROID_ADB_BIN="$ADB"

mkdir -p "$ROOT/outputs/cainiao_logistics"

"$PYTHON" scripts/cainiao_logistics_capture.py \
  --scan-details \
  --max-details "$DETAILS" \
  --scroll-pages "$SCROLL_PAGES" \
  --evidence-dir "$EVIDENCE_DIR" \
  --commit

