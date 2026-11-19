import importlib.util
from pathlib import Path
import tempfile
import unittest
from datetime import datetime

spec = importlib.util.spec_from_file_location("roi", Path(__file__).resolve().parents[1]/"scripts/meituan_roi_review.py")
roi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roi)


class ReviewTests(unittest.TestCase):
    def test_promotion_uses_realtime_and_actual_spend(self):
        text = "实时数据\n今日 11-19 21:02 更新\n推广花费\n150.01元\n昨日150元\n推广进店量\n102次\n昨日106次\n历史数据\n推广花费\n870.46元\n推广进店量\n611次"
        row = roi.parse_promotion(text, "2026-11-19")
        self.assertEqual(row["spend"], 150.01)
        self.assertEqual(row["promo_visits"], 102)
        with self.assertRaises(ValueError):
            roi.parse_promotion(text, "2026-11-20")
        with self.assertRaises(ValueError):
            roi.parse_promotion("今日 11-19 21:02 更新\n历史数据\n推广花费870元\n推广进店量611次", "2026-11-19")

    def test_flow_own_store_and_target_date(self):
        text = "今日实时 昨日 已选时间：2026-11-19 流量转化 32.17%\n下单转化率\n31.11%\n下单转化率 经营建议"
        self.assertAlmostEqual(roi.parse_flow(text, "2026-11-19")["conversion_rate"], .3217)
        with self.assertRaises(ValueError):
            roi.parse_flow(text, "2026-11-18")

    def test_income_does_not_use_yesterday(self):
        text = "今日实时数据\n11-19 21:02更新\n预计订单收入\n3,000.00\n比昨日同时段\n20\n订单量\n100\n历史收益概览\n订单量\n200"
        self.assertEqual(roi.parse_overview(text, "2026-11-19")["orders"], 100)

    def test_realtime_flow_css_percent_requires_selected_today(self):
        text = "今日实时 昨日 11-19 21:00更新 流量转化 本店 8.12 入店转化率 33.61 下单转化率 2,930人 238人 80人 7.29 入店转化率 32.29 下单转化率"
        self.assertAlmostEqual(roi.parse_flow(text,"2026-11-19",active_today=True)["conversion_rate"],.3361)
        with self.assertRaises(ValueError):
            roi.parse_flow(text,"2026-11-19")
        with self.assertRaises(ValueError):
            roi.parse_flow(text,"2026-11-20",active_today=True)

    def test_estimate_and_weighted_summary(self):
        a = roi.estimate(dict(spend=200, promo_visits=100, conversion_rate=.3, income=3000, orders=100))
        b = roi.estimate(dict(spend=100, promo_visits=20, conversion_rate=.5, income=2000, orders=100))
        self.assertEqual(a["estimated_income"], 900)
        self.assertEqual(a["roi"], 4.5)
        self.assertAlmostEqual(roi.summarize([a,b])["roi"], 1100/300)
        self.assertNotEqual(roi.summarize([a,b])["roi"], (a["roi"]+b["roi"])/2)

    def test_missing_zero_and_invalid_are_not_false_success(self):
        base = dict(spend=150, promo_visits=100, conversion_rate=.3, income=3000, orders=100)
        for key in base:
            self.assertEqual(roi.estimate(dict(base, **{key:None}))["status"], "failed")
        self.assertEqual(roi.estimate(dict(base, spend=0))["status"], "no_spend")
        self.assertIsNone(roi.estimate(dict(base, orders=0))["roi"])
        self.assertEqual(roi.estimate(dict(base, conversion_rate=32))["status"], "failed")

    def test_cache_requires_same_day_fresh_matching_platform(self):
        at = datetime(2026,11,19,21,5,tzinfo=roi.TZ)
        payload = dict(generated_at="2026-11-19 21:00:00", items=[dict(store="中关村",platform="美团",orders=100,income=3000,income_status="trusted")])
        task = dict(keyword="第3档口", sourceStore="档口", store="熊小小")
        self.assertEqual(roi.cached_income(payload,task,at)["income"],3000)
        self.assertIsNone(roi.cached_income(dict(payload,generated_at="2026-11-18 21:00:00"),task,at))
        self.assertIsNone(roi.cached_income(dict(payload,generated_at="2026-11-19 19:00:00"),task,at))
        payload["items"][0]["income_status"]="untrusted"
        self.assertIsNone(roi.cached_income(payload,task,at))

    def test_today_failure_never_reuses_yesterday(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            for date, status in [("2026-11-18","ok"),("2026-11-19","failed")]:
                roi.save_review(output,dict(date=date,generated_at=date+"T21:05:00+08:00",status="finished",items=[dict(store="安贞",status=status,spend=150,estimated_income=450,estimated_orders=15)]))
            history=roi.read_json(output/"history.json")["days"]
            self.assertEqual(history[0]["date"],"2026-11-19")
            self.assertEqual(history[0]["items"][0]["status"],"failed")
            self.assertIsNone(history[0]["summary"]["roi"])


if __name__ == "__main__":
    unittest.main()
