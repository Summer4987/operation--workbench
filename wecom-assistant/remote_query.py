"""Read-only cloud data adapter. Request is JSON on stdin; never interpolated into shell."""
import json
import sqlite3
import sys
from pathlib import Path


def query(q):
    start, end = q['start'], q['end']
    region = q.get('region', 'all')
    rows, expected, errors = [], [], []
    if region == 'daily':
        p = Path('/opt/inventory-board/data/inventory.sqlite3')
        if not p.exists():
            raise ValueError('日配订货数据库不存在')
        with sqlite3.connect('file:' + str(p) + '?mode=ro', uri=True) as conn:
            conn.execute('PRAGMA query_only=ON')
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute('''
                SELECT m.created_at AS 提交时间, m.store_name AS 门店,
                f.filename AS 订单号, m.sku AS SKU, m.name AS 品名,
                m.quantity AS 数量, m.unit AS 单位, m.document_date AS 单据日期
                FROM movements m JOIN import_files f ON f.id=m.import_file_id
                WHERE m.movement_type='outbound' AND f.source='熊小小日配订货出库'
                AND substr(m.created_at,1,10)>=? AND substr(m.created_at,1,10)<=?
                ORDER BY m.created_at DESC, m.id''', (start, end))]
        note = '日配按提交/入库时间筛选；只含成功进入日配出库记录的订单。未订货门店名单未配置。'
    else:
        for key, directory, catalog in [
            ('chengdu', 'submissions', 'catalog.json'),
            ('beijing', 'beijing-submissions', 'catalog-beijing.json'),
        ]:
            if region not in ('all', key):
                continue
            root = Path('/opt/daily-order')
            folder = root / 'data' / directory
            if not folder.exists():
                errors.append(key + '订单目录不存在')
                continue
            cat = root / 'app' / catalog
            if not cat.exists():
                errors.append(key + '门店清单不存在')
            else:
                expected.extend(json.loads(cat.read_text()).get('stores', []))
            for file in folder.glob('*.json'):
                try:
                    order = json.loads(file.read_text())
                    timestamp = str(order.get('submitted_at', ''))
                    if not start <= timestamp[:10] <= end:
                        continue
                    for item in order.get('items', []):
                        rows.append({'区域': '成都' if key == 'chengdu' else '北京',
                                     '订单号': order.get('order_id', ''), '提交时间': timestamp,
                                     '门店': order.get('store_name', ''), '状态': order.get('status', ''),
                                     '采购渠道': item.get('purchase_channel', ''),
                                     'SKU': item.get('sku', ''), '品名': item.get('output_name') or item.get('name', ''),
                                     '数量': item.get('quantity', 0), '单位': item.get('unit', '')})
                except (OSError, ValueError, TypeError):
                    errors.append('有订单文件无法解析')
        note = '按订单提交日期筛选；未订货指所选期间未提交，不能推断为每天都未提交。'
    store = str(q.get('store', '')).strip()
    if store:
        rows = [r for r in rows if store in str(r.get('门店', ''))]
        expected = [s for s in expected if store in s]
    submitted = sorted(set(r['门店'] for r in rows))
    return {'source': '云端正式订货数据（SSH只读）', 'start': start, 'end': end,
            'region': region, 'rows': rows, 'line_count': len(rows),
            'order_count': len(set((r.get('区域', ''), r['订单号']) for r in rows)),
            'submitted_stores': submitted,
            'unsubmitted_stores': sorted(set(expected) - set(submitted)) if expected and not errors else None,
            'errors': sorted(set(errors)), 'note': note}


if __name__ == '__main__':
    try:
        print(json.dumps(query(json.load(sys.stdin)), ensure_ascii=False, allow_nan=False))
    except Exception:
        print(json.dumps({'error': '云端订货查询失败，请检查数据目录、数据库或SSH权限。'}, ensure_ascii=False))
        sys.exit(1)
