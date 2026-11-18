# 15 HTTPS 域名与标准 Google OAuth（2026-11-18）

> **用途**：记录 `jacklika.com` 域名、Cloudflare Tunnel、HTTPS、标准 Google OAuth（Web/Admin/APK）的最终落地方式。
> **读者**：维护登录、域名、隧道、APK 的人。
> **最后核实**：2026-11-18 · 代码基线 `main`
> **相关文档**：[14 Google OAuth 与行情懒加载](14-Google-OAuth与行情懒加载-2026-11-18.md) · [07 部署](07-部署与运维.md) · [06 前端与APK](06-前端与APK.md) · [04 配置](04-配置与数据存储.md)

## 1. 域名与 HTTPS

- 域名：`jacklika.com`（Cloudflare Registrar，已 Active，自动续费）
- 公网入口：**https://gt.jacklika.com**（Cloudflare 代理 + 命名 Tunnel）
- 源站：广州服务器 `127.0.0.1:8000`（只监听回环，公网 8000 已关闭）
- 隧道：Cloudflare Zero Trust → Networks → Tunnels → `gridtrade`
  - Replica：`VM-0-15-ubuntu`，systemd `cloudflared.service`
  - Public Hostname：`gt.jacklika.com` → `http://127.0.0.1:8000`
  - DNS 自动创建 CNAME `gt.jacklika.com → <tunnel-id>.cfargotunnel.com`
- TLS：Cloudflare 边缘证书；源站不需要 443/证书，也不需要备案入口
- 服务器：
  - `GRIDTRADE_HOST=127.0.0.1`
  - `GRIDTRADE_SECURE_COOKIE=1`
  - `GRIDTRADE_PUBLIC_URL=https://gt.jacklika.com`
  - ufw 已删除 8000 放行；应急入口 `ssh -L 18000:127.0.0.1:8000 wmac@81.71.71.131`

> 注意：Cloudflare Tunnel 的 Token 存于服务器 `/etc/cloudflared`（root），不在仓库；轮换 Token 后需更新服务。
> `trycloudflare.com` 临时隧道已停用。

## 2. 标准 Google OAuth（账号选择页）

### 2.1 客户端

| 客户端 | 类型 | 用途 | 配置位置 |
| --- | --- | --- | --- |
| TV 客户端 | TVs and Limited Input devices | 设备流备用（APK/无 HTTPS 环境） | `var/auth.db` |
| Web 客户端 | Web application | 标准 OAuth，账号选择页 | `var/auth.db` |

Web 客户端重定向 URI：
```text
https://gt.jacklika.com/api/auth/google/callback
```
授权 JavaScript 来源：
```text
https://gt.jacklika.com
```

### 2.2 路由

| 路由 | 作用 |
| --- | --- |
| `GET /api/auth/google/web/start?next=&app=0\\|1` | 面板：302 到 Google 账号选择页；`app=1` 给 APK |
| `GET /api/admin/google/web/start?next=/admin` | 后台：302 到 Google 账号选择页 |
| `GET /api/auth/google/callback` | 换 token、读 userinfo、校验白名单/后台标记、设置 Cookie 或跳深链 |
| `POST /api/auth/google/exchange` | APK 用一次性 code 换 WebView Cookie |

- 面板 Cookie：`gt_token`，30 天，httpOnly，SameSite=Lax。
- 后台 Cookie：`gt_admin`，12h，httpOnly，SameSite=Strict；只有 `google_users.is_admin=1` 的邮箱可进。
- 回调错误会带 `?oauth_error=...` 回到登录页显示。
- Google token/userinfo 请求经东京中继 `GRIDTRADE_GOOGLE_RELAY`。

### 2.3 前端

- `Login.tsx`：浏览器点击 Google → `location.href = /api/auth/google/web/start`；账号选择页直接出现。
- `/admin` 登录页：同样标准 OAuth；菜单可在 `#/google` 配置 Web/TV 客户端与白名单。
- APK（`GridtradeShell` UA）：
  1. 点击 Google → `window.open('/api/auth/google/web/start?app=1')`
  2. MainActivity `onCreateWindow` 交给系统浏览器
  3. Google 授权后回调后端，后端生成一次性 code，302 到 `gridtrade://oauth?code=...`
  4. MainActivity 的 intent-filter 接收深链，加载 `https://gt.jacklika.com/?oauth_code=...`
  5. Web App 调 `/api/auth/google/exchange` 换 Cookie，进入面板

### 2.4 已验证（2026-11-18）

- `https://gt.jacklika.com/api/health`、`/`、`/admin` 均 200
- `GET /api/auth/google/web/start` 302 到 `accounts.google.com`，client_id/redirect_uri/scope/state 正确
- 手机 Chrome：账号选择页（040418jie@gmail.com）→ 授权 → 回 App → APK 已登录进入总览
- 手机 Chrome：`/admin` Google 登录 → 授权 → 后台概览（测试账号临时授予后台，验证后已撤回）
- 测试：`pytest` **162 项**

## 3. 当前状态

| 项 | 值 |
| --- | --- |
| 面板 | https://gt.jacklika.com |
| 后台 | https://gt.jacklika.com/admin |
| APK | v0.3.1，`SERVER_URL=https://gt.jacklika.com`，`TOKEN=` 空 |
| 8000 公网 | 已关闭 |
| 隧道 | `cloudflared.service`（命名隧道） |
| Google | TV + Web 客户端均已配置；白名单 3 人；后台 1 人 |
| 测试 | 162 项通过 |

## 4. 风险与待办

- [ ] 后台默认密码 `admin/admin` 仍未改；上 HTTPS 后风险降低，但建议尽快改。
- [ ] Google Client Secret 曾在聊天中出现，建议在 Google Cloud 重置 Web/TV Secret 并更新 `/admin`。
- [ ] 域名自动续费/到期提醒；Cloudflare Tunnel Token 轮换流程。
- [ ] Cloudflare Tunnel 依赖 Cloudflare；如被墙/故障，面板不可达，保留 SSH 隧道应急。
- [ ] 内地服务器 + 境外域名的合规风险仍在（技术上避开入口拦截，不等于法律免备案）；若要彻底规避，迁东京/香港。
- [ ] APK 仍允许旧“访问令牌登录”备用；令牌轮换后需重新构建。
