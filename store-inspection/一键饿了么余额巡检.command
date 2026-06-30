#!/bin/zsh
cd "$(dirname "$0")"
PYTHON="/usr/bin/python3"
if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
from PIL import Image
PY
then
  PYTHON="python3"
fi
"$PYTHON" one_click_eleme_balance.py
open "index.html"
if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
