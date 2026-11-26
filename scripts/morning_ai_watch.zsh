#!/bin/zsh
# 上午运营失败后、自动续跑前，唤醒 Codex 排除现场环境问题（弹窗、卡顿、Chrome 无响应等）。
# 任何前置条件不满足都只记日志并返回 0；真正唤醒过 Codex 返回 10。绝不阻塞原有续跑流程。
# 规则见 docs/MORNING_AI_WATCH.md。
set -uo pipefail

ROOT="${OPERATION_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LOG_DIR="$HOME/Library/Logs/xiong-operation/ai-watch"
STATE_DIR="$ROOT/outputs/morning_ai_watch"
mkdir -p "$LOG_DIR" "$STATE_DIR"
TODAY="$(date +%F)"
TS="$(date +%F-%H%M%S)"
SCHED_LOG="$HOME/Library/Logs/xiong-operation/morning/scheduler.log"

note() { echo "[$(date '+%F %T')] AI值守：$*" | tee -a "$LOG_DIR/watch.log" >> "$SCHED_LOG"; }

if [[ "${MORNING_AI_WATCH_ENABLED:-1}" != "1" || -e "$ROOT/config/morning_ai_watch.disabled" ]]; then
  note "已关闭，跳过。"; exit 0
fi

COUNT_FILE="$STATE_DIR/$TODAY.count"
count="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
if (( count >= ${MORNING_AI_WATCH_MAX_RUNS:-3} )); then
  note "今天已运行 $count 次，达到上限，跳过。"; exit 0
fi

# 与企微值守请求共用一把锁，同一时间只跑一个 Codex。
LOCK="$ROOT/outputs/ai_watch/lock"
mkdir -p "$ROOT/outputs/ai_watch"
if ! mkdir "$LOCK" 2>/dev/null; then
  holder="$(cat "$LOCK/pid" 2>/dev/null || echo)"
  if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
    note "企微值守正在处理其它请求，本轮跳过。"; exit 0
  fi
  rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || { note "值守锁不可用，跳过。"; exit 0; }
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

GUARD="$ROOT/outputs/platform_auth_guard/meituan.json"
if [[ -r "$GUARD" ]] && grep -q '"status": *"blocked"' "$GUARD"; then
  note "美团处于人工安全验证暂停，需要人工处理，AI 不介入（已有暂停通知）。"; exit 0
fi

CODEX="${CODEX_WATCH_BIN:-}"
# 只用独立安装的新版 Codex 命令行；Codex.app 自带的旧版不支持当前模型。
for candidate in "$HOME/Library/Application Support/xiong-operation/codex-cli/codex"; do
  [[ -n "$CODEX" ]] && break
  [[ -x "$candidate" ]] && CODEX="$candidate"
done
if [[ -z "$CODEX" || ! -x "$CODEX" ]]; then
  note "未找到 Codex 命令行，跳过。"; exit 0
fi

PROXY="${CODEX_WATCH_PROXY:-http://127.0.0.1:7897}"
if ! /usr/bin/curl -s -o /dev/null --max-time 8 -x "$PROXY" https://chatgpt.com; then
  note "Codex 专用代理不可用（$PROXY），跳过。"; exit 0
fi

echo $(( count + 1 )) > "$COUNT_FILE"
note "第 $(( count + 1 )) 次唤醒 Codex 处理失败项。"

PROMPT_FILE="$STATE_DIR/prompt-$TS.md"
{
  cat "$ROOT/docs/MORNING_AI_WATCH.md"
  echo
  echo "## 本次上下文"
  echo "- 生产目录（当前工作目录）：$ROOT"
  echo "- 今天：$TODAY，现在：$(date '+%H:%M')；续跑窗口到 10:50"
  echo "- 今天第 $(( count + 1 )) 次唤醒；之前的处理记录在 $LOG_DIR/ 下以 $TODAY 开头的文件"
} > "$PROMPT_FILE"

OUT="$LOG_DIR/$TS.summary.md"
RUN_LOG="$LOG_DIR/$TS.log"
model_args=()
[[ -n "${CODEX_WATCH_MODEL:-}" ]] && model_args=(-m "$CODEX_WATCH_MODEL")

# 只有 Codex 自身走代理；它启动的命令（会访问美团/饿了么）剔除代理变量，保持国内直连。
env HTTPS_PROXY="$PROXY" HTTP_PROXY="$PROXY" ALL_PROXY="$PROXY" NO_PROXY="localhost,127.0.0.1,::1" \
  "$CODEX" exec "${model_args[@]}" -C "$ROOT" -s danger-full-access --skip-git-repo-check \
  -c 'shell_environment_policy.exclude=["*PROXY*","*proxy*"]' \
  -o "$OUT" - < "$PROMPT_FILE" > "$RUN_LOG" 2>&1 &
pid=$!
limit="${MORNING_AI_WATCH_TIMEOUT_SECONDS:-1080}"
waited=0
while kill -0 "$pid" 2>/dev/null && (( waited < limit )); do sleep 5; waited=$(( waited + 5 )); done
if kill -0 "$pid" 2>/dev/null; then
  kill -TERM "$pid" 2>/dev/null; sleep 3; kill -KILL "$pid" 2>/dev/null
  note "Codex 超过 ${limit}s 未结束，已终止。日志：$RUN_LOG"
fi
wait "$pid" 2>/dev/null
rc=$?
if [[ -s "$OUT" ]]; then
  { echo "[$(date '+%F %T')] AI值守结果（退出码 $rc）："; sed 's/^/  /' "$OUT"; } | tee -a "$LOG_DIR/watch.log" >> "$SCHED_LOG"
else
  note "Codex 未产出结论（退出码 $rc），日志：$RUN_LOG"
fi
# 10 = 本次确实唤醒过 Codex，包装脚本据此缩短续跑等待。
exit 10
