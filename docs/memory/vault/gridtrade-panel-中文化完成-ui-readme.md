---
title: Gridtrade Panel 中文化完成（UI + README）
tags:
  - gridtrade
  - i18n
  - frontend
  - readme
created: '2026-11-16T14:10:56+08:00'
---

# Gridtrade Panel 中文化完成（UI + README）

已完成 Gridtrade Panel 的简体中文化，覆盖 9 个页面、登录页、导航/命令面板、共享组件与图表，以及后端执行模式标签（MODES：研究/模拟/实盘）与任务消息（产物 N KiB、服务重启导致任务中断）。

关键约定：
- 技术缩写与交易所术语保留英文：Sharpe、Parquet、SQLite、bp、Maker/Taker、post-only、OHLC、httpOnly、listenKey，以及 BUY/SELL 等逻辑值仅在展示层映射。
- 展示层映射集中在各页面或 web/src/labels.ts：任务状态 queued 排队中/running 运行中/succeeded 已完成/failed 失败/canceled 已取消；订单状态 CANCELED 已撤销；审计动作经 auditLabel()；Quality 的 contract_type/underlying_type/session.type/session.market 已中文化；Positions 的 strategy_state 键已映射。
- 后端动态数据（run id、symbol、审计 detail、拒单明细）保持原样。
- 术语统一：walkforward=前向滚动，halted=已停止，bar_age=K 线延迟（分钟），审计 walkforward 入队=前向滚动入队。

验证：pnpm typecheck 通过；pnpm build 产出 index-f91rO3P2.js；pytest 53 passed；WebView（360×800 CSS，font_scale 1.3）九条路由 DOM 审计 scrollW=360/clientW=360/navBottom=710 且无横向溢出；docs/screens 全部截图已用中文界面重拍。

README.md 为中文，英文版保留在 README.en.md。
