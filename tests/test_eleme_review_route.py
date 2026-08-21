from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_eleme_reviews_use_current_group_account_route():
    text = (ROOT / "business-report-dashboard" / "chrome_cdp_reports.py").read_text(encoding="utf-8")
    assert 'ELEME_COMMENTS_URL = "https://melody.shop.ele.me/app/unit/comments#app.unit.comments"' in text
    assert "/app/chain/93331264/comments" not in text
