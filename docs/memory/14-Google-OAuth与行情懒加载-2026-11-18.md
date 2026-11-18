# 14 Google OAuth 登录与行情页懒加载（2026-11-18）

> **用途**：记录 2026-11-18 新增的 Google OAuth 登录、后台账号白名单、行情页黑屏根因与懒加载改造。
> **读者**：要登录/配置 Google 账号、排查行情页、重打 APK 的人。
> **最后核实**：2026-11-18 · 代码基线 `main`（提交见文末）
> **相关文档**：[03 接口](03-接口参考.md) · [04 配置](04-配置与数据存储.md) · [06 前端与APK](06-前端与APK.md) · [07 部署](07-部署与运维.md) · [08 测试](08-测试与验收.md)

## 1. 行情页黑屏：根因与修复

**现象**：手机 WebView 点“行情”（`#/market`）后整页黑屏；每次必现。

**根因（已定位）**：后端 `/api/market/funding` 在“东京节点行情代理”路径下只返回
`{symbol,count,funding,source}`，**漏了 `summary`**；前端 `Market.tsx` 直接读
`funding.data.summary.mean_rate`，抛 `TypeError: Cannot read properties of undefined (reading 'mean_rate')`，
React 卸载整棵树，页面变黑。和“一次拉的数据太多”关系不大——180/500 根 K 线本身很小。

**修复**：
- 后端 `service.market_funding()` 节点路径补齐 `summary`（mean/median/positive_pct/annualized/last/interval）。
- 前端 `api.funding()` 对缺失 `summary` 做兜底计算，避免旧节点再次触发白屏。
- `App.tsx` 每个路由包 `ErrorBoundary`：单页渲染异常显示错误卡片，不再整页黑屏。

**懒加载（按“视觉优先”改造）**：
- `Market.tsx` 首屏只请求 180 根 K 线（原 500），底部提供“加载更多”每次 +180，最多 500。
- 资金费率历史 + 套息快照在页面下方：用 `useInView` 滚动接近时才请求/渲染（原一次请求 240 条）。
- K 线/资金费图表用 `useDeferredMount` 延后到首帧之后挂载，先出统计卡片。
- 新增 hooks：`useInView`、`useDeferredMount`；新增 `components/ErrorBoundary.tsx`。
- **真机验证（2026-11-18 10:40）**：APK v0.3.0 卸载旧签名版本后安装；登录页正常、令牌登录后 `#/market` 渲染 180 根 K 线/14 canvas、0 console 异常、0 异常，黑屏不再复现。

## 2. Google OAuth 登录

### 2.1 为什么用 Device Flow
当前线上是 **HTTP**（`http://81.71.71.131:8000`），Google 不接受非 HTTPS 的 OAuth redirect URI；
所以采用 **OAuth 2.0 Device Authorization Grant**（Google Cloud OAuth 客户端类型：**TVs and Limited Input devices**）：
- 网页/APK 只展示 `user_code`，用户在任意设备的浏览器打开 <https://www.google.com/device> 输入；
- 后端轮询 Google token 端点，拿到 access token 后读 userinfo；
- 校验 `email_verified=true` 且邮箱在 `/admin` 白名单后，建立 **30 天面板会话 Cookie**。
以后上 HTTPS 可再加标准 redirect 登录；Device Flow 可保留为备用。

### 2.2 关键代码
| 层 | 文件 | 作用 |
| --- | --- | --- |
| 后端 | `src/gridtrade/api/google_auth.py` | `GoogleAuthStore`（auth.db：配置/白名单/会话）、`GoogleDeviceFlow`（device code/token/userinfo） |
| 路由 | `src/gridtrade/api/app.py` | `/api/auth/providers`、`/api/auth/google/start`、`/api/auth/google/poll`；`/api/auth/logout` 撤销会话；`require_token` 同时接受静态令牌与 Google 会话 |
| 管理端 | 同上 | `GET/POST /api/admin/google*`：Client ID/Secret、启停、允许邮箱增删 |
| 前端 | `web/src/pages/Login.tsx`、`api.ts`、`store.tsx` | Google 登录按钮、code 展示、轮询、cookie 会话恢复；令牌登录保留为备用 |
| 后台 UI | `web/public/admin/index.html` | “Google 登录”卡片：凭据、启停、允许账号列表 |
| APK | `MainActivity.java` | 外链（Google 授权页）交给系统浏览器；`CookieManager.flush()` 持久化会话；APK v0.3.0 不再内嵌令牌 |

### 2.3 数据与配置
- 数据库：`var/auth.db`（0600，SQLite）
  - `google_settings(client_id, client_secret, enabled)`
  - `google_users(email, name, added_at, added_by, active)`
  - `google_sessions(token, email, created_at, expires_at)`
- 新增环境变量（`.env`，需重启）：
  - `GRIDTRADE_GOOGLE_RELAY`：东京 Google 中继地址（如 `http://10.66.0.2:8101`）
  - `GRIDTRADE_GOOGLE_RELAY_TOKEN`：中继共享头 `X-Relay-Token`（可选，建议设置）
- 删除白名单账号会同时删除其 Google 会话；静态面板令牌不受影响。

### 2.4 广州 → Google 的网络问题（部署前提）
实测广州服务器 **无法直连 Google**（`oauth2.googleapis.com` 8s 超时），但东京节点可以。
因此新增：
- `scripts/tokyo_google_relay.py`：只转发 3 个固定 Google 端点（`/device/code`、`/token`、`/userinfo`），
  监听 WireGuard `10.66.0.2:8101`，不是通用代理。
- 面板配置 `GRIDTRADE_GOOGLE_RELAY` 指向它；未配置时仍会尝试直连 Google（仅本地/可直连环境可用）。

东京节点部署（Lightsail 浏览器 SSH / 你的 SSH）：
```bash
sudo mkdir -p /opt/gridtrade/scripts
sudo curl -fsSL https://raw.githubusercontent.com/JackLiKa/BinanceTrade/main/scripts/tokyo_google_relay.py \
  -o /opt/gridtrade/scripts/tokyo_google_relay.py
sudo tee /etc/systemd/system/gridtrade-google-relay.service >/dev/null <<'UNIT'
[Unit]
Description=Gridtrade Google OAuth relay
After=network-online.target wg-quick@wg0.service
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/gridtrade/scripts/tokyo_google_relay.py
Environment=RELAY_BIND=10.66.0.2
Environment=RELAY_PORT=8101
Environment=RELAY_TOKEN=请替换为随机串
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now gridtrade-google-relay
curl -s http://10.66.0.2:8101/healthz
```
广州 `.env`：
```
GRIDTRADE_GOOGLE_RELAY=http://10.66.0.2:8101
GRIDTRADE_GOOGLE_RELAY_TOKEN=请替换为随机串
```
重启 gridtrade。

### 2.5 Google Cloud 配置步骤
1. <https://console.cloud.google.com/> 建项目 → APIs & Services → OAuth consent screen（External）。
2. Credentials → Create credentials → OAuth client ID → 类型选 **TVs and Limited Input devices**。
3. 复制 **Client ID / Client Secret**。
4. `/admin` → Google 登录：填入并启用，保存。
5. `/admin` → Google 登录：添加允许的 Google 邮箱（精确匹配）。
6. 若 OAuth consent screen 仍是 **Testing**，必须把允许账号加入 **Test users**（否则 Google 会拒绝）。
7. 手机/电脑打开面板 → “使用 Google 账号登录” → 在 Google 页面输入 code。

### 2.6 APK v0.3.0
- `apk/build.sh` 默认 `VERSION_CODE=4 / VERSION_NAME=0.3.0`；manifest 同步。
- **不再内嵌面板令牌**（`apk/.env` 的 `TOKEN=` 留空），首次打开显示 Google 登录页；令牌登录仍可在“使用访问令牌登录”里使用。
- `MainActivity` 新增 `onCreateWindow`：`target=_blank` 的 Google 授权页交给系统浏览器；
  `onPause` 调用 `CookieManager.flush()`，Google 会话跨重启保留。
- 重打：`./apk/build.sh`；签名不变，覆盖安装。

## 3. 测试与验证

- pytest：**159 项**（新增 `tests/test_google_auth.py` 5 项；其余为原有）。
- 无头 Chrome（393×851 移动视口）验证 `#/market`：0 console 异常、0 loading、14 canvas、资金费文本。
- 本地模拟 Google（device flow）端到端：登录页 → 显示 code → 轮询 → 设置 cookie → 进入 `#/overview`；0 异常。
- 生产 Google 登录需完成 §2.4 中继 + §2.5 Client 凭据后才能验收。

## 4. 待办 / 风险
- [ ] 部署东京 Google relay（需要东京节点 SSH 或你在 Lightsail 浏览器 SSH 执行）。
- [ ] 创建 Google OAuth Client（TV devices）并填入 `/admin`。
- [ ] 添加允许登录的 Google 邮箱；Testing 模式记得加 Test users。
- [x] 真机复测 `#/market`：已通过（2026-11-18 10:40，APK v0.3.0）。
- [ ] 上 HTTPS 后可改为标准 redirect 登录，Device Flow 保留备用。
- [ ] `var/auth.db` 纳入备份；删除它等于清空 Google 白名单/会话（不会动面板令牌）。
