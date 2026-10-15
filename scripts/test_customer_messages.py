import unittest
import subprocess
import shutil
from pathlib import Path
from datetime import date
from unittest.mock import patch
from customer_message_data import stamp,normalize,merge_messages,scope_status,project_scope,reconcile_hidden_cards,media_type,retain_previous_scope,unique_group_store
from render_customer_messages import page

class DataTests(unittest.TestCase):
 def test_dates_and_rollover(self):
  today=date(2026,10,15)
  self.assertEqual(stamp('昨天',today),'2026-10-14')
  self.assertEqual(stamp('昨天 14:34',today),'2026-10-14 14:34:00')
  self.assertEqual(stamp('10月14日 17:05',today),'2026-10-14 17:05:00')
  self.assertEqual(stamp('2026年10月14日 17:05',today),'2026-10-14 17:05:00')
  self.assertEqual(stamp('12-31 23:59',date(2027,1,1)),'2026-12-31 23:59:00')
  self.assertEqual(stamp('12月31日 23:59',date(2027,1,1)),'2026-12-31 23:59:00')
  self.assertEqual(stamp('10/14',today),'2026-10-14')
 def test_messages_not_deduped_by_identical_body(self):
  a=dict(id='a',time='10-14 12:00:00',sender='[AI客服]店',role='merchant',content='好的')
  b=dict(a,id='b')
  rows=normalize(merge_messages([[a,b],[a]]),'2026-10-14',date(2026,10,15))
  self.assertEqual(len(rows),2);self.assertEqual(rows[0]['reply_type'],'AI回复')
 def test_today_conversation_includes_yesterday_and_system(self):
  rows=[dict(id='s',role='system',content='发票催办',time='昨天 14:34'),dict(id='a',role='customer',content='请开票',time='10-15 08:00:00')]
  result=normalize(rows,'2026-10-14',date(2026,10,15))
  self.assertTrue(result[0]['on_target_date']);self.assertFalse(result[1]['on_target_date'])
 def test_earlier_batches_sorted_and_untimed_events_kept(self):
  rows=[dict(id='late',time='10-14 16:00',role='merchant',content='好的'),dict(id='system',time='',role='system',content='用户发起会话'),dict(id='early',time='10-14 12:00',role='customer',content='你好')]
  result=normalize(rows,'2026-10-14',date(2026,10,15))
  self.assertEqual(result[0]['id'],'early');self.assertEqual(len(result),3)
  self.assertEqual([m['timestamp'] for m in result],sorted(m['timestamp'] for m in result))
 def test_partial_and_failed_not_zero(self):
  self.assertEqual(scope_status(dict(error='登录失效')),'failed')
  self.assertEqual(scope_status(dict(list_complete=False,sessions=[],errors=[])),'partial')
  s=dict(list_complete=True,errors=[],sessions=[dict(history_complete=True,messages=[dict(on_target_date=True,needs_review=False,media=[dict(status='failed')])])])
  self.assertEqual(scope_status(s),'partial')
  s['sessions'][0]['messages'][0]['media'][0]['status']='saved'
  self.assertEqual(scope_status(s),'ready')
 def test_overlap_projects_calendar_day_and_retains_context(self):
  raw=dict(store='朝阳门店',date='2026-10-14',list_complete=True,errors=[],sessions=[dict(label='x',history_complete=True,messages=normalize([dict(id='old',role='customer',time='10-13 23:59',content='昨天提问'),dict(id='new',role='merchant',time='10-14 08:00',content='次日回复')],'2026-10-14',date(2026,10,15)))])
  prior=project_scope(raw,'2026-10-13')
  self.assertEqual(prior['status'],'ready')
  self.assertTrue(prior['sessions'][0]['messages'][0]['on_target_date'])
  self.assertFalse(prior['sessions'][0]['messages'][1]['on_target_date'])
  self.assertFalse(raw['sessions'][0]['messages'][0]['on_target_date'])
 def test_known_platform_hidden_system_card_is_retained(self):
  row=normalize([dict(id='sys',time='昨天 14:34',role='merchant',type='17019',content='')],'2026-10-14',date(2026,10,15))[0]
  self.assertTrue(row['unavailable_text']);self.assertFalse(row['needs_review'])
  self.assertEqual(row['role'],'system');self.assertIn('电脑版未展示正文',row['content'])
  unknown=normalize([dict(id='x',time='昨天 14:34',role='merchant',type='99999',content='')],'2026-10-14',date(2026,10,15))[0]
  self.assertTrue(unknown['needs_review'])
 def test_reconcile_hidden_type_preserves_message_identity_and_time(self):
  scope=dict(list_complete=True,errors=[],sessions=[dict(history_complete=True,messages=[dict(id='same-id',type='9',timestamp='2026-10-14 19:36:00',on_target_date=True,content='[未解析消息，保留原始类型]',media=[],needs_review=True)])])
  self.assertEqual(reconcile_hidden_cards(scope),1)
  m=scope['sessions'][0]['messages'][0]
  self.assertEqual(m['id'],'same-id');self.assertEqual(m['timestamp'],'2026-10-14 19:36:00')
  self.assertEqual(scope['status'],'ready');self.assertTrue(m['unavailable_text'])
 def test_cdn_octet_stream_image_and_login_html(self):
  self.assertEqual(media_type('application/octet-stream',bytes.fromhex('ffd8ffe00010')),'image/jpeg')
  self.assertEqual(media_type('binary/octet-stream',b'\x89PNG\r\n\x1a\nrest'),'image/png')
  self.assertEqual(media_type('text/html',b'<html>login</html>'),'')
  self.assertEqual(media_type('image/jpeg',b'<html>login</html>'),'')
 def test_voice_duration_without_audio_is_incomplete(self):
  scope=dict(list_complete=True,errors=[],sessions=[dict(history_complete=True,messages=[dict(on_target_date=True,needs_review=False,required_media='audio',content='8秒',media=[])])])
  self.assertEqual(scope_status(scope),'partial')
  scope['sessions'][0]['messages'][0]['media']=[dict(kind='audio',status='saved')]
  self.assertEqual(scope_status(scope),'ready')
 def test_failed_refresh_retains_same_day_evidence_but_stays_failed(self):
  old=dict(date='2026-10-14',collected_at='old',sessions=[dict(id='session',messages=[dict(id='msg',content='原文')])])
  new=dict(date='2026-10-14',status='failed',sessions=[],error='离线')
  result=retain_previous_scope(old,new)
  self.assertEqual(result['status'],'failed');self.assertEqual(result['sessions'][0]['messages'][0]['content'],'原文')
  self.assertEqual(result['previous_capture_at'],'old')
 def test_previous_day_is_never_used_as_current_day_evidence(self):
  old=dict(date='2026-10-13',sessions=[dict(id='old',messages=[])])
  new=dict(date='2026-10-14',status='failed',sessions=[])
  self.assertEqual(retain_previous_scope(old,new)['sessions'],[])
 def test_invoice_class_is_not_voice_media(self):
  from collect_customer_messages import MEDIA_REQUIREMENT_JS
  node=shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
  if not Path(node).exists():self.skipTest('Node runtime unavailable')
  script="const assert=require('assert');const detect=("+MEDIA_REQUIREMENT_JS+");const root=(cls,tag='DIV')=>({querySelectorAll:()=>[{className:cls,tagName:tag}]});assert.equal(detect(root('im-invoice-ai-card')),'');assert.equal(detect(root('invoice-card-content')),'');assert.equal(detect(root('im-card_voice-message')),'audio');assert.equal(detect(root('','AUDIO')),'audio');assert.equal(detect(root('im-card_video-message')),'video');"
  r=subprocess.run([node,'-e',script],capture_output=True,text=True)
  self.assertEqual(r.returncode,0,r.stderr)
 def test_group_attribution_rejects_ambiguous_hints(self):
  self.assertEqual(unique_group_store([],['保利中心店']),'保利中心店')
  self.assertEqual(unique_group_store([],['保利中心店','银泰城店']),'')
  self.assertEqual(unique_group_store(['保利中心店'],['银泰城店','保利中心店']),'保利中心店')
  self.assertEqual(unique_group_store([],[]),'')
 def test_visible_platform_prompt_is_not_a_manual_merchant_reply(self):
  row=normalize([dict(id='system',time='昨天 14:34',type='17019',role='merchant',sender='商户',content='发票处理提醒：请完成开票')],'2026-10-14',date(2026,10,15))[0]
  self.assertEqual(row['role'],'system');self.assertNotEqual(row['reply_type'],'门店回复')
  self.assertEqual(row['content'],'发票处理提醒：请完成开票')
 def test_empty_page_has_all_ten_expected_scopes(self):
  html=page(dict(target_date='2026-10-14',generated_at='test',scopes={}),['2026-10-14'])
  self.assertEqual(html.count('当前结果不可视为'),10)
  self.assertIn('0/10',html)
 def test_escape_customer_html(self):
  s=dict(store='朝阳门店',platform='美团',status='ready',list_complete=True,sessions=[dict(label='<script>',history_complete=True,messages=normalize([dict(id='a',role='customer',time='10-14 12:00',content='<img src=x onerror=evil()>')],'2026-10-14',date(2026,10,15)))])
  html=page(dict(target_date='2026-10-14',generated_at='test',scopes={'朝阳门店|美团':s}),[])
  self.assertNotIn('<img src=x',html);self.assertIn('&lt;img',html)

if __name__=='__main__':unittest.main()
