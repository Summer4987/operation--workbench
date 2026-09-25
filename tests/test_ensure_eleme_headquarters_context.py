import json
import tempfile
import unittest
from pathlib import Path

from scripts.ensure_eleme_headquarters_context import expected_shop_ids


class ExpectedShopIdsTest(unittest.TestCase):
    def test_expected_shop_ids_are_unique_and_sorted(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = Path(directory) / "preview.json"
            preview.write_text(
                json.dumps(
                    {
                        "rows": [
                            {"shopId": 524321320},
                            {"shopId": "166525463"},
                            {"shopId": 524321320},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(expected_shop_ids(preview), ["166525463", "524321320"])

    def test_expected_shop_ids_reject_empty_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            preview = Path(directory) / "preview.json"
            preview.write_text('{"rows": []}', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "没有 shopId"):
                expected_shop_ids(preview)


if __name__ == "__main__":
    unittest.main()

class ModernContextTest(unittest.TestCase):
    def test_modern_brand_region_shop_and_all(self):
        from unittest.mock import Mock, patch
        from scripts.ensure_eleme_headquarters_context import choose_context
        brand = '/ACCOUNT_ROOT:6152949092/BRAND_ROOT:93331264'
        region = brand + '__RC_CASCADER_SPLIT__' + brand + '/BRANCH:95560305'
        for target in ['524321320', '93331264']:
            page = Mock()
            group, option = Mock(), Mock()
            group.get_attribute.return_value = brand
            page.locator.return_value.evaluate_all.return_value = [region]
            visible = [None, group, option] if target == '93331264' else [None, group, None, option]
            with patch('scripts.ensure_eleme_headquarters_context.open_switcher'), patch('scripts.ensure_eleme_headquarters_context.visible_locator', side_effect=visible):
                choose_context(page, '93331264__RC_CASCADER_SPLIT__' + target, '**/expected/**')
            group.click.assert_called_once()
            option.click.assert_called_once()
            page.wait_for_url.assert_called_once_with('**/expected/**', timeout=30000)
