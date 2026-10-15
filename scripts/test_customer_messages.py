import unittest
from datetime import date
from unittest.mock import patch
from customer_message_data import stamp,normalize,merge_messages,scope_status,project_scope
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
 def test_empty_page_has_all_ten_expected_scopes(self):
  html=page(dict(target_date='2026-10-14',generated_at='test',scopes={}),['2026-10-14'])
  self.assertEqual(html.count('当前结果不可视为'),10)
  self.assertIn('0/10',html)
 def test_escape_customer_html(self):
  s=dict(store='朝阳门店',platform='美团',status='ready',list_complete=True,sessions=[dict(label='<script>',history_complete=True,messages=normalize([dict(id='a',role='customer',time='10-14 12:00',content='<img src=x onerror=evil()>')],'2026-10-14',date(2026,10,15)))])
  html=page(dict(target_date='2026-10-14',generated_at='test',scopes={'朝阳门店|美团':s}),[])
  self.assertNotIn('<img src=x',html);self.assertIn('&lt;img',html)

if __name__=='__main__':unittest.main()
