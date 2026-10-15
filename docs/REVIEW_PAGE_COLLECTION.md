# 评价页面与门店评分

入口：运营总看板的加盟店、直营店评价板块。

- 当前门店评分来自平台评价页面总分：淘宝闪购 `ChainRatingService.pageShopDetail.shopScore`，美团 `chain/scores.poiScoreNew` 或单店 `poi/scores.poiScoreNew`。旧版页面仅明确返回旧总分时使用 `poiScoreOld`。不使用服务分、商品质量分、评价明细平均分或总账号店均分。
- 淘宝闪购总账号分别查询满意度 `SERVICE_SCORES` 的1–2星和页面实际3星筛选，使用 `serviceRating`，而非口味、包装分。已申诉或拦截记录仍保留，展示平台原文状态。
- 美团总账号和独立单店账号分开连接；单店先核对当前门店身份，再查询评价。独立账号优先于总账号，不跨账号补零。
- 中国时区，默认回查截至昨日的7个自然日；列表按实际评价日期归属。全量翻页核对总数、重复ID，超限、字段缺失、登录失效均视为采集失败。
- 仅采集中差评，不声称拥有总评价数，不用此样本计算差评率。未回复数来自平台回复状态。
- 当前日已完整核验才显示零差评。采集失败、未覆盖或跨日过期均明确提示。评分失败保留上次值及时间；首次采集无涨跌，之后对比上次采集日。

## 运行和生产发布

只在 Mac mini 使用已有登录态运行：

```sh
"/Users/summer/Documents/New project/business-report-dashboard/.venv/bin/python" scripts/collect_review_pages.py
# 仅重试某一账号，不影响其他账号快照
"/Users/summer/Documents/New project/business-report-dashboard/.venv/bin/python" scripts/collect_review_pages.py --account eleme_headquarters
```

脚本只打开自己创建的临时评价页，读取页面发起的评分/评价查询并复用其分页查询，结束关闭自己创建的页。不会回复、申诉、发券或修改平台配置。浏览器无需退出。

`outputs/review_pages/latest.json` 保留在生产本机（Git忽略），只包含规范化评分、评价和采集覆盖；不保存Cookie、签名、请求头或登录令牌。看板数据沿用现有发布通道。每日运营既有流程已替换评价下载为评价页采集，不增加定时任务，不触发推广预算。

本地验证：`python3 -m unittest discover -s tests -p test_review_page_data.py`。验证后提交并推送 GitHub main，Mac mini 仅从GitHub拉取运行；禁止从开发机拷贝采集脚本到生产。
