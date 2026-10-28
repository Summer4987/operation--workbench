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
        self.assertTrue(daily.identity('熊小小牛排饭POKEBEAR（第3档','中关村店','meituan'))
        self.assertFalse(daily.identity('熊小小牛排饭POKEBEAR（第30档','中关村店','meituan'))
        self.assertFalse(daily.identity('熊小小牛排饭POKEBEAR（第3档','中关村店','taobao-shangou'))
        self.assertTrue(daily.identity('熊小小牛排饭POKEBEAR（第4号档','清河店','meituan'))

    def test_split_address_control_requires_adjacent_observed_labels(self):
        switch=dict(text='切换',x=1015,y=151);address=dict(text='地址',x=1012,y=191)
        self.assertEqual(daily.location_control([switch,address],'meituan'),switch)
        self.assertIsNone(daily.location_control([switch],'meituan'))
        self.assertIsNone(daily.location_control([switch,dict(text='地址',x=300,y=191)],'meituan'))

    def test_taobao_sticky_filter_is_not_location(self):
        for label in ['筛选','新人红包','堂食店','30分钟达','好评如潮']:
            self.assertIsNone(daily.location_control([dict(text=label,x=1007,y=143)],'taobao-shangou'))
        row=dict(text='◎ 中建 天、',x=946,y=169)
        self.assertEqual(daily.location_control([dict(text='熊小小',x=242,y=167),row],'taobao-shangou'),row)
        self.assertIsNone(daily.location_control([dict(text='丁口几',x=1007,y=211)],'taobao-shangou'))

    def test_city_dropdown_accepts_merged_placeholder_and_pending_gps(self):
        row=dict(text='成都~ Q 请输入地址',x=263,y=288)
        self.assertEqual(daily.city_control([row]),dict(row,x=100))
        pending=dict(text='定位中v',x=141,y=274)
        self.assertEqual(daily.city_control([pending]),pending)
        self.assertIsNone(daily.city_control([dict(text='北京市西城区',x=279,y=600)]))

    def test_merged_city_label_focuses_editable_input(self):
        nav=object.__new__(daily.Navigator)
        nav.args=type('Args',(),dict(platform='taobao-shangou'))()
        nav.store={'city':'北京'}
        merged=dict(text='北京市> Q请输入地址',x=279,y=288)
        with patch.object(nav,'click') as click:
            nav.focus_address(merged)
            self.assertEqual(click.call_args.args[0]['x'],600)
            self.assertEqual(click.call_args.args[0]['y'],288)
            separate=dict(text='Q请输入地址',x=347,y=288)
            nav.focus_address(separate)
            self.assertEqual(click.call_args.args[0],separate)

    def test_home_logo_does_not_send_back_instead_of_search(self):
        nav=object.__new__(daily.Navigator)
        nav.args=type('Args',(),dict(platform='meituan'))()
        logo=dict(text='熊小小&原切谷饲牛排饭',x=203,y=1861)
        placeholder=dict(text='Q 饿作剧派对',x=191,y=260)
        submit=dict(text='搜索',x=961,y=260)
        focused=dict(text='饿作剧派对',x=239,y=169)
        with patch.object(nav,'observe',side_effect=[(None,[logo,placeholder,submit]),(None,[focused])]),patch.object(nav,'click'),patch.object(nav,'type_text') as typed,patch.object(nav,'back') as back:
            nav.search_results()
            back.assert_not_called()
            typed.assert_called_once_with('熊小小')

    def test_wrong_result_never_clicked_and_search_is_bounded(self):
        nav=object.__new__(daily.Navigator)
        nav.args=type('Args',(),dict(store='安贞店',platform='meituan'))()
        rows=[dict(text='熊小小牛排饭(望京店)',x=520,y=480)]
        with patch.object(nav,'observe',return_value=(Path('proof.png'),rows)),patch.object(nav,'click') as click,patch.object(nav,'swipe') as swipe:
            with self.assertRaisesRegex(RuntimeError,'没有找到准确门店'):nav.merchant()
            click.assert_not_called();self.assertEqual(swipe.call_count,4)

    def test_meituan_promoted_query_is_focused_instead_of_submitted(self):
        nav=object.__new__(daily.Navigator)
        nav.args=type('Args',(),dict(platform='meituan'))()
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
