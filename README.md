# Gridtrade Panel

面向 `gridtrade` 引擎的单用户量化面板：FastAPI 后端（SQLite 持久化 + 后台研究队列），
以及一套同时服务两种外壳的 React 单页应用——浏览器（桌面侧边栏）与 WebView APK
（移动端底部导航）。

面板以研究与模拟为主，另提供 **Binance 账户/执行节点只读分析**。实盘下单能力尚未开放，默认锁死
（`GRIDTRADE_LIVE_TRADING=0`），需要显式配置凭据、确认风险并开启总开关后才会发送真实订单。

英文文档见 [README.en.md](README.en.md)。

![总览](docs/screens/01-overview.png)

## 包含什么

```
src/gridtrade/            引擎、策略、OMS、模拟撮合、研究运行器
src/gridtrade/api/        FastAPI 应用、配置、SQLite 存储、任务队列、行情推送
web/                      React 19 + Vite 6 + Tailwind 4 单页应用（hash 路由，12 个页面）
apk/                      无 Gradle 的 Android 构建：manifest、单个 Activity、build.sh
research/                 parquet 数据集、抓取脚本、回测辅助
tests/                    pytest 用例（领域、引擎、OMS、风控、模拟、策略）
docs/screens/             APK 验收截图（Pixel 6 模拟器）
```

## 环境要求

| 工具 | 版本 |
| --- | --- |
| Python | 3.12+ |
| Node | 22.x |
| pnpm | 10+ |
| Android SDK | build-tools 36.0.0、platform android-34、JDK 21（仅构建 APK 需要） |

## 启动

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

cd web && pnpm install && pnpm build && cd ..

.venv/bin/python -m gridtrade.api
# -> http://127.0.0.1:8000  （SPA 与 API 同源）
```

SPA 从 `web/dist` 提供。做前端开发时改用 Vite dev server（把 `/api`、`/ws` 代理到 8000）：

```bash
cd web && pnpm dev     # http://localhost:5173
.venv/bin/python -m gridtrade.api
```

### 在线实例

当前部署在 **https://gt.jacklika.com**（Cloudflare Tunnel + 广州服务器 systemd；公网 8000 已关闭）。
该实例目前是明文 HTTP，仅建议临时使用；公网长期使用应加 HTTPS 反向代理，详见
[docs/memory/07-部署与运维.md](docs/memory/07-部署与运维.md)。

### 登录

面板默认使用 **Google 账号登录**（标准 OAuth，Web 应用客户端）。点击后直接打开 Google 账号选择页，
授权后回到 `https://gt.jacklika.com` 并设置 30 天 `gt_token` httpOnly Cookie。
APK 通过系统浏览器完成同一流程，再用 `gridtrade://oauth` 深链回 App。设备流作为备用方案保留。

静态令牌仍是备用方式（登录页“使用访问令牌登录”）：令牌在服务器 `var/token`（权限 `0600`），
支持 `Authorization: Bearer <token>`、`X-API-Token: <token>` 与 `/api/auth/login` Cookie；
WebSocket 用 `?token=<token>`。

> Google 登录前提：广州服务器通过东京节点中继访问 Google（`GRIDTRADE_GOOGLE_RELAY`），
> `/admin` 已配置 TV（设备流）与 Web（账号选择页）两套客户端。详见
> [15](docs/memory/15-HTTPS与标准Google-OAuth-2026-11-18.md)。

### 配置

全部通过环境变量控制，默认只监听本机：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `GRIDTRADE_HOST` | `127.0.0.1` | 监听地址（局域网使用设 `0.0.0.0`） |
| `GRIDTRADE_PORT` | `8000` | HTTP 端口 |
| `GRIDTRADE_TOKEN` | 自动生成 | 覆盖令牌，不再读取 `var/token` |
| `GRIDTRADE_DATA` | `research/data` | Parquet 数据集目录 |
| `GRIDTRADE_VAR` | `var` | SQLite 数据库、令牌、任务产物 |
| `GRIDTRADE_WEB` | `web/dist` | 构建后的 SPA |
| `GRIDTRADE_SYMBOL` | `GOOGLUSDT` | 默认交易对 |
| `GRIDTRADE_AUTORUN` | `1` | 启动时把上一进程遗留的排队/运行中任务标记为失败 |
| `GRIDTRADE_MARKET_LIVE` | `1` | 是否访问 Binance 实时行情；服务器出网被墙时设 `0`，否则每请求会等待连接超时 |
| `GRIDTRADE_PROXY` | 空 | 访问 Binance 的代理（`http://host:port` 或 `socks5://host:port`），需能 CONNECT 到 443 |
| `GRIDTRADE_GOOGLE_RELAY` | 空 | 东京 Google OAuth 中继地址，如 `http://10.66.0.2:8101` |
| `GRIDTRADE_GOOGLE_RELAY_TOKEN` | 空 | 中继共享头 `X-Relay-Token` |
| `GRIDTRADE_PUBLIC_URL` | 空 | 公网 HTTPS 地址，用于 OAuth redirect URI，如 `https://gt.jacklika.com` |
| `GRIDTRADE_SECURE_COOKIE` | `0` | HTTPS 部署时设 `1`，Cookie 加 Secure |
| `GRIDTRADE_SECURE_COOKIE` | `0` | 为认证 Cookie 加 `Secure`（仅 HTTPS） |
| `GRIDTRADE_CORS_ORIGINS` | localhost:5173 | 逗号分隔的开发源 |

也可以把配置写在仓库根目录的 `.env`（已 gitignore，真实环境变量优先）：

```bash
cp .env.example .env
# 编辑 GRIDTRADE_TOKEN、GRIDTRADE_HOST、模拟盘参数等，然后重启服务
```

模拟盘相关变量：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `GRIDTRADE_PAPER_ENABLED` | `0` | 是否启用实时模拟盘 |
| `GRIDTRADE_PAPER_AUTOSTART` | `0` | 服务启动后自动开始/恢复模拟盘 |
| `GRIDTRADE_PAPER_SYMBOLS` | `SKHY_USDT,SPCX_USDT,GOOGL_USDT,AMGN_USDT` | Binance USDT 永续代码（下划线自动兼容成 `GOOGLUSDT`） |
| `GRIDTRADE_PAPER_CAPITAL` | `10000` | 纸面本金（USDT） |
| `GRIDTRADE_PAPER_LEVERAGE` | `2` | 总名义 / 本金 |
| `GRIDTRADE_PAPER_SPACING_BP` | `60` | 网格间距（bp） |
| `GRIDTRADE_PAPER_LEVELS` | `20` | 单边最大格数 |
| `GRIDTRADE_PAPER_STOP_DD_PCT` | `10` | 回撤止损（0 关闭） |
| `GRIDTRADE_PAPER_MAKER_FEE_BP` | `2` | 挂单费率 |
| `GRIDTRADE_PAPER_TAKER_FEE_BP` | `5` | 吃单费率 |
| `GRIDTRADE_PAPER_POLL_SECONDS` | `3` | 行情轮询间隔 |

实盘/账户变量（2026-11-18 起 Gate Key 已全部移除，使用 Binance 东京执行节点）：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `GRIDTRADE_BINANCE_NODE_URL` | 空 | 东京执行节点 `http://10.66.0.2:8100`；`#/live`、`#/binance` 数据来源 |
| `GRIDTRADE_PAPER_SOURCE` | `binance` | 模拟盘公开行情：`binance`（经节点）或 `gate`（旧兼容） |
| `GRIDTRADE_PAPER_SYMBOLS` | 四个标的 | Binance 合约代码（下划线兼容） |
| `GRIDTRADE_ENV_FILE` | 自动 | 指定 `.env` 路径（工作目录不是部署根时使用） |

> Gate API Key/Secret 已从服务器 `.env` 和后台移除；Gate 私有实盘代码仅作历史保留，不再启用。

在 localhost 之外暴露面板：

- 局域网 / Tailscale：`GRIDTRADE_HOST=0.0.0.0`，然后访问 `http://<host>:8000`。
- 公网：放在 HTTPS 隧道或反向代理之后，并设置 `GRIDTRADE_SECURE_COOKIE=1`。
  只有私有网络才适合直接使用明文 HTTP。

## 页面

| 路由 | 内容 |
| --- | --- |
| `#/overview` | 最新回放权益与回撤、前向滚动月度结果、执行模式、数据源、最近任务 |
| `#/market` | 带成交标记的 K 线、资金费率历史、套息汇总 |
| `#/strategy` | 网格参数、参数校验、价格区间/敞口/止损风险的实时预览 |
| `#/backtest` | 回放 / 前向滚动 / 参数扫描、月度归因、订单流、权益与回撤 |
| `#/paper` | 实时组合模拟盘：多标的共享保证金、网格纸面成交、手续费/资金费、组合权益与持仓 |
| `#/live` | 实盘账户（Binance）：余额/持仓/挂单/**交割单**、历史订单；只读 |
| `#/binance` | Binance 东京执行节点（只读）：健康/账户/持仓/挂单/成交/告警 |
| `#/orders` | 任务选择、订单/成交表、拒单原因、期末挂单 |
| `#/positions` | 模拟持仓、网格状态、分层库存 |
| `#/risk` | 派生限额、回撤保护、紧急停止、拒单计数 |
| `#/quality` | K 线覆盖、缺口、时间戳单调性、交易规则元数据 |
| `#/settings` | 服务器地址、令牌、执行模式、紧急停止、存储路径、审计日志 |

导航是响应式的：`lg` 及以上为侧边栏，以下为底部导航栏加“更多”抽屉。
布局已在 390×844 CSS 与真机 WebView 下验证，所有路由均无横向溢出
（`document.scrollWidth == clientWidth`）。

## API

除 `/api/health` 与 `/api/auth/login` 外，所有 `/api/*` 路由都需要令牌。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 免鉴权存活探针 |
| POST | `/api/auth/login` | `{token}` -> 设置 `gt_token` Cookie |
| POST | `/api/auth/logout` | 清除 Cookie |
| GET | `/api/session` | 当前鉴权状态与服务端信息 |
| GET | `/api/dataset/symbols` | 数据集中存在的交易对 |
| GET | `/api/dataset/quality` | 覆盖率、缺口、结构校验 |
| GET | `/api/market/snapshot` | 标记/指数/最新价、24h 区间与成交量、资金费率（公共 REST，失败时标记 `offline`） |
| GET | `/api/market/candles` | 降采样 OHLCV，用于图表 |
| GET | `/api/market/funding` | 资金费率历史 |
| GET | `/api/overview` | 首页聚合卡片 |
| GET | `/api/runs` | 任务历史 |
| GET | `/api/runs/{id}` | 状态、进度、摘要 |
| GET | `/api/runs/{id}/artifact` | 成交、订单、权益曲线、月度行 |
| POST | `/api/runs/{id}/cancel` | 协作式取消 |
| POST | `/api/runs/replay` | 202 + 排队中的回放 |
| POST | `/api/runs/walkforward` | 202 + 排队中的前向滚动 |
| POST | `/api/runs/sweep` | 202 + 排队中的参数扫描（组合数 ≤ 48） |
| GET | `/api/risk` | 限额、回撤状态、紧急停止 |
| POST | `/api/settings/kill-switch` | 触发/解除紧急停止 |
| GET | `/api/settings` | 服务端设置 |
| GET | `/api/audit` | 审计日志 |
| WS | `/ws?token=` | 每 3 秒推送一条行情快照（`type=market`）；**不含任务状态**，任务状态由前端轮询 `/api/runs/{id}` |

交互式文档：`http://127.0.0.1:8000/api/docs`（Swagger UI）；OpenAPI schema 在 `/api/openapi.json`。
注意 `/docs` 不是有效路径，它会落入 SPA 兜底返回 `index.html`。

## 研究数据

面板读取币安 USDⓈ-M 永续合约的分钟级 parquet 文件（`<SYMBOL>_1m.parquet`、
`<SYMBOL>_funding.parquet`、`<SYMBOL>_meta.json`）。当前内置
`GOOGLUSDT / SKHYUSDT / SPCXUSDT / AMGNUSDT` 四个数据集；数据集存在几个，页面顶部的
交易对下拉就有几个。新增/刷新某个合约：

```bash
.venv/bin/python research/fetch.py --symbol SKHYUSDT
```

抓取需要能访问 `fapi.binance.com`（服务器出口被墙，通常在本地抓好后上传
`research/data/`）。切换交易对后，总览、行情、策略、回测、订单、持仓、风控、数据质量
都会使用所选合约；选择记忆在 `localStorage['gridtrade.symbol']`。

任务在两个工作线程上运行，进度写入 SQLite，可在分块之间取消。对于固定的数据集与
参数组合，回放结果是确定性的。

## Android APK

APK 不使用 Gradle 构建：`aapt2 -> javac (release 17) -> d8 -> zip -> zipalign -> apksigner`。

```bash
./apk/build.sh                    # -> apk/gridtrade.apk
adb install -r apk/gridtrade.apk
```

部分 OPPO/OnePlus 机型会在 `adb install` 时卡在安装引导，可改用
`pm install-create` / `pm install-write` / `pm install-commit` 分段安装。

**APK v0.3.1 默认 Google 登录**：构建时读取 `apk/.env`（gitignore）写入服务器地址；
`TOKEN` 留空时首次启动显示登录页。点击 Google 会打开系统浏览器完成标准 OAuth，授权后通过
`gridtrade://oauth?code=...` 深链回 App，App 用一次性 code 换取 WebView Cookie。

```bash
cp apk/.env.example apk/.env
# SERVER_URL=https://gt.jacklika.com
# TOKEN=            # 留空 => 显示 Google 登录页；填令牌 => 自动登录（备用）
./apk/build.sh
```

注意：

- 不再默认内嵌令牌；如需自动登录可把 `TOKEN` 填回 `apk/.env` 再构建。
- 令牌一旦编译进 APK，只应安装在自己的设备上；令牌轮换后需要重新构建。
- `minSdk 26`、`target 34`，允许明文 HTTP 以便局域网/公网 IP 访问。
- 只改 Web UI 不需要重建 APK：Activity 从服务端加载 `web/dist`。只有 Java、
  manifest、资源或 `apk/.env` 变更才需要重建 APK。

- `apk/gridtrade.jks` 是本地生成的密钥库（口令 `gridtrade`），仅用于侧载——
  分发前请用自己的密钥重新签名。

验收截图（模拟器，`font_scale 1.3`，density 480）：

| | |
| --- | --- |
| ![更多抽屉](docs/screens/02-more.png) | ![回测](docs/screens/04-backtest.png) |
| ![月度归因](docs/screens/04e-monthly.png) | ![风控](docs/screens/07-risk.png) |

## 管理后台

独立后台地址：**https://gt.jacklika.com/admin**（优先 Google 登录，管理员密码备用）。

- 默认账号/密码：`admin / admin`（首次登录后请立即在“安全”里修改）；Google 账号需标记“后台”才能进。
- 功能：概览、模拟盘标的与参数、Google 登录、安全、审计日志；**Gate Key 配置已移除**。
- **Google 登录**：配置 OAuth Client ID/Secret、启停、维护允许登录的 Google 邮箱；数据存 `var/auth.db`。
- **后台 Google 登录**：登录页同样支持 Google OAuth（带官方 G 图标）；账号需在 Google 页被标记为“后台”才可进入，管理员密码保留为备用。
- **菜单式布局**：左侧切换概览 / 实盘配置 / 模拟盘 / Google 登录 / 安全 / 审计日志；移动端为顶部横向菜单。
- **APK 专用导航**：首页行情；底部首页/实盘/模拟盘/Binance/数据；左上设置；右上“其他信息”面板。
- 凭据写服务器 `.env`；管理员密码以 PBKDF2 哈希存在 `var/admin.db`，不在 `.env` 中。
- **安全提示**：后台走 HTTP 时密码是明文传输，建议尽快配 HTTPS；默认密码务必修改。

## 开发交接与记忆文档

换一台电脑继续开发时，先读 [docs/memory/README.md](docs/memory/README.md)。其中包含：

- [01 项目总览](docs/memory/01-项目总览.md)
- [02 后端架构与领域模型](docs/memory/02-后端架构与领域模型.md)
- [03 接口参考](docs/memory/03-接口参考.md)
- [04 配置与数据存储](docs/memory/04-配置与数据存储.md)
- [05 模拟盘与实盘接入](docs/memory/05-模拟盘与实盘接入.md)
- [06 前端与APK](docs/memory/06-前端与APK.md)
- [07 部署与运维](docs/memory/07-部署与运维.md)
- [08 测试与验收](docs/memory/08-测试与验收.md)（桌面 Web 与真机 APK 的可复现步骤）
- [14 Google OAuth 与行情懒加载](docs/memory/14-Google-OAuth与行情懒加载-2026-11-18.md)
- [15 HTTPS 域名与标准 Google OAuth](docs/memory/15-HTTPS与标准Google-OAuth-2026-11-18.md)
- [16 移除 Gate 凭据与 Binance-only](docs/memory/16-移除Gate凭据与Binance-only-2026-11-18.md)
- [17 TradingWorkstation 登录网关](docs/memory/17-TradingWorkstation登录网关-2026-11-18.md)
- [18 Binance 式爆仓引擎](docs/memory/18-Binance式爆仓引擎-2026-11-18.md)
- [09 策略研究结论](docs/memory/09-策略研究结论.md)（**改策略前必读**）
- [10 问题与决策记录](docs/memory/10-问题与决策记录.md)
- [11 外部接口清单](docs/memory/11-外部接口清单.md)
- [12 待办与路线图](docs/memory/12-待办与路线图.md)
- [13 历史归档](docs/memory/13-历史归档.md)
- [记忆库原始笔记索引](docs/memory/vault/README.md)

仓库不包含令牌（`var/token`）、行情数据（`research/data/`）、签名密钥（`apk/*.jks`）
与前端构建产物（`web/dist/`），恢复步骤见交接文档。

## 测试

```bash
.venv/bin/python -m pytest            # 175 项
cd web && pnpm typecheck              # tsc --noEmit
```

## 有意为之的边界

- **实盘只读。** `#/live` 和 `#/binance` 都读取东京 Binance 执行节点；面板没有写接口，真实下单
  仍需在节点上人工执行并满足三重锁。Gate API Key/Secret 已移除。
- 实时组合模拟盘使用 **Binance USDT 永续公开行情与资金费率**（经东京节点，无需 API Key），
  默认 `SKHY_USDT / SPCX_USDT / GOOGL_USDT / AMGN_USDT`，共享保证金池；成交、手续费、
  资金费与组合权益写入 `var/paper.db`。
- 所有外部接口见 [外部接口清单](docs/memory/11-外部接口清单.md)。
- 单用户、单进程。写入通过锁串行化；SQLite 使用 WAL 模式与短连接。
- 行情快照走币安公共 REST，失败时降级为 `source: "offline"`，而不是阻塞界面。
- 模拟成交使用分钟 K 线的最高/最低价；资金费率按记录的资金事件扣缴，
  因此月度归因包含资金费。
