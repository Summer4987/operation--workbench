#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${OPERATION_CLOUD_SERVER:-ubuntu@139.155.148.169}"
REMOTE_DIR="${OPERATION_CLOUD_REMOTE_DIR:-/var/www/html/operation-workbench}"
PUBLIC_URL="${OPERATION_CLOUD_PUBLIC_URL:-http://139.155.148.169/operation-workbench/}"
DEPLOY_MODE="${OPERATION_CLOUD_DEPLOY_MODE:-data-only}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
IDENTITY_FILE="${OPERATION_CLOUD_IDENTITY_FILE:-$HOME/.ssh/xiong_operation_cloud_ed25519}"
if [[ -f "$IDENTITY_FILE" ]]; then
  SSH_OPTS+=(-i "$IDENTITY_FILE")
fi

cd "$ROOT"

python3 scripts/sync_promo_budget_overrides.py
python3 scripts/build_workbench_data.py

ssh "${SSH_OPTS[@]}" "$SERVER" "sudo mkdir -p '$REMOTE_DIR' && sudo chown -R \$(whoami):\$(whoami) '$REMOTE_DIR' && chmod -R u+rwX '$REMOTE_DIR'"

if [[ "$DEPLOY_MODE" == "full" ]]; then
  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    index.html workbench.css workbench.js workbench-data.js PROJECT_TREE.md \
    "$SERVER:$REMOTE_DIR/"

  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/business-report-dashboard/data'"
  rsync -az -e "ssh ${SSH_OPTS[*]}" business-report-dashboard/data/latest.json business-report-dashboard/data/unified_daily.csv business-report-dashboard/data/unified_reviews.csv "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"

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
else
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/data'"
  rsync -az \
    -e "ssh ${SSH_OPTS[*]}" \
    workbench-data.js \
    "$SERVER:$REMOTE_DIR/"
  rsync -az \
    -e "ssh ${SSH_OPTS[*]}" \
    data/realtime-history.json \
    "$SERVER:$REMOTE_DIR/data/"
  echo "已按 data-only 模式发布，仅更新 workbench-data.js 和 data/realtime-history.json，未同步页面布局文件。"
fi

ssh "${SSH_OPTS[@]}" "$SERVER" "find '$REMOTE_DIR' -type d -exec chmod 755 {} + && find '$REMOTE_DIR' -type f -exec chmod 644 {} +"

echo "运营总看板已发布：$PUBLIC_URL"
