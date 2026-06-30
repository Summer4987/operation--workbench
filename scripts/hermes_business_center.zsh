#!/bin/zsh
set -euo pipefail

ROOT="${OPERATION_CENTER_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT"

case "${1:-status}" in
  status|状态|health|只读健康检查)
    shift || true
    python3 ai-business-center/center.py agent-status "$@"
    ;;
  list|tasks|任务列表)
    python3 ai-business-center/agent_bridge.py list
    ;;
  task|任务)
    shift || true
    if [[ $# -lt 1 ]]; then
      echo "请提供任务 ID 或名称，例如：任务 ops.daily_report_publish"
      exit 2
    fi
    python3 ai-business-center/agent_bridge.py task "$@"
    ;;
  commands|help|命令|帮助)
    python3 ai-business-center/agent_bridge.py commands
    ;;
  aliases|alias|简称|简称表)
    python3 ai-business-center/agent_bridge.py aliases
    ;;
  monitor|report|自动化报告|任务报告|失败报告)
    python3 scripts/agent_task_monitor.py >/dev/null
    cat outputs/agent_task_monitor/latest.txt
    ;;
  finance-intake|财务记录|财务变动|记账)
    shift || true
    if [[ $# -lt 1 ]]; then
      echo "请提供财务文本，例如：财务记录 今天 银泰城 微信支付采购原料 128.50 元"
      exit 2
    fi
    python3 scripts/finance_system.py record --operator hermes-weixin --text "$*"
    ;;
  finance-drafts|财务草稿|待确认财务|财务待确认)
    python3 scripts/finance_system.py drafts
    ;;
  finance-status|财务状态|财务概览)
    python3 scripts/finance_system.py status
    ;;
  finance-ledger|财务账本|确认账本)
    shift || true
    python3 scripts/finance_system.py ledger "$@"
    ;;
  finance-sync|财务同步|飞书财务同步)
    shift || true
    python3 scripts/finance_system.py sync "$@"
    ;;
  finance-entry|财务入口|财务录入入口)
    echo "熊小小财务系统正式录入口："
    echo "1. 在项目根目录双击：熊小小财务系统.command"
    echo "2. 或运行：python3 scripts/finance_system.py serve"
    echo "3. 浏览器打开：http://127.0.0.1:8765/"
    echo "录入只生成待确认草稿，不会自动入账或同步飞书。"
    ;;
  finance-guide|财务说明|财务手册|财务使用说明)
    python3 scripts/finance_system.py guide
    ;;
  finance-schema|财务字段|财务系统)
    python3 scripts/finance_system.py guide
    ;;
  route|自然语言)
    shift || true
    if [[ $# -lt 1 ]]; then
      python3 ai-business-center/agent_bridge.py commands
      exit 0
    fi
    python3 ai-business-center/agent_bridge.py route "$@"
    ;;
  *)
    python3 ai-business-center/agent_bridge.py route "$@"
    ;;
esac
