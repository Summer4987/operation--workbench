# 源数据轻量同步和清理

默认同步到云服务器的只有轻量源数据，不再上传巡检截图/OCR 全量证据。

- 默认服务器：`ubuntu@139.155.148.169`
- 默认目录：`/var/www/html/operation-source-data/macmini`
- 本地清单：`data/source-sync-manifest.json`
- 云端清单：`/var/www/html/operation-source-data/macmini/data/source-sync-manifest.json`

默认同步内容：

- 日报原始下载和汇总数据
- 评价原始下载和汇总数据
- 点金/预算自动化 JSON
- 实时单量收入数据
- 推广预算预览数据
- 余额巡检的最新汇总文件

不默认同步：

- `outputs/store_inspection` 下的截图和 OCR 证据

手动同步轻量源数据：

```zsh
./同步轻量源数据到云服务器.command
```

按需上传当天巡检证据：

```zsh
./上传今天巡检证据到云服务器.command
```

本地清理默认保留期：

- 日报/评价原始下载：90 天
- 自动化 JSON 和实时记录：60 天
- 巡检截图和 OCR 证据：3 天，且默认最多保留 800MB
- 日志文件：30 天

手动清理本地旧数据：

```zsh
./清理本地旧运营数据.command
```

可以通过环境变量调整保留期：

```zsh
export OPERATION_CLEAN_RAW_DAYS=90
export OPERATION_CLEAN_JSON_DAYS=60
export OPERATION_CLEAN_EVIDENCE_DAYS=3
export OPERATION_CLEAN_EVIDENCE_MAX_MB=800
export OPERATION_CLEAN_LOG_DAYS=30
```
