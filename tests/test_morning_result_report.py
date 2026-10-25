import copy
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import morning_result_report as report
import build_promo_budget_result as budget_result

STEPS = ['总部平台登录态预检', '直营美团逐账号登录态预检', '启动/检查后台 Chrome',
         '双平台评价页及门店评分采集', '评价看板生成', '评价待办状态更新',
         '直营美团日报下载', '门店日报采集并发布', '日报重点状态更新', '直营双平台客服消息采集',
         '推广余额总巡检', '巡检证据清单生成', '推广余额状态更新', '巡检证据上传云端',
         '上午推广低余额通知', '同步云端预算配置', '推广预算初始化预览',
         '饿了么午餐预算真实提交', '美团午餐预算真实提交', '运营总看板数据更新', '运营总看板发布腾讯云']


class MorningReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = dict(status='success', step='汇总', finished_at='2026-10-25 08:45:00')
        self.runs = dict(events=[dict(task_id=report.TASK_ID, step='初始化', status='running', created_at='2026-10-25 08:00:00', extra={'mode':'commit'})])
        self.runs['events'] += [dict(task_id=report.TASK_ID, step=s, status='success', created_at='2026-10-25 08:30:00') for s in STEPS]
        scope = dict(ratings_status='ready', reviews_status='ready', collected_at='2026-10-25T08:20:00+08:00',
                     start_date='2026-10-18', end_date='2026-10-24', ratings={'A':{'value':4.8}}, records=[])
        self.write('outputs/review_pages/latest.json', {'scopes': {key:copy.deepcopy(scope) for key in ['eleme_headquarters','meituan_headquarters','direct_a']}})
        self.write('config/direct_meituan_accounts.json', {'accounts':[{'id':'direct_a','enabled':True}]})
        self.write('config/customer_messages.json', {'stores':[{'store':'A'},{'store':'B'}]})
        self.write('outputs/customer_messages/latest.json', dict(target_date='2026-10-24', generated_at='2026-10-25 08:20:00', context_restored=True,
            scopes={store+'|'+plat:dict(status='ready',collected_at='2026-10-25 08:20:00') for store in ['A','B'] for plat in ['美团','淘宝闪购']}))
        self.write('outputs/promo_budget_result/latest.json', dict(period='午餐',generated_at='2026-10-25 08:40:00',platforms={
            p:dict(total=2,success_count=2,failed_count=0,skipped_count=0) for p in ['eleme','meituan']}))
        self.write('outputs/promo_balance_status/latest.json', dict(generated_at='2026-10-25 08:20:00',summary={'low_balance_count':2,'platform_failure_count':0}))
        self.write('outputs/agent_task_notifications/state.json', {'sent':{'growth.promo_balance.low_balance':'notification_slot|2026-10-25|上午'}})
        page=self.root/'business-report-dashboard/direct-dashboard/customer-messages/index.html'
        page.parent.mkdir(parents=True);page.write_text('messages');dt=datetime(2026,10,25,8,20).timestamp();os.utime(page,(dt,dt))

    def write(self, relative, data):
        p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data))

    def build(self):
        return report.build_payload(self.task,self.runs,self.root)

    def rows(self):
        return {r['name']:r for c in self.build()['categories'] for r in c['items']}

    def test_all_categories_and_every_project_are_reported(self):
        p=self.build();self.assertEqual(len(p['categories']),7)
        self.assertEqual(p['counts'],{'success':27});self.assertEqual(p['status'],'success')
        text=report.format_report(p)
        for category in p['categories']:
            self.assertIn('【'+category['name']+'】',text)
            for row in category['items']:self.assertIn(row['name']+'：成功',text)

    def test_review_failure_does_not_hide_successful_budget(self):
        data=report.read_json(self.root/'outputs/review_pages/latest.json');data['scopes']['eleme_headquarters']['reviews_status']='failed';self.write('outputs/review_pages/latest.json',data)
        self.runs['events'][4]['status']='failed';self.task['status']='failed'
        rows=self.rows()
        self.assertEqual(rows['淘宝闪购差评采集']['status'],'failed')
        self.assertEqual(rows['淘宝闪购门店评分']['status'],'success')
        self.assertEqual(rows['美团午餐预算提交']['status'],'success')

    def test_missing_direct_review_account_is_not_success(self):
        data=report.read_json(self.root/'outputs/review_pages/latest.json');del data['scopes']['direct_a'];self.write('outputs/review_pages/latest.json',data)
        self.assertEqual(self.rows()['美团差评采集']['status'],'partial')

    def test_incomplete_customer_scope_and_restore_failure_are_visible(self):
        data=report.read_json(self.root/'outputs/customer_messages/latest.json');data['scopes']['B|淘宝闪购']['status']='partial';data['context_restored']=False;self.write('outputs/customer_messages/latest.json',data)
        rows=self.rows();self.assertEqual(rows['美团客服消息采集']['status'],'success')
        self.assertEqual(rows['淘宝闪购客服消息采集']['status'],'partial');self.assertIn('B',rows['淘宝闪购客服消息采集']['detail'])
        self.assertEqual(rows['淘宝全国门店范围恢复']['status'],'failed')

    def test_new_run_does_not_reuse_same_day_old_evidence(self):
        self.runs['events'][0]['created_at']='2026-10-25 08:41:00'
        for e in self.runs['events'][1:]:e['created_at']='2026-10-25 08:42:00'
        rows=self.rows();self.assertNotEqual(rows['淘宝闪购差评采集']['status'],'success')
        self.assertNotEqual(rows['美团午餐预算提交']['status'],'success')

    def test_no_execution_is_not_reported_as_success(self):
        self.runs['events']=self.runs['events'][:1];self.task['status']='failed'
        p=self.build();self.assertEqual(p['counts'],{'missing':27})

    def test_budget_skip_and_failed_readback_are_not_success(self):
        self.runs['events'].append(dict(task_id=report.TASK_ID,step='饿了么午餐预算真实提交',status='skipped',created_at='2026-10-25 08:44:00',message='按设置跳过'))
        data=report.read_json(self.root/'outputs/promo_budget_result/latest.json');data['platforms']['meituan'].update(success_count=1,failed_count=1,failed_stores=['B']);self.write('outputs/promo_budget_result/latest.json',data)
        rows=self.rows();self.assertEqual(rows['淘宝闪购午餐预算提交']['status'],'skipped')
        self.assertEqual(rows['美团午餐预算提交']['status'],'partial');self.assertIn('B',rows['美团午餐预算提交']['detail'])

    def test_balance_business_failure_is_not_hidden_by_zero_exit_code(self):
        self.write('outputs/promo_balance_status/latest.json',dict(generated_at='2026-10-25 08:20:00',summary={'platform_failure_count':1,'low_balance_count':0}))
        self.assertEqual(self.rows()['双平台余额巡检']['status'],'partial')

    def test_notification_exit_zero_is_not_a_delivery_receipt(self):
        self.write('outputs/agent_task_notifications/state.json', {'sent':{}})
        self.assertEqual(self.rows()['低余额通知']['status'], 'partial')

    def test_lunch_evidence_survives_dinner_update(self):
        data=report.read_json(self.root/'outputs/promo_budget_result/latest.json')
        self.write('outputs/promo_budget_result/latest_午餐.json',data)
        self.write('outputs/promo_budget_result/latest.json',dict(period='晚餐',generated_at='2026-10-25 17:00:00'))
        self.assertEqual(self.rows()['美团午餐预算提交']['status'],'success')

    def test_budget_producer_keeps_period_specific_receipts(self):
        output=self.root/'receipts/latest.json'
        for period in ['午餐','晚餐']:
            with patch.object(sys,'argv',['test','--period',period,'--since-epoch','0','--output',str(output)]), \
                 patch.object(budget_result,'build_result',return_value={'period':period,'status':'success'}):
                self.assertEqual(budget_result.main(),0)
        self.assertEqual(report.read_json(output)['period'],'晚餐')
        self.assertEqual(report.read_json(output.with_name('latest_午餐.json'))['period'],'午餐')


if __name__=='__main__':unittest.main()
