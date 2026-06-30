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

## 饿了么固定生产流程

饿了么评价下载固定走 `chrome_cdp_reports.py` 的 `download_eleme_reviews()`：

1. 打开 `ELEME_COMMENTS_URL`。
2. 等待包含 `导出评价` 的真实评价 iframe，当前 iframe 是 `https://melody-comment.faas.ele.me/`。
3. 点击 `导出评价`。
4. 监听 `ExportRatingTaskService.exportRatingData` 获取 `taskId`。
5. 调用 `ExportRatingTaskService.getExportRatingTask` 轮询导出完成。
6. 下载返回的文件链接到 `data/reviews/raw/`。
7. 运行 `process_reports.py --allow-missing-platform` 重新生成看板数据。

单独验证饿了么评价，不打开美团：

```bash
python3 - <<'PY'
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("chrome_cdp_reports", Path("chrome_cdp_reports.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.download_eleme_reviews())
PY
```

饿了么日报固定走 `chrome_cdp_reports.py` 的 `generate_eleme_report()` 和 `wait_for_eleme_report()`。成功文件名必须匹配当天 `门店下载_YYYYMMDD至YYYYMMDD_*.xlsx`。

重要准则：

- 没拿到当天饿了么日报时，不允许自动使用更早日期的饿了么日报补位。
- 没拿到当天评价时，不允许展示历史评价作为当天评价。
- `--allow-missing-platform` 只表示缺失平台不自动找历史文件；看板必须如实缺失该平台当天记录。
- 修复前先复核上述固定函数和最近日志，不重新发明流程。

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
