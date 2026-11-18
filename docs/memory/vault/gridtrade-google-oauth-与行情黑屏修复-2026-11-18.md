---
title: gridtrade Google OAuth 与行情黑屏修复（2026-11-18）
tags:
  - gridtrade
  - google-oauth
  - device-flow
  - market
  - apk
  - lazy-loading
verified: true
created: '2026-11-18T10:41:38+08:00'
---

# Google OAuth Device Flow + 行情页黑屏修复（2026-11-18）

**结论：面板/APK 已改为 Google 账号登录（Device Flow）并支持 `/admin` 白名单；行情页黑屏根因是节点 `/api/market/funding` 漏 `summary`，不是数据量过大；已修复并做懒加载，真机 APK v0.3.0 复测通过。**

## 行情页黑屏

- 根因：广州面板走东京节点取资金费时，后端只返回 `{symbol,count,funding,source}` 缺 `summary`；前端 `Market.tsx` 直接读 `funding.data.summary.mean_rate` → TypeError → React 整树卸载 → 黑屏。
- 修复：`service.market_funding()` 节点路径补 summary（mean/median/positive_pct/annualized/last/8h）；`api.funding()` 对缺失 summary 做兜底；`App.tsx` 每路由包 `ErrorBoundary`。
- 懒加载：`Market` 首屏 180 根 K 线 + “加载更多”（最多 500）；资金费历史/套息快照用 `useInView` 进入视口才请求/渲染；图表 `useDeferredMount` 延后挂载。
- 验证：真机 APK v0.3.0（OnePlus PJA110）`#/market` 180 根 K 线、14 canvas、0 console 异常；无头 Chrome 同结果。

## Google OAuth（Device Flow）

- 背景：面板是 HTTP，Google 不接受非 HTTPS redirect URI；广州服务器又访问不到 Google（oauth2.googleapis.com 超时）。
- 实现：
  - `src/gridtrade/api/google_auth.py`：`GoogleAuthStore`（`var/auth.db`：google_settings/google_users/google_sessions）、`GoogleDeviceFlow`（device code/token/userinfo）。
  - 路由：`GET /api/auth/providers`、`POST /api/auth/google/start|poll`；`/api/auth/logout` 撤销会话；`require_token` 同时接受静态令牌与 Google 30 天会话 Cookie。
  - `/admin` 新增 Google 卡片：Client ID/Secret、启停、允许邮箱增删；接口 `/api/admin/google*`。
  - 登录页 Google 按钮 + code 展示/轮询；令牌登录折叠为备用；`AppProvider` 启动总是请求 `/api/session`（Cookie 会话无 localStorage 令牌）。
  - APK v0.3.0（versionCode 4）：默认不内嵌令牌，打开 web 登录页；`onCreateWindow` 把 Google 授权页交系统浏览器；`onPause` flush Cookie。
- 网络前提：广州无法连 Google，东京节点需部署 `scripts/tokyo_google_relay.py`（监听 `10.66.0.2:8101`，固定转发 device/token/userinfo），面板设 `GRIDTRADE_GOOGLE_RELAY=http://10.66.0.2:8101` + `GRIDTRADE_GOOGLE_RELAY_TOKEN`。
- Google Cloud：OAuth client 类型必须为 **TVs and Limited Input devices**；Testing 模式需把允许邮箱加 Test users。
- 验证：本地 mock Google 端到端：登录页→code→轮询→Cookie 会话→总览，0 异常；真实 Google 端到端待东京 relay 与 Client 凭据。

## 其他

- 测试：`pytest` 159 项（新增 `tests/test_google_auth.py` 5 项）。
- APK 签名：repo 里旧 v0.2.1 与本机 keystore 不一致，真机已卸载旧版后安装 v0.3.0；后续覆盖更新必须用同一 keystore，否则需卸载。
- 文档：新增 `docs/memory/14-Google-OAuth与行情懒加载-2026-11-18.md`，更新 README/索引/测试/部署/配置/时间线。
- 待办：东京 relay 部署、Google OAuth Client 凭据、把允许邮箱录入 /admin；上 HTTPS 后可加标准 redirect 登录。
