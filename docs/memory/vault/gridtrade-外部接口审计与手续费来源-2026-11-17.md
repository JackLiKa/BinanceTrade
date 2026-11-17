---
title: gridtrade 外部接口审计与手续费来源（2026-11-17）
tags:
  - gridtrade
  - api-audit
  - gate
  - binance
  - fees
verified: true
created: '2026-11-17T14:31:39+08:00'
---

# 外部接口审计与手续费来源（2026-11-17）

**重点：审计确认应用只调用官方公开接口；模拟盘手续费改为直接使用 Gate 合约返回的 `maker_fee_rate/taker_fee_rate`（当前四标的 maker -0.000075、taker 0.00075），不再用固定 2/5bp。**

## 审计方法

- 扫描源码：`src/gridtrade/api/live.py`、`src/gridtrade/api/paper.py`、`research/fetch.py`。
- 对照记忆库《Binance API 完整接口目录（2026-11）》中 USDⓈ-M Futures 行情章节；Gate 用官方 API v4 文档 + 官方 SDK（gateapi-nodejs docs/FuturesApi.md，因 gate.io 文档站对本网络 403）交叉验证。
- 增加自动校验 `tests/test_external_endpoints.py`：源码出现未登记的 `/fapi/*`、`/futures/*` 路径或非 `fapi.binance.com`/`api.gateio.ws` host 即失败。

## Binance USDⓈ-M Futures（7 个，全部在 catalog 内）

`/fapi/v1/premiumIndex`、`/fapi/v1/ticker/24hr`、`/fapi/v1/klines`、`/fapi/v1/fundingRate`、`/fapi/v1/exchangeInfo`、`/fapi/v1/fundingInfo`、`/fapi/v1/tradingSchedule`。
用于实时快照与数据集抓取；服务器出口访问不了 fapi，面板回退数据集。

## Gate USDT 永续（3 个，官方公开行情）

- `GET /futures/{settle}/contracts/{contract}`（费率、tick、乘数、资金费间隔/下次结算）
- `GET /futures/{settle}/tickers`（标记价/指数价/资金费率/涨跌幅）
- `GET /futures/{settle}/funding_rate`（资金费历史，取与结算时刻最近一条）

`settle=usdt`，标的 SKHY_USDT/SPCX_USDT/GOOGL_USDT/AMGN_USDT。

## 手续费与资金费口径变更

- 新增 `GRIDTRADE_PAPER_USE_EXCHANGE_FEES`（默认 1）；为 1 时使用合约 `maker_fee_rate/taker_fee_rate`，缺失才回退 `GRIDTRADE_PAPER_MAKER_FEE_BP/TAKER_FEE_BP`。
- Gate 四个标的实测：maker `-0.000075`（-0.75bp 返佣）、taker `0.00075`（7.5bp 成本）。负费率按返佣入账：`fee=|qty|×price×rate; cash -= fee`。
- 资金费仍按 `funding_next_apply` 结算：`cash -= position×mark×rate`，费率取 `funding_rate` 历史最近值（±15 分钟）。
- 快照 `portfolio[]` 增加 `maker_fee_bp/taker_fee_bp/fee_source`；前端表格显示“-0.75/7.5bp 合约”。

## 验证

- `pytest` 61 passed（组合引擎 5 + 交易所费率 1 + 接口审计 2 + 原有 53）。
- 服务器部署后 `/api/paper` 四标的 `fee_source=exchange`；用 3bp 网格实测成交，手续费为负（返佣），随后删除库恢复默认 10bp 账户。
- 公网页面显示费率列与“合约”来源，无 4xx/异常。

## 约束

- 新增外部接口必须：确认官方文档 → 更新 `docs/memory/07-外部接口清单与官方文档对照.md` → 更新测试白名单 → 用真实响应校验字段。
- 实盘/私有接口（下单、账户、WebSocket 订单流）尚未接入，需单独审计签名、时钟与错误码。
