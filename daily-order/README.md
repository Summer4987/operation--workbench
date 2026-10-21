# 日常订货链接

正式名称：熊小小成都门店订货。

后续说“门店订货”时，默认指这个链接：

```text
http://139.155.148.169/daily-order/
```

统一入口：

```text
http://139.155.148.169/store-ops/
```

兼容入口，不依赖新增 Nginx location：

```text
http://139.155.148.169/daily-order/store-ops/
```

统一入口包含成都门店日常订货、熊小小日配订货和物流信息。北京门店订货不包含在这个入口内。

北京独立复制入口：

正式名称：熊小小北京门店订货。

后续说“北京门店订货”时，默认指这个链接：

```text
http://139.155.148.169/beijing-order/
```

这个模块是独立的门店日常 SKU 下单链接，不接入现有库存管理、旧订货模板或旧门店订货链接。

## 本地运行

```bash
cd /Users/summer/Documents/New\ project/daily-order
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

打开：

```text
http://127.0.0.1:8010/daily-order/
```

## 数据来源

SKU 来自 `日常订货sku.xlsx`，已整理到：

```text
app/catalog.json
app/catalog-beijing.json
```

当前包含 67 个品项，字段包括配送方式、分类、品名、规格、单位、备注和库存下单状态。

## 提交结果

门店提交后会在本模块内生成独立文件：

```text
data/submissions/*.json
data/submissions/*.csv
```

这些文件是运行结果，默认不提交到 GitHub。

## 订货通知路由

2026-10-21 起，成都／北京门店逐单的「有门店下单啦」提醒停用；每天
18:00 微信群订货汇总改用「熊小小日配订货」现有 Excel／出库单通知群。
Excel 推送和 18:00 后补单提醒也使用这个目标，旧门店通知群不再承担这些通知。
若指定日期没有微信群商品订单，汇总接口仍返回 empty，不发送空汇总。

配置只存放在云端 systemd 的 `zzz-order-notification-routing.conf`，不将机器人
地址提交 Git。此配置清空 `DAILY_ORDER_NOTIFY_WEBHOOK`，将
`DAILY_ORDER_WECHAT_NOTIFY_WEBHOOK` 指向正在运行的日配服务的
`ORDER_NOTIFY_WEBHOOK`，保持 18:00 定时器不变。

在 Mac mini 从 GitHub main 拉取后，可以预览或更新路由（不会发送测试消息）：

```sh
python3 scripts/configure_order_notification_routing.py
python3 scripts/configure_order_notification_routing.py --apply
```

输出仅包含通知目标指纹。验证时确认逐单提醒关闭、汇总目标与日配目标一致，
并检查正式订货页面和只读汇总预览接口。机器人地址本身不包含可查询的群名称。
