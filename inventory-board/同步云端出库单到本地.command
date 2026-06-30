#!/usr/bin/env bash
cd "$(dirname "$0")"
PYTHON="$(pwd)/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
"$PYTHON" scripts/sync_order_outputs.py --server http://139.155.148.169 --token xiongxiaoxiao-order --output-dir "/Users/summer/Desktop/库存管理/出库记录" --latest 20
if [ -t 0 ]; then
  read -n 1 -s -r -p "按任意键关闭"
fi
