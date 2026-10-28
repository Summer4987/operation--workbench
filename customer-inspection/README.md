# 客户端巡检结果

2026-10-28：按用户要求停用每日采集及自动发布提醒。`enabled: false` 是当前生产状态；安装入口在停用状态会卸载相关定时任务，避免误装恢复。历史结果及原图保留。以下轮换说明仅作历史记录。

## 每日4店生产任务

`config/customer-inspection-rotation.json` 是轮换配置，2026-10-26成都为第一组，随后北京东部4店、北京西部4店、武汉2店+杭州滨江+长沙五一广场，4天循环。每天北京时间10:30，由生产Mac mini 的 `com.summer.customer-inspection-daily` LaunchAgent执行，本机Codex/MacBook不必在线。Mac mini须处于登录运行状态、安卓机保持连接授权；关机期间不能采集。睡眠恢复时launchd可能补触发，不跨天回放旧批次。

生产从GitHub main拉取后执行 `zsh scripts/install_customer_inspection_daily.zsh`。安装不会立刻重新采集当天门店。`python3 scripts/customer_inspection_daily.py --plan --date YYYY-MM-DD` 查看排期；`--preflight` 只检查设备和冲突，不操作平台。安装器拒绝脏生产代码及非main分支，日志留在 `~/Library/Logs/customer-inspection-daily`。

执行器仅用本机ADB和Vision OCR，不依赖模型登录；只点击新截图中已识别的搜索、地址、具名商家和分类。先用当前地址找店，未找到才做一次地址重试。每平台每店最多150秒、双平台每店合计最多300秒；验证码暂停该平台。发现菜鸟任务占用则跳过，任务自身有文件锁。手机锁屏、控件变化、截断身份、地址或店铺无法确认，均记缺失，不盲点、不加购。中间导航截图为临时文件，单店结束删除；合格原图仅保留规定两张。每批结束一次性发布清单，避免每家发送通知。

自动合格状态 `ocr_verified` 明确表示OCR核验，不等同人工逐图复核；页面与私聊均区分。依次核验具名搜索结果、进入店铺后的品牌和优惠头部、实际分类点击、商品名称和价格。不保证平台不弹验证码，也不保证四天内全部成功；四天是排期覆盖周期，失败不会借用旧图或别店图片凑数。自动导航仍需在实跑中验证各城市平台的页面差异。

正式入口：`/operation-workbench/#customer-inspection`，独立页 `/operation-workbench/customer-inspection/`。沿用运营看板登录保护，支持日期、城市、平台筛选和原图查看。

## 发布与通知

生产 Mac mini 从 GitHub main 拉取代码后运行：

```sh
python3 scripts/customer_inspection_results.py --source "$HOME/Documents/customer-inspection/YYYY-MM-DD-city"
zsh scripts/install_customer_inspection_results.zsh
```

输入必须是已人工/视觉复核的 `reviewed-progress.json`；合格记录状态 `visually_accepted`、`files` 中两张 PNG 的相对路径和 SHA256。原图仍在 Mac mini，发布时只复制合格两图，不复制验证码、地址簿、私有日志或绝对路径。校验失败停止发布，不把仅保存文件当作完成。`--build-only DIRECTORY` 可在开发机离线预览。

运行数据保存在 `~/Library/Application Support/customer-inspection`，发布缓存在其中 `published`，不入 GitHub。后台任务不使用受macOS文稿隐私限制的目录。历史 `~/Documents/customer-inspection` 原件保留，迁移运行数据时复制并校验，不删除原件。图片先上传，日期数据随后原子更新，日期索引最后更新；正常登录正式 URL 并校验页面及每张原图后，才生成发布回执并请求本机企微服务发私聊摘要。结果通过现有长连接仅发给已绑定老板，不允许调用者指定收件人或正文。凭据、发布去重记录和消息回执均留在生产机。

安装器只创建结果发布/通知任务，每5分钟检查当天新增或变更的复核清单；同一结果不重复发送，发送失败保留重试。它不创建手机采集任务，不修改平台登录态，也不能解决验证码或提高采集成功率。其他日期历史可以显式 `--source` 发布。源结果修改后将重新校验发布，通知按照门店状态和图片哈希去重。

页面统计仅包含所选日期已有记录的批次，未纳入的门店不算成功；历史日期会标识为历史。未来采集应在完成两图验收后写入同一约定的复核清单，即可自动上传并通知。

验证：`python3 -m unittest discover -s tests -p test_customer_inspection_results.py`；`node --test wecom-assistant/test_inspection.mjs`。生产 `ops` 通知 Webhook 并非此模块依赖。
