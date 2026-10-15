"""Review-page snapshots. Store scores and individual review scores have separate meanings."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'outputs/review_pages/latest.json'
TZ = ZoneInfo('Asia/Shanghai')


def read_snapshot(path=SNAPSHOT):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def store_aliases(root=ROOT):
    entries = []
    for name in ['config.json', 'direct_config.json']:
        config = json.loads((root / 'business-report-dashboard' / name).read_text(encoding='utf-8'))
        for row in config['store_aliases']:
            for alias in [row['short_name'], *row['aliases']]:
                entries.append((row['platform'], normalize(alias), row['short_name']))
    return sorted(set(entries), key=lambda x: -len(x[1]))


def normalize(text):
    return re.sub(r'[\s（）()·._-]', '', str(text)).lower()


def match_store(name, platform, aliases):
    name = normalize(name)
    return next((short for plat, alias, short in aliases if plat == platform and alias and alias in name), '')


def score_value(value):
    try:
        number = float(value)
        return number if 0 < number <= 5 else None
    except (ValueError, TypeError):
        return None


def meituan_review(item, account, aliases):
    # commentScoreType is a category code, never a star rating.
    rating = score_value(item.get('orderCommentScore')) or score_value(item.get('productScore'))
    name = item.get('poiName') or account.get('store_name', '')
    return dict(review_id=str(item.get('id') or ''), platform='美团',
                store=match_store(name, '美团', aliases), store_raw=name,
                store_id=str(item.get('wmPoiId') or ''), date=str(item.get('createTime') or '')[:10],
                rating=rating, content=item.get('cleanComment') or item.get('comment') or '',
                replied=bool(item.get('eCommentList')),
                appeal_status=(item.get('wmCommentReportInfo') or {}).get('reportReviewResultDescNew') or '',
                negative=rating is not None and rating <= 3, source_account=account['id'])


def eleme_reviews(item, aliases):
    rows = []
    for rate in item.get('orderRateInfos') or []:
        rating = score_value(rate.get('serviceRating'))  # UI: 满意度
        rows.append(dict(review_id=str(rate.get('rateId') or ''), platform='饿了么',
                         store=match_store(item.get('shopName', ''), '饿了么', aliases),
                         store_raw=item.get('shopName', ''), store_id=str(item.get('shopId') or ''),
                         date=str(rate.get('ratingAt') or '')[:10], rating=rating,
                         content=rate.get('ratingContent') or '', replied=bool(rate.get('replied')),
                         appeal_status=(item.get('interceptStatus') or {}).get('desc') or '',
                         negative=rating is not None and rating <= 3, source_account='eleme_headquarters'))
    return rows


def scope_fresh(scope, today):
    return scope.get('collected_at', '')[:10] == today


def build_summary(target_stores, snapshot=None, now=None):
    snapshot = read_snapshot() if snapshot is None else snapshot
    if not snapshot:
        return None
    now = now or datetime.now(TZ)
    today = now.strftime('%Y-%m-%d')
    target = (now.date() - timedelta(days=1)).isoformat()
    start = (now.date() - timedelta(days=7)).isoformat()
    stores = {}
    complete = 0
    scopes = snapshot.get('scopes', {})
    for store in target_stores:
        details = {}
        for platform in ['美团', '饿了么']:
            candidates = [s for s in scopes.values() if s.get('platform') == platform and store in s.get('stores', [])]
            # Dedicated accounts are authoritative over the headquarters scope.
            scope = next((s for s in candidates if s.get('account_type') == 'single'), candidates[0] if candidates else {})
            fresh = scope_fresh(scope, today)
            covered = (fresh and scope.get('reviews_status') == 'ready'
                       and scope.get('start_date', '9999') <= start and scope.get('end_date', '') >= target)
            status = 'ready' if covered else ('stale' if scope and not fresh else 'failed' if scope else 'missing')
            rating = (scope.get('ratings') or {}).get(store, {})
            rating_fresh = fresh and scope.get('ratings_status') == 'ready' and bool(rating)
            all_rows = [r for r in scope.get('records', []) if r.get('store') == store and r.get('negative') and start <= r.get('date', '') <= target]
            yesterday = [r for r in all_rows if r['date'] == target]
            details[platform] = dict(status=status, message=scope.get('message', ''),
                negative_count=len(yesterday) if covered else None, review_count=None,
                pending_count=sum(not r.get('replied') for r in yesterday) if covered else None,
                bad_reviews=yesterday if covered else [], recent_bad_reviews=all_rows if covered else [],
                current_rating=rating.get('value'), rating_status='ready' if rating_fresh else 'stale' if rating else 'missing',
                rating_collected_at=rating.get('collected_at', ''), rating_source_date=rating.get('source_date', ''),
                rating_delta=rating.get('delta'), rating_previous_at=rating.get('previous_at', ''),
                account_type=scope.get('account_type', ''), collected_at=scope.get('collected_at', ''))
            complete += covered
        bad = [r for d in details.values() for r in d['bad_reviews']]
        stores[store] = dict(date=target, platforms=details, negative_count=len(bad), review_count=None,
            pending_count=sum(d.get('pending_count') or 0 for d in details.values()),
            bad_reviews=bad, bad_review_examples=[r['content'] for r in bad],
            recent_bad_reviews=sorted([r for d in details.values() for r in d['recent_bad_reviews']], key=lambda r:r['date'], reverse=True),
            coverage_complete=all(d['status'] == 'ready' for d in details.values()))
    return dict(source='review_pages', status='ready' if complete == len(stores)*2 else 'partial' if complete else 'missing',
                target_date=target, used_date=target, start_date=start, collected_at=snapshot.get('generated_at', ''),
                message=f'评价页面采集：已核验 {complete}/{len(stores)*2} 个门店平台；差评口径为满意度/商品评价 1–3 星。',
                stores=stores, total_review_count_available=False)


def refresh_payloads(snapshot=None):
    """Refresh review sections without collecting or replacing operating revenue data."""
    import csv
    snapshot = read_snapshot() if snapshot is None else snapshot
    for config_name, payload_name, csv_name in [
        ("config.json", "latest.json", "unified_reviews.csv"),
        ("direct_config.json", "direct-latest.json", "direct_unified_reviews.csv"),
    ]:
        report_dir = ROOT / "business-report-dashboard"
        config = json.loads((report_dir / config_name).read_text(encoding="utf-8"))
        summary = build_summary(config["target_stores"], snapshot)
        if summary is None:
            continue
        payload_path = report_dir / "data" / payload_name
        if payload_path.exists():
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            payload["review_summary"] = summary
            payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records = [dict(r, keywords=[], source_file="review_pages") for item in summary["stores"].values() for r in item["recent_bad_reviews"]]
        columns = ["date", "platform", "store", "store_raw", "rating", "content", "review_id", "negative", "keywords", "source_file", "replied", "appeal_status"]
        csv_path = report_dir / "data" / csv_name
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
