#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

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
echo

echo "== Git 状态 =="
git status --short --branch
echo

echo "== 配置与语法检查 =="
"$PYTHON" scripts/validate_ai_business_center_tasks.py
"$PYTHON" -m py_compile \
  scripts/task_run_state.py \
  scripts/record_task_run.py \
  scripts/build_task_health.py \
  scripts/build_workbench_data.py \
  morning-ops/run_morning_ops.py \
  store-inspection/run_all_balances.py
/bin/zsh -n scripts/run_realtime_order_income.zsh
/bin/zsh -n scripts/run_current_budget.zsh
/bin/zsh -n scripts/run_evening_budget.zsh
/bin/zsh -n scripts/deploy_workbench_to_cloud.zsh
/bin/zsh -n scripts/install_macmini_operation_launchd.zsh
if command -v "$NODE" >/dev/null 2>&1; then
  "$NODE" --check workbench.js
else
  echo "提示：未找到 Node，跳过 workbench.js 语法检查。"
fi
echo

echo "== 生成只读健康数据 =="
"$PYTHON" scripts/build_task_health.py
"$PYTHON" scripts/build_workbench_data.py
echo

echo "== 生产定时任务标签 =="
for label in \
  com.summer.operation.morning \
  com.summer.operation.realtime-order-income \
  com.summer.operation.evening
do
  if /bin/launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
    echo "已安装：${label}"
  else
    echo "未安装或未加载：${label}"
  fi
done
echo

echo "检查完成。若 launchd 标签未安装，请在 Mac mini 上运行："
echo "  /bin/zsh scripts/install_macmini_operation_launchd.zsh"
