from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_macmini_installer_schedules_daily_order_wechat_delivery():
    text = (ROOT / "scripts" / "install_macmini_operation_launchd.zsh").read_text(encoding="utf-8")

    assert "com.summer.operation.daily-order-wechat-delivery" in text
    assert "run_daily_order_wechat_delivery.zsh" in text
    assert "--latest \"\\$LATEST\"" in text
    assert "DAILY_ORDER_WECHAT_LATEST:-20" in text
    assert "熊小小牛排饭-易代仓仓储配送群" in text
    assert "Desktop/库存管理/出库记录" in text

    for hour in range(9, 20):
        assert f"<dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>0</integer></dict>" in text
        assert f"<dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>30</integer></dict>" in text
    assert "<dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>" in text
