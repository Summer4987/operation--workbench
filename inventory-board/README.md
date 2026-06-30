# 库存看板

这个项目用于构建一套云端为主的库存体系：门店在云端下单，服务器自动生成出库单并扣减库存；运营在总看板上传入库 Excel，服务器解析后更新库存、流水和预警。

## 模板识别

- 入库：读取 `Sheet1`，使用 `商品编码`、`商品名称`、`物料规格`、`到货数量`、`单位`。
- 出库：读取 `客户订单填写`，使用 `存货编码`、`名称`、`规格`、`数量`、`单位`。
- 商品以编码为主键，页面主展示品名和余量。
- 同一个 Excel 文件重复上传时不会重复计算库存。
- `app/catalog.json` 内置了当前易代仓模板里的 15 个商品，服务器首次启动会自动初始化商品目录。

## 本地运行

```bash
cd /Users/summer/Documents/New\ project/inventory-board
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

打开 `http://127.0.0.1:8000`。

## 云端生成出库单

门店下单和微信订货识别都应由云端服务完成。服务器会按模板生成出库 Excel，并直接登记出库流水、扣减库存。

默认生成文件目录：

```text
data/order_outputs
```

文件名格式为：

```text
熊小小排饭订单模板_年月日_时分秒.xlsx
```

当前商品识别规则来自模板里的 `货品信息`：存货编码、规格、单位会按货品名称自动带出。门店支持 `金融城店`、`银泰城店`、`万象城店`、`保利中心店`，地址、联系人、电话会自动填写。微信消息可以连续粘贴多家门店，例如：

```text
金融城店
拌饭汁 2件
双椒酱 1件
银泰城店
冷冻菠菜 3件 藤椒酱 1件
```

## 门店链接提交

正式名称：熊小小日配订货。

后续说“日配订货”时，默认指这个链接：

```text
http://139.155.148.169/order-submit?token=xiongxiaoxiao-order
```

后台顶部有“门店提交链接”。把这个链接发给门店，门店选择自己的门店名并填写商品数量，提交后云端会自动生成出库单。

门店提交成功后，服务器会同时完成两件事：

- 按 `data/templates/熊小小牛排饭订单模板.xlsx` 生成出库 Excel，明细写入 `客户订单填写`。
- 自动写入一条出库导入记录，并按提交数量扣减库存。

生成的出库单已经登记过文件指纹，后续如果用备用上传脚本再次上传同一个出库单，系统会按重复文件处理，不会重复扣库存。

当前链接口令默认为：

```text
xiongxiaoxiao-order
```

云端链接格式：

```text
http://139.155.148.169/order-submit?token=xiongxiaoxiao-order
```

如需在本地打印或归档，可用备用脚本同步云端生成的出库单：

```text
同步云端出库单到本地.command
```

同步后的文件默认会放到：

```text
~/Desktop/库存管理/出库记录
```

默认只检查最近 20 个云端出库单，适合作为手动打印和归档工具；如果需要更多历史文件，可以命令行调整 `--latest`。

## 门店提交通知

服务器支持 Mac mini 普通微信自动发送、Hermes、企业微信或飞书机器人通知。生产环境要把“熊小小日配订货”生成的 Excel 直接发到普通微信群时，推荐让 Mac mini 从云端拉取新 Excel，再通过已登录的本机微信窗口搜索群名并发送。这样普通微信登录态和附件文件都在 Mac mini 本地，不依赖企业微信 webhook。

```bash
sudo nano /etc/inventory-board.env
```

云端不再推企业微信时，移除 `ORDER_NOTIFY_WEBHOOK` 或把通知类型改成不使用 webhook。Mac mini 上先把历史文件标记为基线，避免首次安装时群发旧单：

```bash
python3 inventory-board/scripts/deliver_order_outputs_with_hermes.py --init-baseline
```

之后定时运行：

```bash
python3 inventory-board/scripts/deliver_order_outputs_with_hermes.py \
  --sender wechat-gui \
  --target 熊小小牛排饭-易代仓仓储配送群
```

默认发送到：

```text
熊小小牛排饭-易代仓仓储配送群
```

可选环境/参数：

```text
--hermes-bin /Users/summer/.local/bin/hermes
--sender wechat-gui
--wechat-gui-bin /Users/summer/HermesPrivate/bin/wechat_gui_sender.py
--target 熊小小牛排饭-易代仓仓储配送群
--state-path ~/HermesPrivate/state/daily_order_hermes_delivery.json
```

`wechat-gui` 发送方式需要 Mac mini 已登录微信，并且运行脚本的进程具备 macOS“辅助功能”权限。可先做健康检查：

```bash
python3 inventory-board/scripts/wechat_gui_sender.py --health-check --json
```

如果只想做健康检查、不真实发群，临时加：

```bash
python3 inventory-board/scripts/deliver_order_outputs_with_hermes.py --sender wechat-gui --dry-run
```

企业微信机器人新增：

```text
ORDER_NOTIFY_TYPE=wecom
ORDER_NOTIFY_WEBHOOK=企业微信机器人 webhook 地址
```

飞书机器人新增：

```text
ORDER_NOTIFY_TYPE=feishu
ORDER_NOTIFY_WEBHOOK=飞书机器人 webhook 地址
```

保存后重启：

```bash
sudo systemctl restart inventory-board
```

配置后，门店每次提交都会生成 Excel；Mac mini 投递器会同步新文件、按状态文件去重，并通过本机微信把文本和 Excel 文件直接发送到目标普通微信群。

如果要加访问密码：

```bash
export INVENTORY_PASSWORD='换成你的密码'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 腾讯云部署

推荐部署到 `/opt/inventory-board`，用系统服务守护后端，用 Nginx 对外提供访问。

```bash
sudo mkdir -p /opt/inventory-board
sudo cp -R inventory-board/* /opt/inventory-board/
cd /opt/inventory-board
sudo bash deploy/install_on_server.sh
```

部署完成后，腾讯云安全组需要放行 80 端口。浏览器访问：

```text
http://服务器公网 IP/
```

脚本会自动生成访问密码，并保存到 `/etc/inventory-board.env`。如果要改密码：

```bash
sudo nano /etc/inventory-board.env
sudo systemctl restart inventory-board
```

生产环境如有域名，建议再配置 HTTPS。

## 运营入库上传

正式流程里，运营只需要在总看板上传入库 Excel。页面默认只保留入库上传入口，出库不再依赖本地手动上传。

## 本地脚本兜底

本地脚本只作为备用工具，不再承担主流程。

监听脚本默认只监听入库目录：

```text
~/Desktop/库存管理/入库记录
```

发现新的 `.xlsx` 或 `.xlsm` 后会自动上传到云端。上传成功后移动到：

```text
~/Desktop/库存管理/已导入
```

上传失败会在这里生成失败原因：

```text
~/Desktop/库存管理/导入失败
```

双击运行：

```text
启动自动上传.command
```

也可以命令行运行：

```bash
python3 scripts/watch_inventory_folder.py --server http://139.155.148.169
```

如果确实要补录历史出库 Excel，再显式加参数：

```bash
python3 scripts/watch_inventory_folder.py --server http://139.155.148.169 --movement outbound
```

## 模板路径

云端部署推荐把出库模板放在：

```text
data/templates/熊小小牛排饭订单模板.xlsx
```

也可以通过环境变量覆盖：

```bash
export INVENTORY_TEMPLATE_PATH=/opt/inventory-board/data/templates/熊小小牛排饭订单模板.xlsx
export INVENTORY_OUTPUT_DIR=/opt/inventory-board/data/order_outputs
```

总看板里的“下载入库模板”按钮会优先查找以下文件名：

```text
data/templates/入库模板.xlsx
data/templates/入库模板.xlsm
data/templates/库存入库模板.xlsx
data/templates/库存入库模板.xlsm
```
