#!/bin/zsh
cd "$(dirname "$0")"
PYTHON="$(pwd)/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" scripts/watch_inventory_folder.py --movement inbound
