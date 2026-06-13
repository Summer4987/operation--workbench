#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REMOTE="${MACMINI_DEPLOY_REMOTE:-origin}"
BRANCH="${MACMINI_DEPLOY_BRANCH:-codex/ai-business-center}"
RUN_SMOKE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --smoke)
      RUN_SMOKE=1
      shift
      ;;
    *)
      echo "未知参数：$1"
      echo "用法：/bin/zsh scripts/macmini_pull_and_check.zsh [--branch codex/ai-business-center] [--smoke]"
      exit 2
      ;;
  esac
done

echo "== Mac mini 拉取并只读检查 =="
echo "目录：$ROOT"
echo "远端：$REMOTE"
echo "分支：$BRANCH"
echo

if [[ -n "$(git status --porcelain)" ]]; then
  echo "拒绝继续：当前工作区存在未提交或未跟踪改动。"
  echo "请先把下面状态发给 Codex 判断，不要强制覆盖："
  git status --short --branch
  exit 64
fi

echo "== 1. 获取远端 =="
git fetch "$REMOTE" "$BRANCH"

echo
echo "== 2. Fast-forward 更新 =="
git merge --ff-only "$REMOTE/$BRANCH"

echo
echo "== 3. 只读健康检查 =="
/bin/zsh scripts/check_macmini_ai_center.zsh

if (( RUN_SMOKE )); then
  echo
  echo "== 4. 只读冒烟检查 =="
  /bin/zsh scripts/run_macmini_ai_center_smoke.zsh
else
  echo
  echo "未运行冒烟检查。如需验证证据上传 dry-run 和上午 preview，请追加 --smoke。"
fi

echo
echo "Mac mini 拉取并只读检查完成。"
