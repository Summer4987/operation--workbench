import json
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'business-report-dashboard'))
import process_reports as reports


class CustomerMetricsTests(unittest.TestCase):
    def test_rate_formats_and_missing_are_distinct_from_zero(self):
        for raw, expected in [('12.5%', .125), (.125, .125), ('0%', 0), (0, 0), ('--', None), (None, None), ('bad', None)]:
            self.assertEqual(reports.customer_rate(raw), expected)

    def test_export_mapping_preserves_periods_and_json_null(self):
        config = reports.load_config()
        frame = pd.DataFrame([{'日期':'2026-11-21', '门店名称':'熊小小牛排饭(安贞店)', '新客下单转化率':'12.5%', '老客下单转化率':.4, '近7日复购率':0, '近30日复购率':'18.5%'}])
        unified, _ = reports.standardize(frame, '饿了么', config['eleme']['columns'], reports.build_alias_lookup(config))
        row = json.loads(unified.to_json(orient='records'))[0]
        self.assertEqual([row[k] for k in ['new_customer_order_conversion', 'old_customer_order_conversion', 'repurchase_rate_7d', 'repurchase_rate_30d']], [.125, .4, 0, .185])
        frame = frame.drop(columns=['近7日复购率', '近30日复购率'])
        unified, _ = reports.standardize(frame, '饿了么', config['eleme']['columns'], reports.build_alias_lookup(config))
        self.assertIsNone(json.loads(unified.to_json(orient='records'))[0]['repurchase_rate_30d'])

    def test_meituan_repurchase_is_30_day_rate_not_score(self):
        config = reports.load_config()
        frame = pd.DataFrame([{'日期':'2026-11-21', '门店名称':'安贞店', '复购率':'21%', '复购率指标得分':4.9}])
        unified, _ = reports.standardize(frame, '美团', config['meituan']['columns'], reports.build_alias_lookup(config))
        self.assertEqual(unified.iloc[0]['repurchase_rate_30d'], .21)
        self.assertIsNone(unified.iloc[0]['repurchase_rate_7d'])
