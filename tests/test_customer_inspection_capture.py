import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("capture", Path(__file__).parents[1] / "scripts/customer_inspection_capture.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureGuards(unittest.TestCase):
    def test_challenge_stops_but_reservation_does_not(self):
        self.assertTrue(capture.verification([{"text": "向右滑动验证"}]))
        self.assertFalse(capture.verification([{"text": "现在预订，明天10点配送"}]))

    def test_product_name_is_not_category_navigation(self):
        self.assertIsNone(capture.category_target([{"text": "牛排饭STEAK", "x": 550, "y": 700}]))
        self.assertIsNotNone(capture.category_target([{"text": "牛排饭 STEAK", "x": 100, "y": 700}]))

    def test_collapsed_search_mention_does_not_pass_header(self):
        self.assertFalse(capture.header_valid([{"text": "根据熊小小为你找到"}, {"text": "红包"}]))
        self.assertFalse(capture.header_valid([{"text": "熊小小牛排饭 POKEBEAR"}, {"text": "30减16"}]))
        self.assertTrue(capture.header_valid([{"text": "熊小小牛排饭 POKEBEAR"}, {"text": "30减16"}, {"text": "点餐"}]))
