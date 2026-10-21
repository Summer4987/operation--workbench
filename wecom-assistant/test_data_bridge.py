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

if __name__=='__main__':unittest.main()
