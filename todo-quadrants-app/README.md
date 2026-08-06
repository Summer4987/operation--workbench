# 待办四象限 App

一个原生 SwiftUI 待办小软件源码包，目标是 iPhone 和 Mac 共用一套数据，并支持 iPhone 桌面小组件。

## 功能

- 一个页面完成全部操作
- 顶部 2x2 四象限：重要且紧急、重要不紧急、紧急不重要、不紧急不重要
- 中间五个分类输入行：平台、直营门店、加盟业务、供应链、AI
- 输入时选择“重要 / 紧急”，添加后自动进入对应象限
- 底部已完成集合
- 每条待办都有方形勾选框
- SwiftData 本地存储 + 轻量云端 JSON 同步，用于 iPhone/Mac 互通
- WidgetKit 小组件读取 App Group 快照

## 当前同步方式

Debug 配置不依赖 iCloud，因为 Personal Team 不能启用 iCloud 能力。App 会访问：

```text
http://139.155.148.169/daily-order/api/todo-quadrants?token=xiongxiaoxiao-todo-sync
```

逻辑是：启动先拉云端数据；新增、完成、删除后推送整份待办；打开期间每 5 秒拉一次云端。Release 配置仍保留 iCloud/App Group entitlements，后续升级 Apple Developer Program 后可以切回 CloudKit。

## Xcode 使用

工程已经生成在 `TodoQuadrants.xcodeproj`。如果后续改了 `project.yml`，再安装 XcodeGen 重新生成：
   ```bash
   brew install xcodegen
   cd "/Users/summer/Documents/New project/todo-quadrants-app"
   xcodegen generate
   ```

打开工程：
   ```bash
   cd "/Users/summer/Documents/New project/todo-quadrants-app"
   open TodoQuadrants.xcodeproj
   ```

当前已配置 Team：`SHR23XM2U8`。标识如下：
   - App Bundle ID：`com.xiongxiaoxiao.todoquadrants`
   - Mac Bundle ID：`com.xiongxiaoxiao.todoquadrants.mac`
   - Widget Bundle ID：`com.xiongxiaoxiao.todoquadrants.widget`
   - App Group：`group.com.xiongxiaoxiao.todoquadrants`
   - iCloud Container：`iCloud.com.xiongxiaoxiao.todoquadrants`

## 文件结构

- `Shared/`：App 和 Widget 共用常量、快照模型
- `TodoQuadrantsApp/`：主 App、SwiftData 模型、界面、Widget 快照写入
- `TodoQuadrantsWidget/`：iPhone 桌面小组件
- `project.yml`：XcodeGen 工程配置

## 下一期建议

- 给每条待办加截止日期和备注
- Widget 支持锁屏小组件
- 分类颜色和四象限颜色可配置
- 完成项按日期折叠
- 支持从 Widget 快速打开新增页
