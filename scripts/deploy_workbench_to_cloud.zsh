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
"$PYTHON" scripts/build_agent_mobile_status.py
"$PYTHON" scripts/build_workbench_data.py
mkdir -p "$STAGE_DIR/data"
"$PYTHON" - <<PY
from pathlib import Path
import shutil
import re

root = Path("$ROOT")
stage = Path("$STAGE_DIR")
version = "$DEPLOY_VERSION"
if stage.exists():
    shutil.rmtree(stage)
stage.mkdir(parents=True, exist_ok=True)
(stage / "data").mkdir(parents=True, exist_ok=True)

index = (root / "index.html").read_text(encoding="utf-8")
for name in ("workbench-data.js", "workbench.js"):
    index = re.sub(rf'(\./{re.escape(name)}\?v=)[^"]+', rf'\g<1>{version}', index)
(stage / "index.html").write_text(index, encoding="utf-8")

for name in ("workbench.css", "workbench.js", "workbench-data.js"):
    (stage / name).write_bytes((root / name).read_bytes())
copy_agent_page = root / "agent.html"
if copy_agent_page.exists():
    (stage / "agent.html").write_bytes(copy_agent_page.read_bytes())
(stage / "data" / "realtime-history.json").write_bytes((root / "data" / "realtime-history.json").read_bytes())

def copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

def copy_tree_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        shutil.copytree(source, target, dirs_exist_ok=True)

copy_if_exists(root / "PROJECT_TREE.md", stage / "PROJECT_TREE.md")
copy_tree_if_exists(root / "business-report-dashboard" / "dashboard", stage / "business-report-dashboard" / "dashboard")
copy_tree_if_exists(root / "business-report-dashboard" / "direct-dashboard", stage / "business-report-dashboard" / "direct-dashboard")
copy_tree_if_exists(root / "franchise-contract-generator", stage / "franchise-contract-generator")
copy_tree_if_exists(root / "floor-plan-designer", stage / "floor-plan-designer")
for name in ("latest.json", "unified_daily.csv", "unified_reviews.csv", "direct-latest.json", "direct_unified_daily.csv", "direct_unified_reviews.csv"):
    copy_if_exists(root / "business-report-dashboard" / "data" / name, stage / "business-report-dashboard" / "data" / name)
for name in ("index.html", "meituan-budget.html", "styles.css", "app.js", "latest.json", "latest-data.js", "budget-editor.html"):
    copy_if_exists(root / "store-inspection" / name, stage / "store-inspection" / name)
for name in ("index.html", "styles.css", "app.js", "logic.js", "rules.js", "current_state.js", "execution_preview.js"):
    copy_if_exists(root / "dianjin-prototype" / name, stage / "dianjin-prototype" / name)
for name in ("latest.json", "latest-data.js"):
    copy_if_exists(root / "outputs" / "promo_budget_preview" / name, stage / "outputs" / "promo_budget_preview" / name)
copy_if_exists(root / "outputs" / "agent_mobile" / "latest.json", stage / "outputs" / "agent_mobile" / "latest.json")
copy_if_exists(root / "outputs" / "realtime_order_income" / "latest.json", stage / "outputs" / "realtime_order_income" / "latest.json")
PY

ssh "${SSH_OPTS[@]}" "$SERVER" "sudo mkdir -p '$REMOTE_DIR' && sudo chown -R \$(whoami):\$(whoami) '$REMOTE_DIR' && chmod -R u+rwX '$REMOTE_DIR'"

validate_realtime_history_deploy() {
  local local_file="$STAGE_DIR/data/realtime-history.json"
  local local_metrics local_count local_latest
  local_metrics="$("$PYTHON" - "$local_file" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
snapshots = payload.get("snapshots") or []
if not snapshots:
    raise SystemExit("待发布实时历史没有快照，拒绝覆盖线上数据。")
latest = str(snapshots[-1].get("generated_at") or "").replace(" ", "T")
print(len(snapshots), latest)
PY
)"
  read -r local_count local_latest <<< "$local_metrics"

  ssh "${SSH_OPTS[@]}" "$SERVER" \
    "python3 - '$REMOTE_DIR/data/realtime-history.json' '$local_count' '$local_latest' '${ALLOW_REALTIME_HISTORY_SHRINK:-0}'" <<'PY'
import json
import sys
from pathlib import Path

remote_path = Path(sys.argv[1])
local_count = int(sys.argv[2])
local_latest = sys.argv[3]
allow_shrink = sys.argv[4] == "1"
if not remote_path.exists():
    raise SystemExit(0)

payload = json.loads(remote_path.read_text(encoding="utf-8"))
snapshots = payload.get("snapshots") or []
remote_count = len(snapshots)
remote_latest = str(snapshots[-1].get("generated_at") or "").replace(" ", "T") if snapshots else ""
history_regressed = bool(
    remote_latest
    and (
        not local_latest
        or local_latest < remote_latest
        or (local_latest == remote_latest and local_count < remote_count)
    )
)
if not allow_shrink and history_regressed:
    raise SystemExit(
        "拒绝用较旧的实时历史覆盖线上数据："
        f"待发布 count={local_count}, latest={local_latest or '-'}；"
        f"线上 count={remote_count}, latest={remote_latest or '-'}。"
    )
PY
}

validate_realtime_history_deploy

if [[ "$DEPLOY_MODE" == "full" ]]; then
  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/index.html" "$STAGE_DIR/workbench.css" "$STAGE_DIR/workbench.js" "$STAGE_DIR/workbench-data.js" "$STAGE_DIR/PROJECT_TREE.md" \
    "$SERVER:$REMOTE_DIR/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/agent.html" \
    "$SERVER:$REMOTE_DIR/"

  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/business-report-dashboard/data'"
  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/business-report-dashboard/dashboard/" \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/"
  rsync -az -e "ssh ${SSH_OPTS[*]}" "$STAGE_DIR/business-report-dashboard/data/" "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"
  rsync -az --delete --delete-excluded --exclude='* 2.html' \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/business-report-dashboard/direct-dashboard/" \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/direct-dashboard/"
  rsync -az --delete --exclude='* 2*' \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/franchise-contract-generator/" \
    "$SERVER:$REMOTE_DIR/franchise-contract-generator/"

  rsync -az --delete --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/floor-plan-designer/" \
    "$SERVER:$REMOTE_DIR/floor-plan-designer/"

  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/store-inspection/" \
    "$SERVER:$REMOTE_DIR/store-inspection/"

  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/dianjin-prototype/" \
    "$SERVER:$REMOTE_DIR/dianjin-prototype/"

  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/outputs/promo_budget_preview'"
  rsync -az -e "ssh ${SSH_OPTS[*]}" "$STAGE_DIR/outputs/promo_budget_preview/" "$SERVER:$REMOTE_DIR/outputs/promo_budget_preview/"
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/outputs/agent_mobile'"
  rsync -az -e "ssh ${SSH_OPTS[*]}" "$STAGE_DIR/outputs/agent_mobile/" "$SERVER:$REMOTE_DIR/outputs/agent_mobile/"
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/outputs/realtime_order_income'"
  rsync -az -e "ssh ${SSH_OPTS[*]}" "$STAGE_DIR/outputs/realtime_order_income/" "$SERVER:$REMOTE_DIR/outputs/realtime_order_income/"
elif [[ "$DEPLOY_MODE" == "data-only" ]]; then
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/data' '$REMOTE_DIR/business-report-dashboard/data' '$REMOTE_DIR/business-report-dashboard/direct-dashboard' '$REMOTE_DIR/outputs/agent_mobile' '$REMOTE_DIR/outputs/realtime_order_income' '$REMOTE_DIR/outputs/promo_budget_preview'"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/index.html" "$STAGE_DIR/agent.html" \
    "$STAGE_DIR/workbench-data.js" \
    "$SERVER:$REMOTE_DIR/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/outputs/agent_mobile/latest.json" \
    "$SERVER:$REMOTE_DIR/outputs/agent_mobile/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/outputs/realtime_order_income/latest.json" \
    "$SERVER:$REMOTE_DIR/outputs/realtime_order_income/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/outputs/promo_budget_preview/latest.json" "$STAGE_DIR/outputs/promo_budget_preview/latest-data.js" \
    "$SERVER:$REMOTE_DIR/outputs/promo_budget_preview/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/data/realtime-history.json" \
    "$SERVER:$REMOTE_DIR/data/"
  rsync -az --delete --delete-excluded --exclude='* 2.html' --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/business-report-dashboard/direct-dashboard/" \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/direct-dashboard/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/business-report-dashboard/data/direct-latest.json" "$STAGE_DIR/business-report-dashboard/data/direct_unified_daily.csv" "$STAGE_DIR/business-report-dashboard/data/direct_unified_reviews.csv" \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"
  echo "已按 data-only 模式发布，更新工作台数据、Agent 手机入口、实时明细、预算预览、实时历史、直营日报数据和直营日报独立看板。"
else
  ssh "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$REMOTE_DIR/data' '$REMOTE_DIR/business-report-dashboard/data' '$REMOTE_DIR/business-report-dashboard/direct-dashboard' '$REMOTE_DIR/store-inspection' '$REMOTE_DIR/outputs/agent_mobile' '$REMOTE_DIR/outputs/realtime_order_income' '$REMOTE_DIR/outputs/promo_budget_preview'"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/index.html" "$STAGE_DIR/agent.html" "$STAGE_DIR/workbench.css" "$STAGE_DIR/workbench.js" "$STAGE_DIR/workbench-data.js" \
    "$SERVER:$REMOTE_DIR/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/outputs/agent_mobile/latest.json" \
    "$SERVER:$REMOTE_DIR/outputs/agent_mobile/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/outputs/realtime_order_income/latest.json" \
    "$SERVER:$REMOTE_DIR/outputs/realtime_order_income/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/outputs/promo_budget_preview/latest.json" "$STAGE_DIR/outputs/promo_budget_preview/latest-data.js" \
    "$SERVER:$REMOTE_DIR/outputs/promo_budget_preview/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/data/realtime-history.json" \
    "$SERVER:$REMOTE_DIR/data/"
  rsync -az --delete --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/business-report-dashboard/dashboard/" \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/"
  rsync -az --delete --delete-excluded --exclude='* 2.html' --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/business-report-dashboard/direct-dashboard/" \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/direct-dashboard/"
  rsync -az --delete --exclude='* 2*' --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/franchise-contract-generator/" \
    "$SERVER:$REMOTE_DIR/franchise-contract-generator/"
  rsync -az --delete --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/floor-plan-designer/" \
    "$SERVER:$REMOTE_DIR/floor-plan-designer/"
  rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    -e "ssh ${SSH_OPTS[*]}" \
    "$STAGE_DIR/business-report-dashboard/data/" \
    "$SERVER:$REMOTE_DIR/business-report-dashboard/data/"
  if [[ -f "$STAGE_DIR/store-inspection/latest.json" && -f "$STAGE_DIR/store-inspection/latest-data.js" ]]; then
    rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
      -e "ssh ${SSH_OPTS[*]}" \
      "$STAGE_DIR/store-inspection/latest.json" "$STAGE_DIR/store-inspection/latest-data.js" \
      "$SERVER:$REMOTE_DIR/store-inspection/"
  else
    echo "提示：本地没有余额巡检 latest.json/latest-data.js，跳过余额巡检静态数据发布。"
  fi
  echo "已按 ui-data 模式发布，更新首页 UI、工作台数据、实时明细、预算预览、加盟/直营日报和余额巡检数据。"
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
  verify_remote_file "agent.html" "$STAGE_DIR/agent.html"
  verify_remote_file "outputs/agent_mobile/latest.json" "$STAGE_DIR/outputs/agent_mobile/latest.json"
  verify_remote_file "outputs/realtime_order_income/latest.json" "$STAGE_DIR/outputs/realtime_order_income/latest.json"
  verify_remote_file "outputs/promo_budget_preview/latest.json" "$STAGE_DIR/outputs/promo_budget_preview/latest.json"
  verify_remote_file "data/realtime-history.json" "$STAGE_DIR/data/realtime-history.json"
  verify_remote_file "workbench-data.js" "$STAGE_DIR/workbench-data.js"
  verify_remote_file "business-report-dashboard/data/direct-latest.json" "$STAGE_DIR/business-report-dashboard/data/direct-latest.json"
else
  verify_remote_file "index.html" "$STAGE_DIR/index.html"
  verify_remote_file "agent.html" "$STAGE_DIR/agent.html"
  verify_remote_file "outputs/agent_mobile/latest.json" "$STAGE_DIR/outputs/agent_mobile/latest.json"
  verify_remote_file "outputs/realtime_order_income/latest.json" "$STAGE_DIR/outputs/realtime_order_income/latest.json"
  verify_remote_file "outputs/promo_budget_preview/latest.json" "$STAGE_DIR/outputs/promo_budget_preview/latest.json"
  verify_remote_file "data/realtime-history.json" "$STAGE_DIR/data/realtime-history.json"
  verify_remote_file "workbench.css" "$STAGE_DIR/workbench.css"
  verify_remote_file "workbench.js" "$STAGE_DIR/workbench.js"
  verify_remote_file "workbench-data.js" "$STAGE_DIR/workbench-data.js"
  verify_remote_file "franchise-contract-generator/index.html" "$STAGE_DIR/franchise-contract-generator/index.html"
  verify_remote_file "franchise-contract-generator/app.js" "$STAGE_DIR/franchise-contract-generator/app.js"
  verify_remote_file "floor-plan-designer/index.html" "$STAGE_DIR/floor-plan-designer/index.html"
  verify_remote_file "floor-plan-designer/styles.css" "$STAGE_DIR/floor-plan-designer/styles.css"
  verify_remote_file "floor-plan-designer/app.js" "$STAGE_DIR/floor-plan-designer/app.js"
fi

echo "运营总看板已发布：$PUBLIC_URL"
