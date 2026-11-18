# 17 TradingWorkstation 登录网关（tw.jacklika.com）

> **用途**：记录为 TradingWorkstation 子域名增加账号密码 + Gmail 登录、首次登录创建密码、nginx 鉴权门禁。
> **最后核实**：2026-11-18 · 代码基线 `main`

## 1. 访问与登录

- 地址：**https://tw.jacklika.com**（自动跳到 `/TradingWorkstation`）
- 未登录访问 `/TradingWorkstation*` → 302 `/__tw_auth/login?next=...`
- 登录方式：
  1. **Gmail 登录**：仅允许
     - `040418jie@gmail.com`
     - `jacklika.business@gmail.com`
     其他邮箱会在回调时被拒绝。
  2. **账号密码**：首次必须先用 Gmail 登录，然后进入“创建登录密码”（至少 8 位，两次一致）；之后可用邮箱+密码登录。
- 会话 Cookie：`tw_session`，30 天，httpOnly，SameSite=Lax，Secure。
- 退出：`/__tw_auth/logout`。
- **修改密码**：`/__tw_auth/change-password`（登录后可用，所有用户均可改；未登录会先跳登录并回跳改密页）；TradingWorkstation 页面**右上角**注入“账户 · 修改密码 · 退出”悬浮入口；登录页也有“修改密码”链接。
- 其他路由：
  - `/admin` → `https://gt.jacklika.com/admin`（后台管理）
  - `/grafana` → `http://81.71.71.131:3000/`（Grafana）
  - `/account` → 修改密码页

## 2. 实现

### 2.1 认证服务
- `src/gridtrade/api/tw_auth.py`：`TwAuthStore`（`var/tw_auth.db`：users/pending/codes/sessions）、登录页/创建密码页 HTML。
- 路由（挂在现有面板 FastAPI 上，nginx 内网代理）：
  - `GET /__tw_auth/login`、`POST /__tw_auth/login`
  - `GET /__tw_auth/google/start` → Google（**独立 Web 客户端**，redirect URI `https://tw.jacklika.com/__tw_auth/google/callback`，不复用 gt）
  - `GET /__tw_auth/google/callback` → tw 域名回调，换 code/userinfo
  - `GET /__tw_auth/google/return`（一次性 code 换 tw_session）
  - `GET/POST /__tw_auth/set-password`
  - `GET /__tw_auth/check`（nginx auth_request，204/401）
  - `GET /__tw_auth/logout`
- Google 回调按 `purpose="tw"` 分支（新回调路径 `/__tw_auth/google/callback`）：
  - 邮箱不在白名单 → 回 tw 登录页报错
  - 没有密码 → 生成 15 分钟 pending token → `/__tw_auth/set-password`
  - 已有密码 → 生成一次性 code → `/__tw_auth/google/return` → 设置 tw_session

### 2.2 nginx
- 文件：`/etc/nginx/sites-available/zz-tw-auth.conf`（必须排在默认站之后，避免代理回环）
- `tw.jacklika.com` server：
  - `/__tw_auth/` → `127.0.0.1:8000`
  - `location /` → `auth_request /__tw_auth/check`，401 跳登录；通过后 `proxy_pass http://127.0.0.1:80`（Host localhost → 默认 TradingWorkstation 站）
- 服务器 `.env`：
  - `GRIDTRADE_TW_PUBLIC_URL=https://tw.jacklika.com`
  - `GRIDTRADE_TW_ALLOWED_EMAILS=040418jie@gmail.com,jacklika.business@gmail.com`
  - `GRIDTRADE_TW_GOOGLE_CLIENT_ID` / `GRIDTRADE_TW_GOOGLE_CLIENT_SECRET`（独立 Web 客户端）

## 3. 已验证

- 未登录根路径/`/TradingWorkstation` → 302 登录页
- 登录页返回 200，包含 Gmail 按钮与账号密码表单
- Gmail start 302 到 Google，redirect_uri 为 `https://tw.jacklika.com/__tw_auth/google/callback`
- 独立 Web 客户端未配置时，明确返回登录页错误，不回退到 gt 客户端
- 用临时账号密码验证：POST 登录设置 `tw_session` → `/__tw_auth/check` 204 → `/TradingWorkstation` 200
- 修改密码验证：旧密码登录失败、新密码登录成功；测试账号已删除
- `/admin` 302 到 gt 后台；`/grafana` 302 到 Grafana；`/account` 302 到修改密码页
- 受保护页面 HTML 注入账号悬浮入口（修改密码/退出）
- nginx `nginx -t` 通过；无回环/worker 耗尽

## 3.1 Service Worker 导致的 ERR_FAILED（已修复）

现象：加登录网关后，访问 `/TradingWorkstation/` 在 Chrome 显示 `ERR_FAILED`，但 `curl` 正常 302 到登录页。

原因：TradingWorkstation 旧版注册了 scope 为 `/TradingWorkstation/` 的 service worker，它拦截导航并返回旧/错误响应，登录网关的 302 被劫持。

修复：
- `/reset-sw` 公共页：注销所有 SW、清空 CacheStorage、跳回 `/TradingWorkstation`
- `/TradingWorkstation/sw.js` 返回“注销自身并清缓存”的脚本（`no-store`），浏览器更新 SW 后自动退出
- 登录页底部提供“页面打不开？清理旧缓存”入口
- 用户若仍报错，访问一次 `https://tw.jacklika.com/reset-sw` 即可恢复

## 4. 注意

- “grafana”若指真实的 Grafana 服务（3000 端口），本次没有改 Grafana 自身登录；需要单独配置 Google OAuth/白名单，或让 Grafana 走同一套反代鉴权。
- 首次 Gmail 登录需 Google OAuth 同意屏幕允许这些账号；测试模式加 Test users。
- 登录页和认证服务均只走 HTTPS；不允许 HTTP。
