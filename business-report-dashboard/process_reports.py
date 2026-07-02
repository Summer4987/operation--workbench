from __future__ import annotations

import argparse
import glob
import html as html_lib
import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DASHBOARD_DIR = ROOT / "dashboard"

METRICS = [
    "orders",
    "income",
    "customer_paid",
    "impressions",
    "visit_conversion",
    "order_conversion",
    "old_customer_order_conversion",
    "new_customer_order_conversion",
    "old_customer_orders",
    "new_customer_orders",
]

DISPLAY_COLUMNS = {
    "orders": "单量",
    "income": "收入",
    "customer_paid": "顾客实付",
    "impressions": "曝光量",
    "visit_conversion": "进店转化率",
    "order_conversion": "下单转化率",
    "old_customer_order_conversion": "老客下单转化率",
    "new_customer_order_conversion": "新客下单转化率",
    "old_customer_orders": "下单老客",
    "new_customer_orders": "下单新客",
}

OPTIONAL_METRICS = {"customer_paid"}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"[\s·（）()【】\[\]_\-—]+", "", text).lower()


def parse_date(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text
    return parsed.strftime("%Y-%m-%d")


def to_number(value: object, default: float = 0.0) -> float:
    if pd.isna(value) or value == "":
        return default
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return default
    return float(numeric)


def source_value(source: pd.Series, columns: object) -> tuple[object, bool]:
    if isinstance(columns, list):
        for column in columns:
            if column in source.index:
                return source.get(column), True
        return None, False
    return source.get(columns), columns in source.index


def build_alias_lookup(config: dict) -> dict[str, list[tuple[str, str]]]:
    lookup: dict[str, list[tuple[str, str]]] = {}
    for item in config["store_aliases"]:
        platform = item["platform"]
        for alias in item["aliases"]:
            lookup.setdefault(platform, []).append((normalize_text(alias), item["short_name"]))
    return lookup


def match_store(platform: str, raw_name: object, alias_lookup: dict[str, list[tuple[str, str]]]) -> str | None:
    normalized = normalize_text(raw_name)
    matches: list[tuple[int, str]] = []
    for alias, short_name in alias_lookup.get(platform, []):
        if alias and alias in normalized:
            matches.append((len(alias), short_name))
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


REVIEW_RAW_DIR = DATA_DIR / "reviews" / "raw"
REVIEW_ISSUE_PATTERNS = {
    "口味": ["不好吃", "难吃", "腥", "异味", "怪味", "不新鲜"],
    "分量": ["太少", "少了", "分量少", "量少"],
    "漏放": ["漏", "没放", "少送", "缺"],
    "配送": ["太慢", "很慢", "送慢", "凉了", "冷了", "洒了"],
    "口感": ["太硬", "有点硬", "不够软", "太咸", "很咸", "太淡", "油腻"],
    "包装": ["包装破", "包装漏", "撒了", "洒了", "餐盒破"],
    "服务": ["态度差", "服务差", "不满意", "失望", "差评"],
    "异物": ["头发", "虫", "壳", "异物"],
}


def find_column(columns: list[str], names: list[str]) -> str | None:
    for name in names:
        for column in columns:
            if name in str(column):
                return column
    return None


def review_issue_keywords(text: str) -> list[str]:
    normalized = text.strip()
    issues: list[str] = []
    for label, patterns in REVIEW_ISSUE_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            issues.append(label)
    return issues


def review_source_paths() -> list[Path]:
    candidates: list[Path] = []
    for directory in [REVIEW_RAW_DIR, Path.home() / "Downloads"]:
        if not directory.exists():
            continue
        for pattern in ("*评价*.xlsx", "*评价*.xls", "*评价*.csv", "*评论*.xlsx", "*评论*.xls", "*评论*.csv"):
            candidates.extend(path for path in directory.glob(pattern) if path.is_file())
    by_name: dict[str, Path] = {}
    for path in sorted(candidates, key=lambda item: item.stat().st_mtime):
        by_name[path.name] = path
    return sorted(by_name.values(), key=lambda path: path.stat().st_mtime)


def read_review_table(path: Path) -> pd.DataFrame | None:
    try:
        if path.suffix.lower() in {".xlsx", ".xls"}:
            excel = pd.ExcelFile(path)
            preferred = "data" if "data" in excel.sheet_names else excel.sheet_names[0]
            return pd.read_excel(path, sheet_name=preferred)
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return pd.read_csv(path, encoding=encoding)
            except UnicodeDecodeError:
                continue
    except Exception:
        return None
    return None


def review_platform_from_file(path: Path, source: pd.Series, store_col: str, alias_lookup: dict[str, list[tuple[str, str]]]) -> str:
    name = path.name
    if "美团" in name or "外卖评价统计" in name or name.startswith("评价_全部门店_"):
        return "美团"
    if "饿了么" in name or name.startswith("评价下载_"):
        return "饿了么"
    channel_col = find_column([str(column) for column in source.index], ["渠道", "平台", "来源"])
    channel = str(source.get(channel_col, "")) if channel_col else ""
    if "美团" in channel:
        return "美团"
    if "饿了么" in channel or "淘宝" in channel or "闪购" in channel:
        return "饿了么"
    store_name = source.get(store_col, "")
    if match_store("美团", store_name, alias_lookup):
        return "美团"
    return "饿了么"


def read_review_files(alias_lookup: dict[str, list[tuple[str, str]]]) -> pd.DataFrame:
    rows: list[dict] = []
    for path in review_source_paths():
        df = read_review_table(path)
        if df is None or df.empty:
            continue
        columns = [str(column) for column in df.columns]
        date_col = find_column(columns, ["评价时间", "评论时间", "日期", "时间"])
        store_col = find_column(columns, ["门店名称", "门店", "商家名称", "店铺名称", "店名"])
        rating_col = find_column(columns, ["综合评分", "总体评分", "商家评分", "评分", "星级"])
        content_col = find_column(columns, ["评价内容", "评论内容", "顾客评价", "用户评价", "内容"])
        review_id_col = find_column(columns, ["评价id", "评价ID", "评论id", "评论ID", "订单评价id", "id"])
        if not date_col or not store_col or (not rating_col and not content_col):
            continue
        REVIEW_RAW_DIR.mkdir(parents=True, exist_ok=True)
        target = REVIEW_RAW_DIR / path.name
        if path.resolve() != target.resolve() and not target.exists():
            shutil.copy2(path, target)
        for _, source in df.iterrows():
            platform = review_platform_from_file(path, source, store_col, alias_lookup)
            store = match_store(platform, source.get(store_col, ""), alias_lookup)
            if not store:
                fallback = "美团" if platform == "饿了么" else "饿了么"
                store = match_store(fallback, source.get(store_col, ""), alias_lookup)
                if store:
                    platform = fallback
            if not store:
                continue
            content = "" if not content_col or pd.isna(source.get(content_col, "")) else str(source.get(content_col, "")).strip()
            rating = to_number(source.get(rating_col), default=0.0) if rating_col else 0.0
            keywords = review_issue_keywords(content)
            review_id = "" if not review_id_col or pd.isna(source.get(review_id_col, "")) else str(source.get(review_id_col, "")).strip()
            rows.append(
                {
                    "date": parse_date(source.get(date_col)),
                    "platform": platform,
                    "store": store,
                    "store_raw": str(source.get(store_col, "")),
                    "rating": rating,
                    "content": content,
                    "review_id": review_id,
                    "negative": bool((rating and rating <= 3) or keywords),
                    "keywords": keywords,
                    "source_file": path.name,
                }
            )
    review_df = pd.DataFrame(rows)
    if review_df.empty:
        return review_df
    with_id = review_df["review_id"].astype(str).str.strip() != ""
    deduped_parts = []
    if with_id.any():
        deduped_parts.append(review_df[with_id].drop_duplicates(subset=["platform", "review_id"], keep="last"))
    if (~with_id).any():
        deduped_parts.append(
            review_df[~with_id].drop_duplicates(
                subset=["date", "platform", "store", "rating", "content"],
                keep="last",
            )
        )
    return pd.concat(deduped_parts, ignore_index=True) if deduped_parts else review_df.iloc[0:0].copy()


def summarize_reviews(review_df: pd.DataFrame, target_stores: list[str], report_date: str) -> dict:
    if review_df.empty:
        return {
            "status": "missing",
            "target_date": report_date,
            "used_date": "",
            "message": "未找到评价导出文件",
            "stores": {},
        }
    available_dates = sorted(date for date in review_df["date"].dropna().unique().tolist() if date)
    if report_date in available_dates:
        used_date = report_date
        status = "ready"
    else:
        return {
            "status": "missing",
            "target_date": report_date,
            "used_date": "",
            "message": f"暂无 {report_date} 评价导出，本次不展示历史评价",
            "stores": {},
        }
    selected = review_df[review_df["date"] == used_date].copy() if used_date else review_df.iloc[0:0].copy()
    stores: dict[str, dict] = {}
    for store in target_stores:
        group = selected[selected["store"] == store]
        negative = group[group["negative"]]
        bad_reviews = group[(group["rating"] > 0) & (group["rating"] <= 3)]
        keyword_counter: Counter[str] = Counter()
        for keywords in negative["keywords"].tolist():
            keyword_counter.update(keywords or [])
        examples = [text for text in bad_reviews["content"].dropna().astype(str).tolist() if text][:3]
        platform_summary = {}
        for platform in ["美团", "饿了么"]:
            platform_group = group[group["platform"] == platform]
            platform_negative = platform_group[platform_group["negative"]]
            platform_summary[platform] = {
                "review_count": int(len(platform_group)),
                "negative_count": int(len(platform_negative)),
                "review_avg_rating": round(float(platform_group["rating"].mean()), 2) if len(platform_group) else 0,
                "avg_rating": round(float(platform_group["rating"].mean()), 2) if len(platform_group) else 0,
            }
        stores[store] = {
            "date": used_date,
            "review_count": int(len(group)),
            "negative_count": int(len(negative)),
            "review_avg_rating": round(float(group["rating"].mean()), 2) if len(group) else 0,
            "avg_rating": round(float(group["rating"].mean()), 2) if len(group) else 0,
            "platforms": platform_summary,
            "top_keywords": [keyword for keyword, _ in keyword_counter.most_common(4)],
            "examples": examples,
            "bad_review_examples": examples,
        }
    message = f"已接入 {used_date} 评价导出" if status == "ready" else f"暂无 {report_date} 评价导出，当前展示最近一次 {used_date} 评价"
    return {
        "status": status,
        "target_date": report_date,
        "used_date": used_date,
        "message": message,
        "stores": stores,
    }


def store_review_note(review_summary: dict, store: str) -> str:
    status = review_summary.get("status")
    if status == "missing":
        return "评价数据未找到：请先在平台导出评价下载文件。"
    item = review_summary.get("stores", {}).get(store, {})
    prefix = "昨日评价" if status == "ready" else f"最近评价（{review_summary.get('used_date') or '未知日期'}）"
    if not item or not item.get("review_count"):
        return f"{prefix}：暂无评价记录。"
    keywords = "、".join(item.get("top_keywords") or []) or "未集中出现明确差评关键词"
    review_avg = float(item.get("review_avg_rating") or item.get("avg_rating") or 0)
    base = f"{prefix} {item['review_count']} 条，疑似差评/问题评价 {item['negative_count']} 条，评价明细均分 {review_avg:.2f}，关键词：{keywords}。"
    platforms = item.get("platforms") or {}
    platform_parts = []
    for platform in ["美团", "饿了么"]:
        detail = platforms.get(platform) or {}
        count = int(detail.get("review_count") or 0)
        negative = int(detail.get("negative_count") or 0)
        rating = float(detail.get("review_avg_rating") or detail.get("avg_rating") or 0)
        platform_parts.append(f"{platform} {count} 条/差评 {negative}/评价均分 {rating:.2f}" if count else f"{platform} 0 条")
    base += " 平台拆分：" + "；".join(platform_parts) + "。"
    examples = item.get("examples") or []
    if examples:
        snippets = [re.sub(r"\s+", " ", text).strip() for text in examples if str(text).strip()]
        if snippets:
            base += " 差评内容：" + " / ".join(snippets)
    return base


def standardize(df: pd.DataFrame, platform: str, mapping: dict, alias_lookup: dict[str, list[tuple[str, str]]]) -> tuple[pd.DataFrame, list[dict]]:
    rows = []
    warnings = []
    for _, source in df.iterrows():
        raw_name = source.get(mapping["store_raw"], "")
        short_name = match_store(platform, raw_name, alias_lookup)
        if not short_name:
            warnings.append({"platform": platform, "store_raw": str(raw_name), "issue": "未匹配到目标门店"})
            continue

        row = {
            "date": parse_date(source.get(mapping["date"])),
            "platform": platform,
            "store": short_name,
            "store_raw": str(raw_name),
        }
        for metric in METRICS:
            raw_value, has_column = source_value(source, mapping[metric])
            if metric in {"orders", "impressions", "old_customer_orders", "new_customer_orders"}:
                row[metric] = int(round(to_number(raw_value)))
            else:
                row[metric] = round(to_number(raw_value), 4)
            if metric == "customer_paid":
                row["customer_paid_available"] = has_column
                row["customer_paid_orders"] = row["orders"] if has_column else 0
            if (pd.isna(raw_value) or raw_value == "") and (has_column or metric not in OPTIONAL_METRICS):
                warnings.append(
                    {
                        "platform": platform,
                        "store_raw": str(raw_name),
                        "field": DISPLAY_COLUMNS[metric],
                        "issue": "原始为空，已按 0 处理",
                    }
                )
        rows.append(row)
    return pd.DataFrame(rows), warnings


def read_eleme(path: Path, config: dict, alias_lookup: dict[str, list[tuple[str, str]]]) -> tuple[pd.DataFrame, list[dict]]:
    df = pd.read_excel(path, sheet_name=config["eleme"]["sheet_name"])
    return standardize(df, "饿了么", config["eleme"]["columns"], alias_lookup)


def read_meituan(path: Path, config: dict, alias_lookup: dict[str, list[tuple[str, str]]]) -> tuple[pd.DataFrame, list[dict]]:
    encodings = [config["meituan"]["encoding"], "utf-8-sig", "utf-8"]
    last_error: UnicodeDecodeError | None = None
    for encoding in dict.fromkeys(encodings):
        try:
            df = pd.read_csv(path, encoding=encoding)
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    else:
        raise last_error or UnicodeDecodeError("unknown", b"", 0, 1, "无法识别美团 CSV 编码")
    return standardize(df, "美团", config["meituan"]["columns"], alias_lookup)


def weighted_rate(group: pd.DataFrame, column: str, weight_column: str) -> float:
    weights = group[weight_column].astype(float)
    values = group[column].astype(float)
    weight_sum = weights.sum()
    if weight_sum <= 0:
        return round(values.mean(), 4) if len(values) else 0.0
    return round((values * weights).sum() / weight_sum, 4)


def build_store_summary(unified: pd.DataFrame, target_stores: list[str]) -> list[dict]:
    rows = []
    for store in target_stores:
        group = unified[unified["store"] == store]
        row = {"store": store}
        for platform in ["饿了么", "美团"]:
            p = group[group["platform"] == platform]
            prefix = "eleme" if platform == "饿了么" else "meituan"
            row[f"{prefix}_income"] = round(float(p["income"].sum()), 2)
            row[f"{prefix}_customer_paid"] = round(float(p["customer_paid"].sum()), 2)
            row[f"{prefix}_customer_paid_orders"] = int(p["customer_paid_orders"].sum()) if "customer_paid_orders" in p else 0
            row[f"{prefix}_orders"] = int(p["orders"].sum())
            row[f"{prefix}_impressions"] = int(p["impressions"].sum())
        row["total_income"] = round(row["eleme_income"] + row["meituan_income"], 2)
        row["total_customer_paid"] = round(row["eleme_customer_paid"] + row["meituan_customer_paid"], 2)
        row["total_customer_paid_orders"] = row["eleme_customer_paid_orders"] + row["meituan_customer_paid_orders"]
        row["customer_paid_available"] = row["total_customer_paid_orders"] > 0
        row["customer_paid_ticket"] = round(safe_div(row["total_customer_paid"], row["total_customer_paid_orders"]), 2)
        row["total_orders"] = row["eleme_orders"] + row["meituan_orders"]
        row["total_impressions"] = row["eleme_impressions"] + row["meituan_impressions"]
        if len(group):
            row["visit_conversion"] = weighted_rate(group, "visit_conversion", "impressions")
            row["order_conversion"] = weighted_rate(group, "order_conversion", "orders")
            row["old_customer_orders"] = int(group["old_customer_orders"].sum())
            row["new_customer_orders"] = int(group["new_customer_orders"].sum())
        else:
            row["visit_conversion"] = 0.0
            row["order_conversion"] = 0.0
            row["old_customer_orders"] = 0
            row["new_customer_orders"] = 0
        rows.append(row)
    return rows


def build_platform_summary(unified: pd.DataFrame) -> list[dict]:
    rows = []
    for platform in ["饿了么", "美团"]:
        group = unified[unified["platform"] == platform]
        rows.append(
            {
                "platform": platform,
                "income": round(float(group["income"].sum()), 2),
                "customer_paid": round(float(group["customer_paid"].sum()), 2),
                "customer_paid_orders": int(group["customer_paid_orders"].sum()) if "customer_paid_orders" in group else 0,
                "orders": int(group["orders"].sum()),
                "impressions": int(group["impressions"].sum()),
                "visit_conversion": weighted_rate(group, "visit_conversion", "impressions") if len(group) else 0,
                "order_conversion": weighted_rate(group, "order_conversion", "orders") if len(group) else 0,
                "old_customer_orders": int(group["old_customer_orders"].sum()),
                "new_customer_orders": int(group["new_customer_orders"].sum()),
            }
        )
    return rows


def fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def fmt_int(value: int | float) -> str:
    return f"{int(value):,}"


def fmt_rate(value: float) -> str:
    return f"{value * 100:.1f}%"


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def fmt_delta(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def health_class(row: dict, avg_order_conversion: float) -> tuple[str, str]:
    if row["total_orders"] == 0:
        return "停业/无单", "bad"
    if row["order_conversion"] < avg_order_conversion * 0.75:
        return "转化偏弱", "warn"
    if row["total_income"] >= 5000 and row["order_conversion"] >= avg_order_conversion:
        return "高贡献", "good"
    return "正常", "ok"


STORE_SLUGS = {
    "安贞": "anzhen",
    "中关村": "zhongguancun",
    "清河": "qinghe",
    "金融街": "jinrongjie",
    "丽泽": "lize",
    "双井": "shuangjing",
    "光谷": "guanggu",
    "五一广场": "wuyiguangchang",
}


def store_slug(store: str) -> str:
    fallback = re.sub(r"[^a-zA-Z0-9]+", "-", store).strip("-").lower()
    return STORE_SLUGS.get(store, fallback or "store")


def day_records(payload: dict, report_date: str) -> list[dict]:
    return [row for row in payload["records"] if row.get("date") == report_date]


def sum_metric(rows: list[dict], key: str) -> float:
    return sum(float(row.get(key) or 0) for row in rows)


def weighted_rate_records(rows: list[dict], column: str, weight_column: str) -> float:
    weight_sum = sum_metric(rows, weight_column)
    if weight_sum <= 0:
        return round(sum_metric(rows, column) / len(rows), 4) if rows else 0.0
    return round(sum(float(row.get(column) or 0) * float(row.get(weight_column) or 0) for row in rows) / weight_sum, 4)


def compact_store_summary(rows: list[dict]) -> dict:
    income = round(sum_metric(rows, "income"), 2)
    customer_paid = round(sum_metric(rows, "customer_paid"), 2)
    customer_paid_orders = int(sum_metric(rows, "customer_paid_orders"))
    customer_paid_available = customer_paid_orders > 0
    orders = int(sum_metric(rows, "orders"))
    impressions = int(sum_metric(rows, "impressions"))
    old_customers = int(sum_metric(rows, "old_customer_orders"))
    new_customers = int(sum_metric(rows, "new_customer_orders"))
    return {
        "income": income,
        "customer_paid": customer_paid,
        "customer_paid_orders": customer_paid_orders,
        "customer_paid_available": customer_paid_available,
        "orders": orders,
        "impressions": impressions,
        "ticket": round(safe_div(income, orders), 2),
        "customer_paid_ticket": round(safe_div(customer_paid, customer_paid_orders), 2),
        "visit_conversion": weighted_rate_records(rows, "visit_conversion", "impressions"),
        "order_conversion": weighted_rate_records(rows, "order_conversion", "orders"),
        "old_customer_orders": old_customers,
        "new_customer_orders": new_customers,
        "new_customer_ratio": safe_div(new_customers, old_customers + new_customers),
    }


def pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / previous


def fmt_delta_text(change: float | None) -> str:
    if change is None:
        return "前日无可比数据"
    return f"{'+' if change > 0 else ''}{change * 100:.1f}%"


def fmt_rate_delta_text(change: float | None) -> str:
    if change is None:
        return "前日无可比数据"
    return f"{'+' if change > 0 else ''}{change * 100:.1f}个百分点"


def delta_class(change: float | None) -> str:
    return "up" if (change or 0) >= 0 else "down"


def fmt_customer_paid_ticket(summary: dict) -> str:
    if not summary.get("customer_paid_available") or not summary.get("customer_paid_orders"):
        return "待新报表"
    return fmt_money(summary["customer_paid_ticket"])


def fmt_record_customer_paid_ticket(row: dict) -> str:
    if not row.get("customer_paid_available") or not row.get("customer_paid_orders"):
        return "待新报表"
    return fmt_money(safe_div(float(row.get("customer_paid") or 0), float(row.get("customer_paid_orders") or 0)))


def latest_report_date(payload: dict) -> str:
    dates = [date for date in payload.get("source_dates", []) if date]
    return max(dates) if dates else ""


def previous_report_date(payload: dict, report_date: str) -> str | None:
    dates = sorted(date for date in payload.get("source_dates", []) if date)
    if report_date not in dates:
        return None
    index = dates.index(report_date)
    return dates[index - 1] if index > 0 else None


def common_platform_records(payload: dict, store: str, report_date: str) -> tuple[list[dict], list[dict], str | None]:
    previous_date = previous_report_date(payload, report_date)
    current = [row for row in day_records(payload, report_date) if row.get("store") == store]
    if not previous_date:
        return current, [], None
    previous = [row for row in day_records(payload, previous_date) if row.get("store") == store]
    current_platforms = {row["platform"] for row in current}
    previous_platforms = {row["platform"] for row in previous}
    shared = current_platforms & previous_platforms
    return (
        [row for row in current if row.get("platform") in shared],
        [row for row in previous if row.get("platform") in shared],
        previous_date,
    )


def build_focus_items(payload: dict, store: str, report_date: str) -> list[dict]:
    current = [row for row in day_records(payload, report_date) if row.get("store") == store]
    current_compare, previous_compare, previous_date = common_platform_records(payload, store, report_date)
    summary = compact_store_summary(current)
    previous_summary = compact_store_summary(previous_compare)
    compare_summary = compact_store_summary(current_compare)

    all_store_rows = build_store_summary(pd.DataFrame(day_records(payload, report_date)), payload["target_stores"])
    avg_visit = weighted_rate_records(all_store_rows, "visit_conversion", "total_impressions")
    avg_order = weighted_rate_records(all_store_rows, "order_conversion", "total_orders")

    items: list[dict] = []
    checks = [
        ("收入", "income", "优先确认是否有平台活动、门店营业状态或客单价变化。"),
        ("单量", "orders", "先看曝光是否同步下降，再看转化是否掉得更快。"),
        ("曝光", "impressions", "重点检查平台入口、活动资源、营业时段和门店排名。"),
    ]
    for label, key, advice in checks:
        change = pct_change(compare_summary[key], previous_summary[key])
        if change is not None and change <= -0.15:
            items.append(
                {
                    "level": "high",
                    "title": f"{label}较前日下降 {abs(change) * 100:.1f}%",
                    "body": f"对比 {previous_date} 的共同平台，{advice}",
                }
            )

    if summary["order_conversion"] and avg_order and summary["order_conversion"] < avg_order * 0.8:
        items.append(
            {
                "level": "high",
                "title": f"下单转化低于门店均值，当前 {fmt_rate(summary['order_conversion'])}",
                "body": "建议检查菜品排序、优惠力度、配送费、起送价和差评影响。",
            }
        )
    if summary["visit_conversion"] and avg_visit and summary["visit_conversion"] < avg_visit * 0.8:
        items.append(
            {
                "level": "medium",
                "title": f"进店转化偏低，当前 {fmt_rate(summary['visit_conversion'])}",
                "body": "优先看门店封面、招牌品、活动标签和平台搜索/推荐位置。",
            }
        )
    if summary["orders"] == 0:
        items.append({"level": "high", "title": "今日无订单", "body": "需要立刻确认营业状态、平台在线状态和配送范围。"})
    if summary["new_customer_ratio"] < 0.2 and summary["orders"] >= 30:
        items.append(
            {
                "level": "medium",
                "title": f"新客占比偏低，当前 {fmt_rate(summary['new_customer_ratio'])}",
                "body": "可以重点看拉新活动、曝光入口和新客券是否有效。",
            }
        )

    platforms = sorted(current, key=lambda row: float(row.get("income") or 0), reverse=True)
    if len(platforms) >= 2:
        total_income = sum_metric(platforms, "income")
        leader = platforms[0]
        weak = platforms[-1]
        if total_income and float(leader.get("income") or 0) / total_income >= 0.75:
            items.append(
                {
                    "level": "medium",
                    "title": f"{leader['platform']}占收入超过 75%",
                    "body": f"{weak['platform']}贡献偏弱，建议单独看该平台的曝光、活动和下载数据是否完整。",
                }
            )

    if not items:
        items.append({"level": "good", "title": "今日没有明显异常", "body": "继续关注收入排名、客单价和新客占比的细小变化。"})
    return items[:5]


def issue_level(levels: list[str]) -> str:
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "good"


def explain_primary_driver(summary: dict, previous_summary: dict) -> str:
    income_change = pct_change(summary["income"], previous_summary["income"])
    orders_change = pct_change(summary["orders"], previous_summary["orders"])
    impressions_change = pct_change(summary["impressions"], previous_summary["impressions"])
    ticket_change = pct_change(summary["ticket"], previous_summary["ticket"])
    drivers = []
    if orders_change is not None and orders_change <= -0.12:
        drivers.append(f"单量下降 {abs(orders_change) * 100:.1f}%")
    if impressions_change is not None and impressions_change <= -0.12:
        drivers.append(f"曝光下降 {abs(impressions_change) * 100:.1f}%")
    if ticket_change is not None and ticket_change <= -0.08:
        drivers.append(f"客单价下降 {abs(ticket_change) * 100:.1f}%")
    if not drivers and income_change is not None:
        return "收入变化没有被单一指标解释，需要结合平台拆分和活动状态确认。"
    if not drivers:
        return "暂无前日可比数据，先以今日横向排名和转化率判断。"
    return "主要拖累：" + "、".join(drivers) + "。"


def build_store_diagnosis(payload: dict, store: str, report_date: str) -> dict:
    current = [row for row in day_records(payload, report_date) if row.get("store") == store]
    current_compare, previous_compare, previous_date = common_platform_records(payload, store, report_date)
    summary = compact_store_summary(current)
    previous_summary = compact_store_summary(previous_compare)
    compare_summary = compact_store_summary(current_compare)
    all_store_rows = build_store_summary(pd.DataFrame(day_records(payload, report_date)), payload["target_stores"])
    avg_visit = weighted_rate_records(all_store_rows, "visit_conversion", "total_impressions")
    avg_order = weighted_rate_records(all_store_rows, "order_conversion", "total_orders")

    issues: list[str] = []
    levels: list[str] = []
    actions: list[str] = []

    income_change = pct_change(compare_summary["income"], previous_summary["income"])
    orders_change = pct_change(compare_summary["orders"], previous_summary["orders"])
    impressions_change = pct_change(compare_summary["impressions"], previous_summary["impressions"])
    visit_gap = summary["visit_conversion"] - avg_visit if avg_visit else 0
    order_gap = summary["order_conversion"] - avg_order if avg_order else 0

    if summary["orders"] == 0:
        issues.append("今日无订单")
        levels.append("high")
        actions.append("立刻确认门店营业状态、平台在线状态、配送范围和是否被限流。")
    if income_change is not None and income_change <= -0.15:
        issues.append(f"收入较前日下降 {abs(income_change) * 100:.1f}%")
        levels.append("high")
        actions.append("优先对照平台活动、营业时长、客单价和单量变化。")
    if orders_change is not None and orders_change <= -0.15:
        issues.append(f"单量较前日下降 {abs(orders_change) * 100:.1f}%")
        levels.append("high")
        actions.append("先看曝光是否同步下降，再看下单转化是否掉得更快。")
    if impressions_change is not None and impressions_change <= -0.20:
        issues.append(f"曝光较前日下降 {abs(impressions_change) * 100:.1f}%")
        levels.append("medium")
        actions.append("检查平台入口、搜索排名、活动资源和推广余额。")
    if avg_order and summary["order_conversion"] < avg_order * 0.8:
        issues.append(f"下单转化低于门店均值 {abs(order_gap) * 100:.1f} 个百分点")
        levels.append("high")
        actions.append("检查菜品排序、主推品、优惠力度、配送费、起送价和差评影响。")
    if avg_visit and summary["visit_conversion"] < avg_visit * 0.8:
        issues.append(f"进店转化低于门店均值 {abs(visit_gap) * 100:.1f} 个百分点")
        levels.append("medium")
        actions.append("检查门店封面、招牌品、活动标签、平台搜索/推荐位置。")
    if summary["new_customer_ratio"] < 0.2 and summary["orders"] >= 30:
        issues.append(f"新客占比偏低，仅 {fmt_rate(summary['new_customer_ratio'])}")
        levels.append("medium")
        actions.append("检查新客券、拉新活动和曝光入口是否正常。")

    level = issue_level(levels)
    if not issues:
        issues.append("今日未发现明显经营异常")
        actions.append("保持当前节奏，继续观察收入排名、转化率和新客占比。")

    platforms = sorted(current, key=lambda row: float(row.get("income") or 0), reverse=True)
    platform_note = "暂无平台拆分数据"
    if platforms:
        platform_note = "平台贡献：" + "，".join(
            f"{row['platform']} {fmt_money(float(row.get('income') or 0))}/{fmt_int(row.get('orders') or 0)}单"
            for row in platforms
        )

    return {
        "store": store,
        "level": level,
        "headline": "；".join(issues[:2]),
        "driver": explain_primary_driver(compare_summary, previous_summary),
        "evidence": f"收入 {fmt_money(summary['income'])}，单量 {fmt_int(summary['orders'])}，曝光 {fmt_int(summary['impressions'])}，进店 {fmt_rate(summary['visit_conversion'])}，下单 {fmt_rate(summary['order_conversion'])}。",
        "platform_note": platform_note,
        "action": actions[0],
        "review_note": store_review_note(payload.get("review_summary", {}), store),
        "previous_date": previous_date or "",
    }


def build_all_store_diagnoses(payload: dict, report_date: str) -> list[dict]:
    diagnoses = [build_store_diagnosis(payload, store, report_date) for store in payload["target_stores"]]
    priority = {"high": 0, "medium": 1, "good": 2}
    return sorted(diagnoses, key=lambda item: (priority.get(item["level"], 9), item["store"]))


def build_all_focus_items(payload: dict, report_date: str) -> list[dict]:
    items = []
    for store in payload["target_stores"]:
        for item in build_focus_items(payload, store, report_date):
            if item["level"] in {"high", "medium"}:
                items.append({"store": store, **item})
    priority = {"high": 0, "medium": 1, "good": 2}
    return sorted(items, key=lambda item: (priority.get(item["level"], 9), item["store"]))[:8]


def json_script(data: object) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def write_dashboard(payload: dict) -> Path:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    output = DASHBOARD_DIR / "index.html"
    generated_at = payload["generated_at"]
    focus_items = payload.get("focus_items", [])
    diagnoses = payload.get("all_store_diagnoses", [])
    review_summary = payload.get("review_summary", {})
    review_message = review_summary.get("message") or "评价数据未找到"
    if focus_items:
        focus_html = "\n".join(
            f"""<a class="focus-item {html_lib.escape(item['level'])}" href="stores/{store_slug(item['store'])}.html">
          <b>{html_lib.escape(item['store'])}：{html_lib.escape(item['title'])}</b>
          <span>{html_lib.escape(item['body'])}</span>
        </a>"""
            for item in focus_items
        )
    else:
        focus_html = '<div class="empty">今日没有明显异常。</div>'
    diagnosis_html = "\n".join(
        f"""<a class="diagnosis-card {html_lib.escape(item['level'])}" href="stores/{store_slug(item['store'])}.html">
          <div class="diagnosis-head"><b>{html_lib.escape(item['store'])}</b><span>{level_label(item['level'])}</span></div>
          <strong>{html_lib.escape(item['headline'])}</strong>
          <p>{html_lib.escape(item['driver'])}</p>
          <p>{html_lib.escape(item['evidence'])}</p>
          <em>{html_lib.escape(item['action'])}</em>
          <small>{html_lib.escape(item['review_note'])}</small>
        </a>"""
        for item in diagnoses
    ) or '<div class="empty">暂无门店诊断数据。</div>'

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>经营日报看板</title>
  <style>
    :root {{
      --bg: #f3f6f8;
      --panel: #ffffff;
      --line: #dfe5ee;
      --text: #172033;
      --muted: #667085;
      --accent: #0f766e;
      --accent-2: #2563eb;
      --soft: #e0f2fe;
      --warn: #b45309;
      --good: #0f766e;
      --bad: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
      background:
        linear-gradient(180deg, #e8f1f0 0, rgba(232, 241, 240, 0) 260px),
        var(--bg);
      color: var(--text);
    }}
    main {{ max-width: 1320px; margin: 0 auto; padding: 22px 26px 26px; }}
    header {{ display: flex; justify-content: space-between; gap: 18px; align-items: flex-end; margin-bottom: 14px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
    .muted {{ color: var(--muted); font-size: 14px; }}
    .toolbar {{ display: flex; align-items: center; gap: 10px; }}
    .toolbar label {{ color: var(--muted); font-size: 13px; }}
    .toolbar select {{ height: 36px; min-width: 150px; padding: 0 34px 0 12px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; color: var(--text); font-size: 14px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }}
    .ai-week-panel {{ margin-bottom: 12px; }}
    .week-analysis-body {{ display: grid; gap: 12px; }}
    .week-summary-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .week-summary-card {{ min-width: 0; min-height: 78px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; display: grid; gap: 7px; }}
    .week-summary-card span {{ color: var(--muted); font-size: 12px; font-weight: 650; }}
    .week-summary-card strong {{ font-size: 20px; line-height: 1; }}
    .week-summary-card:first-child strong {{ font-size: 14px; line-height: 1.35; }}
    .week-summary-card em {{ color: var(--muted); font-size: 12px; font-style: normal; }}
    .week-store-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }}
    .week-store-card {{ min-width: 0; min-height: 128px; padding: 13px 14px; border: 1px solid var(--line); border-left: 4px solid #98a2b3; border-radius: 8px; background: #fff; display: grid; gap: 7px; }}
    .week-store-card.up {{ border-left-color: var(--bad); background: #fff8f7; }}
    .week-store-card.down {{ border-left-color: var(--good); background: #f0fdf4; }}
    .week-store-card b {{ font-size: 15px; }}
    .week-store-card strong {{ font-size: 14px; }}
    .week-store-card p {{ margin: 0; color: var(--muted); font-size: 12px; line-height: 1.45; }}
    .week-store-card em {{ color: var(--text); font-size: 12px; font-style: normal; font-weight: 650; line-height: 1.45; }}
    .focus-panel {{ margin-bottom: 12px; }}
    .focus-list {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .focus-item {{ display: grid; gap: 5px; min-height: 74px; padding: 12px 14px; border: 1px solid var(--line); border-left: 4px solid #98a2b3; border-radius: 8px; background: #fff; color: inherit; text-decoration: none; }}
    .focus-item.high {{ border-left-color: var(--bad); background: #fff8f7; }}
    .focus-item.medium {{ border-left-color: var(--warn); background: #fffbeb; }}
    .focus-item.good {{ border-left-color: var(--good); background: #f0fdfa; }}
    .focus-item b {{ font-size: 14px; }}
    .focus-item span {{ color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .card, .panel, .table-wrap {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }}
    .card {{ padding: 12px 14px; min-height: 82px; display: grid; gap: 8px; }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ font-size: 24px; font-weight: 780; line-height: 1; }}
    .hint {{ color: var(--muted); font-size: 12px; }}
    .delta {{ display: inline-flex; align-items: center; width: fit-content; padding: 3px 7px; border-radius: 999px; font-size: 12px; font-weight: 650; background: #eef2f6; color: #475467; }}
    .delta.up {{ background: #fee4e2; color: #b42318; }}
    .delta.down {{ background: #dcfae6; color: #067647; }}
    .panel {{ padding: 18px; }}
    .compare-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 14px; }}
    .chart-box {{ min-height: 318px; padding: 18px; }}
    .wide {{ grid-column: 1 / -1; }}
    h2 {{ font-size: 18px; margin: 0 0 12px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 1460px; }}
    th, td {{ padding: 12px 11px; border-bottom: 1px solid #edf1f6; text-align: right; white-space: nowrap; }}
    th {{ color: var(--muted); font-size: 13px; background: #fbfcfe; font-weight: 650; }}
    td.store, th:first-child {{ text-align: left; font-weight: 650; }}
    td.store a {{ color: var(--text); text-decoration: none; }}
    td.store a:hover {{ color: var(--accent-2); text-decoration: underline; }}
    tbody tr:hover td {{ background: #f8fafc; }}
    .strong {{ font-weight: 760; }}
    .money {{ font-weight: 650; }}
    .eleme-text {{ color: var(--accent); }}
    .meituan-text {{ color: var(--accent-2); }}
    .status {{ display: inline-block; min-width: 58px; margin-right: 8px; padding: 3px 7px; border-radius: 999px; font-size: 12px; text-align: center; font-weight: 650; }}
    .status.good {{ color: #067647; background: #dcfae6; }}
    .status.ok {{ color: #344054; background: #eef2f6; }}
    .status.warn {{ color: #b54708; background: #fef0c7; }}
    .status.bad {{ color: #b42318; background: #fee4e2; }}
    .metric-row {{
      display: grid;
      grid-template-columns: 88px 1fr 108px;
      gap: 10px;
      align-items: center;
      margin: 12px 0;
      font-size: 13px;
    }}
    .metric-row b {{ text-align: right; }}
    .metric-track {{
      height: 16px;
      background: #edf2f7;
      border-radius: 999px;
      overflow: hidden;
    }}
    .metric-track i {{ display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--accent), var(--accent-2)); }}
    .metric-track i.up {{ background: linear-gradient(90deg, #fda29b, #d92d20); }}
    .metric-track i.down {{ margin-left: auto; background: linear-gradient(90deg, #12b76a, #067647); }}
    .customer-chart {{ display: grid; grid-template-columns: repeat(8, minmax(90px, 1fr)); gap: 14px; align-items: end; min-height: 250px; }}
    .customer-col {{ display: grid; grid-template-rows: 190px auto; gap: 8px; justify-items: center; min-width: 0; }}
    .stack-bar {{ width: 44px; height: 190px; display: flex; flex-direction: column-reverse; overflow: hidden; border-radius: 7px; background: #eef2f6; border: 1px solid #d0d5dd; }}
    .stack-new {{ display: grid; place-items: center; min-height: 20px; background: #2563eb; color: #fff; font-size: 11px; font-weight: 700; }}
    .stack-old {{ display: grid; place-items: center; min-height: 20px; background: #cbd5e1; color: #344054; font-size: 11px; font-weight: 700; }}
    .customer-name {{ font-size: 12px; color: var(--muted); text-align: center; white-space: nowrap; }}
    .legend {{ display: flex; gap: 14px; align-items: center; margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }}
    .legend .new {{ background: #2563eb; }}
    .legend .old {{ background: #cbd5e1; }}
    .section-title {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 14px; }}
    .section-title h2 {{ margin: 0; }}
    .section-title span {{ color: var(--muted); font-size: 12px; }}
    .analysis-panel {{ margin-bottom: 14px; }}
    .analysis-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .diagnosis-card {{ display: grid; gap: 8px; min-height: 178px; padding: 14px; border: 1px solid var(--line); border-left: 4px solid #98a2b3; border-radius: 8px; background: #fff; color: inherit; text-decoration: none; }}
    .diagnosis-card.high {{ border-left-color: var(--bad); background: #fff8f7; }}
    .diagnosis-card.medium {{ border-left-color: var(--warn); background: #fffbeb; }}
    .diagnosis-card.good {{ border-left-color: var(--good); background: #f0fdfa; }}
    .diagnosis-head {{ display: flex; justify-content: space-between; gap: 10px; align-items: center; }}
    .diagnosis-head b {{ font-size: 15px; }}
    .diagnosis-head span {{ padding: 3px 7px; border-radius: 999px; background: #eef2f6; color: #475467; font-size: 12px; font-weight: 650; }}
    .diagnosis-card strong {{ font-size: 14px; }}
    .diagnosis-card p {{ margin: 0; color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .diagnosis-card em {{ font-style: normal; color: var(--text); font-size: 13px; font-weight: 650; line-height: 1.45; }}
    .diagnosis-card small {{ color: #7a5b13; font-size: 12px; line-height: 1.45; }}
    .empty {{ padding: 28px; color: var(--muted); text-align: center; }}
    @media (max-width: 900px) {{
      main {{ padding: 18px; }}
      header {{ display: block; }}
      .toolbar {{ margin-top: 12px; }}
      .kpis, .compare-grid {{ grid-template-columns: 1fr; }}
      .focus-list, .analysis-grid, .week-summary-grid, .week-store-grid {{ grid-template-columns: 1fr; }}
      .chart-box {{ height: 280px; }}
      .customer-chart {{ overflow-x: auto; grid-template-columns: repeat(8, 92px); }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>经营日报看板</h1>
        <div class="muted">生成时间：{generated_at}</div>
      </div>
      <div class="toolbar">
        <label for="dateSelect">数据日期</label>
        <select id="dateSelect"></select>
      </div>
    </header>

    <section class="kpis">
      <div class="card"><div class="label">总收入</div><div class="value" id="kpiIncome"></div><div class="delta" id="incomeDelta"></div></div>
      <div class="card"><div class="label">总单量</div><div class="value" id="kpiOrders"></div><div class="delta" id="ordersDelta"></div></div>
      <div class="card"><div class="label">总曝光</div><div class="value" id="kpiImpressions"></div><div class="delta" id="impressionsDelta"></div></div>
      <div class="card"><div class="label">平均客单价</div><div class="value" id="kpiTicket"></div><div class="hint" id="kpiTicketHint"></div></div>
    </section>

    <section class="panel ai-week-panel">
      <div class="section-title"><h2>AI周分析</h2><span>近 7 个数据日对比前 7 个数据日，涨红跌绿</span></div>
      <div class="week-analysis-body" id="aiWeekAnalysis"></div>
    </section>

    <section class="panel focus-panel">
      <div class="section-title"><h2>重点关注</h2><span>点击门店进入单店日报</span></div>
      <div class="focus-list">
        {focus_html}
      </div>
    </section>

    <section class="panel analysis-panel">
      <div class="section-title"><h2>所有门店数据分析</h2><span>按昨日经营表现自动诊断，{html_lib.escape(review_message)}</span></div>
      <div class="analysis-grid">
        {diagnosis_html}
      </div>
    </section>

    <section class="compare-grid">
      <div class="panel chart-box">
        <div class="section-title"><h2>门店收入横向对比</h2><span>用于判断今日资源重点</span></div>
        <div id="incomeBars"></div>
      </div>
      <div class="panel chart-box">
        <div class="section-title"><h2>门店单量横向对比</h2><span>收入之外看实际订单贡献</span></div>
        <div id="orderCountBars"></div>
      </div>
      <div class="panel chart-box">
        <div class="section-title"><h2>门店曝光横向对比</h2><span>观察流量入口是否偏弱</span></div>
        <div id="impressionBars"></div>
      </div>
      <div class="panel chart-box">
        <div class="section-title"><h2>客单价横向对比</h2><span>识别高客单与低客单门店</span></div>
        <div id="ticketBars"></div>
      </div>
      <div class="panel chart-box">
        <div class="section-title"><h2>顾客实付单均价横向对比</h2><span>按顾客实付 / 有效订单计算</span></div>
        <div id="customerPaidTicketBars"></div>
      </div>
      <div class="panel chart-box">
        <div class="section-title"><h2>进店转化率横向对比</h2><span>曝光到进店</span></div>
        <div id="visitBars"></div>
      </div>
      <div class="panel chart-box">
        <div class="section-title"><h2>下单转化率横向对比</h2><span>进店到下单</span></div>
        <div id="orderBars"></div>
      </div>
      <div class="panel chart-box wide">
        <div class="section-title"><h2>新老客占比横向对比</h2><span>蓝色为新客，灰色为老客</span></div>
        <div class="customer-chart" id="customerBars"></div>
        <div class="legend"><span><i class="new"></i>新客</span><span><i class="old"></i>老客</span></div>
      </div>
      <div class="panel chart-box wide">
        <div class="section-title"><h2>门店收入较前一日变化</h2><span id="previousDateLabel"></span></div>
        <div id="incomeChangeBars"></div>
      </div>
    </section>

    <section class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>门店</th>
            <th>收入</th>
            <th>收入较前日</th>
            <th>单量</th>
            <th>单量较前日</th>
            <th>客单价</th>
            <th>饿了么客单价</th>
            <th>美团客单价</th>
            <th>顾客实付单均价</th>
            <th>曝光量</th>
            <th>曝光较前日</th>
            <th>进店转化率</th>
            <th>进店较前日</th>
            <th>下单转化率</th>
            <th>下单较前日</th>
            <th>新客占比</th>
            <th>饿了么收入</th>
            <th>美团收入</th>
          </tr>
        </thead>
        <tbody id="storeRows"></tbody>
      </table>
    </section>
  </main>

  <script type="application/json" id="dashboard-data">{json_script(payload)}</script>
  <script>
    const payload = JSON.parse(document.getElementById('dashboard-data').textContent);
    const records = payload.records || [];
    const targetStores = payload.target_stores || [...new Set(records.map((item) => item.store))];
    const storeReportFiles = payload.store_report_files || {{}};
    const dates = [...new Set(records.map((item) => item.date).filter(Boolean))].sort().reverse();
    const datesAsc = [...dates].reverse();
    const dateSelect = document.getElementById('dateSelect');

    const fmtMoney = (value) => Number(value || 0).toLocaleString('zh-CN', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    const fmtInt = (value) => Math.round(Number(value || 0)).toLocaleString('zh-CN');
    const fmtRate = (value) => `${{(Number(value || 0) * 100).toFixed(1)}}%`;
    const fmtCustomerPaidTicket = (row) => row.customer_paid_available && row.customer_paid_orders ? fmtMoney(row.customer_paid_ticket) : '待新报表';
    const safeDiv = (a, b) => b ? a / b : 0;
    const pctChange = (current, previous) => previous ? (current - previous) / previous : null;
    const deltaClass = (change) => change === null ? '' : change >= 0 ? 'up' : 'down';
    const deltaText = (change, scope = '较前日') => change === null ? '前日无数据' : `${{change >= 0 ? '+' : ''}}${{(change * 100).toFixed(1)}}% ${{scope}}`;
    const ratePointChange = (current, previous, hasPrevious) => hasPrevious ? Number(current || 0) - Number(previous || 0) : null;
    const rateDeltaText = (change) => change === null ? '前日无数据' : `${{change >= 0 ? '+' : ''}}${{(change * 100).toFixed(1)}}个百分点`;
    const weightedRate = (rows, column, weightColumn) => {{
      const weightSum = rows.reduce((sum, row) => sum + Number(row[weightColumn] || 0), 0);
      if (weightSum <= 0) return rows.length ? rows.reduce((sum, row) => sum + Number(row[column] || 0), 0) / rows.length : 0;
      return rows.reduce((sum, row) => sum + Number(row[column] || 0) * Number(row[weightColumn] || 0), 0) / weightSum;
    }};

    function platformSummary(dayRecords) {{
      return ['饿了么', '美团'].map((platform) => {{
        const rows = dayRecords.filter((row) => row.platform === platform);
        return {{
          platform,
          income: rows.reduce((sum, row) => sum + Number(row.income || 0), 0),
          customer_paid: rows.reduce((sum, row) => sum + Number(row.customer_paid || 0), 0),
          customer_paid_orders: rows.reduce((sum, row) => sum + Number(row.customer_paid_orders || 0), 0),
          orders: rows.reduce((sum, row) => sum + Number(row.orders || 0), 0),
          impressions: rows.reduce((sum, row) => sum + Number(row.impressions || 0), 0),
          visit_conversion: weightedRate(rows, 'visit_conversion', 'impressions'),
          order_conversion: weightedRate(rows, 'order_conversion', 'orders'),
          old_customer_orders: rows.reduce((sum, row) => sum + Number(row.old_customer_orders || 0), 0),
          new_customer_orders: rows.reduce((sum, row) => sum + Number(row.new_customer_orders || 0), 0),
        }};
      }});
    }}

    function storeSummary(dayRecords) {{
      return targetStores.map((store) => {{
        const rows = dayRecords.filter((row) => row.store === store);
        const eleme = rows.filter((row) => row.platform === '饿了么');
        const meituan = rows.filter((row) => row.platform === '美团');
        const sum = (list, key) => list.reduce((total, row) => total + Number(row[key] || 0), 0);
        return {{
          store,
          eleme_income: sum(eleme, 'income'),
          meituan_income: sum(meituan, 'income'),
          eleme_customer_paid: sum(eleme, 'customer_paid'),
          meituan_customer_paid: sum(meituan, 'customer_paid'),
          eleme_customer_paid_orders: sum(eleme, 'customer_paid_orders'),
          meituan_customer_paid_orders: sum(meituan, 'customer_paid_orders'),
          eleme_orders: sum(eleme, 'orders'),
          meituan_orders: sum(meituan, 'orders'),
          total_income: sum(rows, 'income'),
          total_customer_paid: sum(rows, 'customer_paid'),
          total_customer_paid_orders: sum(rows, 'customer_paid_orders'),
          customer_paid_available: sum(rows, 'customer_paid_orders') > 0,
          total_orders: sum(rows, 'orders'),
          total_impressions: sum(rows, 'impressions'),
          ticket: safeDiv(sum(rows, 'income'), sum(rows, 'orders')),
          customer_paid_orders: sum(rows, 'customer_paid_orders'),
          customer_paid_ticket: safeDiv(sum(rows, 'customer_paid'), sum(rows, 'customer_paid_orders')),
          visit_conversion: weightedRate(rows, 'visit_conversion', 'impressions'),
	          order_conversion: weightedRate(rows, 'order_conversion', 'orders'),
	          old_customer_orders: sum(rows, 'old_customer_orders'),
          new_customer_orders: sum(rows, 'new_customer_orders'),
	        }};
	      }});
	    }}

    function previousDate(date) {{
      const index = datesAsc.indexOf(date);
      return index > 0 ? datesAsc[index - 1] : null;
    }}

    function totalsFromStores(stores) {{
      const totalIncome = stores.reduce((sum, row) => sum + row.total_income, 0);
      const totalCustomerPaid = stores.reduce((sum, row) => sum + row.total_customer_paid, 0);
      const totalCustomerPaidOrders = stores.reduce((sum, row) => sum + Number(row.total_customer_paid_orders || row.customer_paid_orders || 0), 0);
      const totalOrders = stores.reduce((sum, row) => sum + row.total_orders, 0);
      const totalImpressions = stores.reduce((sum, row) => sum + row.total_impressions, 0);
      return {{ totalIncome, totalCustomerPaid, totalCustomerPaidOrders, totalOrders, totalImpressions, ticket: safeDiv(totalIncome, totalOrders), customerPaidTicket: safeDiv(totalCustomerPaid, totalCustomerPaidOrders) }};
    }}

    function attachPrevious(stores, currentCompareStores, previousCompareStores) {{
      const currentByStore = new Map(currentCompareStores.map((row) => [row.store, row]));
      const previousByStore = new Map(previousCompareStores.map((row) => [row.store, row]));
      return stores.map((row) => {{
        const current = currentByStore.get(row.store) || {{}};
        const prev = previousByStore.get(row.store) || {{}};
        const hasPrevious = previousByStore.has(row.store);
        return {{
          ...row,
          income_change: pctChange(Number(current.total_income || 0), Number(prev.total_income || 0)),
          orders_change: pctChange(Number(current.total_orders || 0), Number(prev.total_orders || 0)),
          impressions_change: pctChange(Number(current.total_impressions || 0), Number(prev.total_impressions || 0)),
          visit_conversion_change: ratePointChange(current.visit_conversion, prev.visit_conversion, hasPrevious),
          order_conversion_change: ratePointChange(current.order_conversion, prev.order_conversion, hasPrevious),
        }};
      }});
    }}

    function platformNames(dayRecords) {{
      return [...new Set(dayRecords.map((row) => row.platform).filter(Boolean))];
    }}

    function commonPlatforms(currentRecords, previousRecords) {{
      const previous = new Set(platformNames(previousRecords));
      return platformNames(currentRecords).filter((platform) => previous.has(platform));
    }}

    function filterPlatforms(dayRecords, platforms) {{
      const allowed = new Set(platforms);
      return dayRecords.filter((row) => allowed.has(row.platform));
    }}

    function health(row, avgOrderConversion) {{
      if (row.total_orders === 0) return ['停业/无单', 'bad'];
      if (row.order_conversion < avgOrderConversion * 0.75) return ['转化偏弱', 'warn'];
      if (row.total_income >= 5000 && row.order_conversion >= avgOrderConversion) return ['高贡献', 'good'];
      return ['正常', 'ok'];
    }}

	    function renderBars(id, rows, metric, formatter) {{
	      const ranked = [...rows].sort((a, b) => Number(b[metric] || 0) - Number(a[metric] || 0));
	      const max = Math.max(1, ...ranked.map((row) => Number(row[metric] || 0)));
	      document.getElementById(id).innerHTML = ranked.map((row) => `
        <div class="metric-row">
          <span>${{row.store}}</span>
          <div class="metric-track"><i style="width:${{(Number(row[metric] || 0) / max) * 100}}%"></i></div>
          <b>${{formatter(row[metric])}}</b>
        </div>
	      `).join('');
	    }}

    function renderChangeBars(id, rows, metric) {{
      const ranked = [...rows].filter((row) => row[metric] !== null).sort((a, b) => Number(b[metric] || 0) - Number(a[metric] || 0));
      if (!ranked.length) {{
        document.getElementById(id).innerHTML = '<div class="empty">没有前一日数据可对比。</div>';
        return;
      }}
      const max = Math.max(0.01, ...ranked.map((row) => Math.abs(Number(row[metric] || 0))));
      document.getElementById(id).innerHTML = ranked.map((row) => {{
        const value = Number(row[metric] || 0);
        return `
          <div class="metric-row">
            <span>${{row.store}}</span>
            <div class="metric-track"><i class="${{value < 0 ? 'down' : 'up'}}" style="width:${{Math.abs(value) / max * 100}}%"></i></div>
            <b class="${{value >= 0 ? 'meituan-text' : 'eleme-text'}}">${{value >= 0 ? '+' : ''}}${{(value * 100).toFixed(1)}}%</b>
          </div>
        `;
      }}).join('');
    }}

    function recordsForDates(dateList) {{
      const allowed = new Set(dateList);
      return records.filter((row) => allowed.has(row.date));
    }}

    function weekPeriod(date) {{
      const selectedIndex = datesAsc.indexOf(date);
      if (selectedIndex < 0) return {{ currentDates: [], previousDates: [] }};
      const currentStart = Math.max(0, selectedIndex - 6);
      const previousStart = Math.max(0, currentStart - 7);
      return {{
        currentDates: datesAsc.slice(currentStart, selectedIndex + 1),
        previousDates: datesAsc.slice(previousStart, currentStart),
      }};
    }}

    function dailyAverage(value, dayCount) {{
      return dayCount ? Number(value || 0) / dayCount : 0;
    }}

    function weekDeltaText(delta, unit, formatter = fmtInt) {{
      const absText = formatter(Math.abs(delta));
      return `${{delta >= 0 ? '涨 +' : '跌 -'}}${{absText}}${{unit}}`;
    }}

    function weekReason(current, previous, orderDelta, incomeDelta) {{
      const impressionDelta = Number(current.total_impressions || 0) - Number(previous.total_impressions || 0);
      const orderConversionDelta = Number(current.order_conversion || 0) - Number(previous.order_conversion || 0);
      const ticketDelta = Number(current.ticket || 0) - Number(previous.ticket || 0);
      if (orderDelta < 0 && impressionDelta < 0) return '主要原因偏向流量减少，优先检查曝光入口、活动资源和推广状态。';
      if (orderDelta < 0 && orderConversionDelta < 0) return '主要原因偏向下单转化走弱，优先检查价格、主推品、配送费和差评影响。';
      if (incomeDelta < 0 && ticketDelta < 0) return '收入下降同时客单走低，优先复看套餐结构、满减力度和平台补贴。';
      if (orderDelta > 0 && incomeDelta > 0) return '单量和营业额同步提升，建议保留有效动作并确认是否能复制到同类门店。';
      if (orderDelta > 0) return '单量提升但收入未完全同步，继续观察客单价和优惠成本。';
      return '变化不集中在单一指标，建议结合平台拆分、营业时长和活动记录复核。';
    }}

    function renderWeeklyAnalysis(date) {{
      const container = document.getElementById('aiWeekAnalysis');
      const {{ currentDates, previousDates }} = weekPeriod(date);
      if (!container) return;
      if (!currentDates.length || !previousDates.length) {{
        container.innerHTML = '<div class="empty">历史数据不足，暂时无法生成 7 日环比周分析。</div>';
        return;
      }}

      const currentStores = storeSummary(recordsForDates(currentDates));
      const previousStores = storeSummary(recordsForDates(previousDates));
      const previousByStore = new Map(previousStores.map((row) => [row.store, row]));
      const currentTotals = totalsFromStores(currentStores);
      const previousTotals = totalsFromStores(previousStores);
      const currentDays = currentDates.length;
      const previousDays = previousDates.length;
      const orderDelta = dailyAverage(currentTotals.totalOrders, currentDays) - dailyAverage(previousTotals.totalOrders, previousDays);
      const incomeDelta = dailyAverage(currentTotals.totalIncome, currentDays) - dailyAverage(previousTotals.totalIncome, previousDays);
      const ticketDelta = Number(currentTotals.ticket || 0) - Number(previousTotals.ticket || 0);
      const periodText = `${{currentDates[0]}} 至 ${{currentDates[currentDates.length - 1]}} 对比 ${{previousDates[0]}} 至 ${{previousDates[previousDates.length - 1]}}`;

      const movers = currentStores.map((row) => {{
        const previous = previousByStore.get(row.store) || {{}};
        const storeOrderDelta = dailyAverage(row.total_orders, currentDays) - dailyAverage(previous.total_orders, previousDays);
        const storeIncomeDelta = dailyAverage(row.total_income, currentDays) - dailyAverage(previous.total_income, previousDays);
        return {{
          ...row,
          previous,
          storeOrderDelta,
          storeIncomeDelta,
          score: Math.abs(storeOrderDelta) + Math.abs(storeIncomeDelta / 120),
        }};
      }}).sort((a, b) => b.score - a.score).slice(0, 8);

      container.innerHTML = `
        <div class="week-summary-grid">
          <div class="week-summary-card">
            <span>分析区间</span>
            <strong>${{periodText}}</strong>
            <em>按已有日报数据日计算，不强行补空日期</em>
          </div>
          <div class="week-summary-card">
            <span>单量日均环比</span>
            <strong class="delta ${{deltaClass(orderDelta)}}">${{weekDeltaText(orderDelta, ' 单/日')}}</strong>
            <em>本期日均 ${{fmtInt(dailyAverage(currentTotals.totalOrders, currentDays))}} 单</em>
          </div>
          <div class="week-summary-card">
            <span>营业额日均环比</span>
            <strong class="delta ${{deltaClass(incomeDelta)}}">${{weekDeltaText(incomeDelta, ' 元/日', fmtMoney)}}</strong>
            <em>客单价 ${{weekDeltaText(ticketDelta, ' 元', fmtMoney)}}</em>
          </div>
        </div>
        <div class="week-store-grid">
          ${{movers.map((row) => {{
            const tone = row.storeOrderDelta >= 0 ? 'up' : 'down';
            return `
              <div class="week-store-card ${{tone}}">
                <b>${{row.store}}</b>
                <strong class="delta ${{tone}}">${{weekDeltaText(row.storeOrderDelta, ' 单/日')}}</strong>
                <p>营业额日均 ${{weekDeltaText(row.storeIncomeDelta, ' 元/日', fmtMoney)}}，下单转化 ${{fmtRate(row.order_conversion)}}。</p>
                <em>${{weekReason(row, row.previous, row.storeOrderDelta, row.storeIncomeDelta)}}</em>
              </div>
            `;
          }}).join('')}}
        </div>
      `;
    }}

    function renderCustomerBars(stores) {{
      const ranked = [...stores].sort((a, b) => safeDiv(b.new_customer_orders, b.new_customer_orders + b.old_customer_orders) - safeDiv(a.new_customer_orders, a.new_customer_orders + a.old_customer_orders));
      document.getElementById('customerBars').innerHTML = ranked.map((row) => {{
        const total = row.new_customer_orders + row.old_customer_orders;
        const newRatio = safeDiv(row.new_customer_orders, total);
        const oldRatio = total ? 1 - newRatio : 0;
        return `
          <div class="customer-col">
            <div class="stack-bar" title="${{row.store}} 新客 ${{fmtRate(newRatio)}} / 老客 ${{fmtRate(oldRatio)}}">
              <div class="stack-new" style="height:${{Math.max(0, newRatio * 100)}}%">${{newRatio >= 0.16 ? fmtRate(newRatio) : ''}}</div>
              <div class="stack-old" style="height:${{Math.max(0, oldRatio * 100)}}%">${{oldRatio >= 0.16 ? fmtRate(oldRatio) : ''}}</div>
            </div>
            <div class="customer-name">${{row.store}}</div>
          </div>
        `;
      }}).join('');
    }}

    function render(date) {{
      const dayRecords = records.filter((row) => row.date === date);
      if (!dayRecords.length) return;
      const prevDate = previousDate(date);
      const prevRecords = prevDate ? records.filter((row) => row.date === prevDate) : [];
      const sharedPlatforms = commonPlatforms(dayRecords, prevRecords);
      const currentCompareRecords = filterPlatforms(dayRecords, sharedPlatforms);
      const previousCompareRecords = filterPlatforms(prevRecords, sharedPlatforms);
      const compareScope = sharedPlatforms.length ? `较前日（${{sharedPlatforms.join('、')}}）` : '较前日';
      const stores = attachPrevious(storeSummary(dayRecords), storeSummary(currentCompareRecords), storeSummary(previousCompareRecords));
      const totals = totalsFromStores(stores);
      const compareTotals = totalsFromStores(storeSummary(currentCompareRecords));
      const prevTotals = totalsFromStores(storeSummary(previousCompareRecords));
      const avgVisit = weightedRate(stores, 'visit_conversion', 'total_impressions');
      const avgOrder = weightedRate(stores, 'order_conversion', 'total_orders');

      document.getElementById('kpiIncome').textContent = fmtMoney(totals.totalIncome);
      document.getElementById('kpiOrders').textContent = fmtInt(totals.totalOrders);
      document.getElementById('kpiImpressions').textContent = fmtInt(totals.totalImpressions);
      document.getElementById('kpiTicket').textContent = fmtMoney(totals.ticket);
      document.getElementById('kpiTicketHint').textContent = `进店转化 ${{fmtRate(avgVisit)}} · 下单转化 ${{fmtRate(avgOrder)}}`;

      [
        ['incomeDelta', pctChange(compareTotals.totalIncome, prevTotals.totalIncome)],
        ['ordersDelta', pctChange(compareTotals.totalOrders, prevTotals.totalOrders)],
        ['impressionsDelta', pctChange(compareTotals.totalImpressions, prevTotals.totalImpressions)],
      ].forEach(([id, change]) => {{
        const el = document.getElementById(id);
        el.textContent = deltaText(change, compareScope);
        el.className = `delta ${{deltaClass(change)}}`;
      }});

      renderBars('incomeBars', stores, 'total_income', fmtMoney);
      renderBars('orderCountBars', stores, 'total_orders', fmtInt);
      renderBars('impressionBars', stores, 'total_impressions', fmtInt);
      renderBars('ticketBars', stores, 'ticket', fmtMoney);
      const customerPaidStores = stores.filter((row) => row.customer_paid_available);
      if (customerPaidStores.length) {{
        renderBars('customerPaidTicketBars', customerPaidStores, 'customer_paid_ticket', fmtMoney);
      }} else {{
        document.getElementById('customerPaidTicketBars').innerHTML = '<div class="empty">当前历史报表未包含顾客实付字段；下一次一键下载后显示。</div>';
      }}
      renderBars('visitBars', stores, 'visit_conversion', fmtRate);
      renderBars('orderBars', stores, 'order_conversion', fmtRate);
      renderCustomerBars(stores);
      document.getElementById('previousDateLabel').textContent = prevDate && sharedPlatforms.length ? `对比 ${{prevDate}}，共同平台：${{sharedPlatforms.join('、')}}` : '无可比前一日平台数据';
      renderChangeBars('incomeChangeBars', stores, 'income_change');
      renderWeeklyAnalysis(date);

      document.getElementById('storeRows').innerHTML = stores
        .sort((a, b) => b.total_income - a.total_income)
        .map((row) => {{
          const [statusText, statusClass] = health(row, avgOrder);
          const newRatio = safeDiv(row.new_customer_orders, row.new_customer_orders + row.old_customer_orders);
          return `
            <tr>
              <td class="store"><span class="status ${{statusClass}}">${{statusText}}</span><a href="${{storeReportFiles[row.store] || '#'}}">${{row.store}}</a></td>
              <td class="strong">${{fmtMoney(row.total_income)}}</td>
              <td><span class="delta ${{deltaClass(row.income_change)}}">${{deltaText(row.income_change, '').trim()}}</span></td>
              <td>${{fmtInt(row.total_orders)}}</td>
              <td><span class="delta ${{deltaClass(row.orders_change)}}">${{deltaText(row.orders_change, '').trim()}}</span></td>
              <td>${{fmtMoney(row.ticket)}}</td>
              <td>${{fmtMoney(safeDiv(row.eleme_income, row.eleme_orders))}}</td>
              <td>${{fmtMoney(safeDiv(row.meituan_income, row.meituan_orders))}}</td>
              <td>${{fmtCustomerPaidTicket(row)}}</td>
              <td>${{fmtInt(row.total_impressions)}}</td>
              <td><span class="delta ${{deltaClass(row.impressions_change)}}">${{deltaText(row.impressions_change, '').trim()}}</span></td>
              <td>${{fmtRate(row.visit_conversion)}}</td>
              <td><span class="delta ${{deltaClass(row.visit_conversion_change)}}">${{rateDeltaText(row.visit_conversion_change)}}</span></td>
              <td>${{fmtRate(row.order_conversion)}}</td>
              <td><span class="delta ${{deltaClass(row.order_conversion_change)}}">${{rateDeltaText(row.order_conversion_change)}}</span></td>
              <td>${{fmtRate(newRatio)}}</td>
              <td><span class="money eleme-text">${{fmtMoney(row.eleme_income)}}</span></td>
              <td><span class="money meituan-text">${{fmtMoney(row.meituan_income)}}</span></td>
            </tr>
          `;
        }}).join('');
    }}

    if (!dates.length) {{
      document.querySelector('main').insertAdjacentHTML('beforeend', '<div class="empty">还没有可展示的数据。</div>');
    }} else {{
      dateSelect.innerHTML = dates.map((date) => `<option value="${{date}}">${{date}}</option>`).join('');
      dateSelect.addEventListener('change', () => render(dateSelect.value));
      render(dates[0]);
    }}
  </script>
</body>
</html>
"""
    output.write_text(html, encoding="utf-8")
    return output


def level_label(level: str) -> str:
    return {"high": "重点", "medium": "留意", "good": "正常"}.get(level, "提示")


def write_store_reports(payload: dict) -> list[Path]:
    stores_dir = DASHBOARD_DIR / "stores"
    stores_dir.mkdir(parents=True, exist_ok=True)
    report_date = latest_report_date(payload)
    previous_date = previous_report_date(payload, report_date)
    paths = []

    for store in payload["target_stores"]:
        records = [row for row in day_records(payload, report_date) if row.get("store") == store]
        current_compare, previous_compare, _ = common_platform_records(payload, store, report_date)
        previous_records = [row for row in day_records(payload, previous_date) if row.get("store") == store] if previous_date else []
        previous_by_platform = {row.get("platform"): row for row in previous_records}
        summary = compact_store_summary(records)
        previous_summary = compact_store_summary(previous_compare)
        compare_summary = compact_store_summary(current_compare)
        changes = {
            "income": pct_change(compare_summary["income"], previous_summary["income"]),
            "orders": pct_change(compare_summary["orders"], previous_summary["orders"]),
            "impressions": pct_change(compare_summary["impressions"], previous_summary["impressions"]),
            "ticket": pct_change(compare_summary["ticket"], previous_summary["ticket"]),
            "customer_paid_ticket": pct_change(compare_summary["customer_paid_ticket"], previous_summary["customer_paid_ticket"]),
        }
        focus_items = build_focus_items(payload, store, report_date)
        review_note = store_review_note(payload.get("review_summary", {}), store)
        focus_html = "\n".join(
            f"""<div class="alert {html_lib.escape(item['level'])}">
        <strong>{level_label(item['level'])}：{html_lib.escape(item['title'])}</strong>
        <span>{html_lib.escape(item['body'])}</span>
      </div>"""
            for item in focus_items
        )
        platform_rows = "\n".join(
            f"""<tr>
          <td>{html_lib.escape(row['platform'])}</td>
          <td>{fmt_money(float(row.get('income') or 0))}</td>
          <td>{fmt_int(row.get('orders') or 0)}</td>
          <td>{fmt_money(safe_div(float(row.get('income') or 0), float(row.get('orders') or 0)))}</td>
          <td>{fmt_record_customer_paid_ticket(row)}</td>
          <td>{fmt_int(row.get('impressions') or 0)}</td>
          <td>{fmt_rate(float(row.get('visit_conversion') or 0))}</td>
          <td>{fmt_rate(float(row.get('order_conversion') or 0))}</td>
          <td>{fmt_rate(safe_div(float(row.get('new_customer_orders') or 0), float(row.get('new_customer_orders') or 0) + float(row.get('old_customer_orders') or 0)))}</td>
        </tr>"""
            for row in sorted(records, key=lambda item: item.get("platform", ""))
        )
        if not platform_rows:
            platform_rows = '<tr><td colspan="9" class="empty-cell">今日没有该门店平台数据。</td></tr>'

        platform_cards_html = "\n".join(
            f"""<div class="platform-card">
        <div class="platform-card-head">
          <strong>{html_lib.escape(row['platform'])}</strong>
          <span>{fmt_money(float(row.get('income') or 0))} / {fmt_int(row.get('orders') or 0)} 单</span>
        </div>
        <div class="platform-metrics">
          <div><span>曝光</span><b>{fmt_int(row.get('impressions') or 0)}</b><em class="delta {delta_class(pct_change(float(row.get('impressions') or 0), float((previous_by_platform.get(row.get('platform')) or {}).get('impressions') or 0)))}">{fmt_delta_text(pct_change(float(row.get('impressions') or 0), float((previous_by_platform.get(row.get('platform')) or {}).get('impressions') or 0)))}</em></div>
          <div><span>进店转化</span><b>{fmt_rate(float(row.get('visit_conversion') or 0))}</b><em class="delta {delta_class((float(row.get('visit_conversion') or 0) - float((previous_by_platform.get(row.get('platform')) or {}).get('visit_conversion') or 0)) if previous_by_platform.get(row.get('platform')) else None)}">{fmt_rate_delta_text((float(row.get('visit_conversion') or 0) - float((previous_by_platform.get(row.get('platform')) or {}).get('visit_conversion') or 0)) if previous_by_platform.get(row.get('platform')) else None)}</em></div>
          <div><span>下单转化</span><b>{fmt_rate(float(row.get('order_conversion') or 0))}</b><em class="delta {delta_class((float(row.get('order_conversion') or 0) - float((previous_by_platform.get(row.get('platform')) or {}).get('order_conversion') or 0)) if previous_by_platform.get(row.get('platform')) else None)}">{fmt_rate_delta_text((float(row.get('order_conversion') or 0) - float((previous_by_platform.get(row.get('platform')) or {}).get('order_conversion') or 0)) if previous_by_platform.get(row.get('platform')) else None)}</em></div>
        </div>
      </div>"""
            for row in sorted(records, key=lambda item: item.get("platform", ""))
        )
        if not platform_cards_html:
            platform_cards_html = '<div class="empty-cell">今日没有该门店平台数据。</div>'

        trend_rows = []
        for date_value in sorted(payload.get("source_dates", []), reverse=True):
            rows = [row for row in day_records(payload, date_value) if row.get("store") == store]
            day = compact_store_summary(rows)
            trend_rows.append(
                f"""<tr>
          <td>{html_lib.escape(date_value)}</td>
          <td>{fmt_money(day['income'])}</td>
          <td>{fmt_int(day['orders'])}</td>
          <td>{fmt_money(day['ticket'])}</td>
          <td>{fmt_customer_paid_ticket(day)}</td>
          <td>{fmt_int(day['impressions'])}</td>
          <td>{fmt_rate(day['visit_conversion'])}</td>
          <td>{fmt_rate(day['order_conversion'])}</td>
          <td>{fmt_rate(day['new_customer_ratio'])}</td>
        </tr>"""
            )

        path = stores_dir / f"{store_slug(store)}.html"
        html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_lib.escape(store)}日报</title>
  <style>
    :root {{
      --bg: #f5f7fa;
      --panel: #ffffff;
      --line: #dfe5ee;
      --text: #172033;
      --muted: #667085;
      --accent: #0f766e;
      --blue: #2563eb;
      --warn: #b45309;
      --bad: #b42318;
      --good: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      background: linear-gradient(180deg, #e8f1f0 0, rgba(232, 241, 240, 0) 260px), var(--bg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 22px 24px 28px; }}
    header {{ display: flex; justify-content: space-between; gap: 18px; align-items: flex-end; margin-bottom: 14px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .muted {{ color: var(--muted); font-size: 14px; }}
    .panel, .card, .table-wrap {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }}
	    .kpis {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }}
    .card {{ min-height: 92px; padding: 13px 14px; display: grid; gap: 8px; }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ font-size: 25px; font-weight: 780; line-height: 1; }}
    .delta {{ width: fit-content; padding: 3px 7px; border-radius: 999px; font-size: 12px; font-weight: 650; background: #eef2f6; color: #475467; }}
    .delta.up {{ background: #fee4e2; color: #b42318; }}
    .delta.down {{ background: #dcfae6; color: #067647; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }}
    .panel {{ padding: 18px; }}
    .platform-cards {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }}
    .platform-card {{ padding: 15px; border: 1px solid var(--line); border-radius: 8px; background: #fff; }}
    .platform-card-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 12px; }}
    .platform-card-head strong {{ font-size: 17px; }}
    .platform-card-head span {{ color: var(--muted); font-size: 13px; }}
    .platform-metrics {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .platform-metrics div {{ display: grid; gap: 7px; min-width: 0; }}
    .platform-metrics span {{ color: var(--muted); font-size: 12px; }}
    .platform-metrics b {{ font-size: 20px; line-height: 1; }}
    .platform-metrics em {{ font-style: normal; }}
    .alert {{ display: grid; gap: 6px; padding: 12px 14px; border: 1px solid var(--line); border-left: 4px solid #98a2b3; border-radius: 8px; background: #fff; margin-bottom: 10px; }}
    .alert.high {{ border-left-color: var(--bad); background: #fff8f7; }}
    .alert.medium {{ border-left-color: var(--warn); background: #fffbeb; }}
    .alert.good {{ border-left-color: var(--good); background: #f0fdfa; }}
    .alert span {{ color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .summary-list {{ display: grid; gap: 10px; }}
    .summary-row {{ display: flex; justify-content: space-between; gap: 16px; padding-bottom: 10px; border-bottom: 1px solid #edf1f6; }}
    .summary-row:last-child {{ border-bottom: 0; padding-bottom: 0; }}
    .summary-row span {{ color: var(--muted); }}
    .summary-row b {{ text-align: right; }}
    .review-note {{ margin-top: 12px; padding: 12px 14px; border: 1px solid #fde68a; border-radius: 8px; background: #fffbeb; color: #7a5b13; font-size: 13px; line-height: 1.5; }}
    .table-wrap {{ overflow-x: auto; margin-bottom: 12px; }}
	    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ padding: 11px 10px; border-bottom: 1px solid #edf1f6; text-align: right; white-space: nowrap; }}
    th {{ color: var(--muted); font-size: 13px; background: #fbfcfe; font-weight: 650; }}
    th:first-child, td:first-child {{ text-align: left; font-weight: 650; }}
    .empty-cell {{ text-align: center !important; color: var(--muted); padding: 24px; }}
    @media (max-width: 820px) {{
      main {{ padding: 18px; }}
      header {{ display: block; }}
      .kpis, .grid, .platform-cards, .platform-metrics {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>{html_lib.escape(store)}日报</h1>
        <div class="muted">数据日期：{html_lib.escape(report_date)} · 生成时间：{html_lib.escape(payload["generated_at"])}</div>
      </div>
      <a href="../index.html">返回总看板</a>
    </header>

    <section class="kpis">
      <div class="card"><div class="label">收入</div><div class="value">{fmt_money(summary["income"])}</div><div class="delta {'up' if (changes['income'] or 0) >= 0 else 'down'}">{fmt_delta_text(changes["income"])}</div></div>
	      <div class="card"><div class="label">单量</div><div class="value">{fmt_int(summary["orders"])}</div><div class="delta {'up' if (changes['orders'] or 0) >= 0 else 'down'}">{fmt_delta_text(changes["orders"])}</div></div>
	      <div class="card"><div class="label">曝光量</div><div class="value">{fmt_int(summary["impressions"])}</div><div class="delta {'up' if (changes['impressions'] or 0) >= 0 else 'down'}">{fmt_delta_text(changes["impressions"])}</div></div>
	      <div class="card"><div class="label">客单价</div><div class="value">{fmt_money(summary["ticket"])}</div><div class="delta {'up' if (changes['ticket'] or 0) >= 0 else 'down'}">{fmt_delta_text(changes["ticket"])}</div></div>
	      <div class="card"><div class="label">顾客实付单均价</div><div class="value">{fmt_customer_paid_ticket(summary)}</div><div class="delta {'up' if (changes['customer_paid_ticket'] or 0) >= 0 else 'down'}">{fmt_delta_text(changes["customer_paid_ticket"])}</div></div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>今日重点关注</h2>
        {focus_html}
        <div class="review-note">{html_lib.escape(review_note)}</div>
      </div>
      <div class="panel">
        <h2>经营摘要</h2>
        <div class="summary-list">
          <div class="summary-row"><span>进店转化率</span><b>{fmt_rate(summary["visit_conversion"])}</b></div>
          <div class="summary-row"><span>下单转化率</span><b>{fmt_rate(summary["order_conversion"])}</b></div>
          <div class="summary-row"><span>新客占比</span><b>{fmt_rate(summary["new_customer_ratio"])}</b></div>
          <div class="summary-row"><span>新客 / 老客订单</span><b>{fmt_int(summary["new_customer_orders"])} / {fmt_int(summary["old_customer_orders"])}</b></div>
          <div class="summary-row"><span>对比基准</span><b>{html_lib.escape(previous_date or "无前日数据")}</b></div>
        </div>
      </div>
    </section>

    <section class="platform-cards">
      {platform_cards_html}
    </section>

    <section class="table-wrap">
      <table>
        <thead>
          <tr>
	            <th>平台</th><th>收入</th><th>单量</th><th>客单价</th><th>顾客实付单均价</th><th>曝光</th><th>进店转化</th><th>下单转化</th><th>新客占比</th>
          </tr>
        </thead>
        <tbody>
          {platform_rows}
        </tbody>
      </table>
    </section>

    <section class="table-wrap">
      <table>
        <thead>
          <tr>
	            <th>日期</th><th>收入</th><th>单量</th><th>客单价</th><th>顾客实付单均价</th><th>曝光</th><th>进店转化</th><th>下单转化</th><th>新客占比</th>
          </tr>
        </thead>
        <tbody>
          {"".join(trend_rows)}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""
        path.write_text(html_text, encoding="utf-8")
        paths.append(path)
    return paths


def process(eleme_path: Path | None, meituan_path: Path | None) -> dict:
    config = load_config()
    alias_lookup = build_alias_lookup(config)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for path in (eleme_path, meituan_path):
        if path is None:
            continue
        target = RAW_DIR / path.name
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)

    def latest_by_report_date(paths: list[Path], pattern: str) -> list[Path]:
        latest: dict[str, Path] = {}
        for path in paths:
            match = re.search(pattern, path.name)
            key = match.group(1) if match else path.stem
            current = latest.get(key)
            if current is None or path.stat().st_mtime > current.stat().st_mtime:
                latest[key] = path
        return sorted(latest.values(), key=lambda path: path.stat().st_mtime)

    eleme_paths = latest_by_report_date(
        sorted(RAW_DIR.glob("门店下载_*.xlsx"), key=lambda path: path.stat().st_mtime),
        r"门店下载_(\d{8})至\1",
    )
    meituan_paths = latest_by_report_date(
        sorted((path for path in RAW_DIR.glob("门店_全部门店_*.csv") if "_UTF8" not in path.stem), key=lambda path: path.stat().st_mtime),
        r"门店_全部门店_(\d{8})_\1",
    )

    frames = []
    warnings = []
    for path in eleme_paths:
        frame, frame_warnings = read_eleme(path, config, alias_lookup)
        frames.append(frame)
        warnings.extend(frame_warnings)
    for path in meituan_paths:
        frame, frame_warnings = read_meituan(path, config, alias_lookup)
        frames.append(frame)
        warnings.extend(frame_warnings)

    unified = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "platform", "store"])
    unified = unified[unified["store"].isin(config["target_stores"])].copy()
    unified.sort_values(["date", "store", "platform"], inplace=True)
    unified.drop_duplicates(subset=["date", "platform", "store"], keep="last", inplace=True)

    unified_path = DATA_DIR / "unified_daily.csv"
    unified.to_csv(unified_path, index=False, encoding="utf-8-sig")

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_dates": sorted([date for date in unified["date"].dropna().unique().tolist() if date]),
        "target_stores": config["target_stores"],
        "store_summary": build_store_summary(unified, config["target_stores"]),
        "platform_summary": build_platform_summary(unified),
        "warnings": warnings,
        "records": unified.to_dict(orient="records"),
    }
    payload["store_report_files"] = {store: f"stores/{store_slug(store)}.html" for store in config["target_stores"]}
    latest_date = latest_report_date(payload)
    review_df = read_review_files(alias_lookup)
    if not review_df.empty:
        review_df.to_csv(DATA_DIR / "unified_reviews.csv", index=False, encoding="utf-8-sig")
    payload["review_summary"] = summarize_reviews(review_df, config["target_stores"], latest_date) if latest_date else {}
    payload["focus_items"] = build_all_focus_items(payload, latest_date) if latest_date else []
    payload["all_store_diagnoses"] = build_all_store_diagnoses(payload, latest_date) if latest_date else []

    (DATA_DIR / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    dashboard_path = write_dashboard(payload)
    store_report_paths = write_store_reports(payload)
    return {
        "unified_path": str(unified_path),
        "dashboard_path": str(dashboard_path),
        "store_report_paths": [str(path) for path in store_report_paths],
        "payload": payload,
    }


def latest_file(downloads_dir: Path, patterns: list[str]) -> Path | None:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(Path(path) for path in glob.glob(str(downloads_dir / pattern)))
    candidates = [path for path in candidates if path.is_file() and "_UTF8" not in path.stem.upper()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def latest_report_file(search_dirs: list[Path], patterns: list[str]) -> Path | None:
    for directory in search_dirs:
        path = latest_file(directory.expanduser(), patterns)
        if path:
            return path
    return None


def resolve_input_files(
    eleme: Path | None,
    meituan: Path | None,
    downloads_dir: Path,
    *,
    allow_missing_platform: bool = False,
) -> tuple[Path | None, Path | None]:
    search_dirs = [downloads_dir, RAW_DIR]
    if allow_missing_platform:
        eleme_path = eleme
        meituan_path = meituan
    else:
        eleme_path = eleme or latest_report_file(search_dirs, ["门店下载_*.xlsx", "*饿了么*.xlsx", "eleme.xlsx"])
        meituan_path = meituan or latest_report_file(search_dirs, ["门店_全部门店_*.csv", "*美团*.csv", "meituan.csv"])
    missing = []
    if not eleme_path:
        missing.append("饿了么 Excel")
    if not meituan_path:
        missing.append("美团 CSV")
    if missing and not allow_missing_platform:
        raise FileNotFoundError(
            f"未找到：{'、'.join(missing)}。请放到下载目录或 data/raw，或用 --eleme / --meituan 指定文件。"
        )
    return (
        eleme_path.expanduser().resolve() if eleme_path else None,
        meituan_path.expanduser().resolve() if meituan_path else None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="生成经营日报看板")
    parser.add_argument("--eleme", type=Path, help="饿了么 Excel 文件路径；不填则自动从下载目录找最新文件")
    parser.add_argument("--meituan", type=Path, help="美团 CSV 文件路径；不填则自动从下载目录找最新文件")
    parser.add_argument("--downloads-dir", type=Path, default=Path.home() / "Downloads", help="自动查找报表的下载目录")
    parser.add_argument("--allow-missing-platform", action="store_true", help="只处理显式传入的平台文件；缺失平台不自动使用历史文件")
    args = parser.parse_args()

    eleme_path, meituan_path = resolve_input_files(
        args.eleme,
        args.meituan,
        args.downloads_dir,
        allow_missing_platform=args.allow_missing_platform,
    )
    print(f"使用饿了么报表：{eleme_path if eleme_path else '缺失，本次不自动使用历史文件'}")
    print(f"使用美团报表：{meituan_path if meituan_path else '缺失，本次不自动使用历史文件'}")
    result = process(eleme_path, meituan_path)
    payload = result["payload"]
    print(f"已生成统一数据：{result['unified_path']}")
    print(f"已生成网页看板：{result['dashboard_path']}")
    print(f"门店数：{len(payload['store_summary'])}，明细记录：{len(payload['records'])}，提示：{len(payload['warnings'])}")


if __name__ == "__main__":
    main()
