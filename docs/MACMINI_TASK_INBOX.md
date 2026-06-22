# Mac mini 任务收件箱

这个文件用于给 Mac mini 上的 Codex 传递下一步执行任务。Mac mini 默认只在 clean 仓库读取此文件，除非任务明确要求，不要修改旧生产目录。

## 使用方式

在 Mac mini 上优先双击：

```text
Mac mini Codex接管.command
```

或在终端执行：

```zsh
cd "/Users/summer/Documents/New project"
/bin/zsh scripts/macmini_takeover_clean_checkout.zsh
```

这会准备或更新 `/Users/summer/Documents/operation-workbench-clean` 干净交接仓库，并打印 `docs/MACMINI_NEXT_TASK.md`。然后让 Mac mini Codex 在这个干净交接仓库里按任务执行。

如果需要手动读取任务：

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git status --short --branch
cat docs/MACMINI_NEXT_TASK.md
```

## 规则

- 默认不要修改 `/Users/summer/Documents/New project`。
- 默认在 `/Users/summer/Documents/operation-workbench-clean` 执行接管任务。
- 默认不要触碰已有定时任务。
- 默认不要提交或推送。
- 如果任务需要修改旧生产目录，必须只修改任务列出的文件。
- 如果任务要求验证，必须输出验证结果。
- 如果遇到 Git 卡住、网络失败、权限失败或远端冲突，停止并回报，不要强行 reset、pull、push 或覆盖。
