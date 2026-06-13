# Mac mini 下一步任务

## 当前任务：部署上午运营稳定性小修复

目的：

- Chrome 调试端口启动后最多等待 90 秒，避免刚启动就误判失败。
- 上午总控给 Chrome 启动步骤 120 秒窗口。
- 余额巡检的屏幕录制/辅助功能权限检测 5 秒内给结论，避免后台权限问题拖到长超时。
- 步骤超时时保留子进程已经输出的日志，方便判断卡在哪一步。

## 执行范围

只允许从 clean 仓库同步下面四个文件到旧生产目录：

```text
business-report-dashboard/chrome_cdp_reports.py
morning-ops/run_morning_ops.py
store-inspection/one_click_eleme_balance.py
store-inspection/one_click_meituan_balance.py
```

旧生产目录：

```text
/Users/summer/Documents/New project
```

clean 仓库：

```text
/Users/summer/Documents/operation-workbench-clean
```

## 必须遵守

- 不要运行上午运营任务。
- 不要运行日报、评价、余额巡检、预算提交或云端发布。
- 不要修改或 reload 任何 LaunchAgent。
- 不要修改其他文件。
- 不要提交、不要推送。
- 只同步本任务列出的四个文件。

## 建议执行步骤

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
git log --oneline -5

cp "business-report-dashboard/chrome_cdp_reports.py" "/Users/summer/Documents/New project/business-report-dashboard/chrome_cdp_reports.py"
cp "morning-ops/run_morning_ops.py" "/Users/summer/Documents/New project/morning-ops/run_morning_ops.py"
cp "store-inspection/one_click_eleme_balance.py" "/Users/summer/Documents/New project/store-inspection/one_click_eleme_balance.py"
cp "store-inspection/one_click_meituan_balance.py" "/Users/summer/Documents/New project/store-inspection/one_click_meituan_balance.py"

cd "/Users/summer/Documents/New project"
python3 -m py_compile \
  "business-report-dashboard/chrome_cdp_reports.py" \
  "morning-ops/run_morning_ops.py" \
  "store-inspection/one_click_eleme_balance.py" \
  "store-inspection/one_click_meituan_balance.py"

git diff -- \
  business-report-dashboard/chrome_cdp_reports.py \
  morning-ops/run_morning_ops.py \
  store-inspection/one_click_eleme_balance.py \
  store-inspection/one_click_meituan_balance.py
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -5`；
2. 四个文件是否已同步；
3. Python 语法检查是否通过；
4. 旧生产目录四个文件的 `git diff`；
5. 确认没有运行上午运营任务、没有运行日报/评价/余额/预算/发布、没有修改或 reload 定时任务、没有提交或推送。

## 预期效果

明早 08:00 正式任务启动时，Chrome 会有更充足的准备时间。若后台环境没有屏幕录制或辅助功能权限，余额巡检会快速输出明确原因，不再拖到长时间超时。
