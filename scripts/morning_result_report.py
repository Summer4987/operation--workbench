"""Evidence-backed, per-category morning results for the existing WeCom notifier."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = 'ops.morning_collection'
LABELS = {'success': '成功', 'failed': '失败', 'partial': '部分成功',
          'skipped': '跳过', 'missing': '未运行/无记录', 'running': '运行中'}
FINAL_STEPS = {'汇总', 'exception', '异常', 'launchd 包装器', '单项修复汇总', '收尾补偿发布'}


def read_json(path):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, TypeError):
        return None


def is_final(task):
    return task.get('step') in FINAL_STEPS or not task.get('step')


def session_events(task, runs):
    day = str(task.get('finished_at') or task.get('updated_at') or '')[:10]
    if not day:
        return []
    events = [e for e in runs.get('events', []) if e.get('task_id') == TASK_ID
              and str(e.get('created_at', '')).startswith(day)]
    starts = [i for i, e in enumerate(events) if e.get('status') == 'running' and e.get('step') in {'初始化', 'start'}]
    return events[starts[-1]:] if starts else events


def build_payload(task, runs, root=ROOT):
    root = Path(root)
    day = str(task.get('finished_at') or task.get('updated_at') or '')[:10]
    events = session_events(task, runs)
    start = timestamp(events[0].get('created_at')) if events else timestamp(day)
    latest = {e.get('step'): e for e in events if e.get('step')}
    mode = next((e.get('extra', {}).get('mode') for e in events if e.get('step') == '初始化'), '')
    categories = []
    target_date = (timestamp(day)-timedelta(days=1)).date().isoformat() if timestamp(day) else ''
    window_start = (timestamp(day)-timedelta(days=7)).date().isoformat() if timestamp(day) else ''

    def fresh(value):
        dt = timestamp(value)
        return bool(dt and dt.date().isoformat() == day and (not start or dt >= start))

    def event_row(label, step):
        event = latest.get(step, {})
        state = event.get('status', 'missing')
        detail = ''
        if state == 'failed':
            detail = {'auth_block':'登录或验证码异常', 'timeout':'运行超时',
                      'page_structure':'平台页面结构变化', 'publish_failed':'发布校验失败',
                      'dependency_missing':'运行环境缺失'}.get(event.get('failure_type'), '步骤执行未通过')
        elif state == 'skipped':
            detail = str(event.get('message') or '按设置跳过')[:100]
        return dict(name=label, status=state if state in LABELS else 'missing', detail=detail)

    def section(name, rows):
        categories.append(dict(name=name, items=rows))

    section('登录与环境', [event_row('总部平台登录检查', '总部平台登录态预检'),
                        event_row('直营美团账号登录检查', '直营美团逐账号登录态预检'),
                        event_row('后台浏览器检查', '启动/检查后台 Chrome')])

    reviews = read_json(root/'outputs/review_pages/latest.json')
    review_event = latest.get('双平台评价页及门店评分采集', {})
    review_rows = []
    for platform, label in [('饿了么', '淘宝闪购'), ('美团', '美团')]:
        ids = ['eleme_headquarters'] if platform == '饿了么' else ['meituan_headquarters'] + [
            a['id'] for a in read_json(root/'config/direct_meituan_accounts.json').get('accounts', []) if a.get('enabled')]
        scopes = [reviews.get('scopes', {}).get(key, {}) for key in ids]
        for field, suffix in [('ratings_status', '门店评分'), ('reviews_status', '差评采集')]:
            row = event_row(label+suffix, '双平台评价页及门店评分采集')
            if review_event and scopes:
                valid = [s for s in scopes if fresh(s.get('collected_at')) and s.get(field) == 'ready'
                         and (bool(s.get('ratings')) if field == 'ratings_status' else isinstance(s.get('records'), list)
                              and s.get('start_date', '9999') <= window_start and s.get('end_date', '') >= target_date)]
                row['status'] = 'success' if len(valid) == len(scopes) else 'partial' if valid else 'failed'
                count = sum(len(s.get('records', [])) for s in valid) if field == 'reviews_status' else len({store for s in valid for store in s.get('ratings', {})})
                row['detail'] = f'{len(valid)}/{len(scopes)} 个账号通过，{count}'+(' 条近七天差评' if field == 'reviews_status' else ' 家门店')
            elif review_event and review_event.get('status') == 'success':
                row.update(status='partial', detail='步骤完成，但缺少本轮完整采集证据')
            review_rows.append(row)
    section('评价与评分', review_rows + [event_row('评价看板生成', '评价看板生成'), event_row('评价待办更新', '评价待办状态更新')])

    section('经营日报', [event_row('直营美团日报下载', '直营美团日报下载'),
                        event_row('双平台日报采集与发布', '门店日报采集并发布'),
                        event_row('日报重点更新', '日报重点状态更新')])

    messages = read_json(root/'outputs/customer_messages/latest.json')
    configs = read_json(root/'config/customer_messages.json').get('stores', [])
    message_rows = []
    message_event = latest.get('直营双平台客服消息采集', {})
    for platform in ['美团', '淘宝闪购']:
        row = event_row(platform+'客服消息采集', '直营双平台客服消息采集')
        scopes = [messages.get('scopes', {}).get(c['store']+'|'+platform, {}) for c in configs]
        if message_event and scopes:
            valid = [s for s in scopes if fresh(s.get('collected_at')) and s.get('status') == 'ready'
                     and messages.get('target_date') == target_date]
            row['status'] = 'success' if len(valid) == len(scopes) else 'partial' if valid else 'failed'
            row['detail'] = f'{len(valid)}/{len(scopes)} 家门店完整'
            failed = [c['store'] for c, s in zip(configs, scopes) if s not in valid]
            if failed:
                row['detail'] += '；未完成：'+'、'.join(failed)
        elif message_event and message_event.get('status') == 'success':
            row.update(status='partial', detail='步骤完成，但缺少本轮门店完整性证据')
        message_rows.append(row)
    restore = event_row('淘宝全国门店范围恢复', '直营双平台客服消息采集')
    if message_event and fresh(messages.get('generated_at')):
        restore.update(status='success' if messages.get('context_restored') is True else 'failed',
                       detail='' if messages.get('context_restored') is True else '未确认恢复全国范围')
    message_rows.append(restore)
    web = root/'business-report-dashboard/direct-dashboard/customer-messages/index.html'
    page = event_row('客服消息页面生成', '直营双平台客服消息采集')
    if message_event:
        if web.is_file() and fresh(datetime.fromtimestamp(web.stat().st_mtime).isoformat()):
            page.update(status='success', detail='')
        else:
            page.update(status='failed', detail='未找到本轮生成的消息页面')
    message_rows.append(page)
    section('客服消息', message_rows)

    balance_rows = [event_row('双平台余额巡检', '推广余额总巡检'),
                    event_row('巡检证据清单生成', '巡检证据清单生成'),
                    event_row('余额状态更新', '推广余额状态更新'),
                    event_row('巡检证据上传', '巡检证据上传云端'),
                    event_row('低余额通知', '上午推广低余额通知')]
    balance = read_json(root/'outputs/promo_balance_status/latest.json')
    if '推广余额总巡检' in latest and fresh(balance.get('generated_at')):
        summary = balance.get('summary') or {}
        if summary.get('platform_failure_count') or summary.get('direct_coverage_missing_count'):
            if balance_rows[0]['status'] == 'success':
                balance_rows[0]['status'] = 'partial'
        balance_rows[0]['detail'] = f'低余额 {summary.get("low_balance_count", 0)} 项'
        if balance_rows[-1]['status'] == 'success':
            count = summary.get('low_balance_count', 0)
            sent = read_json(root/'outputs/agent_task_notifications/state.json').get('sent', {})
            if not count:
                balance_rows[-1].update(status='skipped', detail='无低余额项目，无需推送')
            elif sent.get('growth.promo_balance.low_balance') == f'notification_slot|{day}|上午':
                balance_rows[-1]['detail'] = f'{count} 项低余额已推送'
            else:
                balance_rows[-1].update(status='partial', detail='通知步骤已运行，尚未确认企微送达')
    section('推广余额与证据', balance_rows)

    budget_rows = [event_row('云端预算配置同步', '同步云端预算配置'), event_row('预算预览生成', '推广预算初始化预览')]
    budget = read_json(root/'outputs/promo_budget_result/latest_午餐.json') or read_json(root/'outputs/promo_budget_result/latest.json')
    for platform, label, step in [('eleme', '淘宝闪购午餐预算提交', '饿了么午餐预算真实提交'),
                                  ('meituan', '美团午餐预算提交', '美团午餐预算真实提交')]:
        row = event_row(label, step)
        result = (budget.get('platforms') or {}).get(platform, {})
        if latest.get(step, {}).get('status') not in {None, 'skipped'} and budget.get('period') == '午餐' and fresh(budget.get('generated_at')) and result:
            skipped = result.get('skipped_count', 0)
            failed = result.get('failed_count', 0)
            total = result.get('total', 0)
            row['status'] = ('partial' if result.get('success_count') else 'failed') if failed else 'skipped' if skipped == total and total else 'partial' if skipped else 'success'
            row['detail'] = f'{result.get("success_count", 0)-skipped}/{total} 家提交并读回；跳过 {skipped}，失败 {failed}'
            if not total or result.get('success_count', 0)+failed != total:
                row.update(status='partial', detail='本轮预算门店执行明细不完整')
            if failed:
                row['detail'] += '（'+'、'.join(result.get('failed_stores', []))+'）'
        elif row['status'] == 'success':
            row.update(status='partial', detail='步骤完成，缺少本轮门店提交与读回明细')
        budget_rows.append(row)
    section('午餐推广预算', budget_rows)
    section('工作台发布', [event_row('运营看板数据生成', '运营总看板数据更新'), event_row('正式看板发布', '运营总看板发布腾讯云')])
    counts = Counter(row['status'] for category in categories for row in category['items'])
    return dict(date=day, mode=mode, categories=categories, counts=dict(counts),
                status='success' if task.get('status') == 'success' and not any(counts[s] for s in ['failed', 'partial', 'missing', 'running']) else 'attention',
                task_message=str(task.get('message') or ''))


def format_report(payload):
    counts = payload['counts']
    date = timestamp(payload['date'])
    business_day = (date-timedelta(days=1)).date().isoformat() if date else '未记录'
    conclusion = '全部项目成功' if payload['status'] == 'success' and not counts.get('skipped') else '执行结束，含跳过项' if payload['status'] == 'success' else '存在异常或未完成项目'
    lines = [f'【上午运营分类报告｜{payload["date"]}】', f'结论：{conclusion}',
             f'日报/消息统计日：{business_day}；预算为当日午餐',
             '总览：'+'，'.join(f'{label} {counts.get(status, 0)}' for status, label in LABELS.items() if status != 'running' or counts.get(status))]
    for category in payload['categories']:
        lines += ['', '【'+category['name']+'】']
        for row in category['items']:
            detail = '；'+row['detail'] if row['detail'] else ''
            lines.append(f'• {row["name"]}：{LABELS[row["status"]]}{detail}')
    if payload['status'] != 'success' and payload['task_message']:
        lines += ['', '本轮说明：'+' '.join(payload['task_message'].split())[:180]]
    lines += ['', '正式看板：http://139.155.148.169/operation-workbench/']
    return '\n'.join(lines)


if __name__ == '__main__':
    runs = read_json(ROOT/'outputs/task_runs/latest.json')
    payload = build_payload(runs.get('tasks', {}).get(TASK_ID, {}), runs)
    out = ROOT/'outputs/morning_result_report'
    out.mkdir(parents=True, exist_ok=True)
    (out/'latest.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    text = format_report(payload)
    (out/'latest.txt').write_text(text+'\n')
    print(text)
