#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

HOSTNAME_TEXT="$(hostname | tr '[:upper:]' '[:lower:]')"
if [[ -z "${AI_BUSINESS_CENTER_ENV:-}" && "$HOSTNAME_TEXT" == *mini* ]]; then
  export AI_BUSINESS_CENTER_ENV="production"
fi
if [[ -z "${AI_BUSINESS_CENTER_ENV:-}" ]]; then
  export AI_BUSINESS_CENTER_ENV="development"
fi

PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

LOG_DIR="$ROOT/outputs/macmini_smoke"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/smoke_$(date +%Y%m%d_%H%M%S).log"
ln -sf "$(basename "$LOG_FILE")" "$LOG_DIR/latest.log"
exec > >(tee "$LOG_FILE") 2>&1

echo "== 熊小小AI业务中心 Mac mini 只读冒烟检查 =="
echo "目录：$ROOT"
echo "主机：$(hostname)"
echo "环境：$AI_BUSINESS_CENTER_ENV"
echo "日志：$LOG_FILE"
echo

echo "== 1. 统一健康检查 =="
/bin/zsh scripts/check_macmini_ai_center.zsh
echo

echo "== 2. 巡检证据上传 dry-run =="
OPERATION_EVIDENCE_DRY_RUN_PRINT_LIMIT="${OPERATION_EVIDENCE_DRY_RUN_PRINT_LIMIT:-12}" \
  /bin/zsh scripts/upload_store_inspection_evidence.zsh --dry-run --days "${OPERATION_EVIDENCE_UPLOAD_DAYS:-7}"
echo

echo "== 3. 上午一键流程 preview =="
"$PYTHON" morning-ops/run_morning_ops.py --mode preview --source macmini-smoke
echo

echo "== 4. 冒烟结论 =="
if [[ "$AI_BUSINESS_CENTER_ENV" != "production" ]]; then
  echo "当前不是 Mac mini 生产环境；这次只证明脚本在开发环境可运行。"
  echo "需要生产判断时，请在 Mac mini 项目目录运行同一条命令。"
else
  echo "Mac mini 只读冒烟检查完成。"
  echo "如果上面没有报错，可等待下一次 launchd 定时任务，或把完整输出发给 Codex 做生产确认。"
fi

"$PYTHON" scripts/build_macmini_smoke_status.py
