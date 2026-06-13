from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import cdp_eleme_balance
import cdp_meituan_balance
from parse_balance_ocr import build_result


ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = ROOT / "cdp-latest.json"
OUTPUT_DATA_JS = ROOT / "cdp-latest-data.js"
THRESHOLD = 200.0


def collect_eleme() -> tuple[list[dict], str]:
    payload, response_url = cdp_eleme_balance.collect_balance_payload()
    items = cdp_eleme_balance.parse_shop_rows(payload or {})
    if not items:
        raise RuntimeError("饿了么 CDP 接口没有读取到门店余额。")
    return items, response_url.split("?")[0] if response_url else ""


def collect_meituan() -> tuple[list[dict], str]:
    items, _network_candidates, base_url = cdp_meituan_balance.collect_balances()
    ok_items = [item for item in items if not item.get("error")]
    if not ok_items:
        raise RuntimeError("美团 CDP 接口没有读取到门店余额。")
    if len(ok_items) < len(items):
        missing = len(items) - len(ok_items)
        raise RuntimeError(f"美团 CDP 有 {missing} 家门店未解析到账户余额。")
    return ok_items, base_url.split("?")[0] if base_url else ""


def write_test_outputs(data: dict) -> None:
    OUTPUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_DATA_JS.write_text(
        "window.CDP_INSPECTION_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def main() -> int:
    items: list[dict] = []
    errors: list[str] = []
    source_urls: dict[str, str] = {}

    for platform_name, collector in [
        ("饿了么", collect_eleme),
        ("美团", collect_meituan),
    ]:
        try:
            platform_items, source_url = collector()
            items.extend(platform_items)
            source_urls[platform_name] = source_url
            print(f"{platform_name} CDP 完成：{len(platform_items)} 条结果。", flush=True)
        except Exception as exc:
            errors.append(f"{platform_name}：{exc}")
            print(f"{platform_name} CDP 失败：{exc}", flush=True)

    data = build_result(items, THRESHOLD)
    data["source"] = "cdp_all_balances"
    data["source_urls"] = source_urls
    data["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if errors:
        data["message"] = "；".join(errors)
        data["status"] = "partial" if items else "failed"

    write_test_outputs(data)
    summary = data["summary"]
    print(
        f"CDP 余额总巡检完成：{summary['platform_count']} 个平台，"
        f"{summary['store_count']} 条结果，{summary['warning_count']} 条低余额。",
        flush=True,
    )
    print(f"测试输出：{OUTPUT_JSON}", flush=True)
    return 0 if items and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
