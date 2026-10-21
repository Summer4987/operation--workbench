import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('remote',Path(__file__).with_name('remote_query.py'))
remote=importlib.util.module_from_spec(spec);spec.loader.exec_module(remote)

class RemoteTests(unittest.TestCase):
    def test_daily_uses_actual_cloud_order_source_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'opt/inventory-board/data/inventory.sqlite3';p.parent.mkdir(parents=True)
            with sqlite3.connect(p) as c:
                c.executescript('''CREATE TABLE import_files(id INTEGER, filename TEXT, source TEXT, status TEXT);
                CREATE TABLE movements(created_at TEXT,store_name TEXT,import_file_id INTEGER,sku TEXT,name TEXT,quantity REAL,unit TEXT,document_date TEXT,movement_type TEXT,id INTEGER);
                INSERT INTO import_files VALUES(1,'order.xlsx','cloud_order','success');
                INSERT INTO movements VALUES('2026-10-21T08:00:00+08:00','金融城店',1,'a','牛排',3,'箱','2026-10-21','outbound',1);''')
            before=p.read_bytes()
            with patch.object(remote,'Path',side_effect=lambda value:Path(d)/str(value).lstrip('/')):
                result=remote.query({'start':'2026-10-21','end':'2026-10-21','region':'daily'})
            self.assertEqual(result['line_count'],1);self.assertEqual(result['rows'][0]['数量'],3)
            self.assertEqual(result['order_count'],1);self.assertEqual(p.read_bytes(),before)
    def test_partial_orders_never_claim_a_complete_unsubmitted_list(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'opt/daily-order';folder=root/'data/submissions';folder.mkdir(parents=True)
            (root/'app').mkdir();(root/'app/catalog.json').write_text(json.dumps({'stores':['A','B']}))
            (folder/'bad.json').write_text('broken')
            with patch.object(remote,'Path',side_effect=lambda value:Path(d)/str(value).lstrip('/')):
                result=remote.query({'start':'2026-10-21','end':'2026-10-21','region':'chengdu'})
            self.assertIsNone(result['unsubmitted_stores']);self.assertTrue(result['errors'])

if __name__=='__main__':unittest.main()
