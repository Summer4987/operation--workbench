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
    python3 ai-business-center/center.py agent-commands
    ;;
  *)
    echo "未知命令：$1"
    python3 ai-business-center/center.py agent-commands
    exit 2
    ;;
esac
