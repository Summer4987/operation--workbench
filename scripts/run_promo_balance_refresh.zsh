#!/bin/zsh
set -euo pipefail

# Old launchd wrappers may still reference this path until reinstalled.
# Never collect balances or send notifications outside morning operations.
echo "独立推广余额刷新已停用；余额巡检仅随每天上午运营执行。"
