#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REMOTE="${MACMINI_DEPLOY_REMOTE:-origin}"
BRANCH="${MACMINI_DEPLOY_BRANCH:-main}"
RUN_SMOKE=0
INSTALL_LAUNCHD=0

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
    --install-launchd)
      INSTALL_LAUNCHD=1
      shift
      ;;
    *)
      echo "未知参数：$1"
      echo "用法：/bin/zsh scripts/macmini_pull_and_check.zsh [--branch main] [--smoke] [--install-launchd]"
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
  echo
  echo "如果只是要让 Mac mini Codex 接管下一步任务，请改用干净交接仓库："
  echo "  /bin/zsh scripts/macmini_takeover_clean_checkout.zsh"
  echo "或双击："
  echo "  Mac mini Codex接管.command"
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

if (( INSTALL_LAUNCHD )); then
  echo
  echo "== 5. 安装或刷新生产定时任务 =="
  /bin/zsh scripts/install_macmini_operation_launchd.zsh
  echo
  echo "== 6. 安装后复查 =="
  /bin/zsh scripts/check_macmini_ai_center.zsh
else
  echo
  echo "未安装生产定时任务。如检查提示缺少 launchd 标签，并确认要启用生产定时任务，请追加 --install-launchd。"
fi

echo
echo "Mac mini 拉取并只读检查完成。"
