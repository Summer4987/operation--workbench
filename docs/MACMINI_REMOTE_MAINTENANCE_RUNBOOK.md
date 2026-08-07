# Mac mini 出门远程维护手册

## 当前远程入口

Mac mini 同时保留两个 SSH 入口：

- 局域网入口：`ssh macmini-local`
- 出门远程入口：`ssh macmini-remote`

`macmini-remote` 的链路是：

```text
MacBook -> 云服务器 139.155.148.169 -> 127.0.0.1:22022 -> Mac mini SSH
```

Mac mini 上的反向隧道由 launchd 保持常驻：

```text
com.summer.macmini.reverse-ssh-tunnel
```

## 出门前检查

在 MacBook 上运行：

```bash
/bin/zsh scripts/macmini_remote_health_check.zsh
```

最小验收项：

- `ssh macmini-remote` 能进入 Mac mini。
- 反向 SSH 隧道 `launchd：已加载`，`进程：运行中`。
- Mac mini `sleep = 0`。
- Chrome 正在运行；如果 CDP 9222 不可访问，远程修复浏览器自动化会受限。
- 生产仓库状态必须先读清楚；有未提交改动时不要强制拉取或覆盖。

## 我远程修复时的标准流程

1. 先运行远程体检：

   ```bash
   /bin/zsh scripts/macmini_remote_health_check.zsh --notify
   ```

2. 判断故障类型：

   - 代码/配置问题：在 MacBook 或干净临时仓库修复，测试后推 GitHub `main`。
   - 生产机部署问题：Mac mini 只从 GitHub `main` 拉取或用 clean checkout 接管，不能手动拷贝生产代码。
   - 登录态/验证码问题：我可以定位平台、页面和失败证据；如果需要短信、扫码或滑块真人验证，需要你配合。
   - 高风险动作：预算真实提交、出价、订货默认不执行，除非你明确说“执行”。

3. 部署前先看 Mac mini 工作区：

   ```bash
   ssh macmini-remote 'cd ~/Documents/operation-workbench-clean && git status --short --branch'
   ```

4. 如果生产仓库干净，再拉取检查：

   ```bash
   ssh macmini-remote 'cd ~/Documents/operation-workbench-clean && /bin/zsh scripts/macmini_pull_and_check.zsh --smoke'
   ```

5. 如果生产仓库有本地改动：

   - 不做 `git reset --hard`。
   - 先列出改动，判断是运行产物、有效代码，还是重复 ` 2` 文件。
   - 必要时使用 `scripts/macmini_takeover_clean_checkout.zsh` 准备干净接管仓库。

## 反向隧道维护

在 Mac mini 上刷新隧道：

```bash
/bin/zsh scripts/install_macmini_reverse_tunnel_launchd.zsh
```

查看状态：

```bash
launchctl print gui/$(id -u)/com.summer.macmini.reverse-ssh-tunnel
tail -80 ~/Library/Logs/macmini_reverse_ssh_tunnel.err.log
```

从 MacBook 验证：

```bash
ssh macmini-remote 'hostname && date'
```

## 仍然可能需要你处理的情况

- Mac mini 断电、关机、网络断开。
- 云服务器 SSH 不可用。
- 美团/饿了么要求手机验证码、扫码、滑块真人验证。
- macOS 弹出系统权限确认，且无法通过 SSH 授权。
- 向日葵或屏幕共享需要你在本机确认连接。

## 常用命令

```bash
# 远程体检
/bin/zsh scripts/macmini_remote_health_check.zsh

# 远程进入生产机
ssh macmini-remote

# 查看今日任务
ssh macmini-remote 'cd ~/Documents/operation-workbench-clean && python3 scripts/hermes_schedule_status.py --period today'

# 查看生产 launchd
ssh macmini-remote 'launchctl list | grep com.summer.operation'

# 查看 Chrome/CDP
ssh macmini-remote 'curl -sS http://127.0.0.1:9222/json/version'
```
