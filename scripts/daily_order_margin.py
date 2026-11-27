#!/usr/bin/env python3
"""Collect and publish order-margin aggregates from the production Mac mini."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, nullcontext
from datetime import datetime
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time
import unicodedata
from zoneinfo import ZoneInfo

import analyze_order_margin_snapshots as analysis
import collect_order_margin_snapshots as capture
from meituan_roi_review import atomic_json

SOURCE = Path(__file__).resolve().parents[1]
RUNTIME = Path.home() / "Library/Application Support/xiong-operation/production"
COST_INPUT = RUNTIME.parent / "order-margin-inputs/20261127.json"
TZ = ZoneInfo("Asia/Shanghai")
STORES = {
    "银泰城店": "direct", "万象城店": "direct", "金融城店": "direct", "保利中心店": "direct",
    "中关村店": "company", "安贞店": "company", "清河店": "company",
    "金融街店": "franchise", "双井店": "franchise", "望京店": "franchise", "滨江店": "franchise",
}
PORTS = {
    9222: ("mt", ["保利中心店", "中关村店", "安贞店", "清河店", "金融街店", "双井店", "望京店", "滨江店"]),
    19224: ("mt", ["银泰城店"]), 19225: ("mt", ["万象城店"]), 19226: ("mt", ["金融城店"]),
    9223: ("ele", list(STORES)),
}
PLATFORMS = {"mt": "美团", "ele": "淘宝闪购"}
EXPECTED = {(store, platform) for store in STORES for platform in PLATFORMS}


def now():
    return datetime.now(TZ)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def plain(name):
    return re.sub(r'[\s「」【】\[\]()\u200b\ufe0f]+', '', unicodedata.normalize('NFKC', name)).replace('’', "'")


class Costs:
    def __init__(self, path):
        payload = read_json(path)
        self.label = payload["label"]
        self.version = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        self.lookups = {}
        for group, size in (("direct", 37), ("company", 36), ("franchise", 36)):
            section = payload["groups"][group]
            current = {k: Decimal(v) for k, v in section["feishu"].items()}
            fallback = {k: Decimal(v) for k, v in section["fallback"].items()}
            if section["source_rows"] != size or len(current) < size or not fallback:
                raise ValueError("成本表版本或覆盖有误")
            if not all(v.is_finite() and v >= 0 for v in (*current.values(), *fallback.values())):
                raise ValueError("单位成本无效")
            merged = {**fallback, **current}
            keys = sorted(((plain(k), k, v) for k, v in current.items()), key=lambda row: -len(row[0]))
            self.lookups[group] = (current, merged, keys, {plain(k): v for k, v in merged.items()})

    def unit(self, name, store):
        current, merged, keys, normalized = self.lookups[STORES[store]]
        match = plain(name)
        for cleaned, key, cost in keys:
            if cleaned not in match:
                continue
            if key in {"温泉蛋", "芝麻菠菜"} and "饭" in match and cleaned != match:
                continue
            if key.endswith("牛五花饭") and match.startswith("加一份"):
                continue
            return cost
        if "温泉蛋" in match and ("饭饭伴侣" in match or "饭" not in match):
            return current["温泉蛋"]
        if "鲜豆腐味噌汤" in match:
            return current["鲜豆腐味增汤"]
        return merged.get(analysis.normalize(name, merged), normalized.get(match))


def summarize(record, costs):
    orders = analysis.parse_record(record, {}, normalize_name=lambda name, _: name.strip())
    for order in orders:
        prices = [(item, costs.unit(item["name"], record["store"])) for item in order["expanded_items"]]
        order["unknown_costs"] = [item["name"] for item, price in prices if price is None]
        order["cost"] = None if order["unknown_costs"] else str(sum(
            (price * item["quantity"] for item, price in prices), Decimal(0)))
    summary = analysis.summarize(orders)
    ids = {o["id"] for o in orders}
    captured = datetime.fromisoformat(record["captured_at"])
    captured = captured.replace(tzinfo=TZ) if captured.tzinfo is None else captured.astimezone(TZ)
    return dict(
        store=record["store"], group=STORES[record["store"]], date=record["date"],
        platform=PLATFORMS[record["platform_key"]], captured_at=captured.isoformat(timespec="seconds"),
        order_count=summary["valid_orders"], raw_count=summary["total_orders"], income=summary["income"],
        cost=summary["cost"], profit=summary["profit"], margin=summary["margin"],
        known_waste=summary["known_waste"], preorders=summary["preorders"],
        status="missing_cost" if summary["missing_costs"] else "ok",
    ), ids, summary["missing_costs"]


def record_path(raw, store, platform):
    return raw / f"{platform}-{store}.json"


def archive(raw, paths, date):
    for path in sorted(paths.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            store = record["store"]
            platform = "mt" if record["platform"] == "美团" else "ele" if record["platform"] == "饿了么" else None
            if record["date"] != date or (store, platform) not in EXPECTED:
                continue
            target = record_path(raw, store, platform)
            if not target.exists():
                record["platform_key"] = platform
                atomic_json(target, record)


@contextmanager
def job_lock(path, timeout):
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with path.open("a+") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("等待已有生产任务超时")
                time.sleep(2)
        yield


def wait_roi(root, date):
    result = root / "outputs/promo_roi" / f"{date}.json"
    deadline = time.monotonic() + 3600
    print(f"等候 {date} 的 ROI 复盘结束", flush=True)
    while time.monotonic() < deadline:
        if result.exists():
            review = read_json(result)
            if review.get("date") == date and review.get("status") in {"ok", "partial", "failed"}:
                return
        time.sleep(15)
    raise TimeoutError("当天 ROI 复盘未报结束，毛利任务尚未开始采集")


def collect_port(port, platform, stores, raw, date, access):
    from playwright.sync_api import sync_playwright

    pending = [store for store in stores if not record_path(raw, store, platform).exists()]
    if not pending:
        return
    lane = access.Coordinator().lease(access.for_port(port), wait_seconds=480, priority="normal") if platform == "mt" else nullcontext()
    try:
        with lane, sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15000)
            pages = browser.contexts[0].pages
            marker = "e.waimai.meituan.com" if platform == "mt" else "melody.shop.ele.me/"
            matches = [page for page in pages if marker in page.url]
            if not matches:
                raise RuntimeError("没有已登录的订单后台页面")
            page = next((p for p in matches if "/orderbusiness" in p.url or "/order__querying" in p.url), matches[0])
            page.set_default_timeout(12000)
            for store in pending:
                for attempt in range(2):
                    try:
                        if platform == "mt":
                            access.Coordinator().require(access.for_port(port))
                        for record in capture.collect(page, store, platform, [date]):
                            record["platform_key"] = platform
                            atomic_json(record_path(raw, store, platform), record)
                        break
                    except Exception as exc:
                        detail = str(exc).splitlines()[0]
                        print(f"{PLATFORMS[platform]} {store}：{detail}", flush=True)
                        if any(word in detail for word in ("验证", "登录")):
                            return
                        if not attempt:
                            time.sleep(3)
    except Exception as exc:
        print(f"{PLATFORMS[platform]} {'、'.join(pending)}：{type(exc).__name__} {str(exc).splitlines()[0]}", flush=True)


def build_day(raw, date, costs):
    rows, seen = [], {p: set() for p in PLATFORMS}
    for store, group in STORES.items():
        for platform, label in PLATFORMS.items():
            path = record_path(raw, store, platform)
            row = dict(store=store, group=group, date=date, platform=label, status="unavailable")
            if path.exists():
                try:
                    record = read_json(path)
                    if (record["store"], record["date"], record["platform_key"]) != (store, date, platform):
                        raise ValueError("订单快照门店、日期或平台不匹配")
                    computed, ids, missing = summarize(record, costs)
                    if ids & seen[platform]:
                        raise ValueError("跨门店订单重复")
                    seen[platform].update(ids)
                    if missing:
                        print(f"{store} {label} 缺少商品成本：{missing}", flush=True)
                    row = computed
                except (AssertionError, KeyError, TypeError, ValueError, AttributeError) as exc:
                    print(f"{store} {label} 快照校验失败：{type(exc).__name__}", flush=True)
            rows.append(row)
    finish = now().isoformat(timespec="seconds")
    ok = sum(row["status"] == "ok" for row in rows)
    return dict(date=date, generated_at=finish, cost_template=costs.label, cost_version=costs.version,
                status="complete" if ok == len(EXPECTED) else "partial", rows=rows)


def publish_files(files, subdirectory=""):
    server = os.environ.get("OPERATION_CLOUD_SERVER", "ubuntu@139.155.148.169")
    target = os.environ.get("OPERATION_CLOUD_REMOTE_DIR", "/var/www/html/operation-workbench").rstrip("/")
    target += "/" + subdirectory.strip("/") if subdirectory else ""
    identity = Path(os.environ.get("OPERATION_CLOUD_IDENTITY_FILE", str(Path.home() / ".ssh/xiong_operation_cloud_ed25519")))
    opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new"]
    if identity.is_file():
        opts += ["-i", str(identity)]
    subprocess.run(["ssh", *opts, server, "mkdir -p " + shlex.quote(target)], check=True, timeout=30)
    staged = []
    for file in files:
        remote = target + "/" + file.name
        tmp = remote + f".order-margin-{os.getpid()}.tmp"
        subprocess.run(["scp", *opts, str(file), server + ":" + shlex.quote(tmp)], check=True, timeout=45)
        staged.append((tmp, remote))
    commands = [f"chmod 644 {shlex.quote(tmp)} && mv -f {shlex.quote(tmp)} {shlex.quote(remote)}" for tmp, remote in staged]
    subprocess.run(["ssh", *opts, server, " && ".join(commands)], check=True, timeout=30)


def publish_history(output):
    dates = sorted((output / "days").glob("????-??-??.json"), reverse=True)[:90]
    public = output / "history.json"
    atomic_json(public, {"days": [read_json(path) for path in dates]})
    for attempt in range(3):
        try:
            publish_files([public], "outputs/order_margin")
            return
        except (OSError, subprocess.SubprocessError):
            if attempt == 2:
                raise
            time.sleep(10)


def notify_complete(root, output, day):
    marker = output / "days" / f"{day['date']}.notified"
    if marker.exists():
        return
    profit = sum(Decimal(row["profit"]) for row in day["rows"])
    income = sum(Decimal(row["income"]) for row in day["rows"])
    rate = f"{profit / income:.2%}" if income else "—"
    text = (f"结论：{day['date']} 毛利分析任务完成，11 家门店双平台毛利 {profit:,.2f} 元，毛利率 {rate}。\n"
            "原因：订单已抓取，并按确认的成本表完成核算。\n"
            "下一步：到直营店运营数据中心和门店运营数据中心查看明细。\n"
            f"时间：{now():%Y-%m-%d %H:%M}（北京时间）")
    result = subprocess.run([sys.executable, str(root / "scripts/ops_notify.py"), text],
                            env={**os.environ, "OPS_NOTIFY_CHANNEL": "webhook"}, timeout=60)
    if result.returncode:
        raise RuntimeError("通知助手发送失败")
    atomic_json(marker, {"delivered_at": now().isoformat(timespec="seconds")})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime-root", type=Path, default=RUNTIME)
    p.add_argument("--cost-file", type=Path, default=COST_INPUT)
    p.add_argument("--date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date().isoformat())
    p.add_argument("--import-snapshots", type=Path, action="append")
    p.add_argument("--publish-ui", action="store_true")
    p.add_argument("--notify", action="store_true", help="导入历史订单后也发送完成通知")
    args = p.parse_args()
    if sys.platform != "darwin" or "mini" not in socket.gethostname().lower():
        p.error("正式采集与发布仅在生产 Mac mini 执行")
    if args.publish_ui:
        publish_files([SOURCE / "order-margin.js", SOURCE / "index.html"])
        return 0
    date = args.date or now().date().isoformat()
    if not args.import_snapshots and date != now().date().isoformat():
        p.error("历史日期使用已留存的订单快照")
    os.umask(0o077)
    root = args.runtime_root.resolve()
    output = root / "outputs/order_margin"
    raw = output / "snapshots" / date
    result = output / "days" / f"{date}.json"
    output.mkdir(parents=True, exist_ok=True)
    with job_lock(output / "job.lock", 5):
        costs = Costs(args.cost_file)
        previous = read_json(result) if result.exists() else {}
        if previous.get("status") == "complete" and previous.get("cost_version") == costs.version:
            day = previous
        else:
            raw.mkdir(parents=True, exist_ok=True)
            if args.import_snapshots:
                for path in args.import_snapshots:
                    archive(raw, path, date)
            else:
                wait_roi(root, date)
                sys.path.insert(0, str(root / "scripts"))
                import platform_account_access as access

                with job_lock(root / "outputs/locks/morning-ops.lock", 600):
                    if date != now().date().isoformat():
                        raise RuntimeError("已跨日，停止采集前一日订单")
                    with ThreadPoolExecutor(max_workers=len(PORTS)) as workers:
                        pending = [workers.submit(collect_port, port, platform, stores, raw, date, access)
                                   for port, (platform, stores) in PORTS.items()]
                        for job in as_completed(pending):
                            job.result()
            day = build_day(raw, date, costs)
            result.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(result, day)
        publish_history(output)
        complete = day["status"] == "complete"
        print(f"{date} 毛利快照：{sum(row['status'] == 'ok' for row in day['rows'])}/{len(EXPECTED)}", flush=True)
        if complete and (not args.import_snapshots or args.notify):
            notify_complete(root, output, day)
        return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
