import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from meituan_business_daily_fallback import parse_business_daily

ACCOUNT=dict(stores=['测试店'],keyword='测试店')


def fixture():
    params=dict(beginDate='20261014',endDate='20261014',durationType='1',wmPoiId='123')
    return dict(identity=dict(data=dict(wmPoiId=123,wmPoiName='测试店')),
        income=dict(params=dict(params),data=dict(list=[dict(field='settleAmount',current=100.5),dict(field='orderCnt',current=4),dict(field='cusPayment',current=120)])),
        flow=dict(params=dict(params),data=dict(left=dict(layers=[dict(field='exposeUv',base='200')],conversion=[dict(title='进店转化率',base='0.1'),dict(title='下单转化率',base='0.2')]))),
        customer=dict(params=dict(params),data=dict(list=[dict(field='old_fin_usr_num',base='2'),dict(field='new_fin_usr_num',base='1')])))


class BusinessFallbackTests(unittest.TestCase):
    def test_history_core_metrics_and_null_optional_fields(self):
        row=parse_business_daily(ACCOUNT,'20261014',fixture())
        self.assertEqual((row['income'],row['orders'],row['customer_paid'],row['impressions']),(100.5,4,120,200))
        self.assertEqual(row['visit_conversion'],0.1)
        self.assertIsNone(row['old_customer_order_conversion'])
        self.assertIsNone(row['new_customer_order_conversion'])
        self.assertEqual(row['source'],'business_page_fallback')

    def test_realtime_or_another_day_cannot_fill_yesterday(self):
        for field,value in [('beginDate','20261015'),('endDate','20261015'),('durationType','0')]:
            data=fixture();data['income']['params'][field]=value
            with self.assertRaises(RuntimeError):parse_business_daily(ACCOUNT,'20261014',data)

    def test_other_store_cannot_fill_this_store(self):
        data=fixture();data['identity']['data']['wmPoiName']='其他店'
        with self.assertRaises(RuntimeError):parse_business_daily(ACCOUNT,'20261014',data)
        data=fixture();data['income']['params']['wmPoiId']='999'
        with self.assertRaises(RuntimeError):parse_business_daily(ACCOUNT,'20261014',data)

    def test_real_zero_is_valid_missing_is_not_zero(self):
        data=fixture();data['income']['data']['list'][0]['current']=0;data['income']['data']['list'][1]['current']=0
        row=parse_business_daily(ACCOUNT,'20261014',data)
        self.assertEqual(row['orders'],0)
        self.assertEqual(row['income'],0)
        data['income']['data']['list'][0]['current']=None
        with self.assertRaises(RuntimeError):parse_business_daily(ACCOUNT,'20261014',data)

    def test_missing_optional_section_does_not_drop_core_data(self):
        data=fixture();del data['flow'];del data['customer']
        row=parse_business_daily(ACCOUNT,'20261014',data)
        self.assertEqual(row['orders'],4)
        self.assertIsNone(row['impressions'])
        self.assertIsNone(row['new_customer_orders'])

    def test_bad_conversion_is_rejected(self):
        data=fixture();data['flow']['data']['left']['conversion'][0]['base']='10.0'
        with self.assertRaises(RuntimeError):parse_business_daily(ACCOUNT,'20261014',data)

if __name__=='__main__':unittest.main()
