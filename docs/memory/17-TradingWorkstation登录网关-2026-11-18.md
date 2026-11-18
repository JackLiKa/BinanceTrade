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

## 2. 实现

### 2.1 认证服务
- `src/gridtrade/api/tw_auth.py`：`TwAuthStore`（`var/tw_auth.db`：users/pending/codes/sessions）、登录页/创建密码页 HTML。
- 路由（挂在现有面板 FastAPI 上，nginx 内网代理）：
  - `GET /__tw_auth/login`、`POST /__tw_auth/login`
  - `GET /__tw_auth/google/start` → Google（复用已注册的 `https://gt.jacklika.com/api/auth/google/callback`，无需新增 redirect URI）
  - `GET /__tw_auth/google/return`（一次性 code 换 tw_session）
  - `GET/POST /__tw_auth/set-password`
  - `GET /__tw_auth/check`（nginx auth_request，204/401）
  - `GET /__tw_auth/logout`
- Google 回调按 `purpose="tw"` 分支：
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

## 3. 已验证

- 未登录根路径/`/TradingWorkstation` → 302 登录页
- 登录页返回 200，包含 Gmail 按钮与账号密码表单
- Gmail start 302 到 Google，redirect_uri 为已注册的 gt 回调
- 用临时账号密码验证：POST 登录设置 `tw_session` → `/__tw_auth/check` 204 → `/TradingWorkstation` 200；验证后已删除测试账号
- nginx `nginx -t` 通过；无回环/worker 耗尽

## 4. 注意

- “grafana”若指真实的 Grafana 服务（3000 端口），本次没有改 Grafana 自身登录；需要单独配置 Google OAuth/白名单，或让 Grafana 走同一套反代鉴权。
- 首次 Gmail 登录需 Google OAuth 同意屏幕允许这些账号；测试模式加 Test users。
- 登录页和认证服务均只走 HTTPS；不允许 HTTP。
