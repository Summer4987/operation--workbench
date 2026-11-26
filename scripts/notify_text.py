"""把自动化通知整理成老板能直接读懂的中文：去掉路径、任务ID、代码和异常堆栈。

所有企微推送都经过 ops_notify.notify_with_result → clean()，作为最后一道把关。
只删改技术噪音，不改写数字和门店名。
"""
from __future__ import annotations

import re

MAX_CHARS = 1800  # 与 agent_task_notifier 的分段长度一致，避免截断分段

# 常见技术错误 → 中文说法（只替换错误名本身，不动前后业务文字）
ERROR_WORDS = [
    (r"platform_account_access\.AccountQueueBusy|AccountQueueBusy", "美团账号排队中"),
    (r"AccountVerificationRequired", "美团账号待人工验证"),
    (r"TimeoutError|TimeoutExpired|ETIMEDOUT|net::ERR_TIMED_OUT", "超时"),
    (r"Target page, context or browser has been closed", "页面被意外关闭"),
    (r"ECONNREFUSED|ConnectionRefusedError|net::ERR_CONNECTION_REFUSED", "连接被拒绝"),
    (r"net::ERR_[A-Z_]+", "网络异常"),
    (r"KeyError|IndexError|TypeError|ValueError|AttributeError|RuntimeError|JSONDecodeError", "程序异常"),
]

_PATH = re.compile(r"(?<![\w.:/])(?:~|/Users|/private|/tmp|/opt|/home|/var|/Library|/Applications)/[^\s，。；、,;)）】」\"']*")
_TASK_ID = re.compile(
    r"(?<![\w./])(?:schedule\.)?(?:com\.(?:summer|xiongxiaoxiao)\.[\w.\-]+"
    r"|(?:ops|growth|promotion|inventory|morning|finance|schedule)\.[a-z][a-z0-9_]*(?:\.[a-z0-9_\-]+)*)"
)
_CODE_LINE = re.compile(
    r"^\s*(?:[{\[]|Traceback|File \"|raise |at [\w.$<>]+ \(|\w+(?:Error|Exception):|>>>|\$ |"
    r"(?:python3?|node|zsh|bash|/bin/\w+)\s)"
)
_COMMAND_HINT = re.compile(r"(?:；|;)?\s*命令\s*[:：]?\s*\S.*$")
_LEGACY = re.compile(r"[^。；\n]*(?:Hermes|WorkBuddy)[^。；\n]*[。；]?")
_SPACED_DIRS = ("Application Support", "New project", "Mobile Documents")
_SNAKE = re.compile(r"(?<![\w./:-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w./-])")
_STATUS_WORDS = {"failed": "失败", "success": "成功", "skipped": "跳过", "warning": "注意", "missing": "缺少记录"}
_EVIDENCE = re.compile(r"(?:查看(?:证据包|证据|日志)|证据包|证据|详情见|详见)\s*[:：]?\s*(?=$|[；;。\n])")


def _clean_line(line: str) -> str:
    if _CODE_LINE.match(line):
        return ""
    line = line.replace("`", "")
    for name in _SPACED_DIRS:
        line = line.replace(name, name.replace(" ", "_"))
    line = re.sub(r"失败分类(?:是|：|:)\s*\S+?[。；;]?$", "", line)
    for pattern, word in ERROR_WORDS:
        line = re.sub(pattern, word, line)
    line = _COMMAND_HINT.sub("", line)
    line = _LEGACY.sub("", line)
    line = _PATH.sub("", line)
    line = _TASK_ID.sub("", line)
    line = _SNAKE.sub("", line)
    line = re.sub(r"(?<![A-Za-z])(failed|success|skipped|warning|missing)(?![A-Za-z])", lambda m: _STATUS_WORDS[m.group(1)], line)
    line = _EVIDENCE.sub("", line)
    line = re.sub(r"[（(]\s*[)）]", "", line)
    line = re.sub(r"\s*([；;，,])\s*(?=[；;，,。]|$)", "", line)
    line = re.sub(r"[ \t]{2,}", " ", line).strip()
    line = re.sub(r"^[；;，,：:]+|[；;，,：:]+$", "", line).strip()
    return line


def clean(text: str) -> str:
    lines, dropped = [], False
    for raw in str(text or "").splitlines():
        if not raw.strip():
            if lines and lines[-1] != "":
                lines.append("")
            continue
        line = _clean_line(raw)
        if line:
            lines.append(line)
        else:
            dropped = True
    while lines and lines[-1] == "":
        lines.pop()
    result = "\n".join(lines).strip()
    if dropped and "技术细节已省略" not in result:
        result += "\n（技术细节已省略，可在运营看板查看。）"
    if len(result) > MAX_CHARS:
        result = result[: MAX_CHARS - 20].rstrip() + "\n……（内容过长已截断）"
    return result or "运营自动化通知"
