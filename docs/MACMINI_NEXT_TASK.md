# Mac mini 下一步任务

## 当前任务：部署上午运营防重复锁

目的：让 09:30 正式上午运营任务和手动 `上午运营一键采集.command` 共用同一把锁，避免 10:22、10:36 这类重复启动再次发生。

GitHub main 目标提交：

```text
399f27c Prevent duplicate morning operations runs
```

## 执行范围

只允许从 clean 仓库同步下面两个文件到旧生产目录：

```text
morning-ops/run_morning_ops.py
morning-ops/上午运营一键采集.command
```

旧生产目录：

```text
/Users/summer/Documents/New project
```

clean 仓库：

```text
/Users/summer/Documents/operation-workbench-clean
```

## 必须遵守

- 不要运行上午运营任务。
- 不要运行日报、评价、余额巡检、预算提交或云端发布。
- 不要修改或重载任何 LaunchAgent。
- 不要修改 `/Users/summer/Library/Scripts/xiong-operation/run_morning_ops.zsh`。
- 不要提交、不要推送。
- 只同步上面列出的两个文件。

## 建议执行步骤

```zsh
cd "/Users/summer/Documents/operation-workbench-clean"
git pull --ff-only origin main
git log --oneline -3

cp "morning-ops/run_morning_ops.py" "/Users/summer/Documents/New project/morning-ops/run_morning_ops.py"
cp "morning-ops/上午运营一键采集.command" "/Users/summer/Documents/New project/morning-ops/上午运营一键采集.command"
chmod +x "/Users/summer/Documents/New project/morning-ops/上午运营一键采集.command"

cd "/Users/summer/Documents/New project"
python3 -m py_compile "morning-ops/run_morning_ops.py"
zsh -n "morning-ops/上午运营一键采集.command"
git diff -- morning-ops/run_morning_ops.py "morning-ops/上午运营一键采集.command"
```

## 回报内容

请输出：

1. clean 仓库 `git log --oneline -3`；
2. 两个文件是否已同步；
3. `py_compile` 和 `zsh -n` 是否通过；
4. 旧生产目录这两个文件的 `git diff`；
5. 确认没有运行上午运营任务、没有触碰定时任务、没有提交或推送。

## 预期效果

部署后，如果上午运营任务正在运行，再次手动点击或再次启动会输出“已有上午运营任务正在运行，本次不重复启动”，不会开启第二轮日报、余额、预算和发布流程。
