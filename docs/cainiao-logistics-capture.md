# 菜鸟裹裹物流采集

第一版采集走安卓 ADB：Mac mini 登录菜鸟裹裹，脚本读取当前菜鸟页面的控件树和截图，解析物流单号、取件码、状态，再同步到门店物流看板。

## 手动验证

先连接安卓机并打开 USB 调试：

```bash
adb devices
```

先跑 dry-run，只生成证据包，不写看板：

```bash
python3 scripts/cainiao_logistics_capture.py --store-name 银泰城店
```

证据包默认在 `outputs/cainiao_logistics/<时间>/`，关键文件：

- `screen.png`：安卓截图
- `window_dump.xml`：安卓控件树
- `parsed.json`：解析出的单号、取件码、拟写入记录
- `summary.json`：本次运行摘要
- `error.json`：异常时给 agent 接管用的排查说明

确认解析没问题后，真实写入物流看板：

```bash
python3 scripts/cainiao_logistics_capture.py --store-name 银泰城店 --commit
```

如果有多台安卓设备，指定序列号：

```bash
CAINIAO_ADB_SERIAL=<adb序列号> python3 scripts/cainiao_logistics_capture.py --store-name 银泰城店 --commit
```

## 环境变量

- `ANDROID_ADB_BIN`：自定义 adb 路径
- `CAINIAO_ADB_SERIAL`：指定安卓设备
- `CAINIAO_PACKAGE`：菜鸟包名，默认 `com.cainiao.wireless`
- `DAILY_ORDER_SERVER`：看板服务，默认 `http://139.155.148.169`
- `DAILY_ORDER_ADMIN_TOKEN`：物流管理写入 token，默认 `daily-order-admin`

## 定时任务原则

正式每天两次跑之前，先在 Mac mini 真机完成一次 dry-run 和一次 `--commit` 验证。验证通过后再安装 launchd；异常时保留证据包，让 agent 读截图和控件树接管判断。

## Mac mini 运行目录

为避免 macOS 对 Documents 目录的后台访问限制（launchd 退出码 78、posix_spawn Operation not permitted），菜鸟任务使用独立 GitHub main 检出目录：

`~/Library/Application Support/XiongCainiao/github-main`

此目录必须通过 Git 从 GitHub main 拉取，不从开发机复制代码。先确认工作区无有效代码改动，再 `git pull --ff-only origin main`；在此目录完成真机预览及写入验证后，运行 `scripts/install_cainiao_logistics_launchd.zsh`。安装时间为每天 10:00、14:00、17:00；用 `launchctl kickstart gui/$(id -u)/com.summer.operation.cainiao-logistics` 验证后台实际执行结果，不能只检查任务是否加载。

新版首页的独立取件码卡片也作为详情入口；承运商轨迹文字和广告不作为详情入口。应用未安装或启动失败时直接报错，避免把桌面误判为采集成功。未知门店地址仍不写入看板。
