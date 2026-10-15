import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from review_page_data import TZ, build_summary, eleme_reviews, meituan_review, store_aliases, match_store
from collect_review_pages import paged, Collector

NOW = datetime(2026, 10, 15, 12, tzinfo=TZ)


def scope(platform='饿了么', status='ready'):
    return dict(platform=platform, account_type='headquarters', stores=['银泰城店'],
                collected_at='2026-10-15T11:00:00+08:00', start_date='2026-10-08', end_date='2026-10-14',
                reviews_status=status, ratings_status='ready', ratings={'银泰城店':dict(value=4.7,collected_at='2026-10-15T11:00:00+08:00')}, records=[])


class ReviewPageTests(unittest.TestCase):
    def test_satisfaction_is_independent_from_taste_packaging(self):
        rows = eleme_reviews(dict(shopName='熊小小牛排饭POKEBEAR(银泰城店)', shopId=1,
             interceptStatus={'desc':'申诉成功，不计入总分'},orderRateInfos=[dict(rateId=7,serviceRating=3,qualityRating=5,packageRating=5,
             ratingAt='2026-10-14T00:00:00',ratingContent='菜少',replied=True)]), store_aliases())
        self.assertTrue(rows[0]['negative'])
        self.assertEqual(rows[0]['rating'], 3)
        self.assertEqual(rows[0]['store'], '银泰城店')
        self.assertTrue(rows[0]['replied'])
        self.assertIn('申诉成功', rows[0]['appeal_status'])

    def test_category_code_is_not_a_star_rating(self):
        row = meituan_review(dict(id=1,commentScoreType=1,createTime='2026-10-14'), {'id':'test'}, [])
        self.assertIsNone(row['rating'])
        self.assertFalse(row['negative'])

    def test_zero_only_when_complete_and_fresh(self):
        data=scope()
        result=build_summary(['银泰城店'], {'scopes':{'ele':data}}, NOW)['stores']['银泰城店']
        self.assertEqual(result['platforms']['饿了么']['negative_count'],0)
        self.assertIsNone(result['platforms']['美团']['negative_count'])
        data['reviews_status']='failed'
        self.assertIsNone(build_summary(['银泰城店'], {'scopes':{'ele':data}}, NOW)['stores']['银泰城店']['platforms']['饿了么']['negative_count'])

    def test_old_scores_remain_visible_but_stale_and_reviews_not_reused(self):
        data=scope();data['collected_at']='2026-10-14T11:00:00+08:00'
        result=build_summary(['银泰城店'], {'scopes':{'ele':data}}, NOW)['stores']['银泰城店']['platforms']['饿了么']
        self.assertEqual(result['current_rating'],4.7)
        self.assertEqual(result['rating_status'],'stale')
        self.assertEqual(result['status'],'stale')
        self.assertIsNone(result['negative_count'])

    def test_history_not_assigned_to_yesterday(self):
        data=scope();data['records']=[dict(store='银泰城店',platform='饿了么',date='2026-10-10',negative=True,content='历史',replied=False)]
        result=build_summary(['银泰城店'], {'scopes':{'ele':data}}, NOW)['stores']['银泰城店']
        self.assertEqual(result['negative_count'],0)
        self.assertEqual(len(result['recent_bad_reviews']),1)

    def test_seven_day_window_must_be_fully_covered(self):
        data=scope();data['start_date']='2026-10-14'
        result=build_summary(['银泰城店'], {'scopes':{'ele':data}}, NOW)
        self.assertEqual(result['status'],'missing')
        self.assertIsNone(result['stores']['银泰城店']['platforms']['饿了么']['negative_count'])

    def test_single_account_has_priority(self):
        head=scope('美团');single=scope('美团','failed');single['account_type']='single'
        result=build_summary(['银泰城店'], {'scopes':{'head':head,'single':single}}, NOW)
        self.assertIsNone(result['stores']['银泰城店']['platforms']['美团']['negative_count'])

    def test_paginate_beyond_two_pages(self):
        result=paged(lambda n:dict(total=5,list=list(range((n-1)*2,min(n*2,5)))),'list')
        self.assertEqual(result,list(range(5)))

    def test_pagination_truncation_and_changing_total_fail(self):
        with self.assertRaises(RuntimeError):paged(lambda n:dict(total=5,list=[1,2] if n==1 else []),'list')
        with self.assertRaises(RuntimeError):paged(lambda n:dict(total=5 if n==1 else 6,list=[1,2]),'list')

    def test_current_score_uses_no_review_average(self):
        data=scope();data['records']=[dict(store='银泰城店',date='2026-10-14',negative=True,rating=1,content='test')]
        result=build_summary(['银泰城店'], {'scopes':{'ele':data}}, NOW)['stores']['银泰城店']['platforms']['饿了么']
        self.assertEqual(result['current_rating'],4.7)
        self.assertIsNone(result['review_count'])

    def test_aliases_keep_financial_street_separate_from_financial_city(self):
        aliases=store_aliases()
        self.assertEqual(match_store('熊小小牛排饭POKEBEAR(金融城店)','饿了么',aliases),'金融城店')
        self.assertEqual(match_store('熊小小牛排饭POKEBEAR(金融街店)','饿了么',aliases),'金融街')

if __name__=='__main__':unittest.main()
