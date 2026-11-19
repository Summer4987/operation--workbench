from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from longxia_promo_snapshot import read_balance_items

import cdp_eleme_balance
import cdp_meituan_balance
import cdp_direct_meituan_balance
from parse_balance_ocr import build_result, write_outputs
from balance_coverage import (
    DIRECT_ELEME_STORES,
    DIRECT_MEITUAN_CHAIN_STORES,
    aliases_for_direct_store,
    apply_direct_coverage,
    item_matches_store,
)


ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = ROOT / "cdp-latest.json"
OUTPUT_DATA_JS = ROOT / "cdp-latest-data.js"
THRESHOLD = 200.0


def run_isolated_collector(script: Path, output_path: Path, *args: str) -> dict:
    """Run each Playwright collector in its own process.

    Playwright's CDP driver is not reliably restartable in the same Python
    process on the production Mac. Isolation also ensures one platform closing
    its driver cannot silently stop the remaining platform patrols.
    """
    started_at = time.time()
    result = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
        start_new_session=True,
    )
    output = (result.stdout or "").strip()
    if output:
        print(output, flush=True)
    if result.returncode != 0:
        raise RuntimeError(output or f"{script.name} 退出码 {result.returncode}")
    if not output_path.exists() or output_path.stat().st_mtime < started_at - 1:
        raise RuntimeError(f"{script.name} 没有生成本轮余额结果。")
    return json.loads(output_path.read_text(encoding="utf-8"))


def collect_eleme() -> tuple[list[dict], str]:
    payload = run_isolated_collector(
        Path(cdp_eleme_balance.__file__),
        cdp_eleme_balance.OUTPUT_JSON,
    )
    items = payload.get("items") or []
    if not items:
        raise RuntimeError("饿了么 CDP 接口没有读取到门店余额。")
    response_url = str(payload.get("response_url") or "")
    return items, response_url.split("?")[0] if response_url else ""


def collect_meituan() -> tuple[list[dict], str]:
    raise RuntimeError("美团推广读取已统一交由龙虾店长；禁止独立逐店余额采集。")


def collect_direct_meituan() -> tuple[list[dict], str]:
    raise RuntimeError("美团推广读取已统一交由龙虾店长；禁止独立逐店余额采集。")


def is_direct_meituan_item(item: dict) -> bool:
    return any(
        item_matches_store(item, "美团", aliases_for_direct_store("meituan", store))
        for store in DIRECT_ELEME_STORES
        if store not in DIRECT_MEITUAN_CHAIN_STORES
    )


def write_test_outputs(data: dict) -> None:
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_DATA_JS.write_text(
        "window.CDP_INSPECTION_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def reuse_eleme_balances() -> tuple[list[dict], str]:
    payload = json.loads((ROOT / "latest.json").read_text(encoding="utf-8"))
    items = []
    for row in payload.get("items", []):
        if row.get("platform") != "饿了么":
            continue
        captured = row.get("collected_at") or payload.get("generated_at")
        try:
            age = datetime.now() - datetime.strptime(captured, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        if timedelta(minutes=-1) <= age <= timedelta(minutes=90):
            items.append({**row, "collected_at": captured})
    if not items:
        raise RuntimeError("饿了么余额快照缺失或超过90分钟；等待原采集任务，不占用生产浏览器。")
    return items, ""


def collect_all_balances(*, fleet_only=False) -> tuple[dict, bool]:
    items: list[dict] = []
    errors: list[str] = []
    source_urls: dict[str, str] = {}

    for platform_name, collector in [
        ("饿了么", reuse_eleme_balances if fleet_only else collect_eleme),
    ]:
        try:
            platform_items, source_url = collector()
            if platform_name == "美团":
                direct_items = [item for item in platform_items if is_direct_meituan_item(item)]
                if direct_items:
                    print(f"美团 CDP 跳过直营自动扣款门店：{len(direct_items)} 条。", flush=True)
                platform_items = [item for item in platform_items if not is_direct_meituan_item(item)]
            items.extend(platform_items)
            source_urls[platform_name] = source_url
            print(f"{platform_name} CDP 完成：{len(platform_items)} 条结果。", flush=True)
        except Exception as exc:
            errors.append(f"{platform_name}：{exc}")
            print(f"{platform_name} CDP 失败：{exc}", flush=True)

    try:
        meituan_items, balance_issues = read_balance_items()
    except Exception as exc:
        meituan_items = []
        balance_issues = [{"platform": "美团", "store_name": "全部门店", "message": str(exc)}]
    items.extend(meituan_items)
    data = apply_direct_coverage(build_result(items, THRESHOLD), {"饿了么", "美团"})
    data["source"] = "cdp_all_balances"
    data["collected_platforms"] = sorted({item["platform"] for item in items})
    data["balance_collection_issues"] = balance_issues
    if balance_issues:
        print(f"美团龙虾余额未核实：{len(balance_issues)} 家。", flush=True)
    print(f"美团龙虾余额完成：{len(meituan_items)} 家；只读本地快照，未启动采集进程。", flush=True)
    data["source_urls"] = source_urls
    data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if errors or balance_issues:
        data["message"] = "；".join(errors)
        data["status"] = "partial" if items else "failed"
    return data, bool(items and not errors and not balance_issues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="读取饿了么和美团 CDP 余额。")
    parser.add_argument("--official", action="store_true", help="写入正式 latest.json/latest-data.js。")
    parser.add_argument("--fleet-only", action="store_true", help="只读取龙虾与仍有效的饿了么本地快照，不启动浏览器或采集进程")
    args = parser.parse_args(argv)

    data, ok = collect_all_balances(fleet_only=args.fleet_only)

    if args.official:
        write_outputs(data)
        output_path = ROOT / "latest.json"
    else:
        write_test_outputs(data)
        output_path = OUTPUT_JSON
    summary = data["summary"]
    print(
        f"CDP 余额总巡检完成：{summary['platform_count']} 个平台，"
        f"{summary['store_count']} 条结果，{summary['warning_count']} 条低余额。",
        flush=True,
    )
    print(f"输出：{output_path}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
