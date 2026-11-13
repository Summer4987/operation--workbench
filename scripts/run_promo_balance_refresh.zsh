#!/bin/zsh
set -uo pipefail

ROOT="${OPERATION_ROOT:-$HOME/Library/Application Support/xiong-operation/production}"
LOG_DIR="$HOME/Library/Logs/xiong-operation/promo_balance_refresh"
LOCK_DIR="$HOME/Library/Caches/xiong-operation/promo_balance_refresh.lock"
mkdir -p "$LOG_DIR" "${LOCK_DIR:h}"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "推广余额刷新仍在运行，本轮跳过。"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

cd "$ROOT"
PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

LOG_FILE="$LOG_DIR/$(date +%F).log"
"$PYTHON" - "$ROOT" "$PYTHON" <<'PYLOCK' >> "$LOG_FILE" 2>&1
import fcntl
import os
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
lock_path = root / "outputs/locks/morning-ops.lock"
lock_path.parent.mkdir(parents=True, exist_ok=True)
with lock_path.open("a+") as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("上午运营或余额任务正在使用生产浏览器，本轮独立余额刷新跳过。", flush=True)
        raise SystemExit(0)
    env = os.environ.copy()
    env.update(ROOT=str(root), PYTHON=sys.argv[2])
    result = subprocess.run(["/bin/zsh", "-c", r'''set -uo pipefail
  echo
  echo "[$(date '+%F %T')] 推广余额刷新开始"
  "$PYTHON" store-inspection/run_all_balances.py
  "$PYTHON" scripts/build_promo_balance_status.py
  "$PYTHON" scripts/build_task_health.py
  "$PYTHON" scripts/build_workbench_data.py
  OPERATION_ROOT="$ROOT" OPERATION_CLOUD_DEPLOY_MODE=data-only \
    /bin/zsh "$HOME/Library/Scripts/xiong-operation/deploy_workbench_to_cloud.zsh"
  echo "[$(date '+%F %T')] 推广余额刷新完成"
'''], cwd=root, env=env)
    raise SystemExit(result.returncode)
PYLOCK
