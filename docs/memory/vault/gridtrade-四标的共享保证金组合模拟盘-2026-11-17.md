---
title: gridtrade 四标的共享保证金组合模拟盘（2026-11-17）
tags:
  - gridtrade
  - paper-trading
  - portfolio
  - gate
  - multi-symbol
verified: true
created: '2026-11-17T14:14:36+08:00'
---

# gridtrade 四标的共享保证金组合模拟盘（2026-11-17）

**重点：模拟盘从单标的升级为 4 标的共享保证金组合（SKHY_USDT / SPCX_USDT / GOOGL_USDT / AMGN_USDT），已在服务器用 Gate 真实行情自动运行；手续费与 8h 资金费按标的分别计算并汇总，组合权益、持仓、成交、资金费全部落库。**

## 需求与决策

- 用户选定标的：`SKHYUSDT`、`SPCXUSDT`、`GOOGLUSDT`、`AMGNUSDT`（Binance 名称），Gate 对应 `*_USDT`，四个都有永续且价格一致。
- 组合方式：**共享保证金动态分配**（用户选择），不设固定权重：所有标共用 `权益 × 杠杆` 的总名义上限；每个标的初始按 `本金×杠杆/(标的数×层数)` 定每格数量；成交前校验 `gross + 新名义 ≤ 权益×杠杆`，实际占用随行情动态变化。
- 实盘：用户选择先做混合模拟盘，实盘保持锁定；Gate 私有 API 下单/对账/熔断尚未实现，后续需 API Key 与最小仓位验证。

## 实现

- `src/gridtrade/api/config.py`：`PaperConfig.symbols: list[str]`，`GRIDTRADE_PAPER_SYMBOLS` 逗号分隔（兼容旧的单数 `GRIDTRADE_PAPER_SYMBOL`）。
- `src/gridtrade/api/paper.py`（重写）：
  - `GateFeed.tickers()` 一次拉全量行情，按需过滤；
  - `SymbolState` 每标的价格/网格/持仓；`PortfolioAccount` 共享现金、已实现、手续费、资金费、峰值；
  - 每个标的独立 `_match`，成交前 `_has_margin` 校验共享保证金；
  - 资金费逐标的结算：`cash -= position × mark × rate`，费率取 Gate funding 历史中与 `funding_next_apply` 最接近的一条（±15 分钟）；
  - 组合权益 = 现金 + Σ 未实现；组合回撤触发止损时全部平仓并 `halted`；
  - SQLite：`paper_account`、`paper_symbols`、`paper_fills(symbol)`、`paper_equity`、`paper_funding(symbol)`；v1 单标的库启动时自动重建；
  - API 快照新增 `symbols`、`portfolio[]`、`account.gross_notional/margin_used`；`fills/funding` 带 `symbol`。
- `web/src/pages/Paper.tsx`：改为“实时组合模拟盘”：组合权益/收益/总名义/成本，4 标的持仓表（标记价、24h、资金费、持仓、均价、未实现、买卖价、名义），组合权益图，参数，带标的的成交与资金费表。
- `tests/test_paper.py` 重写为 5 个用例：组格数量、共享手续费、保证金上限、逐标的资金费净额、组合止损与持久化、重置重锚定。全量 **58 passed**。

## 部署与验证

- 服务器 `.env`：`GRIDTRADE_PAPER_SYMBOLS=SKHY_USDT,SPCX_USDT,GOOGL_USDT,AMGN_USDT`，`CAPITAL=10000`、`LEVERAGE=2`、`SPACING_BP=10`、`LEVELS=20`、`STOP_DD_PCT=10`、自动启动。
- 删除旧 `var/paper.db` 后重启，服务自动建立 4 标的组合账户。
- 真实验证：本地与服务器都把间距临时调到 3bp，SKHY/SPCX/AMGN/GOOGL 产生多笔成交，`gross`、手续费、持仓、组合权益同步变化；随后删除库并重启恢复默认 10bp 账户。
- 公网 `/api/paper`：`status=running`、4 标的、标记价持续更新；页面桌面与 390px 移动视口无横向溢出，无 4xx/无异常。
- APK 免登录不变（同源 Web 产物自动加载组合页，无需重装）。

## 已知限制

- AMGN 在 Gate 24h 成交额仅约 $1k，纸面按挂单价成交会偏乐观；单一 `spacing_bp` 对 AMGN（tick 0.1）要求 ≥约 2.2bp，对低价标的偏宽，后续可加每标的覆盖参数。
- 资金费为近似（最近费率 + 当前标记价）；无盘口/滑点；实盘未启用。
- 共享保证金不设权重；如需风险平价或自定义权重需另加配置。
