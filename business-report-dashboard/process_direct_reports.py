from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import process_reports as base  # noqa: E402

REPO_ROOT = ROOT.parent
CONFIG_PATH = ROOT / "direct_config.json"
CHAIN_RAW_DIR = ROOT / "data" / "raw"
DIRECT_RAW_DIR = ROOT / "data" / "direct" / "raw"
DATA_DIR = ROOT / "data"
DIRECT_DASHBOARD_DIR = ROOT / "direct-dashboard"
LEGACY_ROOT = Path.home() / "Documents" / "New project" / "business-report-dashboard"
LEGACY_CHAIN_RAW_DIR = LEGACY_ROOT / "data" / "raw"
LEGACY_DIRECT_RAW_DIR = LEGACY_ROOT / "data" / "direct" / "raw"
LEGACY_DATA_DIR = LEGACY_ROOT / "data"
DIRECT_STORE_SLUGS = {
    "朝阳门店": "chaoyangmen",
    "银泰城店": "yintaicheng",
    "万象城店": "wanxiangcheng",
    "金融城店": "jinrongcheng",
    "保利中心店": "baolizhongxin",
}
UNIFIED_COLUMNS = [
    "date",
    "platform",
    "store",
    "store_raw",
    *base.METRICS,
    "customer_paid_available",
    "customer_paid_orders",
]
REVIEW_COLUMNS = [
    "date",
    "platform",
    "store",
    "store_raw",
    "rating",
    "content",
    "review_id",
    "negative",
    "keywords",
    "source_file",
]


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def latest_by_report_date(paths: list[Path], pattern: str) -> list[Path]:
    latest: dict[str, Path] = {}
    for path in paths:
        match = re.search(pattern, path.name)
        key = match.group(1) if match else path.stem
        current = latest.get(key)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            latest[key] = path
    return sorted(latest.values(), key=lambda item: item.stat().st_mtime)


def latest_direct_meituan_paths(paths: list[Path]) -> list[Path]:
    latest: dict[tuple[str, str], Path] = {}
    for path in paths:
        match = re.search(r"门店_全部门店_(\d{8})_\1_([^_]+)_", path.name)
        key = (match.group(1), match.group(2)) if match else (path.stem, "")
        current = latest.get(key)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            latest[key] = path
    return sorted(latest.values(), key=lambda item: item.stat().st_mtime)


def copy_to_raw(path: Path | None, target_dir: Path) -> Path | None:
    if path is None:
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    source = path.expanduser().resolve()
    target = target_dir / source.name
    if source != target.resolve():
        shutil.copy2(source, target)
    return target


def direct_warnings(warnings: list[dict]) -> list[dict]:
    return [item for item in warnings if item.get("issue") != "未匹配到目标门店"]


def collect_eleme_paths(explicit: Path | None) -> list[Path]:
    copied = copy_to_raw(explicit, CHAIN_RAW_DIR)
    paths = [copied] if copied else []
    paths.extend(sorted(CHAIN_RAW_DIR.glob("门店下载_*.xlsx"), key=lambda item: item.stat().st_mtime))
    paths.extend(sorted(LEGACY_CHAIN_RAW_DIR.glob("门店下载_*.xlsx"), key=lambda item: item.stat().st_mtime))
    return latest_by_report_date([path for path in paths if path], r"门店下载_(\d{8})至\1")


def collect_meituan_paths(explicit: Path | None) -> list[Path]:
    copied = copy_to_raw(explicit, DIRECT_RAW_DIR)
    chain_paths = latest_by_report_date(
        sorted(
            (
                path
                for directory in (CHAIN_RAW_DIR, LEGACY_CHAIN_RAW_DIR)
                for path in directory.glob("门店_全部门店_*.csv")
                if "_UTF8" not in path.stem
            ),
            key=lambda item: item.stat().st_mtime,
        ),
        r"门店_全部门店_(\d{8})_\1",
    )
    direct_candidates = [copied] if copied else []
    direct_candidates.extend(
        sorted(
            (
                path
                for directory in (DIRECT_RAW_DIR, LEGACY_DIRECT_RAW_DIR)
                for path in directory.glob("门店_全部门店_*.csv")
                if "_UTF8" not in path.stem
            ),
            key=lambda item: item.stat().st_mtime,
        )
    )
    direct_paths = latest_direct_meituan_paths([path for path in direct_candidates if path])
    return chain_paths + direct_paths


def empty_unified() -> pd.DataFrame:
    return pd.DataFrame(columns=UNIFIED_COLUMNS)


def normalize_unified(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return empty_unified()
    for column in UNIFIED_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0 if column in {*base.METRICS, "customer_paid_orders"} else ""
    return frame[UNIFIED_COLUMNS].copy()


def legacy_output_path(name: str) -> Path | None:
    path = LEGACY_DATA_DIR / name
    return path if path.exists() and path.stat().st_size > 4 else None


def load_legacy_payload() -> dict:
    path = legacy_output_path("direct-latest.json")
    if not path:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def process(eleme_path: Path | None = None, meituan_path: Path | None = None) -> dict:
    config = load_config()
    alias_lookup = base.build_alias_lookup(config)
    base.STORE_SLUGS.update(DIRECT_STORE_SLUGS)

    frames = []
    warnings = []
    for path in collect_eleme_paths(eleme_path):
        frame, frame_warnings = base.read_eleme(path, config, alias_lookup)
        frames.append(frame)
        warnings.extend(direct_warnings(frame_warnings))
    for path in collect_meituan_paths(meituan_path):
        frame, frame_warnings = base.read_meituan(path, config, alias_lookup)
        frames.append(frame)
        warnings.extend(direct_warnings(frame_warnings))

    unified = pd.concat([normalize_unified(frame) for frame in frames], ignore_index=True) if frames else empty_unified()
    if not unified.empty:
        unified = unified[unified["store"].isin(config["target_stores"])].copy()
        unified.sort_values(["date", "store", "platform"], inplace=True)
        unified.drop_duplicates(subset=["date", "platform", "store"], keep="last", inplace=True)
    unified = normalize_unified(unified)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    unified_path = DATA_DIR / "direct_unified_daily.csv"
    unified.to_csv(unified_path, index=False, encoding="utf-8-sig")

    legacy_payload = load_legacy_payload()
    records = unified.to_dict(orient="records")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "group": config["group"],
        "source_dates": sorted([date for date in unified["date"].dropna().unique().tolist() if date]) if not unified.empty else [],
        "target_stores": config["target_stores"],
        "store_summary": base.build_store_summary(unified, config["target_stores"]),
        "platform_summary": base.build_platform_summary(unified),
        "warnings": warnings,
        "records": records,
    }
    if not records and legacy_payload.get("records"):
        payload.update(
            {
                "source_dates": legacy_payload.get("source_dates") or [],
                "store_summary": legacy_payload.get("store_summary") or [],
                "platform_summary": legacy_payload.get("platform_summary") or [],
                "records": legacy_payload.get("records") or [],
                "warnings": warnings
                + [
                    {
                        "issue": "本次未找到 clean repo 原始数据，已沿用旧生产目录 direct-latest.json 作为兜底。",
                        "source": str(legacy_output_path("direct-latest.json") or ""),
                    }
                ],
            }
        )
    payload["store_report_files"] = {store: f"stores/{base.store_slug(store)}.html" for store in config["target_stores"]}
    latest_date = base.latest_report_date(payload)
    review_df = base.read_review_files(alias_lookup)
    if review_df.empty and legacy_output_path("direct_unified_reviews.csv"):
        review_df = pd.read_csv(legacy_output_path("direct_unified_reviews.csv"))
    if review_df.empty:
        review_df = pd.DataFrame(columns=REVIEW_COLUMNS)
    review_df.to_csv(DATA_DIR / "direct_unified_reviews.csv", index=False, encoding="utf-8-sig")
    payload["review_summary"] = base.summarize_reviews(review_df, config["target_stores"], latest_date) if latest_date else {}
    payload["focus_items"] = base.build_all_focus_items(payload, latest_date) if latest_date else []
    payload["all_store_diagnoses"] = base.build_all_store_diagnoses(payload, latest_date) if latest_date else []

    output = DATA_DIR / "direct-latest.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    original_dashboard_dir = base.DASHBOARD_DIR
    try:
        base.DASHBOARD_DIR = DIRECT_DASHBOARD_DIR
        dashboard_path = base.write_dashboard(payload)
        store_report_paths = base.write_store_reports(payload) if latest_date else []
    finally:
        base.DASHBOARD_DIR = original_dashboard_dir

    return {
        "unified_path": str(unified_path),
        "output": str(output),
        "dashboard_path": str(dashboard_path),
        "store_report_paths": [str(path) for path in store_report_paths],
        "payload": payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成直营店日报数据，不覆盖加盟店日报。")
    parser.add_argument("--eleme", type=Path, help="可选：指定饿了么 Excel。默认使用连锁账号历史原始文件。")
    parser.add_argument("--meituan", type=Path, help="可选：指定直营美团 CSV。会复制到 data/direct/raw。")
    args = parser.parse_args()

    result = process(args.eleme, args.meituan)
    payload = result["payload"]
    print(f"已生成直营统一数据：{result['unified_path']}")
    print(f"已生成直营日报数据：{result['output']}")
    print(f"已生成直营网页看板：{result['dashboard_path']}")
    print(f"门店数：{len(payload['store_summary'])}，明细记录：{len(payload['records'])}，提示：{len(payload['warnings'])}")


if __name__ == "__main__":
    main()
