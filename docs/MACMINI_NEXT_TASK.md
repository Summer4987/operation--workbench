# Mac mini 下一步任务

## 当前状态：待命

当前没有新的生产变更任务需要执行。

这个文件是 MacBook 侧 Codex 给 Mac mini 生产线程的固定任务入口。以后有新任务时，MacBook 侧会更新本文件并推送到 GitHub；Mac mini 只需要拉取 clean 仓库后读取本文件。

## Mac mini 固定读取方式

在 Mac mini 生产线程里，可以固定执行：

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
cat docs/MACMINI_NEXT_TASK.md
```

## 当前可做的只读检查

如果需要确认收件箱机制正常，可以只做下面的只读检查：

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git status --short --branch
test -f docs/MACMINI_TASK_INBOX.md && echo "任务收件箱说明存在"
test -f docs/MACMINI_NEXT_TASK.md && echo "下一步任务文件存在"
```

## 禁止事项

当前待命状态下：

- 不要修改 `/Users/summer/Documents/New project`。
- 不要触碰已有定时任务。
- 不要运行余额巡检、日报采集、预算执行或云端发布。
- 不要提交或推送。
- 不要重复执行历史任务。

## 等待下一次任务

当 MacBook 侧完成新代码或规则调整后，会把明确任务写入本文件。届时再按本文件的新内容执行。
