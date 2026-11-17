# Gridtrade Panel

面向 `gridtrade` 引擎的单用户量化面板：FastAPI 后端（SQLite 持久化 + 后台研究队列），
以及一套同时服务两种外壳的 React 单页应用——浏览器（桌面侧边栏）与 WebView APK
（移动端底部导航）。

面板以研究与模拟为主，另提供 **Gate 实盘账户只读分析**。实盘下单能力已经实现，但默认锁死
（`GRIDTRADE_LIVE_TRADING=0`），需要显式配置凭据、确认风险并开启总开关后才会发送真实订单。

英文文档见 [README.en.md](README.en.md)。

![总览](docs/screens/01-overview.png)

## 包含什么

```
src/gridtrade/            引擎、策略、OMS、模拟撮合、研究运行器
src/gridtrade/api/        FastAPI 应用、配置、SQLite 存储、任务队列、行情推送
web/                      React 19 + Vite 6 + Tailwind 4 单页应用（hash 路由，11 个页面）
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

当前部署在 `http://81.71.71.131:8000`（systemd 常驻，令牌在服务器的 `var/token`）。
该实例目前是明文 HTTP，仅建议临时使用；公网长期使用应加 HTTPS 反向代理，详见
[docs/memory/03-部署与运维手册.md](docs/memory/03-部署与运维手册.md)。

### 登录

首次启动会生成随机令牌写入 `var/token`（权限 `0600`）。把它粘贴到登录页，或用
`cat var/token` 查看。

令牌支持三种传递方式：`Authorization: Bearer <token>`、`X-API-Token: <token>`，以及
`/api/auth/login` 设置的 `gt_token` httpOnly Cookie。WebSocket 用 `?token=<token>`
认证，因为浏览器无法为握手设置请求头。

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
| `GRIDTRADE_PAPER_SYMBOLS` | `SKHY_USDT,SPCX_USDT,GOOGL_USDT,AMGN_USDT` | Gate USDT 永续合约（逗号分隔） |
| `GRIDTRADE_PAPER_CAPITAL` | `10000` | 纸面本金（USDT） |
| `GRIDTRADE_PAPER_LEVERAGE` | `2` | 总名义 / 本金 |
| `GRIDTRADE_PAPER_SPACING_BP` | `60` | 网格间距（bp） |
| `GRIDTRADE_PAPER_LEVELS` | `20` | 单边最大格数 |
| `GRIDTRADE_PAPER_STOP_DD_PCT` | `10` | 回撤止损（0 关闭） |
| `GRIDTRADE_PAPER_MAKER_FEE_BP` | `2` | 挂单费率 |
| `GRIDTRADE_PAPER_TAKER_FEE_BP` | `5` | 吃单费率 |
| `GRIDTRADE_PAPER_POLL_SECONDS` | `3` | 行情轮询间隔 |

实盘（Gate USDT 永续）变量，可在页面配置并写回服务器 `.env`：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `GRIDTRADE_LIVE_ENABLED` | `0` | 是否启用实盘账户同步/分析 |
| `GRIDTRADE_LIVE_TRADING` | `0` | **下单总开关**，默认关闭；开启后仍受风控上限约束 |
| `GATE_API_KEY` / `GATE_API_SECRET` | 空 | Gate API 凭据（只读 Key 只能分析） |
| `GRIDTRADE_LIVE_MAX_NOTIONAL` | `5000` | 总名义上限（USDT） |
| `GRIDTRADE_LIVE_MAX_ORDER_NOTIONAL` | `1000` | 单笔上限 |
| `GRIDTRADE_LIVE_MAX_POSITION_NOTIONAL` | `3000` | 单标的上限 |
| `GRIDTRADE_LIVE_MAX_OPEN_ORDERS` | `20` | 最大挂单数 |
| `GRIDTRADE_ENV_FILE` | 自动 | 指定 `.env` 路径（工作目录不是部署根时使用） |

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
| `#/live` | 实盘账户（Gate）：余额/持仓/挂单/成交/流水与实盘分析；下单默认锁定 |
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
| WS | `/ws?token=` | 每 3 秒推送行情快照与任务状态 |

交互式文档：`http://127.0.0.1:8000/docs`。

## 研究数据

面板读取币安 USDⓈ-M 永续合约的分钟级 parquet 文件
（`GOOGLUSDT_1m.parquet`、`GOOGLUSDT_funding.parquet`）。刷新方式：

```bash
.venv/bin/python research/fetch.py --symbol GOOGLUSDT
```

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

**APK 默认免登录**：构建时读取 `apk/.env`（gitignore），把服务器地址与令牌写入
`BuildConfig`，首次启动直接进入面板，不再显示登录页。

```bash
cp apk/.env.example apk/.env
# SERVER_URL=http://81.71.71.131:8000
# TOKEN=<服务端 var/token 或 .env 中的 GRIDTRADE_TOKEN>
./apk/build.sh
```

没有 `apk/.env` 时会回退到内置默认地址并要求手动填写服务器/令牌（首次安装或清除数据后）。
进入面板后，在页面历史尽头按返回键仍可打开“服务器与令牌”菜单。

注意：

- 令牌会被编译进 APK，只应安装在自己的设备上；令牌轮换后需要重新构建。
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

## 开发交接与记忆文档

换一台电脑继续开发时，先读 [docs/memory/README.md](docs/memory/README.md)。其中包含：

- [项目总览与架构](docs/memory/01-项目总览与架构.md)
- [开发进度与变更记录](docs/memory/02-开发进度与变更记录.md)
- [部署与运维手册](docs/memory/03-部署与运维手册.md)
- [测试手册](docs/memory/04-测试手册.md)（桌面 Web 与真机 APK 的可复现步骤）
- [问题与决策记录](docs/memory/05-问题与决策记录.md)
- [下一步与待办](docs/memory/06-下一步与待办.md)
- [外部接口清单与官方文档对照](docs/memory/07-外部接口清单与官方文档对照.md)
- [记忆库原始笔记](docs/memory/vault/)

仓库不包含令牌（`var/token`）、行情数据（`research/data/`）、签名密钥（`apk/*.jks`）
与前端构建产物（`web/dist/`），恢复步骤见交接文档。

## 测试

```bash
.venv/bin/python -m pytest            # 68 项
cd web && pnpm typecheck              # tsc --noEmit
```

## 有意为之的边界

- **实盘下单默认锁定。** `MODES` 启用 `research`、`paper` 与 `live`（Gate 只读分析）；
  下单总开关默认 0，未开启时所有下单/撤单请求返回 403。API 凭据只写入服务器 `.env`，
  页面只显示 Key 后四位，Secret 不回传。
- 实时组合模拟盘使用 Gate.io USDT 永续公开行情与资金费率（服务器可访问），默认
  `SKHY_USDT / SPCX_USDT / GOOGL_USDT / AMGN_USDT`，共享一个保证金池，成交、手续费
  （取自合约 `maker_fee_rate/taker_fee_rate`）、资金费与组合权益写入 `var/paper.db`。
- 实盘接入 Gate 私有只读接口做账户分析；下单代码完整但默认锁定（`GRIDTRADE_LIVE_TRADING=0`），
  未配置 Key 时不会发起任何私有写请求。所有外部接口见
  [外部接口清单](docs/memory/07-外部接口清单与官方文档对照.md)。
- 单用户、单进程。写入通过锁串行化；SQLite 使用 WAL 模式与短连接。
- 行情快照走币安公共 REST，失败时降级为 `source: "offline"`，而不是阻塞界面。
- 模拟成交使用分钟 K 线的最高/最低价；资金费率按记录的资金事件扣缴，
  因此月度归因包含资金费。
