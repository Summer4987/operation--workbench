import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from eleme_bid_dashboard import build, TZ


class ElemeBidDashboardTests(unittest.TestCase):
    def test_day_scope_rotation_and_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / 'outputs/eleme_bid_fleet/latest.json'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'generatedAt':1,'day':'2026-11-26','simulation':True,'stores':[{'name':'安贞店','bid':30,'cookie':'SECRET'}]}))
            events = root / 'events.jsonl'
            stamp = int(datetime(2026,11,26,0,1,tzinfo=TZ).timestamp()*1000)
            events.write_text(json.dumps({'type':'decision','at':stamp,'name':'安贞店','action':'hold','reason':'保持原因','token':'SECRET'})+'\nBROKEN\n'+json.dumps({'type':'adjusted','at':stamp-86400000,'name':'安贞店'})+'\n')
            events.with_suffix('.jsonl.1').write_text(json.dumps({'type':'adjusted','at':stamp-60000,'name':'安贞店','before':30,'after':40})+'\n')
            result = build(root, events, datetime(2026,11,26,12,tzinfo=TZ))
            self.assertEqual(len(result['events']),2)
            self.assertEqual(result['historyStatus'],'partial')
            self.assertEqual(result['historySkipped'],1)
            self.assertEqual(result['events'][1]['reason'],'保持原因')
            self.assertNotIn('SECRET',json.dumps(result))
            self.assertTrue(result['simulation'])

    def test_missing_and_invalid_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=build(root,root/'missing',datetime(2026,11,26,tzinfo=TZ))
            self.assertTrue(result['error'])
            self.assertEqual(result['stores'],[])
            self.assertEqual(result['historyStatus'],'missing')

if __name__ == '__main__': unittest.main()
