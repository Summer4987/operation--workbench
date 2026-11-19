# 美团推广 ROI 复盘

入口：管理系统 → 全品牌推广中心 → 推广 ROI 复盘（`#promo-roi`）。第一版只采集美团。

估算 ROI = 推广进店次数 × 当日全店下单转化率 ×（当日预计收入 / 当日订单量）/ 当日实际推广消耗。
全店转化率和收入客单价代表推广流量是统一模型假设，不是平台归因成交，也不是扣除成本后的利润。

生产端使用既有 Chrome 总账号逐店切换，直营账号使用已配置独立会话。不依赖龙虾店长应用，遵守它共用的账号锁和人工验证暂停状态。队列按预算 → 日终ROI复盘 → 龙虾巡检 → 普通采集排序；不打断正在进行的账号操作。只读数据，不编辑预算、出价或推广时段。

每日北京时间21:00触发。实际开始可能等待正在运行的浏览器任务，最多等待10分钟；账号单次等候最多180秒。逐店失败单列，其他门店继续。推广页强制刷新且必须确认当日更新时间；只有实际实时花费参与计算，不用七日花费或预算百分比反推。流量页存在平台分批更新延迟，允许当日45分钟内已更新数据并展示其更新时间。收入和订单优先复用同店同平台、同日20分钟内可信实时数据，缺失再从总览补采，流量页必须选今日实时。缺失、零单量、零花费不填假ROI。

正式结果保存在生产目录 `outputs/promo_roi/YYYY-MM-DD.json`，历史索引保留最近90天；运行产物和账号会话不进GitHub。`history.json`、`latest.json`通过现有云端SSH身份发布，逐文件原子替换；每店完成后尝试更新，最终发布失败保留本地文件并以非零码退出。页面每分钟自动刷新。

安装只允许在Mac mini从GitHub拉取的干净main检出执行：

```sh
python3 scripts/install_roi_review_launchd.py --runtime-root "$HOME/Library/Application Support/xiong-operation/production"
```

新任务标签：`com.summer.operation.meituan-roi-review`。安装不立即启动采集。日志位于 `~/Library/Logs/xiong-operation/promo_roi/`。独立发布检出可直接引用既有生产Python及配置，无须覆盖有本机改动的旧生产检出。

只读验证命令（结果单独保存，不覆盖正式日报）：

```sh
"$HOME/Library/Application Support/xiong-operation/production/business-report-dashboard/.venv/bin/python" scripts/meituan_roi_review.py --runtime-root "$HOME/Library/Application Support/xiong-operation/production" --probe --store 安贞
```

如登录或安全验证阻断，只记录失败并遵守既有账号暂停状态；不自动解除验证、不从开发机代替生产机打开平台。云端发布可使用同一脚本 `--publish-only` 重试，不重新采集。

安装时备份既有云端发布入口，将其指向同一GitHub main发布检出，并以 `OPERATION_UI_SOURCE_ROOT` 读取新版UI。原生产运行数据仍从既有runtime读取，后续半小时数据刷新不会覆盖掉ROI入口。
