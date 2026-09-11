from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_retires_daily_order_wechat_delivery():
    text = (ROOT / "scripts/install_macmini_operation_launchd.zsh").read_text()
    assert '"$SOURCE_ROOT/scripts/uninstall_daily_order_wechat_delivery.zsh"' in text
    assert "write_daily_order_wechat_delivery_plist" not in text
    assert "deliver_order_outputs_with_hermes.py" not in text
    assert "日配订单微信群自动发送失败" not in text
    assert 'write_plist "com.summer.operation.inventory-warning-daily"' in text


def test_retirement_preserves_orders_and_wecom():
    text = (ROOT / "scripts/uninstall_daily_order_wechat_delivery.zsh").read_text()
    assert 'disable "$DOMAIN/$LABEL"' in text
    assert 'bootout "$DOMAIN/$LABEL"' in text
    removals = [line for line in text.splitlines() if line.startswith("rm ")]
    assert removals == [
        'rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"',
        'rm -f "$HOME/Library/Scripts/xiong-operation/run_daily_order_wechat_delivery.zsh"',
    ]
