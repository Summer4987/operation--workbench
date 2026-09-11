from __future__ import annotations

import argparse
from datetime import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_PATH = ROOT / "outputs" / "promo_budget_preview" / "latest.json"
ELEME_DIR = ROOT / "outputs" / "dianjin_automation"
MEITUAN_DIR = ROOT / "outputs" / "meituan_budget_automation"
OUTPUT_PATH = ROOT / "outputs" / "promo_budget_result" / "latest.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def expected_tasks(preview: dict[str, Any], platform: str, period: str) -> list[dict[str, Any]]:
    suffix = "dinner" if period == "晚餐" else "lunch"
    key = f"{platform}_{suffix}"
    return [
        item
        for item in preview.get(key, [])
        if isinstance(item, dict) and item.get("status") in {"auto", "scheduled"}
    ]


def task_key(item: dict[str, Any], platform: str) -> str:
    if platform == "eleme":
        return str(item.get("shopId") or item.get("shop_id") or item.get("store") or "")
    return str(item.get("keyword") or item.get("store") or "")


def task_name(item: dict[str, Any]) -> str:
    return str(item.get("keyword") or item.get("store") or item.get("sourceStore") or "未知门店")


def recent_payloads(directory: Path, pattern: str, since_epoch: float) -> list[dict[str, Any]]:
    paths = [path for path in directory.glob(pattern) if path.is_file() and path.stat().st_mtime >= since_epoch]
    return [read_json(path) for path in sorted(paths, key=lambda path: path.stat().st_mtime)]


def summarize_platform(
    platform: str,
    expected: list[dict[str, Any]],
    payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        if payload.get("mode") != "commit" or payload.get("preflight"):
            continue
        for result in payload.get("results") or []:
            if not isinstance(result, dict):
                continue
            key = task_key(result, platform)
            if key:
                latest[key] = result

    success_names: list[str] = []
    failed_names: list[str] = []
    failure_details: list[dict[str, str]] = []
    for task in expected:
        key = task_key(task, platform)
        result = latest.get(key)
        name = task_name(task)
        if result and result.get("ok"):
            success_names.append(name)
            continue
        failed_names.append(name)
        if result:
            failure_details.append(
                {
                    "store": name,
                    "failure_type": str(result.get("failure_type") or "execution_failed"),
                    "error": str(result.get("error") or result.get("message") or ""),
                }
            )
        else:
            failure_details.append({"store": name, "failure_type": "not_executed", "error": "未看到真实提交成功记录"})

    total = len(expected)
    success_count = len(success_names)
    failed_count = len(failed_names)
    return {
        "status": "success" if total > 0 and failed_count == 0 else "failed",
        "total": total,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_stores": success_names,
        "failed_stores": failed_names,
        "failure_details": failure_details,
    }


def build_message(period: str, platforms: dict[str, dict[str, Any]]) -> str:
    lines = [f"【{period}推广预算执行结果】"]
    for key, label in (("eleme", "饿了么"), ("meituan", "美团")):
        row = platforms[key]
        status = "成功" if row["status"] == "success" else "有失败"
        line = f"{label}：{status}；成功 {row['success_count']}/{row['total']} 家"
        if row["failed_count"]:
            line += f"；失败 {row['failed_count']} 家（{'、'.join(row['failed_stores'])}）"
        lines.append(line)
    if any(row["failed_count"] for row in platforms.values()):
        lines.append("失败门店已隔离，不影响后续其他门店；请处理登录态或页面异常后再单店补跑。")
    else:
        lines.append("两平台全部门店均已完成真实提交并读回验证。")
    return "\n".join(lines)


def build_result(period: str, since_epoch: float) -> dict[str, Any]:
    preview = read_json(PREVIEW_PATH)
    platforms = {
        "eleme": summarize_platform(
            "eleme",
            expected_tasks(preview, "eleme", period),
            recent_payloads(ELEME_DIR, "eleme_execution_commit_*.json", since_epoch),
        ),
        "meituan": summarize_platform(
            "meituan",
            expected_tasks(preview, "meituan", period),
            recent_payloads(MEITUAN_DIR, f"meituan_cdp_{period}_*.json", since_epoch),
        ),
    }
    message = build_message(period, platforms)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "period": period,
        "since_epoch": since_epoch,
        "status": "success" if all(row["status"] == "success" for row in platforms.values()) else "failed",
        "platforms": platforms,
        "message": message,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="汇总本轮饿了么和美团推广预算真实提交结果。")
    parser.add_argument("--period", choices=("午餐", "晚餐"), required=True)
    parser.add_argument("--since-epoch", type=float, required=True)
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--print-message", action="store_true")
    parser.add_argument("--record", action="store_true", help="把真实结果写入预算任务账本，不执行预算")
    parser.add_argument("--log-path", default="")
    args = parser.parse_args()
    payload = build_result(args.period, args.since_epoch)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.record:
        subprocess.run([
            sys.executable, str(ROOT / "scripts" / "record_task_run.py"),
            "growth.promo_budget", payload["status"],
            "--message", payload["message"],
            "--step", f"{args.period}推广预算双平台汇总",
            "--log-path", args.log_path or str(output),
            "--returncode", "0" if payload["status"] == "success" else "1",
        ], check=True, timeout=30)
    if args.print_message:
        print(payload["message"])
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
