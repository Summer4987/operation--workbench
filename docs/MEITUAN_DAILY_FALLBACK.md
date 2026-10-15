# 美团直营日报双路径采集

每日入口保持 `scripts/download_direct_meituan_daily.py --all --submit`，无需新增定时任务。

1. 优先获取指定日期的正式下载报表。核对目标日期、门店、基础列、有效数据行；空文件、字段缺失、错日期不可当作成功。
2. 下载限流、维护、生成超时、报表暂停或下载异常，自动读取同一单店账号的“经营分析 → 经营数据”。读取目标日历史收益、历史流量、顾客概览，拒绝今日实时数据和其它门店数据。
3. 默认报表等待60秒。维护/限流未生成新报表时，查询已有报表失败就直接切换兜底，不等待未知恢复日期；每个账号独立处理，不阻塞其它账号。
4. 两条路径都失败才返回失败，由既有上午任务失败记录/发布流程展示，不使用旧日期假充当天。

经营数据页基础字段：营业收入、订单量、订单实付、曝光人数、进店转化率、下单转化率、下单老客数、下单新客数。新老客各自下单转化率未提供，保存 `null`；其它未取得的可选字段同样不填0。请求必须匹配目标单日和实际门店ID。收入或单量缺失时不写成功记录。

兜底运行结果存于 `business-report-dashboard/data/direct/business_fallback/`，账号状态存于 `outputs/direct_meituan_daily/`，均由 Git 忽略。仅保存规范化指标及日期/门店/来源，不保存Cookie、签名、令牌或请求头。

`process_direct_reports.py`先合并兜底，再合并正式报表，同门店/平台/日期仅保留一条，正式报表优先。看板行及单店平台卡标注“经营数据页兜底”。运行产物不提交GitHub。

只读补采某店（不生成下载任务）：

```sh
python scripts/download_direct_meituan_daily.py --account direct_chaoyangmen --fallback-only
```

以上采集只能在Mac mini执行。代码通过GitHub main同步到正式 `~/Library/Application Support/xiong-operation/production` 后运行，再从Mac mini发布并校验正式链接。
