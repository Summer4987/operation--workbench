import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0,str(SCRIPTS))
spec = importlib.util.spec_from_file_location('daily',SCRIPTS/'customer_inspection_daily.py')
daily = importlib.util.module_from_spec(spec); spec.loader.exec_module(daily)


class DailyRotation(unittest.TestCase):
    def setUp(self):
        self.config=json.loads(daily.CONFIG.read_text())

    def test_four_days_cover_exactly_sixteen_then_repeat(self):
        names=[]
        for day in ['2026-10-26','2026-10-27','2026-10-28','2026-10-29']:
            stores=daily.plan(day,self.config)['stores'];self.assertEqual(len(stores),4)
            names.extend(s['name'] for s in stores)
        self.assertEqual(len(set(names)),16)
        self.assertEqual(daily.plan('2026-10-30',self.config),daily.plan('2026-10-26',self.config))
        self.assertEqual(daily.plan('2026-11-01',self.config),daily.plan('2026-10-28',self.config))

    def test_invalid_or_pre_anchor_rotation_rejected(self):
        with self.assertRaises(ValueError):daily.plan('2026-10-25',self.config)
        self.config['groups'][1]['stores'][0]=self.config['groups'][0]['stores'][0]
        with self.assertRaises(ValueError):daily.plan('2026-10-27',self.config)

    def test_confirmed_qinghe_and_platform_specific_zhongguancun(self):
        self.assertTrue(daily.identity('熊小小牛排饭(第4号档口)','清河店','meituan'))
        self.assertFalse(daily.identity('熊小小牛排饭(第5号档口)','清河店','meituan'))
        self.assertTrue(daily.identity('熊小小牛排饭(第2号档口)','中关村店','taobao-shangou'))
        self.assertFalse(daily.identity('熊小小牛排饭(望京店)','安贞店','meituan'))

    def test_split_address_control_requires_adjacent_observed_labels(self):
        switch=dict(text='切换',x=1015,y=151);address=dict(text='地址',x=1012,y=191)
        self.assertEqual(daily.location_control([switch,address],'meituan'),switch)
        self.assertIsNone(daily.location_control([switch],'meituan'))
        self.assertIsNone(daily.location_control([switch,dict(text='地址',x=300,y=191)],'meituan'))

    def test_wrong_result_never_clicked_and_search_is_bounded(self):
        nav=object.__new__(daily.Navigator)
        nav.args=type('Args',(),dict(store='安贞店',platform='meituan'))()
        rows=[dict(text='熊小小牛排饭(望京店)',x=520,y=480)]
        with patch.object(nav,'observe',return_value=(Path('proof.png'),rows)),patch.object(nav,'click') as click,patch.object(nav,'swipe') as swipe:
            with self.assertRaisesRegex(RuntimeError,'没有找到准确门店'):nav.merchant()
            click.assert_not_called();self.assertEqual(swipe.call_count,4)

    def test_meituan_promoted_query_is_focused_instead_of_submitted(self):
        nav=object.__new__(daily.Navigator)
        placeholder=dict(text='Q 饿作剧派对',x=191,y=260)
        submit=dict(text='搜索',x=961,y=260)
        focused=dict(text='饿作剧派对',x=400,y=165)
        with patch.object(nav,'observe',side_effect=[(None,[placeholder,submit]),(None,[focused])]),patch.object(nav,'click') as click,patch.object(nav,'type_text') as typed:
            nav.search_results()
            self.assertEqual(click.call_args_list[0].args[0],placeholder)
            self.assertEqual(click.call_args_list[1].args[0],focused)
            typed.assert_called_once_with('熊小小')

    def test_verification_stops_platform_but_other_platform_continues(self):
        calls=[]
        class FakeNavigator:
            def __init__(self,args,store):
                self.args=args;self.directory=Path(args.output)/args.platform/store['name'];self.directory.mkdir(parents=True)
            def collect(self):
                calls.append(self.args.platform)
                if self.args.platform=='meituan':raise RuntimeError('Human verification required; platform paused')
                return dict(status='recapture_needed',note='测试缺失，不创建假图')
        with tempfile.TemporaryDirectory() as tmp,patch.object(daily,'RUNTIME',Path(tmp)),patch.object(daily,'Navigator',FakeNavigator),patch.object(daily,'preflight',return_value='/adb'),patch.object(daily,'publish') as publish,patch.object(daily.signal,'alarm'):
            daily.execute('2026-10-27',self.config)
            source=Path(tmp)/'2026-10-27-daily-four'
            records=json.loads((source/'reviewed-progress.json').read_text())['records']
            self.assertEqual(calls.count('meituan'),1);self.assertEqual(calls.count('taobao-shangou'),4)
            self.assertEqual(sum(r['status']=='blocked_human_verification' for r in records),4)
            publish.assert_called_once_with(source)
            daily.execute('2026-10-27',self.config)
            self.assertEqual(len(calls),5) # No platform operations on calendar retry.

    def test_explicit_retry_preserves_accepted_records_and_archives_failure(self):
        calls=[]
        class FakeNavigator:
            def __init__(self,args,store):
                self.args=args;self.directory=Path(args.output)/args.platform/store['name'];self.directory.mkdir(parents=True,exist_ok=True)
            def collect(self):
                calls.append((self.args.platform,self.args.store))
                return dict(status='recapture_needed',note='仍失败，保留证据')
        with tempfile.TemporaryDirectory() as tmp,patch.object(daily,'RUNTIME',Path(tmp)),patch.object(daily,'Navigator',FakeNavigator),patch.object(daily,'preflight',return_value='/adb'),patch.object(daily,'publish'),patch.object(daily.signal,'alarm'):
            source=Path(tmp)/'2026-10-27-daily-four';source.mkdir()
            accepted=dict(platform='meituan',store='朝阳门店',status='ocr_verified',files=[{'sha256':'original'}])
            (source/'reviewed-progress.json').write_text(json.dumps(dict(records=[accepted])))
            daily.execute('2026-10-27',self.config,retry_failed=True)
            records=json.loads((source/'reviewed-progress.json').read_text())['records']
            self.assertEqual(records[0],accepted)
            self.assertEqual(len(calls),7)
            self.assertNotIn(('meituan','朝阳门店'),calls)
            self.assertEqual(len(list(source.glob('attempt-*.json'))),1)

    def test_already_complete_chengdu_not_recollected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(daily,'RUNTIME',Path(tmp)),patch.object(daily,'preflight') as preflight:
            source=Path(tmp)/'2026-10-26-chengdu';source.mkdir()
            rows=[dict(platform=p,store=s['name'],status='visually_accepted') for s in self.config['groups'][0]['stores'] for p in daily.PACKAGES]
            (source/'reviewed-progress.json').write_text(json.dumps(dict(records=rows)))
            daily.execute('2026-10-26',self.config);preflight.assert_not_called()


if __name__=='__main__':unittest.main()
