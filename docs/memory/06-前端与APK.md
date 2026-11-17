# 06 前端与APK

> **用途**：记录 `web/` SPA 与 `apk/` WebView 壳的可复核事实——技术栈与脚本、12 条 hash 路由与导航、页面字段与交互、`api.ts` 全量接口、状态/hooks/格式化、组件与 E2E 选择器、样式与响应式、`/admin` 静态页、APK 构建链与 `MainActivity` 结构。后续改前端、写 E2E、重打 APK 直接查本文。
> **读者**：前端/全栈开发者、测试（E2E/真机验收）、负责发版与 APK 构建的人。
> **最后核实**：2026-11-17 · 代码基线 `9a5cc4f` · 事实均标注 `路径:行号`
> **相关文档**：[README 索引](README.md) · [01 项目总览](01-项目总览.md) · [03 接口参考](03-接口参考.md)
> **可信度**：A（已对照当前代码核实）；标注“历史笔记（未复核）”的条目为 B。

## 速读（TL;DR）

- 面板是 React 19 + Vite 6 + Tailwind 4 的单页应用，纯 hash 路由，无 react-router；依赖锁定 `lightweight-charts 5.3.0`、`react 19.3.1`、`typescript 5.9.3`（`web/pnpm-lock.yaml:12-44`）。
- **12 条路由 / 12 个页面**（`web/src/router.ts:3-15`），不是旧文档里的 9 页；`#/live` 是正式路由（`web/src/App.tsx:52-53`）。
- 桌面侧边栏 **11 项**；移动底栏 **4 个页面项 + “更多” = 5 个按钮**；更多抽屉渲染全部 11 项（`web/src/components/Layout.tsx:33-45,326,434-500`）。
- `api.ts` 共 **33 个 API 方法**（`web/src/api.ts:633-775`），其中 `symbols`、`liveConfig`、`closeLivePosition` 无调用点。
- 图表统一 lightweight-charts v5；4 个图表组件，单页最多 **2 个图表实例**（`Overview`、`Backtest` 回放、`Market`）。
- 状态是 Context + `useState`（无 reducer）；行情走 WebSocket，断线指数退避重连（`web/src/store.tsx:126-187`）。
- `params.ts` 只读写 `localStorage['gridtrade.params']`，**不做 URL/hash 参数序列化**（`web/src/params.ts:18-33`）。
- APK：`versionCode 1 / versionName 0.1.0 / minSdk 26 / targetSdk 34`；`build.sh` 用 `javac --release 17`；**无 JS 桥**（全仓无 `addJavascriptInterface`；`apk/AndroidManifest.xml:4-7`、`apk/build.sh:65`）。

## 目录

0. [速读（TL;DR）](#速读tldr)
1. [技术栈与构建](#1-技术栈与构建)
2. [路由与导航](#2-路由与导航)
3. [页面明细](#3-页面明细)
4. [api.ts 全量函数表](#4-apits-全量函数表)
5. [状态与数据流](#5-状态与数据流)
6. [组件与可测试选择器](#6-组件与可测试选择器)
7. [样式与响应式](#7-样式与响应式)
8. [/admin 静态页](#8-admin-静态页)
9. [APK 构建](#9-apk-构建)
10. [MainActivity 结构](#10-mainactivity-结构)
11. [旧文档勘误](#11-旧文档勘误)

## 1. 技术栈与构建

`web/package.json:1-27`：`name=gridtrade-web`、`private=true`、`version=0.1.0`、`type=module`。

| 依赖 | 声明 | 锁定 | 用途与证据 |
| --- | --- | --- | --- |
| `lightweight-charts` | `^5.0.0` | `5.3.0` | K 线/权益/回撤/资金费图；v5 的 `addSeries(CandlestickSeries…)`（`web/src/components/charts.tsx:1-16`） |
| `lucide-react` | `^0.468.0` | `0.468.0` | 图标（`web/src/components/Layout.tsx:2-19`） |
| `react` | `^19.0.0` | `19.3.1` | `StrictMode`（`web/src/main.tsx:6-10`） |
| `react-dom` | `^19.0.0` | `19.3.1` | `createRoot`（`web/src/main.tsx:2,6`） |
| `@tailwindcss/vite` | `^4.0.0` | `4.3.5` | `web/vite.config.ts:3,6`；`web/src/index.css:1` |
| `@types/react` / `@types/react-dom` | `^19.0.0` | `19.3.0` | 类型检查 |
| `@vitejs/plugin-react` | `^4.3.4` | `4.7.0` | `web/vite.config.ts:2,6` |
| `tailwindcss` | `^4.0.0` | `4.3.5` | 原子类与 `@theme`（`web/src/index.css:3-24`） |
| `typescript` | `^5.7.2` | `5.9.3` | `tsc --noEmit`（`web/package.json:8,10`） |
| `vite` | `^6.0.7` | `6.4.6` | dev/build/preview |

| script | 实际动作 |
| --- | --- |
| `dev`（`web/package.json:7`） | 起 Vite dev server，端口 5173；`/api` 代理到 `http://127.0.0.1:8000`，`/ws` 代理到 `ws://127.0.0.1:8000`（`web/vite.config.ts:7-13`） |
| `build`（`web/package.json:8`） | `tsc --noEmit` 全量类型检查后 `vite build`；产物 `web/dist`，`sourcemap=false`，`chunkSizeWarningLimit=900`（`web/vite.config.ts:14-18`） |
| `preview`（`web/package.json:9`） | `vite preview` 预览 `dist`，无自定义端口 |
| `typecheck`（`web/package.json:10`） | 仅 `tsc --noEmit` |

其他：TS 配置 `target=ES2022`、`moduleResolution=bundler`、`jsx=react-jsx`、`strict=true`、`noEmit=true`（`web/tsconfig.json:3-18`）；`pnpm-workspace.yaml:1-2` 仅 `allowBuilds: esbuild: true`，无 `packages:`（不是 monorepo）。`web/index.html:2-9`：`lang=zh-CN class=dark`、`viewport-fit=cover`、`theme-color=#0B0E11`、标题 `Gridtrade · 研究终端`。

## 2. 路由与导航

路由白名单：`web/src/router.ts:3-15`，`ROUTES` 为 `overview, market, strategy, backtest, paper, live, orders, positions, risk, quality, settings`。hash 读取 `replace(/^#\/?/,'').split('?')[0]`，未知路由回退 `overview`（`web/src/router.ts:19-22`）；空 hash 自动写 `#/overview`，`hashchange` 时滚回顶部（`web/src/router.ts:29-41`）。

| # | hash 路由 | 页面组件（App 分支） | 页面标题（顶栏 h1 = `TITLES[route]`） | 主要区块 | 主要 API |
| --- | --- | --- | --- | --- | --- |
| 1 | `#/overview` | `web/src/pages/Overview.tsx`（`web/src/App.tsx:42-43`） | 总览（`web/src/components/Layout.tsx:48`） | 4 KPI、回放权益+回撤、执行模式、数据源、前向滚动月度、最近任务 | `overview` 60s、`artifact` |
| 2 | `#/market` | `web/src/pages/Market.tsx`（`App.tsx:44-45`） | 行情（Layout:49） | 4 KPI、K 线、资金费率历史、套息快照 | `candles`(500)、`funding`(240) |
| 3 | `#/strategy` | `web/src/pages/Strategy.tsx`（`App.tsx:46-47`） | 策略（Layout:50） | 参数表单、校验、4 KPI、价格区间、阶梯预览 | 无（读 store 快照） |
| 4 | `#/backtest` | `web/src/pages/Backtest.tsx`（`App.tsx:48-49`） | 回测实验室（Layout:51） | 运行配置、历史、回放/前向滚动/扫描三 Tab 结果 | `quality`、`runs` 5s、`run` 700ms、`artifact`、`runs/replay\|walkforward\|sweep`、`cancel` |
| 5 | `#/paper` | `web/src/pages/Paper.tsx`（`App.tsx:50-51`） | 模拟盘（Layout:52） | 状态头、4 KPI、10 列持仓表、权益图、8 项参数、成交/资金费表 | `paper` 3s、`paper/start\|stop\|reset` |
| 6 | `#/live` | `web/src/pages/Live.tsx`（`App.tsx:52-53`） | 实盘（Layout:53） | 实盘配置、账户、持仓、挂单、成交、流水、风控、下单面板 | `live` 15s、`live/config`、`live/test`、`live/sync`、`live/orders` |
| 7 | `#/binance` | `web/src/pages/Binance.tsx`（`App.tsx:54-55`） | Binance 节点（Layout:54） | 节点健康/写锁徽标、4 KPI、持仓表、挂单表 | `binance/state` 15s（只读，经隧道） |
| 8 | `#/orders` | `web/src/pages/Orders.tsx`（`App.tsx:54-55`） | 订单与成交（Layout:54） | 任务侧栏、4 KPI、筛选+成交表、订单生命周期、期末挂单 | `runs('replay',20)` 15s、`artifact` |
| 9 | `#/positions` | `web/src/pages/Positions.tsx`（`App.tsx:56-57`） | 持仓（Layout:55） | 4 KPI、回放结束状态、风险包络、利润保护、最近账本 | `runs('replay',15)` 20s、`risk` 30s、`artifact` |
| 10 | `#/risk` | `web/src/pages/Risk.tsx`（`App.tsx:58-59`） | 风控（Layout:56） | 紧急停止、限额参数、4 KPI、生效限额、拒单、保护行为、审计 | `risk` 20s、`audit(50)` 30s、`kill-switch` |
| 11 | `#/quality` | `web/src/pages/Quality.tsx`（`App.tsx:60-61`） | 数据质量（Layout:57）；页内另有 `h1`：`{symbol} 数据集完整性`（`Quality.tsx:122`） | 4 KPI、6 项完整性检查、价格与缺口、合约过滤器、资金费、时段 | `quality` |
| 12 | `#/settings` | `web/src/pages/Settings.tsx`（`App.tsx:62-63` else 兜底） | 设置（Layout:58） | 连接、执行模式、审计、服务端、路径、紧急停止、关于 | `settings`、`audit(30)` 30s、`session` |

非路由页：`Login`（`web/src/App.tsx:38`，`!session` 时渲染；h1 `解锁研究终端`，`web/src/pages/Login.tsx:98`）；加载态 `Splash`（`App.tsx:18-31`）。页面组件无独立路由级 `<h1>`（Quality 除外），顶栏 h1 统一取 `TITLES[route]`（`web/src/components/Layout.tsx:402`）。

**导航依据**：`NAV` 共 12 条，含 `mobile` 布尔（`web/src/components/Layout.tsx:33-45`）。

| 入口 | 项数 | 具体项 | 代码位置 |
| --- | --- | --- | --- |
| 桌面侧边栏（`lg`≥1024px） | 11 | 总览/行情/策略/回测实验室/模拟盘/实盘/订单与成交/持仓/风控/数据质量/设置 | 渲染 `NAV.map`（`Layout.tsx:341-360`），容器 `hidden … lg:flex w-[228px]`（`Layout.tsx:330`） |
| 移动底部导航（`lg` 以下） | 5 个按钮（4 页面 + 更多） | 总览/行情/回测/风控/更多 | `NAV.filter(item=>item.mobile)`（`Layout.tsx:326`）；`mobile:true` 仅 overview/market/backtest/risk（Layout:34,35,37,42）；底栏渲染 `Layout.tsx:434-460` |
| 移动“更多”抽屉 | 11（全部 NAV，3 列网格） | 上述 11 项 + `仅研究` Badge + 退出登录 | `Layout.tsx:464-500`（`NAV.map` 在 470） |
| 命令面板（⌘K/Ctrl+K） | 12 页面 + N 交易对 + kill switch + logout | `前往{label}`、`切换交易对至 {symbol}`、`触发/解除紧急停止`、`退出登录` | `Layout.tsx:181-201,311-320` |

其他导航事实：移动项文字 `item.short ?? item.label.split(' ')[0]`（Layout:447）；顶栏交易对下拉仅在 `symbols.length>1` 时渲染为 `<select>`（Layout:79-102）；底部导航固定定位并带 `env(safe-area-inset-bottom)`（Layout:432-433）；抽屉同理 `calc(env(safe-area-inset-bottom)+72px)`（Layout:467）。

## 3. 页面明细

| 页面（路由） | 调用 API（轮询） | 关键展示字段 | 交互 | 图表（实例数） |
| --- | --- | --- | --- | --- |
| Overview（`#/overview`） | `api.overview(symbol)` 60s；`useArtifact`→`api.artifact`（`Overview.tsx:114,117`） | `market.mark_price/change_24h_pct/high_24h/low_24h/last_funding_rate/next_funding_time/quote_volume_24h/source`；`dataset.coverage_pct/bars/start/gap_count`；`runs[].id/kind/status/summary.total_return`；`walkforward.summary.median_ret/positive_months/worst_ret/stops`⚠️；`replay.summary.*`（`Overview.tsx:153-412`） | 5 处 `navigate('backtest')`（246,333,348,364,404）；无表单 | `EquityChart`(226px+88px 回撤) ×2（230-235） |

> ⚠️ **已知前后端字段名不一致（潜在显示缺陷，尚未修）**：前端读取 `walkforward.summary.median_ret / mean_ret / worst_ret / positive_months`（`web/src/api.ts:430-433`、`Overview.tsx`），但后端 `walkforward` 产物写入的键是 `mean / median / worst / positive`（`src/gridtrade/research/runner.py:132-141`）。因此这几项在界面上会显示为"—"。要修的话：统一键名（改前端类型与读取，或改后端产物），并同步 `docs/memory/03-接口参考.md` 的 artifact 结构说明。
| Market（`#/market`） | `api.candles({interval,limit:500})`、`api.funding({limit:240})`（`Market.tsx:15-16`） | `candles[][t,o,h,l,c,v]`、`count/from/to`；`funding.summary.count/mean_rate/median_rate/positive_pct/annualized_pct/interval_hours/last`（`Market.tsx:26-182`） | 周期 1m/5m/15m/1h/4h/1d（10,83-95）；刷新按钮 `aria-label="刷新 K 线"`（101） | `PriceChart` 400px ×1（125）、`FundingChart` 220px ×1（154） |
| Strategy（`#/strategy`） | 无；`snapshot.mark_price` + `loadParams()`（`Strategy.tsx:12-15`） | `preview.price/grossNotional/notionalPerLevel/grossLeverage/netProfitPerGrid/roundTripFees/stepPct/lower/upper/stopPrice/maxLossToStop/gridYieldPct`（80-108,159-163） | `ParamsForm`（39-54）；“用于回测实验室”保存并跳转（43-53）；4 条校验告警（23-27） | 无图表库；CSS 价格区间条（124-157） |
| Backtest（`#/backtest`） | `quality`、`runs(undefined,25)` 5s、`run` 700ms、`artifact`、`submitReplay/Walkforward/Sweep`、`cancelRun`（`Backtest.tsx:503-519,575-605`） | Tab=replay/walkforward/sweep；`summary.total_return/ann_return/max_dd/sharpe/final_equity/trades/fees/funding`；月度表 `month/ret/dd/trades/fees/funding/halted`；扫描 `spacing_bp/levels/leverage/ann_return/max_dd` | 日期 `type="date"`（672,676）；快捷区间按钮（634-668）；`minDays`（682-691）；扫描三维文本（693-713）；历史选择回填（533-558）；JSON 导出（612-620） | 回放 `EquityChart`(280+100)×2（220）；前向 `CumulativeChart` 260px ×1（350）；扫描 0 |
| Paper（`#/paper`） | `api.paper()` 3s；`paperStart/Stop/Reset`（`Paper.tsx:45,90-97`） | `status`、`symbols[]`、`config.enabled/poll_seconds`；`account.equity/cash/return_pct/peak_equity/drawdown_pct/gross_notional/margin_used/leverage/fees/funding/unrealized/realized`；`portfolio[]`（19 字段，`api.ts:162-183`）；`fills[]`、`funding[]`、`equity[]` | 启动（running 或未启用时禁用，148-156）、停止（157-159）、重置需二次确认且 4s 复位（160-175）；8 个 `NumberInput`（291-316） | `EquityChart` 260px ×1（276） |
| Live（`#/live`） | `api.live()` 15s；`saveLiveConfig/testLive/liveSync/liveOrder/cancelLiveOrder`（`Live.tsx:32,76-99,347,484`） | `config.configured/api_key_hint/has_secret/max_notional/max_order_notional/max_position_notional/max_open_orders`；`analysis.equity/available/unrealized/realized/margin_ratio/fees_paid/funding_paid/gross_notional/net_notional/open_orders/warnings[]`；`positions/orders/trades/ledger` | Key/Secret 输入（127-141）；2 个 Toggle（144-145，下单需 confirm 101-109）；4 个限额输入（158-168）；撤单/下单（343-351,519） | 0 |
| Orders（`#/orders`） | `api.runs('replay',20)` 15s；`artifact`（`Orders.tsx:100,115`） | `fills[].ts/side/price/qty/fee/tag/liquidity/client_id`；`orders.counts/rejection_reasons/open`；`summary.turnover_x`；`capital` | 方向/流动性筛选（13-14,285-298）；搜索 tag/client_id（306）；分页 120→+200（105,368-374） | 0 |
| Positions（`#/positions`） | `api.runs('replay',15)` 20s；`api.risk(...)` 30s；`artifact`（`Positions.tsx:42,54-65`） | `replay.summary.final_position/final_equity/total_return/funding/halted/avg_inventory_pct/strategy_state`；`risk.limits.*`；`snapshot.mark_price` | 刷新（264）、行选择（292）、跳回测（177） | 0 |
| Risk（`#/risk`） | `api.risk(...)` 20s；`api.audit(50)` 30s；`setKillSwitch`（`Risk.tsx:44-56`） | `limits.max_position_qty/max_order_notional/max_gross_notional/max_open_orders/max_submits_per_minute/max_price_deviation_bp`；`rejections[]`；`latest_run`；`audit` | kill Toggle + 确认（160-178）；参数表单（185，**不落库**）；限额推导表（78-117） | 0 |
| Quality（`#/quality`） | `api.quality(symbol)`（`Quality.tsx:115`） | `bars/expected_bars/coverage_pct/missing_bars/last_close`、`price_min/price_max/median_gap_minutes/max_gap_minutes/gap_count/zero_volume_pct/bad_ohlc/duplicate_timestamps`、`filters.*`、`contract.*`、`funding_*`、`schedule.*` | 重新扫描（127） | 0 |
| Settings（`#/settings`） | `api.settings()`、`api.audit(30)` 30s、`api.session()`（`Settings.tsx:47-48,69`） | `version/symbol/symbols/intervals/modes/kill_switch`、`auth.mode/token_hint/cookie`、`paths.data/var/web/web_built`、`server.host/port/cors_origins/uptime_s` | 服务器地址 `inputMode=url`、令牌 `type=password`（101-121）；保存并重连（58-77）；退出登录、kill Toggle | 0 |
| Login（非路由） | `api.health()`（`Login.tsx:21`，server 变化时重跑） | 服务端版本提示（154-157） | 令牌 `type=password` + `autoFocus`（104-113）；服务器地址折叠（116-142） | 0 |

统计：12 个页面中 **4 个调用图表**（Overview、Market、Backtest、Paper），图表库统一为 `lightweight-charts`；页面最多 2 个图表实例。页面数据轮询集中在 3s（paper）到 60s（overview）。

## 4. api.ts 全量函数表

`web/src/api.ts` 导出 `api` 对象（633-775）与 `ApiError/getServer/setServer/getToken/setToken/streamUrl`；`request()` 统一注入 `Authorization: Bearer <token>`、`credentials:'include'`、JSON Content-Type、401 与 `detail` 错误提取（600-627）。localStorage 键：`gridtrade.token`、`gridtrade.server`（557-558）。`streamUrl()` 生成 `/ws?token=&symbol=`（777-784）。

| # | 函数 | method + path | 参数 | 返回类型 | 调用点 |
| --- | --- | --- | --- | --- | --- |
| 1 | `health` | `GET /api/health` | 无 | `{status,version,uptime_s}` | `Login.tsx:21` |
| 2 | `login` | `POST /api/auth/login` | body `{token}` | `{ok,token_hint,expires_in}` | `store.tsx:96` |
| 3 | `logout` | `POST /api/auth/logout` | 无 | `{ok}` | `store.tsx:105` |
| 4 | `session` | `GET /api/session` | 无 | `Session` | `store.tsx:67`、`Settings.tsx:69` |
| 5 | `overview` | `GET /api/overview[?symbol=]` | `symbol?` | `Overview`（归一 `cumulative`） | `Overview.tsx:114` |
| 6 | `symbols` | `GET /api/dataset/symbols` | 无 | `{symbols,default}` | **未使用** |
| 7 | `quality` | `GET /api/dataset/quality[?symbol=]` | `symbol?` | `DatasetQuality` | `Backtest.tsx:503`、`Quality.tsx:115` |
| 8 | `snapshot` | `GET /api/market/snapshot[?symbol=]` | `symbol?` | `MarketSnapshot` | `store.tsx:171` |
| 9 | `candles` | `GET /api/market/candles?interval=…` | `{symbol?,interval,limit?}` | `CandleResponse` | `Market.tsx:15` |
| 10 | `funding` | `GET /api/market/funding[?symbol=][&limit=]` | `{symbol?,limit?}` | `FundingResponse` | `Market.tsx:16` |
| 11 | `submitReplay` | `POST /api/runs/replay` | `ResearchInput` | `{run}` | `Backtest.tsx:576` |
| 12 | `submitWalkforward` | `POST /api/runs/walkforward` | `ResearchInput & {min_days}` | `{run}` | `Backtest.tsx:578` |
| 13 | `submitSweep` | `POST /api/runs/sweep` | `ResearchInput & {axes{spacings,levels,leverages}}` | `{run}` | `Backtest.tsx:588` |
| 14 | `runs` | `GET /api/runs?limit=&kind=` | `kind?`、`limit=30` | `{runs}` | `Backtest:504`、`Orders:100`、`Positions:42` |
| 15 | `run` | `GET /api/runs/{id}` | `id` | `{run}` | `hooks.ts:79` |
| 16 | `artifact` | `GET /api/runs/{id}/artifact` | `id` | `Artifact`（归一 points） | `hooks.ts:106` |
| 17 | `cancelRun` | `POST /api/runs/{id}/cancel` | `id` | `{canceled,run}` | `Backtest:605` |
| 18 | `risk` | `GET /api/risk?symbol=&capital=&spacing_bp=&levels=&leverage=` | 5 个可选 query | `RiskProfile` | `Risk:46`、`Positions:56` |
| 19 | `setKillSwitch` | `POST /api/settings/kill-switch` | body `{engaged}` | `{kill_switch}` | `store.tsx:116` |
| 20 | `settings` | `GET /api/settings` | 无 | `SettingsView` | `Settings:47` |
| 21 | `audit` | `GET /api/audit?limit=` | `limit=60` | `{entries}` | `Risk:56`、`Settings:48` |
| 22 | `paper` | `GET /api/paper` | 无 | `PaperState` | `Paper:45` |
| 23 | `paperStart` | `POST /api/paper/start` | `{reset?,config?}` | `PaperState` | `Paper:93` |
| 24 | `paperStop` | `POST /api/paper/stop` | 无 | `PaperState` | `Paper:96` |
| 25 | `paperReset` | `POST /api/paper/reset` | `PaperConfigInput` | `PaperState` | `Paper:97` |
| 26 | `live` | `GET /api/live[?refresh=1]` | `refresh=false` | `LiveSnapshot` | `Live:32` |
| 27 | `liveConfig` | `GET /api/live/config` | 无 | `{config}` | **未使用** |
| 28 | `saveLiveConfig` | `POST /api/live/config` | `LiveConfigInput` | `{config}` | `Live:88,99` |
| 29 | `testLive` | `POST /api/live/test` | 无 | `{ok,total,currency}` | `Live:96` |
| 30 | `liveSync` | `POST /api/live/sync` | 无 | `LiveSnapshot` | `Live:97` |
| 31 | `liveOrder` | `POST /api/live/orders` | `LiveOrderInput` | `{order}` | `Live:484` |
| 32 | `cancelLiveOrder` | `DELETE /api/live/orders/{id}` | `id` | `{order}` | `Live:347` |
| 33 | `closeLivePosition` | `POST /api/live/positions/{contract}/close` | `contract`（encoded） | `{order}` | **未使用** |

注意：`limit`/数值 query 只在真值（非 0、非空）时拼接；`request` 无 AbortController；网络失败抛 `ApiError(0, …)`，401 抛固定中文提示，非 2xx 优先取 `detail`，204 返回 `undefined`（`api.ts:600-627`）。

## 5. 状态与数据流

### 5.1 `store.tsx`（Context + `useState`，无 reducer）

`AppState` 定义在 `web/src/store.tsx:19-37`；Provider 内 9 个 `useState` + 1 个 `useRef`（`store.tsx:43-52`）。

| 状态/动作 | 类型 | 行为 |
| --- | --- | --- |
| `session` | `Session\|null` | `refreshSession()` 成功写入（64-81） |
| `loading` | `boolean` | 初始 true；无 token 时直接 false（83-86） |
| `error` | `string\|null` | 会话失败写入；**全仓库无消费者读取**（76-77） |
| `symbol` / `setSymbol` | `string` / `(s)=>void` | 初值 `localStorage['gridtrade.symbol']`（40,46）；无则用 `session.symbol`（123）；设置时写回并清空 snapshot（88-92） |
| `snapshot` | `MarketSnapshot\|null` | WS `type==='market'` 或首拉 `api.snapshot`（145-179） |
| `connected` / `lastBeat` | `boolean` / `number` | socket 开关状态；每次行情帧更新时间戳（141-159） |
| `refreshSession` | `()=>Promise<void>` | `api.session()` → session/killSwitch/symbol 同步 |
| `signIn` / `signOut` | `(token)=>Promise` / `()=>Promise` | 登录：`api.login`→`setToken`→刷新；登出：`api.logout`（忽略错误）→清 token/session/snapshot（94-112） |
| `killSwitch` / `setKillSwitch` | `boolean` / `(engaged)=>Promise` | 来自 session；切换后同步并 toast（114-121） |
| `toast` / `toasts` / `dismiss` | `(text,tone?)=>void` / `Toast[]` / `(id)=>void` | 自增 id；最多 3 条（`slice(-2)`）；5200ms 自动消失（54-62） |
| `modes` | `Record<string,ModeInfo>` | `session?.modes ?? {}`（207） |

行情链路：依赖 `[session, activeSymbol]`；先 `prime()` 拉一次 snapshot，再连接 `streamUrl(symbol)`；断线后退避 `min(15000, 1000*2^min(retry,4))` ms（2s/4s/8s/16s→封顶 15s），`onopen` 重置计数（`store.tsx:126-187`）。持久化键：`gridtrade.symbol`、`gridtrade.token`、`gridtrade.server`、`gridtrade.params`。

### 5.2 `hooks.ts`

| hook | 签名 | 轮询/边界 |
| --- | --- | --- |
| `errorText` | `(unknown)=>string` | `ApiError`/`Error` 取 message，否则“发生未知错误”（4-8） |
| `useFetch` | `(loader, deps, {enabled?,pollMs?})` | 初始 loading=true；`enabled=false` 只置 loading=false（30-33）；`reload()` version+1；`pollMs` 存在则 `setInterval`，不等待上一次完成；清理 `cancelled`+clearInterval（16-56） |
| `useRunWatch` | `(runId\|null, onSettled?)` | `runId` 为空清空；`queued/running` 时 700ms 轮询 `api.run`；终态用 `settled` ref 保证 `onSettled` 每 run 只回调一次；请求异常停止轮询（60-101） |
| `useArtifact` | `(runId, run)` | **防 409 竞态**：仅当 `runId && run.id===runId && run.status==='succeeded'` 才 `enabled=true` 请求 `artifact`；否则返回 `data:null`（103-111） |
| `useInterval` | `(cb, ms\|null)` | `ms` 假值不启动；始终调用最新回调；**无调用点**（113-121） |
| `statusTone` | `(RunStatus)=>'up'\|'down'\|'accent'\|'info'\|'neutral'` | succeeded/failed/running/queued/其它映射（123-136） |

### 5.3 `format.ts`

| 函数 | 行为（含边界） |
| --- | --- |
| `toNumber` | null/undefined/''→null；非有限→null（1-5） |
| `fmtPrice(value,digits?)` | 非有限→`—`；digits 缺省按绝对值 ≥1000/≥10→2、≥1→3、否则 5（7-15） |
| `fmtMoney(value,digits=2)` / `fmtCompact` | 固定小数 / `Intl compact`；非有限→`—`（17-31） |
| `fmtPct(value,digits=2,sign=true)` | 正值 `+`、负值 `−`（U+2212）（33-40） |
| `fmtRate(rate,digits=4)` | `rate*100` 后走 `fmtPct`（42-45） |
| `fmtQty(value,digits=4)` | 最多 digits 位小数（47-50） |
| `fmtDuration(seconds)` | <90 秒、<5400 分、<172800 小时、否则天（52-58） |
| `fmtTime` / `fmtDate` / `fmtDateTimeLocal` | `MM-DD HH:mm` / `YYYY-MM-DD` / `YYYY-MM-DDTHH:mm`（69-100） |
| `fmtMonth` | `YYYY-MM`→`YYYY年M月`；**无调用点**（85-91） |
| `timeAgo` | <45s 刚刚、<1h 分钟、<24h 小时、否则天（102-110） |
| `signClass` | 0/无效→`text-muted`，正→`text-up`，负→`text-down`（112-116） |
| `cx` / `clamp` | 类名拼接 / 区间夹取（118-124） |
| `signed` | `value ?? 0`；**无调用点**（126-128） |

### 5.4 `labels.ts` 与 `params.ts`

- `labels.ts`：`AUDIT_LABELS` 11 条（服务启动/停止、登录失败/成功/退出、三类 run 入队、任务取消、紧急停止切换、设置保存），`auditLabel()` 未命中回退原 key（`web/src/labels.ts:1-17`）；使用于 `Risk.tsx:367`、`Settings.tsx:195`。
- `params.ts`：`DEFAULT_PARAMS` 为本金 10000、间距 120bp、30 层、杠杆 0.5、无重锚、止损 0.1、maker 0.0002、taker 0.0005、滑点 0.2bp、`intrabar=false`（`web/src/params.ts:5-16`）；键 `gridtrade.params`，`loadParams` 合并默认值并 `sanitize`（数字白名单 + null 判断），`saveParams` 直接 stringify（18-33）。
- `buildPreview(price, params)`：`step=spacing_bp/10000`，`qty=capital*leverage/levels/price`，买层 `ceil(levels/2)`、卖层余数，价格按降序排序；`upper/lower`、`grossNotional`、`grossLeverage=grossNotional/capital`、`stopPrice=price*(1-stop_dd/leverage)`、`gridYieldPct`（`params.ts:88-138`）。
- **代码中不存在** URL/hash 参数序列化：`params.ts` 不读写 `location`；`router.ts` 只解析 hash 中的路由名并丢弃 `?` 后内容（`router.ts:20`）。

## 6. 组件与可测试选择器

| 组件（文件） | props | 用途 |
| --- | --- | --- |
| `Layout`（`components/Layout.tsx:304-507`） | `{children:ReactNode}` | 侧边栏/顶栏/内容/底栏/抽屉/命令面板/Toast |
| `TITLES`（Layout:47-59） | `Record<RouteName,string>` | 顶栏 h1 |
| `ConnectionPill` / `SymbolSelect` / `PriceTicker`（61-123） | 无 | 连接状态、交易对下拉、价格 ticker |
| `KillSwitchButton`（125-166） | 无 | 三态 kill switch（紧急停止/确认/已停止） |
| `CommandPalette`（168-276） | `{open,onClose}` | ⌘K 面板 |
| `Toasts`（278-302） | 无 | 右下角 toast |
| `Card` / `CardHead` / `Stat` / `Button` / `Field` / `Toggle` / `Badge` / `Skeleton` / `Empty` / `ErrorNote` / `Progress` / `useNow` / `Delta`（`components/ui.tsx`） | 见文件；`Button` 支持 `variant/size/loading`；`Toggle` 用 `role="switch"+aria-checked` | 基础 UI（13 个导出） |
| `PriceChart` / `EquityChart` / `CumulativeChart` / `FundingChart`（`components/charts.tsx`） | candles/markers、equity/drawdown/baseline、points 等 | v5 图表封装（4 个导出） |
| `NumberInput` / `ParamsForm` / `Segmented`（`components/inputs.tsx`） | 数值输入/网格参数表单/分段按钮 | 表单组件（3 个导出） |

**E2E 选择器**（无 `data-testid`，全仓不存在）：

| 目标 | 选择器事实 | 代码 |
| --- | --- | --- |
| 开关 | `button[role="switch"][aria-checked="true\|false"]`，禁用看 `disabled` | `components/ui.tsx:146-151` |
| 数值输入 | `input[inputmode="decimal"]`；**无 `type="number"`**；仅 blur/Enter 提交（需 Enter 后 blur） | `components/inputs.tsx:49-67` |
| 日期 | `input[type="date"]` ×2 | `pages/Backtest.tsx:672,676` |
| 密码 | `input[type="password"]`：Login/Settings/Live Secret/admin | `pages/Login.tsx:107`、`Settings.tsx:115`、`Live.tsx:135` |
| 服务器地址 | `input[inputmode="url"]` | `Settings.tsx:105-106`、`Login.tsx:131-132` |
| 下拉 | Live 下单 `select.input` ×2；顶栏交易对裸 `select` | `Live.tsx:497,504`；`Layout.tsx:90-100` |
| 搜索 | placeholder `按标签或客户端 ID 筛选` | `Orders.tsx:306` |
| 命令面板 | placeholder `跳转到页面、交易对或操作`；⌘/Ctrl+K、Esc、↑↓、Enter | `Layout.tsx:243,225-242,311-320` |
| 刷新 | `aria-label`：`刷新 K 线`/`刷新运行记录`/`刷新回放任务` | `Market:101`、`Backtest:743`、`Orders:160` |
| kill switch | `title="紧急停止"`/`"紧急停止已触发"` | `Layout.tsx:144,162` |
| 图表 | 容器为普通 `div.w-full`，无 role/testid；按 canvas 或父卡片文案定位 | `charts.tsx:168,276-282` |
| Toast | 无 `role="status"`，关闭按钮仅图标 | `Layout.tsx:281-300` |
| admin | 全部靠 `id`：`username/password/apiKey/apiSecret/…` | `web/public/admin/index.html:68-154,319-339` |

## 7. 样式与响应式

- 主题：Tailwind 4 `@theme` 定义 13 个颜色 token（base `#0b0e11`、panel `#181a20`、elevated `#1e2329`、line `#2b3139`、line-soft `#23272e`、ink `#eaecef`、muted `#848e9c`、faint `#5e6673`、accent `#fcd535`、accent-dim `#d9b62b`、up `#0ecb81`、down `#f6465d`、info `#4a9eff`）、`--font-sans/--font-mono`、动画 `rise`（`web/src/index.css:3-24`）。全局：`html/body/#root {height:100%}`、`-webkit-font-smoothing:antialiased`、`overscroll-behavior-y:none`（56-69）；组件类 `.card/.label/.num/.monthly-table/.input/.skeleton/.live-dot/.grid-motif/.row-hover`（117-232）。
- 断点：`@theme` 未定义 `--breakpoint-*`，用 Tailwind 默认 `sm 640px / md 768px / lg 1024px / xl 1280px`。关键用法：`lg` 控制侧边栏/底栏/抽屉（`Layout.tsx:330,392,432,465`）；`xl` 控制各页多栏（如 `Overview.tsx:153,209,326`、`Backtest.tsx:626`）。
- 移动固定定位：侧边栏 `fixed inset-y-0 left-0 z-30 w-[228px] lg:flex`（Layout:330）；顶栏 `sticky top-0 z-20`（393）；底栏 `fixed inset-x-0 bottom-0 z-30 lg:hidden` + `env(safe-area-inset-bottom)`（432-433）；更多抽屉 `fixed inset-0 z-40` + `calc(env(safe-area-inset-bottom)+72px)`（465-467）；命令面板/Toast `fixed z-50`（211,281）。`viewport-fit=cover` 见 `web/index.html:5`。
- 横向滚动：Paper 持仓 `min-w-[760px]`、成交 `min-w-[520px]`、资金费 `min-w-[460px]`；Live 持仓 `min-w-[720px]`；其余表格用 `overflow-x-auto`/`max-h overflow-auto`（`Paper.tsx:219-220,324-325,364-365`；`Live.tsx:276-277,321,365,400`；`Backtest.tsx:132,288,360,437`；`Orders.tsx:328,420`；`Positions.tsx:268`；`Risk.tsx:246`）。
- WebView 兼容处理：`main :where(.grid) > * {min-width:0}` 防止表格最小内容撑宽 grid、避免 fixed 底栏偏移（`index.css:72-74`）；`input[type=number]` 隐藏 WebKit 旋转按钮并 `appearance:textfield`（85-94，但 `NumberInput` 无 type=number）；细滚动条（96-114）；无 `100vh/dvh/svh` 用法，高度靠 `height:100%` + flex（56-60、`Layout.tsx:329,392`）；无 tap-highlight/touch-action/user-select 处理。

## 8. /admin 静态页

`web/public/admin/index.html`（342 行）是独立静态页，非 SPA 路由，由后端直接返回；内联 CSS、同源 Cookie 认证（`credentials:'same-origin'`，169-174），无构建依赖。

| 区块 | 内容 | 行 |
| --- | --- | --- |
| 登录 `#loginView` | 账号（预填）、密码、`#loginBtn`、错误条 | 63-73 |
| `#appView` | header（`#who`/`#refreshBtn`/`#logoutBtn`）、`#passwordBanner`、`#globalMsg` | 75-85 |
| 概览 | `#envPath` + `#overviewStats`（模拟盘状态/权益/标的数、实盘同步/凭据/下单） | 87-91,199-211 |
| 实盘配置（Gate） | Key/Secret、4 个限额、3 个复选框、保存/清除 | 93-113 |
| 模拟盘配置 | 标的列表、本金/杠杆/间距/层数/止损、保存并重置/启动/停止/仅重置 | 115-132 |
| 安全 | 轮换面板令牌（`#newToken` 只显示一次）、改密（当前/新） | 134-147 |
| 审计日志 | 表头 `时间 / 动作 / 详情`，`#auditRows` | 149-154 |

| 端点 | method | 触发 |
| --- | --- | --- |
| `/api/admin/login` | POST `{username,password}` | 登录/回车（185-188,320） |
| `/api/admin/logout` | POST | 退出（321） |
| `/api/admin/me` | GET | 启动 `boot()`（244） |
| `/api/admin/overview` | GET | 启动、刷新、保存后、15s 轮询（235,339） |
| `/api/admin/live` | POST | 保存实盘配置 / 清除凭据（264,327） |
| `/api/admin/paper` | POST | 保存模拟盘配置并重置（281） |
| `/api/admin/paper/action` | POST `{action}` | start/stop/reset（289,332-334） |
| `/api/admin/token/rotate` | POST | 轮换面板令牌（确认框，296-298） |
| `/api/admin/password` | POST `{current_password,new_password}` | 修改密码（309-312） |

overview 响应字段：`env_path/token_hint/default_password/admin_username`、`paper.status/equity/symbols/config`、`live.enabled/configured/api_key_hint/trading_enabled/max_*`、`audit[{ts,action,detail}]`（199-231）。默认管理员初始密码见页面提示（`admin/index.html:66`），本文不复述。

## 9. APK 构建

`apk/AndroidManifest.xml` 关键项：

| 项 | 值 | 行 |
| --- | --- | --- |
| 包名 | `com.gridtrade.panel` | 3 |
| `versionCode` / `versionName` | `1` / `0.1.0` | 4-5 |
| `minSdkVersion` / `targetSdkVersion` | `26` / `34` | 7 |
| 权限 | `INTERNET`、`ACCESS_NETWORK_STATE` | 9-10 |
| application | `allowBackup=false`、`hardwareAccelerated=true`、`theme=Theme.Material.NoActionBar`、`usesCleartextTraffic=true`、`icon=@mipmap/ic_launcher`、`label=@string/app_name` | 12-19 |
| activity | `.MainActivity`、`exported=true`、`launchMode=singleTop`、`windowSoftInputMode=adjustResize`、`configChanges=orientation\|screenSize\|keyboardHidden\|screenLayout\|smallestScreenSize\|uiMode`、MAIN/LAUNCHER | 21-31 |

`apk/build.sh`（101 行）流水线：`set -euo pipefail`；`SDK=${ANDROID_HOME:-$HOME/Library/Android/sdk}`、`BUILD_TOOLS` 默认 `36.0.0`、`PLATFORM` 默认 `android-34/android.jar`、`JDK` 用 `/usr/libexec/java_home -v 21`（macOS 专用）（`apk/build.sh:4-13`）。

| 步骤 | 工具与参数 | 产物 |
| --- | --- | --- |
| 预检（15-24） | `aapt2/d8/zipalign/apksigner` 必须可执行，`$PLATFORM` 必须存在 | 缺失即退出 |
| 清目录（26-27） | 删 `build/`，建 `classes/dex/gen` | 工作目录 |
| `.env` 注入（29-40） | 若 `apk/.env` 存在：`set -a; . "$ENV_FILE"`；`SERVER_URL` 默认 `http://10.0.2.2:8000`、`TOKEN` 默认空；去掉首尾双引号 | 构建变量 |
| 生成 `BuildConfig`（41-50） | heredoc 写 `build/gen/com/gridtrade/panel/BuildConfig.java`：`final class BuildConfig`、`static final String DEFAULT_SERVER`、`static final String DEFAULT_TOKEN` | 编译源 |
| 资源编译（53） | `aapt2 compile --dir res -o res.zip` | `res.zip` |
| 资源链接（54-62） | `aapt2 link -o unsigned.apk -I $PLATFORM --manifest AndroidManifest.xml res.zip --min-sdk-version 26 --target-sdk-version 34 --version-code 1 --version-name 0.1.0` | `unsigned.apk` |
| Java 编译（64-66） | `javac --release 17 -Xlint:-options -classpath $PLATFORM -d classes $(find src gen -name '*.java')` | `.class`（Java 17 字节码） |
| Dex（68-70） | `d8 --lib $PLATFORM --min-api 26 --output dex …` | `classes.dex` |
| 合并（72-73） | `cp unsigned.apk unaligned.apk`；在 `dex/` 内 `zip -q unaligned.apk classes.dex` | `unaligned.apk` |
| 对齐（75-76） | `zipalign -f 4 unaligned.apk aligned.apk` | `aligned.apk` |
| 签名密钥（78-89） | 仅当 `apk/gridtrade.jks` 不存在时 `keytool -genkeypair`（RSA 2048、有效期 10000 天、dname `CN=Gridtrade,…`；口令硬编码，本文不复述） | `gridtrade.jks` |
| 签名（91-98） | `apksigner sign --ks gridtrade.jks --ks-key-alias gridtrade --out gridtrade.apk aligned.apk` | `apk/gridtrade.apk` |
| 校验（100-101） | `apksigner verify --print-certs` + `echo built` | 证书输出 |

`.env` 机制：构建时把 `SERVER_URL`/`TOKEN` 编译进 `BuildConfig`（`apk/build.sh:37-50`），APK 首启有 token 则跳过设置页（`MainActivity.java:85-93`）；签名口令硬编码在脚本中，密钥文件不入库（需单独保管）。

## 10. MainActivity 结构

`apk/src/com/gridtrade/panel/MainActivity.java`（538 行）是单 Activity WebView 壳，无 Gradle、无 JS 桥。

| 类别 | 事实 | 行 |
| --- | --- | --- |
| 常量 | `TAG="Gridtrade"`、`PREFS="gridtrade"`、`DEFAULT_SERVER/DEFAULT_TOKEN=BuildConfig.*` | 42-45 |
| 字段 | `prefs/root/panel/webView/progress/errorPanel/errorMessage/serverInput/tokenInput/server/injectedToken/pageFailed/tokenPushed` | 59-71 |
| `onCreate` | 读 SharedPreferences `server/token`（空则用 BuildConfig）；token 为空→`showSetup()`，否则直接 `showPanel()` | 73-94 |
| `showSetup` | 原生设置页：品牌 `GRIDTRADE`、`量化研究终端`、`服务器地址`、`访问令牌`、`打开面板`、3 条提示 | 96-168 |
| `connect` | 地址 `normalize`（补 `http://`、去尾 `/`）；写 prefs；`showPanel` | 170-180 |
| `showPanel` | 建 WebView + 2dp 进度条 + 错误面板，`loadUrl(server)` | 182-209 |
| `buildErrorPanel` | `无法连接服务器` + 错误描述 + `重试`（reload）+ `服务器与令牌` | 211-253 |
| `configureWebView` | 调试开关、WebSettings、CookieManager、WebViewClient/WebChromeClient | 255-330 |
| `syncToken` | JS 读 `localStorage['gridtrade.token']`；与注入值不同则写 localStorage 并 `reload()` 一次；否则回写 prefs | 332-349 |
| `signOut` | 清 prefs token、`removeAllCookies`、JS 删 localStorage token，回设置页 | 391-402 |
| `onBackPressed` / `showPanelMenu` | 可后退则 `goBack()`；否则弹菜单：`重新加载`/`服务器与令牌`/`退出登录`/`退出应用`/`取消` | 404-434 |
| 生命周期 | `onPause/onResume` 转发 WebView；`onDestroy` 销毁 panel | 436-452 |

WebView 设置（`MainActivity.java:255-330`）：调试开关 `setWebContentsDebuggingEnabled(true)`（**当前在 :256**）；`useWideViewPort=true`、`loadWithOverviewMode=false`、JS/DOM Storage/Database 开启、文件与内容访问关闭、缩放关闭、`MIXED_CONTENT_COMPATIBILITY_MODE`、UA 追加 `GridtradeShell/0.1`（258-270）；Cookie 接受、拒绝第三方（272-274）；同 host 留在 WebView、异 host 用 `Intent.ACTION_VIEW` 外跳（276-288）；`onPageFinished` 调 `syncToken()`（300-304）。

存储与桥：localStorage 只读写 `gridtrade.token`（335,340,397）；SharedPreferences 文件名 `gridtrade`，键 `server`/`token`（85-86,177,346,392）；Cookie 无手动注入，退出时全部清除（393）；**JS 桥：代码中不存在**（无 `addJavascriptInterface`/`@JavascriptInterface`），原生→JS 仅 `evaluateJavascript` 单向注入。构建时注入的 token 以 `BuildConfig.DEFAULT_TOKEN` 形式存在，仓库中无真实值。

## 11. 旧文档勘误

| 旧说法（来源） | 实际（当前代码） |
| --- | --- |
| “9 页”（`02-开发进度与变更记录.md:52,72,80`、`03-部署与运维手册.md:190`、`04-测试手册.md:81,121`、`06-下一步与待办.md:14,21,60,99`、`vault/gridtrade-项目交接总览-2026-11-16.md`） | **12 条路由/12 页**（`web/src/router.ts:3-15`、`web/src/App.tsx:42-63`） |
| “10 个 hash 路由”，表内缺 `#/live`（`01-项目总览与架构.md:44-57`） | 12 条，含 `#/live`、`#/binance`（`router.ts:8`；`App.tsx:52-53`） |
| “10 条路由（overview/…/strategy）”漏 live（`04-测试手册.md:58`） | 12 条，列表含 `live`、`binance`（`router.ts:3-15`） |
| “更多抽屉内 9 页/列全部 9 页”（`01-项目总览与架构.md:60`、`04-测试手册.md:81`） | 抽屉渲染全部 **11** 项（`Layout.tsx:470`）；底栏确为 4 页面 + “更多”=5 按钮（`Layout.tsx:326,434-460`） |
| 历史笔记称 APK 默认地址已改为/硬编码为 `http://81.71.71.131:8000`（`05-问题与决策记录.md:35`、`vault/gridtrade-项目交接总览:52`） | 源码默认仍是 `http://10.0.2.2:8000`（`apk/build.sh:37`）；公网地址由未入库的 `apk/.env` 注入，模板见 `apk/.env.example:4` |
| “调试开关 `MainActivity.java:252`”（历史笔记/旧报告行号） | 当前在 `apk/src/com/gridtrade/panel/MainActivity.java:256`（`setWebContentsDebuggingEnabled(true)`） |
| “aapt2 → **javac 21** → d8”（`02-开发进度与变更记录.md:65`） | `javac --release 17`（JDK 21 运行 javac，产出 Java 17 字节码，`apk/build.sh:65`） |
| “TypeScript 5.9”技术栈（`01-项目总览与架构.md:18`） | `package.json` 声明 `^5.7.2`，lock 解析 `5.9.3`（`web/package.json:24`、`web/pnpm-lock.yaml:40-41`） |
| 后端 API 清单缺 paper/live/admin（`01-项目总览与架构.md:68-91`） | `api.ts` 有 `/api/paper*`、`/api/live*`，admin 页另有 `/api/admin/*`（`web/src/api.ts:633-775`、`web/public/admin/index.html:185-321`） |
| “设置页 server/token 输入框不在 `<label>` 内”（`04-测试手册.md:103`） | 两输入均由 `Field` 包裹，`Field` 渲染 `<label>`（`Settings.tsx:100-121`、`ui.tsx:126-131`） |
| “单次回放 14 个 canvas/14 图”（`02:54`、`04:59`） | 代码只装配 2 个图表实例（权益+回撤）；canvas 数由库决定，`14` 属运行时观测，历史笔记（未复核） |
| APK 版本/SDK（`02-开发进度与变更记录.md:61`：0.1.0 / minSdk 26 / targetSdk 34） | **一致**；另 `versionCode=1`（旧文档未记）：`apk/AndroidManifest.xml:4-7`、`apk/build.sh:59-62` |
| “pytest 53 passed”（`04-测试手册.md:13`）vs “74 passed”（`02:48`、`09:71`） | 文档内部矛盾，非前端代码事实；以最新测试结果为准，本文不裁决 |
| APK 产物约 25KB（`02-开发进度与变更记录.md:65`） | `apk/gridtrade.apk` 实际 25,409 字节，与 `vault:52` 一致 |
