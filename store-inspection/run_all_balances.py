from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from parse_balance_ocr import merge_results, write_outputs


ROOT = Path(__file__).resolve().parent
LATEST_JSON = ROOT / "latest.json"
PYTHON = sys.executable
REPORT_VENV_PYTHON = ROOT.parent / "business-report-dashboard" / ".venv" / "bin" / "python"


def python_for_script(script_name: str) -> str:
    if script_name == "one_click_meituan_balance.py" and REPORT_VENV_PYTHON.exists():
        return str(REPORT_VENV_PYTHON)
    return PYTHON


def run_platform(script_name: str, platform_name: str, *, timeout_seconds: int = 300) -> dict:
    print(f"开始{platform_name}余额巡检...", flush=True)
    before_mtime = LATEST_JSON.stat().st_mtime if LATEST_JSON.exists() else 0
    python = python_for_script(script_name)
    try:
        result = subprocess.run([python, str(ROOT / script_name)], cwd=ROOT.parent, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if LATEST_JSON.exists() and LATEST_JSON.stat().st_mtime > before_mtime:
            data = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
            data["_run_error"] = f"{platform_name}余额巡检超过 {timeout_seconds} 秒，已使用已生成结果。"
            print(f"{platform_name}超时：使用已生成结果。", flush=True)
            return data
        raise RuntimeError(f"{platform_name}余额巡检超过 {timeout_seconds} 秒，未生成可用结果。")
    if not LATEST_JSON.exists() or LATEST_JSON.stat().st_mtime <= before_mtime:
        raise RuntimeError(f"{platform_name}没有生成本次巡检结果。")
    data = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    item_count = len(data.get("items", []))
    if result.returncode != 0:
        message = data.get("message") or f"{platform_name}余额巡检失败。"
        if item_count == 0:
            raise RuntimeError(message)
        data["_run_error"] = message
    print(f"{platform_name}完成：{item_count} 条结果。", flush=True)
    return data


def main() -> int:
    results = []
    errors = []
    for script_name, platform_name in [
        ("one_click_eleme_balance.py", "饿了么"),
        ("one_click_meituan_balance.py", "美团"),
    ]:
        try:
            data = run_platform(script_name, platform_name)
            results.append(data)
            if data.get("_run_error"):
                errors.append(f"{platform_name}：{data['_run_error']}")
        except Exception as exc:
            errors.append(f"{platform_name}：{exc}")
            print(f"{platform_name}失败：{exc}", file=sys.stderr, flush=True)

    data = merge_results(results)
    if errors:
        data["message"] = "；".join(errors)
        data["status"] = "partial" if data.get("items") else "failed"
    write_outputs(data)

    summary = data["summary"]
    summary_text = (
        f"{summary['platform_count']} 个平台，"
        f"{summary['store_count']} 条结果，{summary['warning_count']} 条低余额。"
    )
    if errors:
        print(f"余额总巡检失败：{summary_text}", flush=True)
    else:
        print(f"余额总巡检完成：{summary_text}", flush=True)
    return 0 if data.get("items") and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
