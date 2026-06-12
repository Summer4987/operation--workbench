# GitHub 仓库归档清单

本仓库用于管理运营自动化系统的程序本体。GitHub 负责同步代码、脚本、看板和配置模板；Mac mini 负责实际运行；云端负责承载发布结果和轻量业务数据。

## 当前仓库

- 远端仓库：`git@github.com:Summer4987/operation--workbench.git`
- 生产分支：`main`
- 生产主机：Mac mini
- 管理/开发设备：MacBook 或 Codex 所在设备

## 应保留在 GitHub 的内容

这些文件描述“系统如何运行”，需要通过 GitHub 在设备之间保持一致。

- 自动化入口和安装脚本：
  - `morning-ops/`
  - `scripts/`
  - `store-inspection/`
  - 根目录下正式 `.command` 入口
- 看板和前端源码：
  - `index.html`
  - `workbench.js`
  - `workbench.css`
  - `business-report-dashboard/dashboard/`
  - `dianjin-prototype/`
  - `order-preview/`
  - `sales-receipt-generator/`
- 库存和订货程序：
  - `inventory-board/`
- 配置模板和非敏感配置：
  - `config/*.example.json`
  - 不含账号、密钥、Cookie、登录态的业务规则配置
- 项目文档：
  - `AGENTS.md`
  - `SOURCE_DATA_SYNC.md`
  - `OPERATION_PROGRESS.md`
  - `PROJECT_TREE.md`
  - `docs/`

## 不应进入 GitHub 的内容

这些文件属于本地运行现场、敏感信息或自动生成结果，不应该用 GitHub 同步。

- 浏览器登录态和 profile：
  - `business-report-dashboard/chrome-profile/`
  - `business-report-dashboard/browser-profile/`
- 依赖和缓存：
  - `node_modules/`
  - `**/.venv/`
  - `__pycache__/`
- 日志和运行状态：
  - `logs/`
  - `morning-ops/logs/`
  - `store-inspection/logs/`
  - `business-report-dashboard/logs/`
- 自动生成数据：
  - `workbench-data.js`
  - `data/realtime-history.json`
  - `business-report-dashboard/data/`
  - `store-inspection/latest*.json`
  - `store-inspection/latest-data.js`
  - `dianjin-prototype/current_state.js`
  - `dianjin-prototype/execution_preview.js`
- 临时截图、渲染结果和调试产物：
  - `outputs/`
  - `*.log`
  - `table-*.png`
  - `debug-*.png`
  - 文档/PDF 临时提取目录
- 敏感配置：
  - `.env`
  - `config/ops_notify.json`
  - `*.pem`
  - `*.key`
  - 平台账号、Cookie、Token、验证码、SSH 私钥

## 已发现的重复文件

盘点时发现一批名字带 ` 2` 的未跟踪文件，内容和正式文件完全相同。它们属于复制冲突或同步副本，不需要提交到 GitHub。

- `AGENTS 2.md`
- `SOURCE_DATA_SYNC 2.md`
- `data/source-sync-manifest 2.json`
- `scripts/build_source_data_manifest 2.py`
- `scripts/cleanup_operation_data 2.zsh`
- `scripts/install_operation_cleanup_launchd 2.zsh`
- `scripts/sync_source_data_to_cloud 2.zsh`
- `scripts/upload_store_inspection_evidence 2.zsh`
- `上传今天巡检证据到云服务器 2.command`
- `同步轻量源数据到云服务器 2.command`
- `安装本地旧运营数据定时清理 2.command`
- `清理本地旧运营数据 2.command`

处理原则：确认仍与正式文件相同后，可以删除本地副本；不要提交。

## 需要逐步改造的风险点

仓库里有少量公网地址和业务口令参数。它们不一定都是高危密码，但长期硬编码在代码中不利于多设备协作和权限管理。

后续建议：

- GitHub 保留配置模板和默认示例。
- Mac mini 本地保存真实生产配置。
- 云服务器通过环境变量保存生产口令。
- 自动化脚本优先从环境变量或本地私有配置读取敏感值。

## 提交前检查

每次提交前先确认：

- 只提交有效代码、脚本、看板、配置模板和文档。
- 不提交浏览器 profile、日志、下载数据、运行结果和密钥。
- 不提交名字带 ` 2` 的重复副本。
- 如果本地有他人或另一台 Mac 产生的改动，先区分来源，再决定是否暂存。
- 验证通过后再提交并推送到 GitHub。
