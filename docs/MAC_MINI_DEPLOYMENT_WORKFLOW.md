# Mac mini 部署机制

Mac mini 是运营自动化的唯一生产主机。GitHub 是代码源，Mac mini 是运行现场，云端是结果发布地。

## 设备分工

Mac mini：

- 运行正式定时任务。
- 保存浏览器登录态和 Chrome profile。
- 下载平台数据。
- 生成看板和运营数据。
- 上传结果到云端。
- 运行未来的健康监控器。

MacBook 或 Codex 所在设备：

- 修改和审查代码。
- 查看看板和运行结果。
- 远程维护 Mac mini。
- 不安装正式生产定时任务。

## 基本规则

- 生产代码只从 GitHub `main` 分支部署到 Mac mini。
- Mac mini 默认只拉取已验证代码；生产现场允许修复紧急 bug，但修复验证后当天必须推送到 GitHub。
- 不通过手动拷贝在两台设备之间同步程序文件。
- Mac mini 的日志、下载文件、浏览器登录态和运行状态不上传 GitHub。
- GitHub 不作为业务数据仓库，只管理程序本体。
- 定时任务只在 Mac mini 安装，避免两台设备重复执行。

## 标准部署流程

在开发设备完成修改后：

1. 验证本地改动。
2. 只暂存本次有效改动。
3. 提交到 Git。
4. 推送到 GitHub `main`。

在 Mac mini 上部署：

1. 进入项目目录：

   ```zsh
   cd "/Users/summer/Documents/New project"
   ```

2. 查看本地状态：

   ```zsh
   git status --short --branch
   ```

3. 如果没有未提交改动，拉取最新代码：

   ```zsh
   git pull --ff-only origin main
   ```

4. 如果出现未提交改动，先暂停部署，不要强行覆盖。需要判断这些改动属于：

   - 本机运行产物：通常不应提交，应该被忽略。
   - 有效代码改动：需要确认是否提交。
   - 另一台设备的重复副本：通常不应提交。
   - 生产配置或登录态：不应进入 GitHub。

5. 拉取完成后，先做轻量验证，再决定是否重新安装定时任务。

### AI 业务中心生产检查

拉取包含 AI 业务中心改动的代码后，先在 Mac mini 项目目录运行：

```zsh
/bin/zsh scripts/check_macmini_ai_center.zsh
```

这个检查只做只读验证：

- 校验任务注册表。
- 检查 Python 和 zsh 脚本语法。
- 生成 `outputs/task_health/latest.json` 和 `workbench-data.js`。
- 查看生产 launchd 标签是否已加载。

它不会采集平台数据、不会提交推广预算、不会付款、不会上传云端。

如果检查输出里出现 `未安装或未加载`，并且本次改动涉及定时任务入口、触发时间或安装脚本，再运行：

```zsh
/bin/zsh scripts/install_macmini_operation_launchd.zsh
```

如果检查里出现 Python、Node、Git、权限或 launchd 错误，把完整输出发给 Codex，不要强行重置或覆盖现场。

## 生产热修复流程

Mac mini 是生产环境，不代表它永远不能产生代码改动。遇到只在生产现场复现、或必须立刻修复的 bug 时，可以在 Mac mini 上修复，但修复必须回到 GitHub。

1. 先确认正式任务没有运行到关键中间步骤。
2. 只修改和本次故障直接相关的代码、脚本、看板或配置模板。
3. 用真实任务或最小可验证流程确认修复有效。
4. 提交前确认没有混入 Chrome profile、日志、下载数据、运行结果、密钥、Cookie 或临时调试产物。
5. 只暂存本次修复相关文件。
6. 提交并在当天推送到 GitHub。
7. 如果因为网络、权限或远端冲突无法推送，必须保留本地修复，输出阻塞原因，并等待处理，不要强行覆盖远端或重置本地仓库。

核心规则：Mac mini 生产修复可以做，但修复验证后，当天必须推送 GitHub。

## 什么时候需要重新安装定时任务

只有以下内容发生变化时，才需要重新安装 launchd：

- `scripts/install_macmini_operation_launchd.zsh`
- `morning-ops/install_launchd.zsh`
- `store-inspection/install_launchd.zsh`
- `scripts/install_eleme_launchd.zsh`
- 定时任务触发时间、任务入口或工作目录发生变化

普通看板、数据处理脚本或页面样式变化，一般不需要重新安装定时任务。

## 遇到冲突时怎么处理

如果 `git pull --ff-only origin main` 失败：

- 不要运行覆盖、重置或强制拉取。
- 先保留现场。
- 把 `git status --short --branch` 的结果交给 Codex 判断。
- 区分生产现场改动和 GitHub 最新改动后，再决定合并、提交或清理。

## 每日运行边界

Mac mini 每天负责：

- 按 launchd 定时触发自动化任务。
- 保存本地日志和下载数据。
- 生成最新看板数据。
- 上传云端结果。

GitHub 不负责：

- 同步 Chrome 登录态。
- 同步验证码处理状态。
- 同步每日下载的原始报表。
- 同步运行日志和临时截图。

## 后续运营中心底座

后续新增健康监控器时，也遵守同一机制：

- 监控器代码进 GitHub。
- 监控器配置模板进 GitHub。
- Mac mini 的真实通知配置、日志和状态文件不进 GitHub。
- 监控器发现失败后主动通知，而不是依赖人工每天发现。
