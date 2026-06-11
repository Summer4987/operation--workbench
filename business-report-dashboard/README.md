# 经营日报看板原型

这个目录是“饿了么 / 美团经营日报下载数据看板”的第一版原型。

当前版本先处理已经下载好的报表：

- 饿了么：`数据中心 -> 数据下载` 导出的 Excel
- 美团：`经营罗盘 -> 报表下载` 导出的 CSV

## 运行方式

默认会自动从下载目录寻找最新的饿了么 Excel 和美团 CSV：

```bash
python3 process_reports.py
```

也可以手动指定文件：

```bash
python3 process_reports.py \
  --eleme "/path/to/饿了么.xlsx" \
  --meituan "/path/to/美团.csv"
```

运行后会生成：

- `data/unified_daily.csv`：统一后的明细数据
- `data/latest.json`：看板使用的数据
- `dashboard/index.html`：本地网页看板

## 当前进度

- 已支持读取样例 Excel/CSV
- 已支持自动从下载目录识别最新报表
- 已支持门店名映射和非目标门店排除
- 已支持本地网页看板

下一步会接入自动登录和自动下载。

## 自动下载阶段

如果独立浏览器触发平台识别，改用常用 Chrome 登录环境。这个方式不绕过验证码或风控；遇到验证时需要人工接管。

配置在：

- `chrome_cdp_config.json`
- `chrome_cdp_reports.py`

第一步：完全退出 Chrome，然后启动带调试端口的常用 Chrome：

```bash
./start_common_chrome.command
```

查看连接状态：

```bash
python3 chrome_cdp_reports.py status
```

打开两个后台入口，确认登录状态：

```bash
python3 chrome_cdp_reports.py open-pages
```

识别下载页：

```bash
python3 chrome_cdp_reports.py probe-pages
```

如果页面能稳定打开，再把 `chrome_cdp_config.json` 里的 `download_url` 改成真实报表下载页地址。

原独立浏览器方案配置在：

- `download_config.json`
- `download_reports.py`

第一次使用：

```bash
./install_browser_automation.command
```

安装完成后：

```bash
python3 download_reports.py open-login
```

它会打开独立浏览器窗口。你需要手动登录饿了么和美团后台一次。

查看当前配置：

```bash
python3 download_reports.py status
```

尝试下载：

```bash
python3 download_reports.py download --manual
```

`--manual` 会在每个平台下载前暂停，方便你手动进入正确页面、选择昨日日期。等页面路径和按钮确认稳定后，再改成全自动下载。


## 当前门店

- 安贞
- 中关村
- 清河
- 金融街
- 丽泽
- 双井
- 光谷
- 五一广场

`金融城店`不会被纳入`金融街`，会被排除。

## 当前字段

- 单量
- 收入
- 曝光量
- 进店转化率
- 下单转化率
- 老客下单转化率
- 新客下单转化率
- 下单老客
- 下单新客
