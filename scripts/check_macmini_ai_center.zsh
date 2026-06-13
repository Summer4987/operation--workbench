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
if [ ! -x "$PYTHON" ]; then
  PYTHON="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

NODE="/Users/summer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if [ ! -x "$NODE" ]; then
  NODE="node"
fi

echo "== 熊小小AI业务中心生产检查 =="
echo "目录：$ROOT"
echo "主机：$(hostname)"
echo "环境：$AI_BUSINESS_CENTER_ENV"
echo

echo "== Git 状态 =="
git status --short --branch
echo

echo "== 配置与语法检查 =="
"$PYTHON" scripts/validate_ai_business_center_tasks.py
"$PYTHON" -m py_compile \
  scripts/task_run_state.py \
  scripts/record_task_run.py \
  scripts/build_morning_collection_status.py \
  scripts/build_realtime_collection_status.py \
  scripts/build_daily_focus_status.py \
  scripts/record_review_reply.py \
  scripts/build_review_action_status.py \
  scripts/check_inventory_cloud_health.py \
  scripts/build_inventory_order_suggestions.py \
  scripts/build_inventory_order_lists.py \
  scripts/build_inventory_order_execution_preview.py \
  scripts/build_inventory_android_execution_plan.py \
  scripts/check_android_execution_config.py \
  scripts/init_android_execution_config.py \
  scripts/build_promo_budget_retry_plan.py \
  scripts/build_promo_bid_advice.py \
  scripts/build_promo_bid_approval_queue.py \
  scripts/build_store_inspection_evidence_manifest.py \
  scripts/build_promo_balance_status.py \
  scripts/build_user_action_queue.py \
  scripts/build_tool_warehouse_status.py \
  scripts/build_finance_center_status.py \
  scripts/build_task_health.py \
  scripts/build_workbench_data.py \
  business-report-dashboard/chrome_cdp_reports.py \
  business-report-dashboard/process_reports.py \
  morning-ops/run_morning_ops.py \
  store-inspection/run_all_balances.py
/bin/zsh -n scripts/run_realtime_order_income.zsh
/bin/zsh -n scripts/run_current_budget.zsh
/bin/zsh -n scripts/run_evening_budget.zsh
/bin/zsh -n scripts/deploy_workbench_to_cloud.zsh
/bin/zsh -n scripts/upload_store_inspection_evidence.zsh
/bin/zsh -n scripts/run_macmini_ai_center_smoke.zsh
/bin/zsh -n scripts/install_macmini_operation_launchd.zsh
if command -v "$NODE" >/dev/null 2>&1; then
  "$NODE" --check workbench.js
  "$NODE" --check scripts/check_sales_receipt_print_layout.mjs
else
  echo "提示：未找到 Node，跳过 workbench.js 语法检查。"
fi
echo

echo "== 生成只读健康数据 =="
"$PYTHON" scripts/build_morning_collection_status.py
"$PYTHON" scripts/build_realtime_collection_status.py
"$PYTHON" scripts/build_daily_focus_status.py
"$PYTHON" scripts/build_review_action_status.py
"$PYTHON" scripts/check_inventory_cloud_health.py
"$PYTHON" scripts/build_inventory_order_suggestions.py
"$PYTHON" scripts/build_inventory_order_lists.py
"$PYTHON" scripts/build_inventory_order_execution_preview.py
"$PYTHON" scripts/build_inventory_android_execution_plan.py
"$PYTHON" scripts/check_android_execution_config.py
"$PYTHON" scripts/build_promo_budget_retry_plan.py
"$PYTHON" scripts/build_promo_bid_advice.py
"$PYTHON" scripts/build_promo_bid_approval_queue.py
"$PYTHON" scripts/build_store_inspection_evidence_manifest.py --days 7
"$PYTHON" scripts/build_promo_balance_status.py
"$PYTHON" scripts/build_user_action_queue.py
if command -v "$NODE" >/dev/null 2>&1; then
  "$NODE" scripts/check_sales_receipt_print_layout.mjs
else
  echo "提示：未找到 Node，跳过销售单打印版式校验。"
fi
"$PYTHON" scripts/build_tool_warehouse_status.py
"$PYTHON" scripts/build_finance_center_status.py
"$PYTHON" scripts/build_task_health.py
"$PYTHON" scripts/build_workbench_data.py
echo

echo "== 生产定时任务标签 =="
MISSING_LABELS=()
for label in \
  com.summer.operation.morning \
  com.summer.operation.realtime-order-income \
  com.summer.operation.evening
do
  if /bin/launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
    echo "已安装：${label}"
  else
    echo "未安装或未加载：${label}"
    MISSING_LABELS+=("$label")
  fi
done
echo

echo "== 行动建议 =="
if [[ "$AI_BUSINESS_CENTER_ENV" != "production" ]]; then
  echo "当前是开发环境检查，不代表 Mac mini 生产状态。"
  echo "需要切生产时，请在 Mac mini 项目目录运行同一条检查命令。"
elif (( ${#MISSING_LABELS[@]} > 0 )); then
  echo "Mac mini 缺少生产定时任务标签：${MISSING_LABELS[*]}"
  echo "请在 Mac mini 上运行："
  echo "  /bin/zsh scripts/install_macmini_operation_launchd.zsh"
  echo "安装后再次运行："
  echo "  /bin/zsh scripts/check_macmini_ai_center.zsh"
else
  echo "Mac mini 生产定时任务已加载。"
  echo "下一步：等待下一次定时任务运行，或由 Codex 指定低风险预览命令做生产冒烟检查。"
fi
