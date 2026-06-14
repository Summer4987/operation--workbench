# 日常订货链接

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
```

当前包含 58 个品项，字段包括配送方式、分类、品名、规格、单位和备注。

## 提交结果

门店提交后会在本模块内生成独立文件：

```text
data/submissions/*.json
data/submissions/*.csv
```

这些文件是运行结果，默认不提交到 GitHub。
