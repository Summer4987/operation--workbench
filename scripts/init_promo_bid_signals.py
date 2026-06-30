from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNAL_DIR = ROOT / "data" / "promo-bid-signals"
TEMPLATE_DIR = SIGNAL_DIR / "templates"
TEMPLATE_PATH = TEMPLATE_DIR / "promo_bid_signal_template.csv"

TEMPLATE = """date,platform,store,period,impressions,visits,orders,spend,current_bid,current_budget,notes
2026-06-13,饿了么,示例门店,午餐,1000,80,12,36.5,0.8,80,示例行，填写真实导出后删除
"""


def main() -> int:
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    (SIGNAL_DIR / ".gitkeep").touch(exist_ok=True)
    if not TEMPLATE_PATH.exists():
        TEMPLATE_PATH.write_text(TEMPLATE, encoding="utf-8")
    print(f"推广出价信号目录已准备：{SIGNAL_DIR.relative_to(ROOT)}")
    print(f"CSV 模板：{TEMPLATE_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
