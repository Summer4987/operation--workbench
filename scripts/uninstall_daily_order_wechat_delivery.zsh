#!/bin/zsh
# Retire only ordinary-WeChat order delivery. Keep all business data and WeCom.
set -euo pipefail
LABEL="com.summer.operation.daily-order-wechat-delivery"
DOMAIN="gui/$(id -u)"
/bin/launchctl disable "$DOMAIN/$LABEL"
/bin/launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
if /bin/launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "无法卸载日配微信群投递任务" >&2
  exit 1
fi
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -f "$HOME/Library/Scripts/xiong-operation/run_daily_order_wechat_delivery.zsh"
echo "已取消日配普通微信群投递、自动重试及失败提醒；保留下单、库存、表格和企业微信流程。"
