#!/bin/zsh
cd "$(dirname "$0")"
PYTHON="/usr/bin/python3"
if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import playwright
PY
then
  PYTHON="python3"
fi
"$PYTHON" inspect_promo_balance.py
if [ -t 0 ]; then
  echo ""
  echo "按回车关闭窗口。"
  read
fi
