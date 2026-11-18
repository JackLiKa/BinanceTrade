# 16 移除 Gate 凭据，切换 Binance-only（2026-11-18）

> **用途**：记录移除 Gate API Key、隐藏 Gate 实盘页面、模拟盘行情切换到 Binance 东京节点的过程与当前状态。
> **读者**：维护实盘/模拟盘、排查行情源的人。
> **最后核实**：2026-11-18 · 代码基线 `main`

## 1. 移除内容

- 服务器 `.env` 删除：
  - `GATE_API_KEY`
  - `GATE_API_SECRET`
- `GRIDTRADE_LIVE_ENABLED=0`、`GRIDTRADE_LIVE_TRADING=0`（只读开关也关闭，不再请求 Gate）。
- `/admin` 删除“实盘配置（Gate）”菜单与卡片、API Key/Secret 输入、清除凭据、Gate 限额表单。
- 面板 `#/live` 不再渲染 Gate 页面，改为 **Binance 实盘只读视图**（账户/持仓/挂单/交割单/历史订单）。
- 模拟盘来源从 Gate 公开行情切换为 **Binance 东京节点**（`GRIDTRADE_PAPER_SOURCE=binance`）。
- Gate 私有代码（`live_gate.py`、旧 `Live.tsx`）保留为历史，不再被 UI/配置使用，无任何凭据。

## 2. 模拟盘 Binance 行情

东京适配器新增两个公开行情端点（无需 API Key）：

| 端点 | 内容 |
| --- | --- |
| `GET /market/contract?symbol=GOOGLUSDT` | exchangeInfo 过滤：tick/step/minQty、maker/taker 假设、下一次资金费 |
| `GET /market/tickers?symbols=GOOGLUSDT,SKHYUSDT` | premiumIndex + 24h ticker：标记价/指数价/涨跌幅/资金费率 |
| `GET /market/funding?symbol=&limit=` | 资金费历史 |

面板 `paper.py` 新增 `NodeFeed`：
- 通过 `GRIDTRADE_BINANCE_NODE_URL` 调节点；
- 兼容下划线代码（`GOOGL_USDT` → `GOOGLUSDT`）；
- 模拟盘仍计算手续费/资金费/滑点，落库 `var/paper.db`；
- 数据源字段 `snapshot.source = "binance"`。

切换后重置过模拟盘：当前配置为 2 个标的（`GOOGL_USDT`、`SKHY_USDT`），权益 10.0 USDT（沿用用户之前 10U 参数）。需要 4 标的可在 `/admin#/paper` 改回。

## 3. 验证

- 服务器 `.env` 已无 `GATE_*`；`/api/paper` 返回 `source=binance`、`last_error=null`。
- `#/live` 手机真机显示 “实盘 · Binance 只读”，含账户/持仓/挂单/交割单。
- `/admin` 菜单无“实盘配置”/Gate 字样。
- `pytest` **162 项**通过；Web 构建通过。

## 4. 注意

- Gate 公开数据仍在旧的 `GateFeed` 代码里，仅当 `GRIDTRADE_PAPER_SOURCE=gate` 时使用；默认不再使用。
- Gate 私有 API 代码保留但未配置/未启用；若要彻底删代码，需另行删除 `live_gate.py`、`/api/live*`、`Live.tsx` 与相关测试。
- 实盘记录目前来自 Binance 东京节点（只读），面板不能下单。
