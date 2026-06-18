#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${OPERATION_CLOUD_REMOTE_DIR:-/var/www/html/operation-workbench}"
PUBLIC_URL="${OPERATION_CLOUD_PUBLIC_URL:-http://139.155.148.169/operation-workbench/}"
DEPLOY_MODE="${OPERATION_CLOUD_DEPLOY_MODE:-ui-data}"
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
run_optional "推广余额状态更新" "$PYTHON" scripts/build_promo_balance_status.py
run_optional "财务三方流水核对预览" "$PYTHON" scripts/build_finance_reconciliation_preview.py
run_optional "品牌财务中心状态" "$PYTHON" scripts/build_finance_center_status.py
"$PYTHON" scripts/build_workbench_data.py

ssh "${SSH_OPTS[@]}" "$SERVER" "sudo mkdir -p '$REMOTE_DIR' && sudo chown -R \$(whoami):\$(whoami) '$REMOTE_DIR' && chmod -R u+rwX '$REMOTE_DIR'"

if [[ "$DEPLOY_MODE" == "full" ]]; then
  rsync -azc --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    index.html workbench.css workbench.js workbench-data.js PROJECT_TREE.md \
    "$SERVER:$REMOTE_DIR/"

  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/business-report-dashboard/data'"
  rsync -azc -e "ssh ${SSH_OPTS[*]}" business-report-dashboard/data/latest.json business-report-dashboard/data/unified_daily.csv business-report-dashboard/data/unified_reviews.csv "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"

  rsync -azc --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    store-inspection/index.html store-inspection/meituan-budget.html store-inspection/styles.css store-inspection/app.js store-inspection/latest.json store-inspection/latest-data.js \
    store-inspection/budget-editor.html \
    "$SERVER:$REMOTE_DIR/store-inspection/"

  rsync -azc --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    dianjin-prototype/index.html dianjin-prototype/styles.css dianjin-prototype/app.js dianjin-prototype/logic.js dianjin-prototype/rules.js dianjin-prototype/current_state.js dianjin-prototype/execution_preview.js \
    "$SERVER:$REMOTE_DIR/dianjin-prototype/"

  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/outputs/promo_budget_preview'"
  rsync -azc -e "ssh ${SSH_OPTS[*]}" outputs/promo_budget_preview/latest.json outputs/promo_budget_preview/latest-data.js "$SERVER:$REMOTE_DIR/outputs/promo_budget_preview/"
elif [[ "$DEPLOY_MODE" == "data-only" ]]; then
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/data'"
  rsync -azc --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    workbench-data.js \
    "$SERVER:$REMOTE_DIR/"
  rsync -azc --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    data/realtime-history.json \
    "$SERVER:$REMOTE_DIR/data/"
  echo "已按 data-only 模式发布，仅更新 workbench-data.js 和 data/realtime-history.json，未同步页面布局文件。"
else
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/data' '$REMOTE_DIR/business-report-dashboard/data' '$REMOTE_DIR/store-inspection'"
  rsync -azc --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    index.html workbench.css workbench.js workbench-data.js \
    "$SERVER:$REMOTE_DIR/"
  rsync -azc --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    data/realtime-history.json \
    "$SERVER:$REMOTE_DIR/data/"
  rsync -azc --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    business-report-dashboard/data/latest.json business-report-dashboard/data/unified_daily.csv business-report-dashboard/data/unified_reviews.csv \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"
  rsync -azc --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    store-inspection/latest.json store-inspection/latest-data.js \
    "$SERVER:$REMOTE_DIR/store-inspection/"
  echo "已按 ui-data 模式发布，更新首页 UI、工作台数据、日报数据和余额巡检数据。"
fi

ssh "${SSH_OPTS[@]}" "$SERVER" "find '$REMOTE_DIR' -type d -exec chmod 755 {} + && find '$REMOTE_DIR' -type f -exec chmod 644 {} +"

verify_remote_file() {
  local file="$1"
  local local_hash remote_hash
  local_hash="$(shasum -a 256 "$file" | awk '{print $1}')"
  remote_hash="$(ssh "${SSH_OPTS[@]}" "$SERVER" "sha256sum '$REMOTE_DIR/$file'" | awk '{print $1}')"
  if [[ "$local_hash" != "$remote_hash" ]]; then
    echo "发布校验失败：$file 本地与云端不一致" >&2
    echo "local:  $local_hash" >&2
    echo "remote: $remote_hash" >&2
    exit 1
  fi
}

if [[ "$DEPLOY_MODE" == "data-only" ]]; then
  verify_remote_file "workbench-data.js"
else
  verify_remote_file "index.html"
  verify_remote_file "workbench.css"
  verify_remote_file "workbench.js"
  verify_remote_file "workbench-data.js"
fi

echo "运营总看板已发布：$PUBLIC_URL"
