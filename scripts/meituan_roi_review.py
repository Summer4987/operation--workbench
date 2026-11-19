#!/usr/bin/env python3
"""Read-only, daily Meituan income-return estimates. Production state stays local."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
SOURCE_ROOT = Path(__file__).resolve().parents[1]
NUMBER = r"([0-9][0-9,]*(?:\.[0-9]+)?)"


def now():
    return datetime.now(TZ)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def numeric(value):
    try:
        result = float(str(value).replace(",", ""))
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def after_label(text, labels):
    for label in labels:
        match = re.search(re.escape(label) + r"\s*[¥￥]?\s*" + NUMBER, text)
        if match:
            return numeric(match[1])
    return None


def parse_promotion(text, target_date):
    # Never fall back to seven-day totals, yesterday, configured budget or rounded %.
    match = re.search(r"今日\s*(\d{2}-\d{2})\s+(\d{2}:\d{2})\s*更新", text)
    if not match or match[1] != target_date[5:]:
        raise ValueError("推广页实时日期未确认或不是目标日期")
    panel = text.split("实时数据", 1)[-1].split("历史数据", 1)[0]
    spend = after_label(panel, ["推广花费"])
    visits = after_label(panel, ["推广进店量"])
    if spend is None or visits is None or not visits.is_integer():
        raise ValueError("未读取到当日实际推广花费或推广进店量")
    return dict(spend=spend, promo_visits=int(visits), promotion_updated_at=f"{target_date} {match[2]}:00")


def parse_overview(text, target_date):
    match = re.search(r"(\d{2}-\d{2})\s+(\d{2}:\d{2})\s*更新", text)
    if "今日实时数据" not in text or not match or match[1] != target_date[5:]:
        raise ValueError("经营总览未确认目标日期的今日实时数据")
    panel = text.split("今日实时数据", 1)[1].split("历史收益概览", 1)[0]
    income = after_label(panel, ["预计订单收入", "预计收入"])
    orders = after_label(panel, ["订单量"])
    if income is None or orders is None or not orders.is_integer():
        raise ValueError("经营总览缺少当日预计收入或订单量")
    return dict(income=income, orders=int(orders), income_source="经营总览·今日实时", income_updated_at=f"{target_date} {match[2]}:00")


def parse_flow(text, target_date, *, active_today=False):
    selected = re.search(r"已选时间\s*[:：]?\s*(\d{4}-\d{2}-\d{2})", text)
    stamp = re.search(r"(\d{2}-\d{2})\s+(\d{2}:\d{2})\s*更新", text)
    confirmed = selected[1] == target_date if selected else active_today and stamp and stamp[1] == target_date[5:]
    if not confirmed:
        raise ValueError("流量页面未确认目标日期，拒绝使用昨日或其他日期转化率")
    # The left (本店) funnel appears before the right peer funnel.
    panel = text.split("流量转化", 1)[-1].split("经营建议", 1)[0]
    match = re.search(NUMBER + r"\s*%?\s*下单转化率", panel)
    if not match:
        match = re.search(r"下单转化率\s*" + NUMBER + r"\s*%", panel)
    rate = numeric(match[1]) / 100 if match else None
    if rate is None or not 0 <= rate <= 1:
        raise ValueError("流量页面未读取到本店下单转化率")
    result = dict(conversion_rate=rate, conversion_source="经营数据·流量·今日实时")
    if stamp:
        result["conversion_updated_at"] = f"{target_date} {stamp[2]}:00"
    return result


def cached_income(payload, task, at, max_age_minutes=20):
    stamp = payload.get("generated_at", "")
    try:
        collected = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        collected = collected.replace(tzinfo=TZ) if collected.tzinfo is None else collected.astimezone(TZ)
    except ValueError:
        return None
    if collected.date() != at.date() or not 0 <= (at-collected).total_seconds() <= max_age_minutes*60:
        return None
    # Use the existing centralized name mapping for legacy stalls, never fuzzy joins.
    aliases = {task.get("keyword"), task.get("sourceStore"), task.get("store")}
    aliases.add({"第3档口": "中关村", "川湘府": "清河", "雅宝": "朝阳门"}.get(task.get("keyword"), ""))
    aliases = {re.sub(r"店$", "", str(v)) for v in aliases if v}
    matches = [r for r in payload.get("items", []) if r.get("platform") == "美团"
               and re.sub(r"店$", "", str(r.get("store", ""))) in aliases
               and r.get("income_status", "trusted") == "trusted"]
    if len(matches) != 1:
        return None
    row = matches[0]
    income, orders = numeric(row.get("income")), numeric(row.get("orders"))
    if income is None or orders is None or not orders.is_integer():
        return None
    return dict(income=income, orders=int(orders), income_source="当日实时采集复用", income_updated_at=stamp)


def estimate(row):
    result = dict(row, estimated_orders=None, average_ticket=None, estimated_income=None, roi=None)
    required = ("spend", "promo_visits", "conversion_rate", "income", "orders")
    if any(numeric(row.get(k)) is None for k in required) or row["conversion_rate"] > 1:
        return dict(result, status="failed", error=row.get("error") or "测算字段缺失或无效")
    if row["orders"] == 0:
        return dict(result, status="no_orders", error="当日订单量为0，客单价与ROI不计算")
    ticket = row["income"] / row["orders"]
    orders = row["promo_visits"] * row["conversion_rate"]
    income = orders * ticket
    result.update(average_ticket=ticket, estimated_orders=orders, estimated_income=income)
    if row["spend"] == 0:
        return dict(result, status="no_spend", error="推广消耗为0，ROI不计算")
    return dict(result, status="ok", roi=income / row["spend"])


def summarize(rows):
    valid = [r for r in rows if r.get("status") == "ok"]
    spend = sum(r["spend"] for r in valid)
    income = sum(r["estimated_income"] for r in valid)
    return dict(store_count=len(rows), success_count=len(valid), failed_count=sum(r.get("status") == "failed" for r in rows),
                excluded_count=len(rows)-len(valid), spend=round(spend, 2), estimated_income=round(income, 2),
                estimated_orders=sum(r["estimated_orders"] for r in valid), roi=income/spend if spend else None)


def save_review(output, review):
    review["summary"] = summarize(review["items"])
    if review.get("status") != "running":
        review["status"] = "ok" if review["summary"]["success_count"] == len(review["items"]) and review["items"] else "partial" if review["summary"]["success_count"] else "failed"
    atomic_json(output / f"{review['date']}.json", review)
    atomic_json(output / "latest.json", review)
    dates = sorted(output.glob("????-??-??.json"), reverse=True)[:90]
    days = [read_json(p) for p in dates]
    atomic_json(output / "history.json", dict(generated_at=review["generated_at"], days=days))


def click(page, label, helpers):
    if not helpers["click_visible_text"](page, label):
        raise RuntimeError(f"没有找到只读入口：{label}")
    page.wait_for_timeout(1500)


def open_headquarters_promotion(page, task, helpers, promo):
    """The current dropdown is .roo-popup li; placement may be top or bottom."""
    page.goto(promo.HEADQUARTERS_HOME_URL, wait_until="domcontentloaded", timeout=45000)
    selector = page.locator(".current-poi_31GHxd").first
    selector.wait_for(state="visible", timeout=20000)
    promo.dismiss_common_modals(page)
    selector.click(timeout=8000)
    items = page.locator(".roo-popup:visible li")
    items.first.wait_for(state="visible", timeout=10000)
    aliases = promo.task_store_aliases(task)
    matches = []
    for index in range(items.count()):
        name = items.nth(index).inner_text()
        if "全部门店" not in name and any(alias in name for alias in aliases):
            matches.append(index)
    if len(matches) != 1:
        raise ValueError("总部账号未唯一匹配目标门店：" + str(task.get("keyword")))
    items.nth(matches[0]).click(timeout=8000)
    deadline = time.monotonic()+20
    while not any(alias in selector.inner_text() for alias in aliases):
        if time.monotonic() >= deadline:
            raise ValueError("切换后页面门店身份未确认")
        page.wait_for_timeout(500)
    # Reuse the established read-only navigation after identity is confirmed.
    click(page, "门店推广", helpers)
    helpers["enter_dianjin_with_recovery"](page, page.url)


def read_business(page, helpers, target_date, cached):
    click(page, "经营罗盘", helpers)
    click(page, "经营数据", helpers)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        text = helpers["page_text"](page)
        if "今日实时数据" in text and re.search(r"预计(?:订单)?收入\s*[\d,]+", text):
            break
        page.wait_for_timeout(500)
    income = cached or parse_overview(text, target_date)
    click(page, "流量", helpers)
    click(page, "今日实时", helpers)
    deadline = time.monotonic() + 25
    while True:
        try:
            # The realtime page has no selected-date label; verify the UI tab,
            # then use its own explicit MM-DD update timestamp.
            active = False
            for frame in page.frames:
                today = frame.get_by_text("今日实时", exact=True)
                if today.count() == 1:
                    classes = today.evaluate("el => [el, el.parentElement].map(e => e.className).join(' ')")
                    active = bool(re.search(r"active|selected|checked", classes, re.I))
                    if active:
                        break
            flow = parse_flow(helpers["page_text"](page), target_date, active_today=active)
            if flow.get("conversion_updated_at"):
                stamp = datetime.fromisoformat(flow["conversion_updated_at"]).replace(tzinfo=TZ)
                if not 0 <= (now()-stamp).total_seconds() <= 20*60:
                    raise ValueError("当日流量数据更新时间超过20分钟")
            return dict(income, **flow)
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            page.wait_for_timeout(700)


def collect_store(task, helpers, pw, contexts, launched, accounts, cache, promo):
    import platform_account_access as access
    row = dict(store=task.get("keyword") or task.get("sourceStore"), platform="美团", wm_poi_id=str(task.get("wmPoiId") or ""),
               date=now().date().isoformat(), status="failed", collected_at=now().isoformat(timespec="seconds"))
    page = None
    coordinator = access.Coordinator()
    account = access.for_task(task)
    try:
        with coordinator.lease(account, wait_seconds=120):
            context = helpers["context_for_task"](pw, contexts, launched, task, accounts)
            page = context.new_page()
            page.set_default_timeout(8000)
            if task.get("directMeituanAccountId"):
                base = helpers["base_url_for_task"]("", task, accounts, context)
                page.goto(promo.dianjin_url_for_store(base, row["wm_poi_id"], helpers), wait_until="domcontentloaded", timeout=45000)
                helpers["enter_dianjin_with_recovery"](page, page.url)
            else:
                open_headquarters_promotion(page, task, helpers, promo)
            page.reload(wait_until="domcontentloaded", timeout=45000)
            deadline = time.monotonic() + 25
            while True:
                promo.raise_if_meituan_verify_page(page)
                text = helpers["page_text"](page)
                try:
                    fields = parse_promotion(text, row["date"])
                    # Confirm actual visible identity, not only a URL parameter.
                    header = promo.visible_page_text(page)
                    if not any(alias in header for alias in promo.task_store_aliases(task)):
                        raise ValueError("页面门店身份与目标门店不符")
                    break
                except ValueError:
                    if time.monotonic() >= deadline:
                        raise
                    page.wait_for_timeout(700)
            row.update(fields)
            stamp = datetime.fromisoformat(fields["promotion_updated_at"]).replace(tzinfo=TZ)
            if not 0 <= (now()-stamp).total_seconds() <= 20*60:
                raise ValueError("推广页面更新时间超过20分钟，未将旧页面作为本轮数据")
            row.update(read_business(page, helpers, row["date"], cached_income(cache, task, now())))
            if now().date().isoformat() != row["date"]:
                raise ValueError("采集跨日，未合并两个日期的数据")
            return estimate(row)
    except Exception as exc:
        from platform_auth_guard import is_auth_failure
        if is_auth_failure(exc) and not isinstance(exc, access.AccountAccessError):
            coordinator.block(account, str(exc))
        # Persist only short text, not signed URLs / request tokens / page content.
        error = re.sub(r"https?://\S+", "[页面链接]", str(exc).split("Call log:")[0])[:240]
        return dict(row, status="failed", error=error)
    finally:
        if page is not None:
            with contextlib.suppress(Exception):
                page.close()


def publish(output):
    server = os.environ.get("OPERATION_CLOUD_SERVER", "ubuntu@139.155.148.169")
    target = os.environ.get("OPERATION_CLOUD_REMOTE_DIR", "/var/www/html/operation-workbench") + "/outputs/promo_roi"
    identity = Path.home()/".ssh/xiong_operation_cloud_ed25519"
    options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new"]
    if identity.exists():
        options += ["-i", str(identity)]
    # Fixed destination; publish two sanitized JSON files by atomic rename.
    import shlex
    subprocess.run(["ssh", *options, server, "mkdir -p " + shlex.quote(target)], check=True, timeout=30)
    for name in ("latest.json", "history.json"):
        remote_tmp = target + "/" + name + ".tmp"
        subprocess.run(["scp", *options, str(output/name), server+":"+shlex.quote(remote_tmp)], check=True, timeout=45)
        command = f"chmod 644 {shlex.quote(remote_tmp)} && mv {shlex.quote(remote_tmp)} {shlex.quote(target+'/'+name)}"
        subprocess.run(["ssh", *options, server, command], check=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--store", action="append", default=[])
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument("--probe", action="store_true", help="生产只读验证，单独保存，不覆盖正式21点结果")
    args = parser.parse_args()
    if sys.platform != "darwin" or "mini" not in socket.gethostname().lower():
        parser.error("真实平台采集和发布只允许在 Mac mini 执行")
    root = args.runtime_root.resolve()
    output = root/"outputs/promo_roi"
    if args.probe:
        if args.publish or args.publish_only:
            parser.error("probe结果不能作为正式复盘发布")
        output = output/"probe"
    output.mkdir(parents=True, exist_ok=True)
    if args.publish_only:
        publish(output)
        return 0
    sys.path.insert(0, str(root/"scripts"))
    import meituan_promo_spend_query as promo
    # Keep the complete browser operation in the existing global job lock.
    lock_path = root/"outputs/locks/morning-ops.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        deadline = time.monotonic()+600
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("等待生产浏览器任务锁10分钟超时，未执行ROI采集")
                time.sleep(2)
        tasks = promo.filter_tasks(promo.load_meituan_tasks("all"), args.store)
        if not tasks:
            raise RuntimeError("美团目标门店清单为空")
        target_date = now().date().isoformat()
        review = dict(date=target_date, generated_at=now().isoformat(timespec="seconds"), status="running", platform="美团",
                      scheduled_time="21:00", timezone="Asia/Shanghai", model="推广进店量 × 全店下单转化率 × 预计收入/订单量 ÷ 实际推广消耗",
                      items=[dict(store=t.get("keyword"), platform="美团", status="pending") for t in tasks])
        save_review(output, review)
        helpers = promo.require_helpers()
        cache = read_json(root/"outputs/realtime_order_income/latest.json")
        accounts = helpers["load_direct_meituan_accounts"]()
        with helpers["sync_playwright"]() as pw:
            contexts, launched = {}, []
            for index, task in enumerate(tasks):
                print(f"[{now().isoformat(timespec='seconds')}] ROI采集 {index+1}/{len(tasks)} {task.get('keyword')}", flush=True)
                review["items"][index] = collect_store(task, helpers, pw, contexts, launched, accounts, cache, promo)
                review["generated_at"] = now().isoformat(timespec="seconds")
                save_review(output, review)
                if args.publish:
                    try:
                        publish(output)
                    except (subprocess.SubprocessError, OSError) as exc:
                        print(f"本店结果已保存在Mac mini，云端更新稍后重试：{type(exc).__name__}", flush=True)
        review["status"] = "finished"
        save_review(output, review)
        if args.publish:
            publish(output)
        print(json.dumps(review["summary"], ensure_ascii=False), flush=True)
        return 0 if review["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
