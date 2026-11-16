---
title: gridtrade Web/APK 真机测试结论与修复（2026-11-16）
tags:
  - gridtrade
  - testing
  - android-webview
  - bugfix
created: '2026-11-16T14:46:29+08:00'
---

# gridtrade Web/APK 真机测试结论与修复（2026-11-16）

## 测试范围
- Web UI 桌面端（headless Chrome CDP 9223）：9 个路由全部加载，回放/前向滚动/参数扫描提交与结果、取消、订单筛选搜索、持仓、风控 kill switch + 审计、数据质量重扫、设置保存/登出/错误令牌、390px 无横向溢出，⌘K 命令面板可搜索跳转、Esc 关闭。
- APK 真机（OnePlus PJA110, Android 16, 1240x2772, serial fe350b43）：底部 5 项导航 + 更多抽屉 9 页、行情周期、订单筛选搜索、持仓、风控开关、设置令牌/认证、结果页（业绩表现/月度归因/月度表/14 图）、前向滚动、参数扫描、原生中文设置页/错误页/菜单。

## 本次修复
1. MainActivity 原生字符串全部中文化；开启 `WebView.setWebContentsDebuggingEnabled(true)`。
2. 主题 NoActionBar 导致菜单不可达：删除 onCreateOptionsMenu/onOptionsItemSelected，改为 `onBackPressed`（有 WebView 历史则 goBack，否则弹原生菜单：重新加载/服务器与令牌/退出登录/退出应用）。
3. 切换历史任务时 artifact 409：`useArtifact(runId, run)` 要求 `run.id === runId && status === 'succeeded'`，避免旧任务的 succeeded 状态触发新 runId 请求。
4. 选中已取消任务仍显示上一份 artifact：useArtifact 在未就绪时返回 data=null（图表清零）。

## 已知限制
- APK 默认服务器 `http://10.0.2.2:8000` 仅适用于模拟器；真机需手填局域网地址或配合 `adb reverse tcp:8000 tcp:8000` 用 127.0.0.1。
- adb reverse 不随 USB 重连恢复。
- live K 线延迟约 123 分钟（数据源滞后，非前端问题）。
- OPPO/OnePlus 安装器在 `adb install` 时卡住，需 `pm install-create/write/commit`。
- WebView 内 uiautomator 无节点，需 CDP：`adb forward tcp:9333 localabstract:webview_devtools_remote_<pid>`。
