#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text

import private_spreadsheet_assistant


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = Path.home() / "HermesPrivate" / "logs" / "spreadsheet_delivery"
DEFAULT_TARGET = "weixin"
DEFAULT_HERMES_BIN = Path.home() / ".local" / "bin" / "hermes"


def send_with_retry(
    message: str,
    *,
    target: str,
    hermes_bin: Path,
    attempts: int,
    delay_seconds: int,
) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            [str(hermes_bin), "send", "--to", target, message],
            cwd=str(ROOT),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=90,
        )
        output = (result.stdout or "").strip()
        if result.returncode == 0:
            return {
                "delivered": True,
                "attempt": attempt,
                "output": output,
                "errors": errors,
            }
        errors.append(f"attempt {attempt}: {output or 'no output'}")
        if attempt < attempts:
            time.sleep(delay_seconds)
    return {
        "delivered": False,
        "attempt": attempts,
        "output": errors[-1] if errors else "",
        "errors": errors,
    }


def build_delivery_message(result: dict[str, Any]) -> str:
    output_path = str(result["output_path"])
    return "\n".join(
        [
            "表格已处理完成，文件见附件。",
            f"新增内容：{result['date']}｜{result['name']}｜{result['quantity']:g}{result['unit']}｜商品编码 {result['sku']}",
            f"文件路径：{output_path}",
            f"MEDIA:{output_path}",
        ]
    )


def process_and_send(args: argparse.Namespace) -> dict[str, Any]:
    text = " ".join(args.text)
    request = private_spreadsheet_assistant.parse_inbound_reservation(text)
    result = private_spreadsheet_assistant.write_inbound_reservation(request)
    delivery = send_with_retry(
        build_delivery_message(result),
        target=args.target,
        hermes_bin=Path(args.hermes_bin).expanduser(),
        attempts=args.attempts,
        delay_seconds=args.delay_seconds,
    )
    payload = {
        "input_text": text,
        "result": result,
        "delivery": delivery,
    }
    log_dir = Path(args.log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{Path(result['output_path']).stem}.json"
    atomic_write_text(log_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    payload["log_path"] = str(log_path)
    return payload


def format_summary(payload: dict[str, Any]) -> str:
    result = payload["result"]
    delivery = payload["delivery"]
    lines = [
        "表格后台处理完成。",
        f"新文件：{result['output_path']}",
        f"发送附件：{'成功' if delivery['delivered'] else '失败'}",
        f"发送尝试：{delivery['attempt']} 次",
        f"日志：{payload['log_path']}",
    ]
    if not delivery["delivered"]:
        lines.append(f"最后错误：{delivery.get('output', '')}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="处理私人表格任务并通过 Hermes 微信回传")
    parser.add_argument("text", nargs="+")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--hermes-bin", default=str(DEFAULT_HERMES_BIN))
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--delay-seconds", type=int, default=35)
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = process_and_send(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_summary(payload))
    return 0 if payload["delivery"]["delivered"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
