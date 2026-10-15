import unittest
from collect_customer_messages_sample import normalize_messages
from render_customer_messages_sample import render, triage

class SampleTests(unittest.TestCase):
    def row(self, id, stamp, sender, content, role='merchant', **extra):
        return dict(id=id,time=stamp,sender=sender,content=content,role=role,separator='',media=[],**extra)
    def test_reverse_order_duplicate_and_day(self):
        rows=[self.row('b','10-15 10:00:00','门店','今天'),self.row('a','10-14 10:00:00','顾客','昨天','customer'),self.row('a','10-14 10:00:00','顾客','昨天','customer')]
        out=normalize_messages(rows,'2026-10-14')
        self.assertEqual([x['id'] for x in out],['a','b'])
        self.assertTrue(out[0]['on_target_date'])
        self.assertFalse(out[1]['on_target_date'])
    def test_ai_and_automatic(self):
        out=normalize_messages([self.row('a','10-14 10:00:00','[AI客服]门店','答复'),self.row('b','10-14 09:00:00','[自动回复]门店','欢迎')],'2026-10-14')
        self.assertEqual([x['reply_type'] for x in out],['自动回复','AI回复'])
    def test_reply_is_not_resolution_and_html_is_escaped(self):
        session={'label':'<script>\ncustomer','history_complete':True,'messages':normalize_messages([self.row('b','10-14 10:00:01','门店','好的'),self.row('a','10-14 10:00:00','顾客','开票失败<script>','customer')],'2026-10-14')}
        self.assertEqual(triage(session)[1],'需跟进')
        page=render(dict(store='朝阳门店',platform='美团',date='2026-10-14',source='test',collected_at='test',sessions=[session],session_list_complete=False,scanned_sessions=1,errors=[]))
        self.assertNotIn('<script>',page)
        self.assertIn('&lt;script&gt;',page)
        self.assertIn('存在未确认完整',page)
    def test_image_without_text_retained(self):
        row=self.row('a','10-14 10:00:00','顾客','','customer')
        row['media']=[dict(alt='照片',src='https://example.org/a.png')]
        self.assertIn('图片消息',normalize_messages([row],'2026-10-14')[0]['content'])

if __name__=='__main__': unittest.main()
