---
title: gridtrade 实时模拟盘与 APK 免登录（2026-11-17）
tags:
  - gridtrade
  - paper-trading
  - env
  - android
  - deployment
verified: true
created: '2026-11-17T13:56:30+08:00'
---

# gridtrade 实时模拟盘与 APK 免登录（2026-11-17）

**重点：新增第 10 页 `/paper` 实时模拟盘，已用 Gate 公开行情在服务器自动运行；APK 改为构建时 `apk/.env` 注入服务器与令牌，安装后直接进面板，不再登录。**

## 背景与约束

- 服务器（81.71.71.131）无法访问 `fapi.binance.com`（超时），但 `api.gateio.ws`、`data-api.binance.vision` 可达。
- 需求：APK 免登录（配置写 `.env`）；实时模拟盘记录收益/持仓，计算手续费与资金费，数据来自接口。

## 数据源

- Gate USDT 永续 `GOOGL_USDT`（对应现有 GOOGL 标的）：标记价、1m K 线、资金费率、8h 结算（`funding_interval=28800`）。
- 合约参数：1 张 = 0.01 GOOGL，最小价格变动 0.01，`order_size_min=1`。
- 探针：`/futures/usdt/tickers?contract=GOOGL_USDT`、`/futures/usdt/contracts/GOOGL_USDT`、`/futures/usdt/funding_rate?contract=...&limit=10`。

## 后端

- `src/gridtrade/api/paper.py`：
  - `GateFeed` 公开 REST；`PaperEngine` 后台线程每 `poll_seconds` 拉标记价；
  - 网格：锚点 ± (level∓1)×step，相邻格挂买卖单，标记价触达按挂单价成交（maker）；
  - 手续费 maker/taker bp；止损平仓用 taker；
  - 资金费：到 `funding_next_apply` 时 `cash -= position × mark × rate`，费率取 Gate funding 历史中与结算时间最接近的一条（±15 分钟）；
  - 权益 = 现金 + 持仓 ×（mark − 均价）；峰值/回撤；超阈值自动平仓并 `halted`；
  - 状态、成交、权益采样（15s）、资金费写入 `var/paper.db`（SQLite），重启恢复；
  - `start/stop/reset/autostart`；autostart 在后台线程执行，行情不可达不阻塞 API 启动，失败每 15s 重试；
  - 校验间距不能小于 tick（过小报错）。
- `config.py`：新增 `.env` 加载（真实环境变量优先）+ `PaperConfig`（enabled/autostart/source/symbol/capital/leverage/spacing_bp/levels/stop_dd_pct/maker_fee_bp/taker_fee_bp/poll_seconds）。默认 `enabled=False`，由 `.env` 打开。
- `app.py`：应用启动 `paper.autostart()`、关闭 `paper.close()`；`/api/paper`、`/api/paper/start`、`/api/paper/stop`、`/api/paper/reset`；MODES.paper 改为可用。
- 测试 `tests/test_paper.py` 4 个用例：成交/手续费/已实现、资金费多空符号、止损与持久化、reset；全量 **57 passed**。

## 前端

- `web/src/pages/Paper.tsx`：状态徽标、标记价/资金费率/下次结算、权益/现金/持仓、收益与成本（未实现/已实现/累计/手续费/资金费/回撤）、网格（锚点/步长/每格/最大持仓/买卖价）、权益图（EquityChart）、参数表单、成交表、资金费表、启动/停止/重置；3s 轮询。
- 路由 `#/paper`，侧边栏与移动“更多”均可进入；390×844 无横向溢出。

## 配置

- 服务端：仓库根 `.env`（gitignore，600），systemd `EnvironmentFile=/home/ubuntu/gridtrade/.env`；模板 `.env.example`。含 `GRIDTRADE_TOKEN` 与 `GRIDTRADE_PAPER_*`。
- APK：`apk/.env`（gitignore，600）含 `SERVER_URL`、`TOKEN`；`apk/build.sh` 生成 `apk/build/gen/com/gridtrade/panel/BuildConfig.java`；`MainActivity` 有令牌时跳过设置页。模板 `apk/.env.example`。令牌轮换后需重建 APK。

## 部署与验证

- 服务器 systemd 改为 `EnvironmentFile`；`.env` 中模拟盘 `SPACING_BP=10`、`LEVELS=20`、`LEVERAGE=2`、`CAPITAL=10000`，`AUTOSTART=1`。
- 公网验证：模拟盘 `running`、`GOOGL_USDT` 标记价更新、真实成交/手续费/持仓/权益落库；启停、移动视口、权益图正常；回放回归成功。
- 演示用 2bp/0.4bp 网格曾产生多笔成交；随后删除 `var/paper.db` 并重启，恢复为 `.env` 默认账户（10000 USDT、10bp）。
- APK：全新安装直接进入 `#/overview`，`localStorage['gridtrade.token']` 32 位；真机锁屏后无法继续 UI 验收，备用机 API 25 < minSdk 26。

## 已知限制与后续

- APK 令牌编译进包，泄露即令牌泄露；仅装自己设备。
- 资金费为近似（最近费率 + 当前标记价）；无盘口/滑点模型。
- 行情为 3s REST 轮询，可升级 Gate WebSocket。
- 待确认：默认参数/标的是否合适、Web 是否也免登录、是否上 HTTPS。
- 后续可做：网格重锚定、多空库存可视化、按费率等级计费、CSV 导出、与回测对比。
