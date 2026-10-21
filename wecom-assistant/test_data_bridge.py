import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('bridge',Path(__file__).with_name('data_bridge.py'))
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)

class QueryTests(unittest.TestCase):
    def test_ranges_and_region_are_bounded(self):
        with self.assertRaises(ValueError): bridge.validate({'start':'2026-01-01','end':'2026-10-21'})
        with self.assertRaises(ValueError): bridge.validate({'start':'2026-10-21','end':'2026-10-20'})
        with self.assertRaises(ValueError): bridge.validate({'start':'2026-10-20','end':'2026-10-21','region':';rm -rf'})
    def test_latest_source_selected_and_missing_data_is_not_zero_rows(self):
        with tempfile.TemporaryDirectory() as d:
            roots=[Path(d)/'old',Path(d)/'new']
            for root,stamp,income in zip(roots,['2026-07-17','2026-10-21'],[99,12.5]):
                p=root/'business-report-dashboard/data/latest.json';p.parent.mkdir(parents=True)
                p.write_text(json.dumps({'generated_at':stamp,'records':[{'date':'2026-10-20','store':'A','income':income,'orders':2,'platform':'美团'}]}))
            q={'start':'2026-10-20','end':'2026-10-20','scope':'franchise'}
            result=bridge.business(q,roots)
            self.assertEqual(result['totals']['收入'],12.5)
            self.assertIsNone(result['rows'][0]['顾客实付'])
            result=bridge.business(dict(q,start='2026-10-21',end='2026-10-21'),roots)
            self.assertEqual(result['rows'],[])
            self.assertEqual(result['sources'][0]['latest_date'],'2026-10-20')
    def test_store_filter_and_nan_handling(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'business-report-dashboard/data/latest.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'records':[{'date':'2026-10-20','store':'A','income':float('nan')},{'date':'2026-10-20','store':'B','income':5}]}))
            r=bridge.business({'start':'2026-10-20','end':'2026-10-20','scope':'franchise','store':'A'},[root])
            self.assertIsNone(r['rows'][0]['收入']);self.assertIsNone(r['totals']['收入']);self.assertEqual(r['missing_income_rows'],1)

    def test_comparison_uses_matching_complete_platforms_and_zero_baseline_is_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'business-report-dashboard/data/latest.json';p.parent.mkdir(parents=True)
            records=[{'date':day,'store':'A','platform':'美团','income':income,'orders':orders}
                     for day,income,orders in [('2026-10-19',100,10),('2026-10-20',80,8)]]
            # A missing Eleme baseline must not be counted as zero or depress comparable growth.
            records.append({'date':'2026-10-20','store':'A','platform':'饿了么','income':1000,'orders':100})
            records.extend([{'date':day,'store':'B','platform':'美团','income':income,'orders':0}
                            for day,income in [('2026-10-19',0),('2026-10-20',20)]])
            p.write_text(json.dumps({'records':records}))
            q={'kind':'business_comparison','start':'2026-10-20','end':'2026-10-20',
               'previous_start':'2026-10-19','previous_end':'2026-10-19','scope':'franchise'}
            bridge.validate(q)
            r=bridge.business_comparison(q,[root]);a=next(x for x in r['rows'] if x['门店']=='A')
            self.assertEqual(a['本期可比收入'],80);self.assertEqual(a['收入差额'],-20)
            self.assertAlmostEqual(a['收入变化率'],-.2);self.assertIn('饿了么',a['状态'])
            self.assertIsNone(next(x for x in r['rows'] if x['门店']=='B')['收入变化率'])
            self.assertEqual(len(r['detail_rows']),5)
            with self.assertRaises(ValueError):bridge.validate(dict(q,previous_end='2026-10-20'))

    def test_duplicate_daily_records_are_not_comparable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'business-report-dashboard/data/latest.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'records':[{'date':day,'store':'A','platform':'美团','income':100,'orders':10}
                                              for day in ['2026-10-19','2026-10-20','2026-10-20']]}))
            r=bridge.business_comparison({'start':'2026-10-20','end':'2026-10-20','previous_start':'2026-10-19','previous_end':'2026-10-19','scope':'franchise'},[root])
            self.assertIsNone(r['rows'][0]['收入差额'])

if __name__=='__main__':unittest.main()

class RealtimeTests(unittest.TestCase):
    def snapshot(self, root, stamp='2026-10-21 20:01:00', **extra):
        p=root/'outputs/realtime_order_income/latest.json';p.parent.mkdir(parents=True,exist_ok=True)
        d={'generated_at':stamp,'status':'ok','target_stores':['A','B'],'stores':[
            {'store':'A','orders':99999,'platforms':{'美团':{'orders':4,'income':100,'income_status':'trusted'},'饿了么':{'orders':6,'income':200,'income_status':'trusted'}}},
            {'store':'B','platforms':{'美团':{'orders':2,'income':99,'income_status':'untrusted'},'饿了么':{'orders':0,'income':0,'income_status':'account_out','source':'account_scope'}}}]}
        d.update(extra);p.write_text(json.dumps(d));return p
    def test_latest_snapshot_platform_totals_missing_permissions_not_zero(self):
        from datetime import datetime,timezone,timedelta
        now=datetime(2026,10,21,20,15,tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as d:
            roots=[Path(d)/'old',Path(d)/'new']
            self.snapshot(roots[0],stamp='2026-08-04 21:00:00')
            self.snapshot(roots[1])
            r=bridge.realtime({},roots,now)
            self.assertEqual(r['generated_at'],'2026-10-21 20:01:00')
            self.assertEqual(r['totals'],{'订单数':12,'收入':300})
            self.assertEqual(r['missing_order_rows'],1)
            self.assertIsNone(next(x for x in r['rows'] if x['门店']=='B' and x['平台']=='饿了么')['订单数'])
            self.assertFalse(r['stale'])
            self.assertEqual(bridge.realtime({'store':'A'},roots,now)['totals']['订单数'],10)
            self.assertIsNone(bridge.realtime({'store':'NO'},roots,now)['totals']['订单数'])
            with self.assertRaises(ValueError):bridge.realtime({'scope':'direct'},roots,now)
    def test_stale_reset_and_missing_snapshot_are_never_current_zero_orders(self):
        from datetime import datetime,timezone,timedelta
        now=datetime(2026,10,21,20,15,tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaises(ValueError):bridge.realtime({},[root],now)
            self.snapshot(root,stamp='2026-10-20 23:00:00')
            self.assertTrue(bridge.realtime({},[root],now)['stale'])
            self.snapshot(root,status='reset')
            r=bridge.realtime({},[root],now)
            self.assertIsNone(r['totals']['订单数']);self.assertIsNone(r['totals']['收入'])
            self.assertTrue(r['reset'])
            self.snapshot(root,stamp='2026-10-22 20:01:00')
            with self.assertRaises(ValueError):bridge.realtime({},[root],now)
