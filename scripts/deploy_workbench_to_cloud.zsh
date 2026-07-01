#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${OPERATION_CLOUD_REMOTE_DIR:-/var/www/html/operation-workbench}"
PUBLIC_URL="${OPERATION_CLOUD_PUBLIC_URL:-http://139.155.148.169/operation-workbench/}"
DEPLOY_MODE="${OPERATION_CLOUD_DEPLOY_MODE:-ui-data}"
DEPLOY_VERSION="${OPERATION_DEPLOY_VERSION:-$(date +%Y%m%d%H%M%S)}"
STAGE_DIR="${TMPDIR:-/tmp}/operation-workbench-deploy"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
IDENTITY_FILE="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "$IDENTITY_FILE" ]]; then
  SSH_OPTS+=(-i "$IDENTITY_FILE")
fi

cd "$ROOT"

PYTHON="$ROOT/business-report-dashboard/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

run_optional() {
  local label="$1"
  shift
  if ! "$@"; then
    echo "警告：${label}失败，继续发布其它已生成数据。" >&2
  fi
}

"$PYTHON" scripts/sync_promo_budget_overrides.py
run_optional "日报重点状态更新" "$PYTHON" scripts/build_daily_focus_status.py
run_optional "评价待办状态更新" "$PYTHON" scripts/build_review_action_status.py
run_optional "直营店日报看板生成" "$PYTHON" business-report-dashboard/process_direct_reports.py
run_optional "推广余额状态更新" "$PYTHON" scripts/build_promo_balance_status.py
"$PYTHON" scripts/build_workbench_data.py
mkdir -p "$STAGE_DIR/data"
"$PYTHON" - <<PY
from pathlib import Path
import re

root = Path("$ROOT")
stage = Path("$STAGE_DIR")
version = "$DEPLOY_VERSION"
stage.mkdir(parents=True, exist_ok=True)
(stage / "data").mkdir(parents=True, exist_ok=True)

index = (root / "index.html").read_text(encoding="utf-8")
for name in ("workbench-data.js", "workbench.js"):
    index = re.sub(rf'(\./{re.escape(name)}\?v=)[^"]+', rf'\g<1>{version}', index)
(stage / "index.html").write_text(index, encoding="utf-8")

for name in ("workbench.css", "workbench.js", "workbench-data.js"):
    (stage / name).write_bytes((root / name).read_bytes())
(stage / "data" / "realtime-history.json").write_bytes((root / "data" / "realtime-history.json").read_bytes())
PY

ssh "${SSH_OPTS[@]}" "$SERVER" "sudo mkdir -p '$REMOTE_DIR' && sudo chown -R \$(whoami):\$(whoami) '$REMOTE_DIR' && chmod -R u+rwX '$REMOTE_DIR'"

if [[ "$DEPLOY_MODE" == "full" ]]; then
  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/index.html" "$STAGE_DIR/workbench.css" "$STAGE_DIR/workbench.js" "$STAGE_DIR/workbench-data.js" PROJECT_TREE.md \
    "$SERVER:$REMOTE_DIR/"

  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/business-report-dashboard/data'"
  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    business-report-dashboard/dashboard/ \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/"
  rsync -az -e "ssh ${SSH_OPTS[*]}" business-report-dashboard/data/latest.json business-report-dashboard/data/unified_daily.csv business-report-dashboard/data/unified_reviews.csv business-report-dashboard/data/direct-latest.json business-report-dashboard/data/direct_unified_daily.csv business-report-dashboard/data/direct_unified_reviews.csv "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"
  rsync -az --delete --exclude='* 2.html' \
    -e "ssh ${SSH_OPTS[*]}" \
    business-report-dashboard/direct-dashboard/ \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/direct-dashboard/"

  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    store-inspection/index.html store-inspection/meituan-budget.html store-inspection/styles.css store-inspection/app.js store-inspection/latest.json store-inspection/latest-data.js \
    store-inspection/budget-editor.html \
    "$SERVER:$REMOTE_DIR/store-inspection/"

  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    dianjin-prototype/index.html dianjin-prototype/styles.css dianjin-prototype/app.js dianjin-prototype/logic.js dianjin-prototype/rules.js dianjin-prototype/current_state.js dianjin-prototype/execution_preview.js \
    "$SERVER:$REMOTE_DIR/dianjin-prototype/"

  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/outputs/promo_budget_preview'"
  rsync -az -e "ssh ${SSH_OPTS[*]}" outputs/promo_budget_preview/latest.json outputs/promo_budget_preview/latest-data.js "$SERVER:$REMOTE_DIR/outputs/promo_budget_preview/"
elif [[ "$DEPLOY_MODE" == "data-only" ]]; then
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/data' '$REMOTE_DIR/business-report-dashboard/data' '$REMOTE_DIR/business-report-dashboard/direct-dashboard'"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/index.html" \
    "$STAGE_DIR/workbench-data.js" \
    "$SERVER:$REMOTE_DIR/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/data/realtime-history.json" \
    "$SERVER:$REMOTE_DIR/data/"
  rsync -az --delete --exclude='* 2.html' --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    business-report-dashboard/direct-dashboard/ \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/direct-dashboard/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    business-report-dashboard/data/direct-latest.json business-report-dashboard/data/direct_unified_daily.csv business-report-dashboard/data/direct_unified_reviews.csv \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"
  echo "已按 data-only 模式发布，更新工作台数据、实时历史、直营日报数据和直营日报独立看板。"
else
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/data' '$REMOTE_DIR/business-report-dashboard/data' '$REMOTE_DIR/business-report-dashboard/direct-dashboard' '$REMOTE_DIR/store-inspection'"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/index.html" "$STAGE_DIR/workbench.css" "$STAGE_DIR/workbench.js" "$STAGE_DIR/workbench-data.js" \
    "$SERVER:$REMOTE_DIR/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/data/realtime-history.json" \
    "$SERVER:$REMOTE_DIR/data/"
  rsync -az --delete --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    business-report-dashboard/dashboard/ \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/"
  rsync -az --delete --exclude='* 2.html' --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    business-report-dashboard/direct-dashboard/ \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/direct-dashboard/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    business-report-dashboard/data/latest.json business-report-dashboard/data/unified_daily.csv business-report-dashboard/data/unified_reviews.csv business-report-dashboard/data/direct-latest.json business-report-dashboard/data/direct_unified_daily.csv business-report-dashboard/data/direct_unified_reviews.csv \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    store-inspection/latest.json store-inspection/latest-data.js \
    "$SERVER:$REMOTE_DIR/store-inspection/"
  echo "已按 ui-data 模式发布，更新首页 UI、工作台数据、加盟/直营日报和余额巡检数据。"
fi

ssh "${SSH_OPTS[@]}" "$SERVER" "find '$REMOTE_DIR' -type d -exec chmod 755 {} + && find '$REMOTE_DIR' -type f -exec chmod 644 {} +"

verify_remote_file() {
  local file="$1"
  local local_file="${2:-$file}"
  local local_hash remote_hash
  local_hash="$(shasum -a 256 "$local_file" | awk '{print $1}')"
  remote_hash="$(ssh "${SSH_OPTS[@]}" "$SERVER" "sha256sum '$REMOTE_DIR/$file'" | awk '{print $1}')"
  if [[ "$local_hash" != "$remote_hash" ]]; then
    echo "发布校验失败：$file 本地与云端不一致" >&2
    echo "local:  $local_hash" >&2
    echo "remote: $remote_hash" >&2
    exit 1
  fi
}

if [[ "$DEPLOY_MODE" == "data-only" ]]; then
  verify_remote_file "index.html" "$STAGE_DIR/index.html"
  verify_remote_file "workbench-data.js" "$STAGE_DIR/workbench-data.js"
  verify_remote_file "business-report-dashboard/data/direct-latest.json"
else
  verify_remote_file "index.html" "$STAGE_DIR/index.html"
  verify_remote_file "workbench.css" "$STAGE_DIR/workbench.css"
  verify_remote_file "workbench.js" "$STAGE_DIR/workbench.js"
  verify_remote_file "workbench-data.js" "$STAGE_DIR/workbench-data.js"
fi

echo "运营总看板已发布：$PUBLIC_URL"
