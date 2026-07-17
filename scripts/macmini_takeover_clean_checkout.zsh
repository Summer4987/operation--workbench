#!/bin/zsh
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SOURCE_ROOT"

REMOTE="${MACMINI_DEPLOY_REMOTE:-origin}"
BRANCH="${MACMINI_DEPLOY_BRANCH:-main}"
CLEAN_DIR="${MACMINI_TAKEOVER_DIR:-$HOME/Library/Application Support/xiong-operation/production}"
REMOTE_URL="${MACMINI_TAKEOVER_REMOTE_URL:-}"
SHOW_TASK=1

usage() {
  cat <<'EOF'
用法：/bin/zsh scripts/macmini_takeover_clean_checkout.zsh [选项]

选项：
  --remote NAME        Git 远端名，默认 origin
  --branch NAME        Git 分支名，默认 main
  --clean-dir PATH     干净交接仓库目录，默认 ~/Library/Application Support/xiong-operation/production
  --remote-url URL     首次 clone 使用的 Git 地址，默认读取当前仓库 remote
  --no-show-task       只准备仓库，不打印 docs/MACMINI_NEXT_TASK.md
EOF
}

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
    --clean-dir)
      CLEAN_DIR="$2"
      shift 2
      ;;
    --remote-url)
      REMOTE_URL="$2"
      shift 2
      ;;
    --no-show-task)
      SHOW_TASK=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$REMOTE_URL" ]]; then
  REMOTE_URL="$(git remote get-url "$REMOTE")"
fi

echo "== Mac mini Codex 干净接管准备 =="
echo "源目录：$SOURCE_ROOT"
echo "交接目录：$CLEAN_DIR"
echo "远端：$REMOTE_URL"
echo "分支：$BRANCH"
echo

mkdir -p "$(dirname "$CLEAN_DIR")"

if [[ -e "$CLEAN_DIR" && ! -d "$CLEAN_DIR/.git" ]]; then
  echo "拒绝继续：交接目录已存在但不是 Git 仓库。"
  echo "请先人工检查：$CLEAN_DIR"
  exit 65
fi

if [[ ! -d "$CLEAN_DIR/.git" ]]; then
  echo "== 1. 创建干净交接仓库 =="
  git clone --branch "$BRANCH" "$REMOTE_URL" "$CLEAN_DIR"
else
  echo "== 1. 检查干净交接仓库 =="
  cd "$CLEAN_DIR"
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "拒绝继续：干净交接仓库存在未提交或未跟踪改动。"
    echo "请先把下面状态发给 Codex 判断，不要强制覆盖："
    git status --short --branch
    exit 64
  fi

  if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
    git remote add "$REMOTE" "$REMOTE_URL"
  else
    git remote set-url "$REMOTE" "$REMOTE_URL"
  fi

  echo
  echo "== 2. 获取 GitHub 最新 main =="
  git fetch "$REMOTE" "$BRANCH"

  echo
  echo "== 3. 切换并 fast-forward =="
  git checkout "$BRANCH"
  git merge --ff-only "$REMOTE/$BRANCH"
fi

cd "$CLEAN_DIR"

echo
echo "== 当前交接仓库状态 =="
git status --short --branch
git log --oneline -5

if (( SHOW_TASK )); then
  echo
  echo "== Mac mini 下一步任务 =="
  if [[ -f docs/MACMINI_NEXT_TASK.md ]]; then
    cat docs/MACMINI_NEXT_TASK.md
  else
    echo "未找到 docs/MACMINI_NEXT_TASK.md。"
    exit 66
  fi
fi

echo
echo "Mac mini Codex 干净接管准备完成。"
echo "请让 Mac mini 上的 Codex 在下面目录执行任务："
echo "  $CLEAN_DIR"
