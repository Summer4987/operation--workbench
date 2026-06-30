from __future__ import annotations

import argparse
import json
import sys

from task_run_state import classify_failure_text, record_task_event


def main() -> int:
    parser = argparse.ArgumentParser(description="记录 AI 业务中心任务运行状态")
    parser.add_argument("task_id", help="任务注册表里的任务 ID")
    parser.add_argument("status", choices=["running", "success", "failed", "skipped"], help="任务状态")
    parser.add_argument("--message", default="", help="状态说明")
    parser.add_argument("--step", default="", help="当前步骤")
    parser.add_argument("--log-path", default="", help="日志路径")
    parser.add_argument("--returncode", type=int, default=None, help="退出码")
    parser.add_argument("--failure-type", default="", help="失败分类")
    parser.add_argument("--extra", action="append", default=[], help="附加字段，格式 key=value，可重复")
    parser.add_argument("--extra-json", default="", help="附加字段 JSON 对象")
    args = parser.parse_args()
    failure_type = args.failure_type
    if args.status == "failed" and not failure_type:
        failure_type = classify_failure_text(args.message, args.returncode)
    extra = {}
    if args.extra_json:
        parsed = json.loads(args.extra_json)
        if not isinstance(parsed, dict):
            raise ValueError("--extra-json must be a JSON object")
        extra.update(parsed)
    for item in args.extra:
        if "=" not in item:
            raise ValueError("--extra must use key=value")
        key, value = item.split("=", 1)
        extra[key] = value
    record_task_event(
        args.task_id,
        args.status,
        message=args.message,
        step=args.step,
        log_path=args.log_path,
        returncode=args.returncode,
        failure_type=failure_type,
        extra=extra or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
