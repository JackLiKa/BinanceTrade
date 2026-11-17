---
title: gridtrade 手机首屏性能定位与修复（2026-11-17）
tags:
  - gridtrade
  - performance
  - android
  - webview
  - binance
  - incident
verified: true
created: '2026-11-17T14:56:57+08:00'
---

# 手机首屏加载不出来：性能定位与修复（2026-11-17）

**重点：不是服务器或 APK 扛不住。根因是 `/api/market/snapshot` 每次请求都尝试访问被墙的 Binance，连接超时把 `/api/overview` 拖到 19–21 秒；手机首屏因此像“加载不出来”。修复后服务器 overview 0.09–0.14s，手机 DOM 加载 0.28s、总览请求 148ms。**

## 证据

- 手机（OnePlus PJA110/Android 16）网络：仅蜂窝 LTE，`ping 81.71.71.131` 35–47ms，手机 `curl /api/health` 200、99ms，说明网络可达。
- 手机 WebView DOM 已 `complete`，`load` 1.2s，JS 已执行（14 canvas 渲染），但 `performance` 里 `overview?symbol=GOOGLUSDT` 耗时 **27–39s**。
- 服务器本地测量：`/api/market/snapshot` 19.7–21.0s，`/api/dataset/quality` 0.08–0.10s，`/api/overview` 20.8–24.0s，`/api/paper` 0.002s。
- 服务器资源：load 0.01–0.5，服务内存 233–258MB（上限 1.8G），`memory.events oom_kill=0`，`NRestarts=0`，磁盘剩 5.6GB。排除内存/CPU/重启。

## 根因

`LiveMarket._fetch` 访问 `fapi.binance.com`（服务器出口被墙），httpx 超时 5s/connect 3s；失败不缓存，`/api/overview` 每次都同步等待；且多个页面/轮询请求会重复触发，对手机表现为长时间白屏/骨架。

## 修复

1. 新增 `GRIDTRADE_MARKET_LIVE`（默认 1）；服务器 `.env` 设 `0`，直接返回 `source=offline`，由 `service.market_snapshot` 回退数据集。
2. `LiveMarket` 失败缓存 60s，避免每个请求重复等超时。
3. 超时缩短为总 3s / connect 1.5s。
4. 静态资源加 `GZipMiddleware`：JS 595KB → 177KB（手机缓存后传输 0）。
5. 服务器重启后 overview 0.09–0.14s。

## 性能基线

服务器：overview 0.09–0.14s；paper 0.002s；service 233MB；load <0.6；无 OOM/重启。
APK/手机：DOM load 0.285s；session 52ms；overview 148ms；JS 595KB（177KB gzip）；PSS 116MB（Graphics 65MB，14 canvas）；Total frames 1129，Janky 1.59%，50th 8ms/90th 10ms/99th 20ms；JS heap 10MB。
结论：APK 与 WebView 性能正常，问题在服务端外网阻塞。

## 建议

- 若需要 Binance 实时行情，先解决服务器出口（代理/中转），再开 `GRIDTRADE_MARKET_LIVE=1`。
- 首屏可继续优化：概览图表按需渲染、接口合并（overview/snapshot 重复）、静态资源 CDN；目前非必要。
- 手机若仍看到旧页面，强制刷新/重装 APK 以清 WebView 缓存。
