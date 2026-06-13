# AI 业务中心 Mac mini 生产交接清单

这份清单只用于把 MacBook 上开发好的 AI 业务中心能力接到 Mac mini 生产环境。MacBook 仍然只做开发验证，Mac mini 才是生产运行现场。

## 用户需要执行的命令

在 Mac mini 上打开终端，进入项目目录：

```zsh
cd "/Users/summer/Documents/New project"
```

先查看现场状态：

```zsh
git status --short --branch
```

如果 Codex 确认可以拉取，再执行：

```zsh
git pull --ff-only origin codex/ai-business-center
```

拉取后运行只读检查：

```zsh
/bin/zsh scripts/check_macmini_ai_center.zsh
```

## 输出怎么判断

如果看到 `环境：production`：

- 说明检查来自 Mac mini 生产环境。
- 后续健康报告可以作为生产判断依据。

如果看到 `环境：development`：

- 说明你不在 Mac mini，或者环境变量没有按生产标记。
- 这只代表开发检查，不代表生产状态。

如果看到 `未安装或未加载`：

- 说明生产定时任务没有加载，或需要重新安装。
- 先把完整输出发给 Codex。
- Codex 确认后再运行：

```zsh
/bin/zsh scripts/install_macmini_operation_launchd.zsh
```

如果看到 Python、Node、Git、权限或 launchd 错误：

- 不要重置仓库。
- 不要强制拉取。
- 不要手动删除 LaunchAgents。
- 把完整输出发给 Codex。

## 这条检查不会做什么

`scripts/check_macmini_ai_center.zsh` 不会：

- 采集平台数据。
- 提交推广预算。
- 调整出价。
- 下单或付款。
- 上传云端。

它只会检查代码、配置、脚本语法、健康数据生成和定时任务标签。

## Codex 后续负责

- 判断 Mac mini 输出是否能进入生产。
- 判断是否需要重装定时任务。
- 指定低风险预览命令。
- 继续把新模块接入统一任务注册表、运行记录和首页健康报告。
