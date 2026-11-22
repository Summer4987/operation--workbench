import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import agent_task_notifier as notifier
import longxia_verification_notify as fleet


class NotificationPolicyTests(unittest.TestCase):
    def test_realtime_success_each_half_hour_once_and_never_historical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(runs=str(root/'runs.json'), state=str(root/'state.json'),
                log=str(root/'log.json'), seed=False, dry_run=False, no_write=False,
                target='weixin', hermes_bin='', include_unconfigured=False)
            def save(at):
                (root/'runs.json').write_text(json.dumps({'tasks': {'ops.realtime_order_income': {
                    'status':'success', 'step':'刷新最终工作台状态', 'finished_at':at,
                }}}))
            now=datetime(2026,11,22,12,35,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
            with patch.object(notifier,'load_policy_rows',return_value=notifier.DIRECT_TASK_ROWS), \
                 patch.object(notifier,'load_schedule_issue_tasks',return_value={}), \
                 patch.object(notifier.time,'time',return_value=now), \
                 patch.object(notifier,'send_weixin',return_value=(True,'ok')) as send:
                save('2026-11-22 12:02:00')
                self.assertEqual(notifier.notify(args)['notification_count'],1)
                self.assertIn('采集批次：2026-11-22 12:00',send.call_args.args[0])
                save('2026-11-22 12:04:00')  # Same slot retried successfully.
                self.assertEqual(notifier.notify(args)['notification_count'],0)
                save('2026-11-22 12:33:00')
                self.assertEqual(notifier.notify(args)['notification_count'],1)
                self.assertIn('采集批次：2026-11-22 12:30',send.call_args.args[0])
                save('2026-11-21 12:33:00')
                self.assertEqual(notifier.notify(args)['notification_count'],0)
                self.assertEqual(send.call_count,2)

    def test_collection_started_before_slot_boundary_uses_original_slot(self):
        task={'finished_at':'2026-11-22 12:31:00'}
        runs={'events':[{'task_id':'ops.realtime_order_income', 'status':'running',
            'message':'实时单量收入采集开始。', 'created_at':'2026-11-22 12:00:05'}]}
        # Operations exceeding 30 minutes are not attributed to an older run.
        self.assertEqual(notifier.realtime_slot(task,runs),'2026-11-22 12:30')
        runs['events'][0]['created_at']='2026-11-22 12:29:55'
        self.assertEqual(notifier.realtime_slot(task,runs),'2026-11-22 12:00')

    def test_only_final_evening_budget_and_human_incidents_are_selected(self):
        self.assertFalse(notifier.notification_allowed('growth.promo_budget',{'step':'午餐预算汇总','status':'success'}))
        self.assertFalse(notifier.notification_allowed('growth.promo_budget',{'step':'晚餐预算提交前预检','status':'failed'}))
        self.assertTrue(notifier.notification_allowed('growth.promo_budget',{'step':'晚餐预算汇总','status':'failed'}))
        self.assertTrue(notifier.notification_allowed('ops.account',{'status':'failed','message':'平台掉线，请重新登录'}))
        self.assertFalse(notifier.notification_allowed('ops.other',{'status':'success'}))
        message=notifier.build_message('growth.promo_budget',{
            'status':'success','step':'晚餐预算汇总','message':'两平台全部门店均已完成真实提交并读回验证。\n附属步骤失败：看板刷新。'}, {})
        self.assertIn('晚间运营｜推广设置成功',message)
        self.assertNotIn('附属步骤',message)

    def test_store_fault_login_and_verification_escalation_are_immediate_and_deduped(self):
        now=1795320000000
        status={'schema':1,'generatedAt':now,'stores':[
            {'id':'1','name':'双井店','status':'error','message':'登录失效，请重新登录'},
            {'id':'2','name':'滨江店','status':'error','message':'页面加载失败，需人工检查'},
            {'id':'3','name':'金融街店','paused':True,'message':'本店已人工暂停'},
        ]}
        sent=[]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            sender=lambda text: sent.append(text) or True
            self.assertEqual(fleet.process_status(status,path,sender,now)['attempted'],2)
            self.assertIn('重新登录',sent[0]);self.assertIn('门店运行故障',sent[0]);self.assertNotIn('金融街店',sent[0])
            self.assertEqual(fleet.process_status(status,path,sender,now)['attempted'],0)
            status['stores'][1]['message']='当前显示安全验证码'
            self.assertEqual(fleet.process_status(status,path,sender,now)['attempted'],1)
            self.assertIn('滨江店',sent[1])

if __name__=='__main__':unittest.main()
