---
created: '2026-11-16T11:36:18+08:00'
---

# Binance API 完整接口目录（2026-11）

> 记录日期：2026-11-16
> 来源：Binance Developer Center
> - https://developers.binance.com/en/
> - https://developers.binance.com/en/docs/catalog
> - https://developers.binance.com/legacy-docs/binance-spot-api-docs/README
> - 中文入口：https://www.binance.com/zh-CN/binance-api
>
> 统计口径：新版文档 Catalog 下每个产品的 OpenAPI schema，共 **46 个 schema、984 条 path、1,079 个 operation**。不含 Spot FIX、SBE 二进制行情、旧版单独列出的 NFT / Auto Invest 等。

## 0. 总览

| 大类 | 内容 | path 数 |
|---|---|---:|
| Core Trading | Spot、Margin、U 本位合约、币本位合约、期权、Wallet、Convert | 478 |
| Advanced Trading | Portfolio Margin、PM Pro、Algo、Alpha、Copy Trading、机构借贷、Stocks | 176 |
| Investment & Services | Simple Earn、Staking、Crypto Loan、VIP Loan、双币投资、折扣买币、Mining、Fiat、Gift Card、Pay、C2C、Rebate | 139 |
| VIP & Institutional | Sub Account、CaaS、OMS、KYC SaaS、Fund Account、Link Plus、Spot Block Matching、VIP CaaS、VIP Service | 140 |
| Web3 | Prediction Trading | 51 |
| **合计** |  | **984** |

### 产品/协议明细

| 产品 | 协议 | 主要前缀 | path 数 |
|---|---|---|---:|
| Spot 现货 | REST | `/api/v3`、`/sapi/v1` | 44 |
| Spot 现货 | WebSocket API | `ws-api/v3` | 55 |
| Spot 现货 | WebSocket Streams | `stream.binance.com` | 15 |
| Margin 杠杆 | REST | `/sapi/v1/margin` | 55 |
| USDⓈ-M Futures | REST | `/fapi/v1`、`/fapi/v2`、`/fapi/v3`、`/futures/data` | 83 |
| USDⓈ-M Futures | WebSocket API | `ws-fapi` | 18 |
| USDⓈ-M Futures | WebSocket Streams | `fstream` | 20 |
| COIN-M Futures | REST | `/dapi/v1`、`/futures/data` | 56 |
| COIN-M Futures | WebSocket API | `ws-dapi` | 10 |
| COIN-M Futures | WebSocket Streams | `dstream` | 19 |
| Options 期权 | REST | `/eapi/v1` | 35 |
| Options 期权 | WebSocket Streams | `nbstream/eoptions` | 10 |
| Wallet 钱包 | REST | `/sapi/v1` | 49 |
| Convert 闪兑 | REST | `/sapi/v1/convert` | 9 |
| Portfolio Margin | REST | `/papi/v1`、`/papi/v2` | 85 |
| Portfolio Margin Pro | REST | `/sapi/v1/portfolio` | 20 |
| Algo Trading | REST | `/sapi/v1/algo` | 12 |
| Alpha Trading | REST + Streams | `/bapi/defi/v1/public/alpha-trade` | 6 + 13 |
| Copy Trading | REST | `/sapi/v1/copyTrading` | 2 |
| Institutional Loan | REST | `/sapi/v1/margin/loan-group` | 15 |
| Stocks Trading | REST + Streams | `/sapi/v1/equity` | 16 + 7 |
| Simple Earn | REST | `/sapi/v1/simple-earn`、`/bfusd`、`/rwusd` | 41 |
| Staking | REST | `/sapi/v1/eth-staking`、`/sol-staking`、`/onchain-yields`、`/soft-staking` | 37 |
| Crypto Loan | REST | `/sapi/v2/loan/flexible` | 12 |
| VIP Loan | REST | `/sapi/v1/loan/vip` | 14 |
| Dual Investment | REST | `/sapi/v1/dci` | 4 |
| Discount Buy | REST | `/sapi/v1/accumulator` | 4 |
| Mining | REST | `/sapi/v1/mining` | 13 |
| Fiat | REST | `/sapi/v1/fiat` | 5 |
| Gift Card | REST | `/sapi/v1/giftcard` | 6 |
| Binance Pay | REST | `/sapi/v1/pay` | 1 |
| C2C | REST | `/sapi/v1/c2c` | 1 |
| Rebate | REST | `/sapi/v1/rebate` | 1 |
| Sub Account | REST | `/sapi/v1/sub-account`、`/managed-subaccount` | 45 |
| CaaS | REST | `/sapi/v1/broker` | 26 |
| OMS Toolkit | REST | `/sapi/v1/apiReferral`、`/v1/api-key` | 18 |
| KYC SaaS | REST | `/bapi/ekyc/v2/public/ekyc` | 12 |
| Fund Account | REST | `/sapi/v1/vip/fund-info`、`/portfolio-account` | 9 |
| Link Plus | REST | `/sapi/v1/vip/link-plus`、`/liquidity-programs` | 8 |
| Spot Block Matching | REST | `/sapi/v1/block-match` | 7 |
| VIP CaaS | REST | `/sapi/v1/vip/caas/commission` | 6 |
| VIP Service | REST | `/sapi/v1/vip/vip-portal`、`/vip/liquidity-programs` | 9 |
| Prediction Trading | REST + Streams | `/sapi/v1/w3w/wallet/prediction` | 36 + 15 |

## 1. 接口形态

| 形态 | 说明 | 入口 |
|---|---|---|
| REST | HTTP JSON，最常用 | `api.binance.com`、`fapi`、`dapi`、`eapi`、`papi` |
| WebSocket API | 通过 WebSocket 发请求/收响应 | Spot `wss://ws-api.binance.com:443/ws-api/v3`；U 本位 `wss://ws-fapi.binance.com/ws-fapi/v1` |
| WebSocket Streams | 服务器推送行情/用户数据 | `wss://stream.binance.com:9443`、`wss://fstream.binance.com`、`wss://dstream.binance.com` |
| FIX API | 机构级 FIX 协议 | 旧版 Spot 文档 FIX API |
| SBE | 二进制行情编码 | Spot SBE Market Data Streams |
| OAuth / OpenAPI | 第三方应用授权 | 旧版文档根目录 Binance OpenAPI |

---

## 2. Spot 现货

### 2.1 Spot REST（44 条 path）

**通用与规则**
- `GET /api/v3/ping`
- `GET /api/v3/time`
- `GET /api/v3/exchangeInfo`
- `GET /api/v3/executionRules`

**行情**
- `GET /api/v3/depth`
- `GET /api/v3/trades`
- `GET /api/v3/historicalTrades`
- `GET /api/v3/historicalBlockTrades`
- `GET /api/v3/aggTrades`
- `GET /api/v3/klines`
- `GET /api/v3/uiKlines`
- `GET /api/v3/avgPrice`
- `GET /api/v3/ticker`
- `GET /api/v3/ticker/24hr`
- `GET /api/v3/ticker/price`
- `GET /api/v3/ticker/bookTicker`
- `GET /api/v3/ticker/tradingDay`
- `GET /api/v3/referencePrice`
- `GET /api/v3/referencePrice/calculation`

**交易**
- `POST /api/v3/order`：下单
- `GET /api/v3/order`：查单
- `DELETE /api/v3/order`：撤单
- `POST /api/v3/order/test`：测试下单
- `POST /api/v3/order/cancelReplace`：撤单并重新下单
- `PUT /api/v3/order/amend/keepPriority`：改单并保持优先级
- `POST /api/v3/order/oco`：OCO（已弃用）
- `POST /api/v3/orderList/oco`
- `POST /api/v3/orderList/oto`
- `POST /api/v3/orderList/otoco`
- `POST /api/v3/orderList/opo`
- `POST /api/v3/orderList/opoco`
- `GET /api/v3/orderList`
- `DELETE /api/v3/orderList`
- `POST /api/v3/sor/order`：SOR 下单
- `POST /api/v3/sor/order/test`
- `DELETE /api/v3/openOrders`：撤销某交易对全部挂单

**账户**
- `GET /api/v3/account`
- `GET /api/v3/account/commission`
- `GET /api/v3/openOrders`
- `GET /api/v3/allOrders`
- `GET /api/v3/allOrderList`
- `GET /api/v3/openOrderList`
- `GET /api/v3/myTrades`
- `GET /api/v3/myAllocations`
- `GET /api/v3/myFilters`
- `GET /api/v3/myPreventedMatches`
- `GET /api/v3/order/amendments`
- `GET /api/v3/rateLimit/order`

### 2.2 Spot WebSocket API（55 条）

**会话**
`session.logon`、`session.logout`、`session.status`、`session.subscriptions`

**通用/行情**
`ping`、`time`、`exchangeInfo`、`executionRules`、`depth`、`klines`、`uiKlines`、`avgPrice`、`ticker`、`ticker.24hr`、`ticker.book`、`ticker.price`、`ticker.tradingDay`、`trades.recent`、`trades.historical`、`trades.aggregate`、`blockTrades.historical`、`referencePrice`、`referencePrice.calculation`

**交易**
`order.place`、`order.test`、`order.cancel`、`order.cancelReplace`、`order.amend.keepPriority`、`openOrders.cancelAll`、`orderList.place`、`orderList.place.oco`、`orderList.place.oto`、`orderList.place.otoco`、`orderList.place.opo`、`orderList.place.opoco`、`orderList.cancel`、`sor.order.place`、`sor.order.test`

**账户**
`account.status`、`account.commission`、`account.rateLimits.orders`、`allOrders`、`allOrderLists`、`openOrders.status`、`openOrderLists.status`、`order.status`、`orderList.status`、`myTrades`、`myAllocations`、`myFilters`、`myPreventedMatches`、`order.amendments`

**用户数据流**
`userDataStream.subscribe`、`userDataStream.subscribe.signature`、`userDataStream.unsubscribe`

### 2.3 Spot WebSocket Streams（15 条）

- `<symbol>@aggTrade`
- `<symbol>@trade`
- `<symbol>@kline_<interval>`
- `<symbol>@kline_<interval>@+08:00`
- `<symbol>@miniTicker`
- `<symbol>@ticker`
- `<symbol>@ticker_<windowSize>`
- `<symbol>@bookTicker`
- `<symbol>@depth@<updateSpeed>`
- `<symbol>@depth<levels>@<updateSpeed>`
- `<symbol>@avgPrice`
- `<symbol>@blockTrade`
- `<symbol>@referencePrice`
- `!miniTicker@arr`
- `!ticker_<windowSize>@arr`

### 2.4 Spot FIX / SBE

- FIX API：会话管理、下单/撤单/改单、订单状态、行情。
- SBE Market Data：Simple Binary Encoding 二进制行情流。

---

## 3. Margin 杠杆（55 条 path）

**账户与风险**
- `/sapi/v1/margin/account`
- `/sapi/v1/margin/tradeCoeff`
- `/sapi/v1/margin/max-leverage`
- `/sapi/v1/bnbBurn`
- `/sapi/v1/margin/capital-flow`
- `/sapi/v1/margin/interestHistory`
- `/sapi/v1/margin/interestRateHistory`
- `/sapi/v1/margin/next-hourly-interest-rate`
- `/sapi/v1/margin/crossMarginCollateralRatio`
- `/sapi/v1/margin/risk-based-liquidation-ratio`
- `/sapi/v1/margin/restricted-asset`
- `/sapi/v1/margin/forceLiquidationRec`
- `/sapi/v1/margin/available-inventory`

**交易对与资产**
- `/sapi/v1/margin/allPairs`
- `/sapi/v1/margin/isolated/allPairs`
- `/sapi/v1/margin/allAssets`
- `/sapi/v1/margin/priceIndex`
- `/sapi/v1/margin/delist-schedule`
- `/sapi/v1/margin/list-schedule`
- `/sapi/v1/margin/limit-price-pairs`
- `/sapi/v1/margin/crossMarginData`
- `/sapi/v1/margin/isolatedMarginData`
- `/sapi/v1/margin/leverageBracket`
- `/sapi/v1/margin/isolatedMarginTier`

**借还、划转、小额负债**
- `/sapi/v1/margin/borrow-repay`
- `/sapi/v1/margin/maxBorrowable`
- `/sapi/v1/margin/maxTransferable`
- `/sapi/v1/margin/transfer`
- `/sapi/v1/margin/liquidation-loan`
- `/sapi/v1/margin/liquidation-loan/repay`
- `/sapi/v1/margin/liquidation-loan/repay-history`
- `/sapi/v1/margin/exchange-small-liability`
- `/sapi/v1/margin/exchange-small-liability-history`

**逐仓**
- `/sapi/v1/margin/isolated/account`
- `/sapi/v1/margin/isolated/accountLimit`

**订单**
- `/sapi/v1/margin/order`
- `/sapi/v1/margin/openOrders`
- `/sapi/v1/margin/orderList`
- `/sapi/v1/margin/allOrders`
- `/sapi/v1/margin/allOrderList`
- `/sapi/v1/margin/openOrderList`
- `/sapi/v1/margin/oto/openOrderList`
- `/sapi/v1/margin/myTrades`
- `/sapi/v1/margin/myPreventedMatches`
- `/sapi/v1/margin/order/oco`
- `/sapi/v1/margin/order/oto`
- `/sapi/v1/margin/order/otoco`
- `/sapi/v1/margin/manual-liquidation`
- `/sapi/v1/margin/rateLimit/order`

**User Data Stream / 特殊 Key**
- `/sapi/v1/margin/listen-key`
- `/sapi/v2/margin/listen-key`
- `/sapi/v1/margin/apiKey`
- `/sapi/v1/margin/apiKey/ip`
- `/sapi/v1/margin/api-key-list`
- `/sapi/v1/margin/exit-special-key-mode`

---

## 4. USDⓈ-M 合约（`/fapi`）

### 4.1 REST（83 条 path）

**账户**
- `/fapi/v2/account`
- `/fapi/v3/account`
- `/fapi/v2/balance`
- `/fapi/v3/balance`
- `/fapi/v1/accountConfig`
- `/fapi/v1/apiTradingStatus`
- `/fapi/v1/feeBurn`
- `/fapi/v1/multiAssetsMargin`
- `/fapi/v1/positionSide/dual`
- `/fapi/v1/leverageBracket`
- `/fapi/v1/symbolConfig`
- `/fapi/v1/commissionRate`
- `/fapi/v1/rateLimit/order`
- `/fapi/v1/income`
- `/fapi/v1/income/asyn`
- `/fapi/v1/income/asyn/id`
- `/fapi/v1/order/asyn`
- `/fapi/v1/order/asyn/id`
- `/fapi/v1/trade/asyn`
- `/fapi/v1/trade/asyn/id`
- `/fapi/v1/pmAccountInfo`
- `/fapi/v1/stock/contract`

**行情**
- `/fapi/v1/ping`
- `/fapi/v1/time`
- `/fapi/v1/exchangeInfo`
- `/fapi/v1/depth`
- `/fapi/v1/rpiDepth`
- `/fapi/v1/trades`
- `/fapi/v1/historicalTrades`
- `/fapi/v1/aggTrades`
- `/fapi/v1/klines`
- `/fapi/v1/continuousKlines`
- `/fapi/v1/indexPriceKlines`
- `/fapi/v1/markPriceKlines`
- `/fapi/v1/premiumIndexKlines`
- `/fapi/v1/premiumIndex`
- `/fapi/v1/fundingRate`
- `/fapi/v1/fundingInfo`
- `/fapi/v1/openInterest`
- `/fapi/v1/ticker/price`
- `/fapi/v2/ticker/price`
- `/fapi/v1/ticker/24hr`
- `/fapi/v1/ticker/bookTicker`
- `/fapi/v1/indexInfo`
- `/fapi/v1/constituents`
- `/fapi/v1/insuranceBalance`
- `/fapi/v1/assetIndex`
- `/fapi/v1/symbolAdlRisk`
- `/fapi/v1/tradingSchedule`
- `/futures/data/basis`
- `/futures/data/openInterestHist`
- `/futures/data/delivery-price`
- `/futures/data/topLongShortAccountRatio`
- `/futures/data/topLongShortPositionRatio`
- `/futures/data/globalLongShortAccountRatio`
- `/futures/data/takerlongshortRatio`

**交易**
- `/fapi/v1/order`
- `/fapi/v1/batchOrders`
- `/fapi/v1/allOpenOrders`
- `/fapi/v1/openOrders`
- `/fapi/v1/openOrder`
- `/fapi/v1/allOrders`
- `/fapi/v1/userTrades`
- `/fapi/v1/forceOrders`
- `/fapi/v1/countdownCancelAll`
- `/fapi/v1/positionMargin`
- `/fapi/v1/positionMargin/history`
- `/fapi/v1/leverage`
- `/fapi/v1/marginType`
- `/fapi/v2/positionRisk`
- `/fapi/v3/positionRisk`
- `/fapi/v1/adlQuantile`
- `/fapi/v1/orderAmendment`
- `/fapi/v1/algoOrder`
- `/fapi/v1/algoOpenOrders`
- `/fapi/v1/openAlgoOrders`
- `/fapi/v1/allAlgoOrders`
- `/fapi/v1/order/test`
- `/fapi/v1/listenKey`

**合约内闪兑**
- `/fapi/v1/convert/exchangeInfo`
- `/fapi/v1/convert/getQuote`
- `/fapi/v1/convert/acceptQuote`
- `/fapi/v1/convert/orderStatus`

### 4.2 WebSocket API（18 条）

`account.status`、`v2/account.status`、`account.balance`、`v2/account.balance`、`account.position`、`v2/account.position`、`order.place`、`order.cancel`、`order.modify`、`order.status`、`algoOrder.place`、`algoOrder.cancel`、`depth`、`ticker.book`、`ticker.price`、`userDataStream.start`、`userDataStream.ping`、`userDataStream.stop`

### 4.3 WebSocket Streams（20 条）

- `<symbol>@aggTrade`
- `<symbol>@markPrice@<updateSpeed>`
- `!markPrice@arr@<updateSpeed>`
- `<symbol>@kline_<interval>`
- `<pair>_<contractType>@continuousKline_<interval>`
- `<symbol>@miniTicker`
- `<symbol>@ticker`
- `!miniTicker@arr`
- `!ticker@arr`
- `<symbol>@bookTicker`
- `!bookTicker`
- `<symbol>@depth@<updateSpeed>`
- `<symbol>@depth<levels>@<updateSpeed>`
- `<symbol>@forceOrder`
- `!forceOrder@arr`
- `<symbol>@compositeIndex`
- `!contractInfo`
- `!assetIndex@arr`
- `tradingSession`
- `<symbol>@rpiDepth@500ms`

---

## 5. COIN-M 合约（`/dapi`）

REST 56 条 path，与 U 本位高度对应，主要差异：

- 账户只有 `/dapi/v1/account`、`/dapi/v1/balance`。
- 杠杆 bracket 分 `/dapi/v1/leverageBracket`（按 pair）和 `/dapi/v2/leverageBracket`（按 symbol）。
- 行情包含 `indexPrice`、指数 K 线、标记价格 K 线、`/futures/data/takerBuySellVol` 等。
- 无 U 本位的多资产模式、资产指数、RPI 深度、合约内闪兑。
- 交易接口：`/dapi/v1/order`、`/batchOrders`、`/allOpenOrders`、`/openOrders`、`/openOrder`、`/allOrders`、`/userTrades`、`/forceOrders`、`/countdownCancelAll`、`/positionMargin`、`/positionMargin/history`、`/leverage`、`/marginType`、`/positionRisk`、`/adlQuantile`、`/orderAmendment`、`/order/test`、`/listenKey`。

WebSocket API 10 条：`account.status`、`account.balance`、`account.position`、`order.place`、`order.cancel`、`order.modify`、`order.status`、`userDataStream.start`、`userDataStream.ping`、`userDataStream.stop`。

WebSocket Streams 19 条：aggTrade、markPrice、kline、continuousKline、indexPrice、indexPriceKline、markPriceKline、miniTicker、ticker、bookTicker、depth、partial depth、forceOrder、contractInfo、全市场 ticker/miniTicker/强平/最优挂单等。

---

## 6. Options 期权（`/eapi`）

### REST（35 条 path）

**行情**
- `/eapi/v1/ping`
- `/eapi/v1/time`
- `/eapi/v1/exchangeInfo`
- `/eapi/v1/klines`
- `/eapi/v1/depth`
- `/eapi/v1/trades`
- `/eapi/v1/blockTrades`
- `/eapi/v1/ticker`
- `/eapi/v1/mark`
- `/eapi/v1/index`
- `/eapi/v1/openInterest`
- `/eapi/v1/exerciseHistory`

**账户**
- `/eapi/v1/marginAccount`
- `/eapi/v1/bill`
- `/eapi/v1/position`
- `/eapi/v1/userTrades`
- `/eapi/v1/commission`
- `/eapi/v1/exerciseRecord`
- `/eapi/v1/listenKey`

**交易**
- `/eapi/v1/order`
- `/eapi/v1/batchOrders`
- `/eapi/v1/allOpenOrders`
- `/eapi/v1/allOpenOrdersByUnderlying`
- `/eapi/v1/openOrders`
- `/eapi/v1/historyOrders`
- `/eapi/v1/countdownCancelAll`
- `/eapi/v1/countdownCancelAllHeartBeat`
- `/eapi/v1/mmp`
- `/eapi/v1/mmpSet`
- `/eapi/v1/mmpReset`
- `/eapi/v1/stock/contract`

**大宗交易**
- `/eapi/v1/block/order/create`
- `/eapi/v1/block/order/execute`
- `/eapi/v1/block/order/orders`
- `/eapi/v1/block/user-trades`

### WebSocket Streams（10 条）

- `!index@arr`
- `<symbol>@kline_<interval>`
- `<underlying>@optionMarkPrice`
- `!optionSymbol`
- `<underlying>@openInterest@<expirationDate>`
- `<symbol>@depth@<updateSpeed>`
- `<symbol>@bookTicker`
- `<symbol>@depth<level>@<updateSpeed>`
- `<symbol>@optionTicker<expirationDate>`
- `<symbol>@optionTrade`

---

## 7. Portfolio Margin

### 7.1 Portfolio Margin（`/papi`，85 条 path）

**账户/资金**
- `/papi/v1/account`
- `/papi/v1/balance`
- `/papi/v1/um/account`
- `/papi/v2/um/account`
- `/papi/v1/cm/account`
- `/papi/v1/um/accountConfig`
- `/papi/v1/um/symbolConfig`
- `/papi/v1/um/leverageBracket`
- `/papi/v1/cm/leverageBracket`
- `/papi/v1/um/commissionRate`
- `/papi/v1/cm/commissionRate`
- `/papi/v1/um/income`
- `/papi/v1/cm/income`
- `/papi/v1/margin/marginLoan`
- `/papi/v1/margin/repayLoan`
- `/papi/v1/margin/marginInterestHistory`
- `/papi/v1/margin/maxBorrowable`
- `/papi/v1/margin/maxWithdraw`
- `/papi/v1/portfolio/interest-history`
- `/papi/v1/portfolio/negative-balance-exchange-record`
- `/papi/v1/repay-futures-switch`
- `/papi/v1/repay-futures-negative-balance`
- `/papi/v1/auto-collection`
- `/papi/v1/asset-collection`
- `/papi/v1/bnb-transfer`
- `/papi/v1/rateLimit/order`

**UM 交易**
- `/papi/v1/um/order`
- `/papi/v1/um/openOrders`
- `/papi/v1/um/openOrder`
- `/papi/v1/um/allOrders`
- `/papi/v1/um/positionRisk`
- `/papi/v1/um/adlQuantile`
- `/papi/v1/um/orderAmendment`
- `/papi/v1/um/userTrades`
- `/papi/v1/um/forceOrders`
- `/papi/v1/um/leverage`
- `/papi/v1/um/positionSide/dual`
- `/papi/v1/um/feeBurn`
- `/papi/v1/um/algo/order`
- `/papi/v1/um/algo/openAlgoOrders`
- `/papi/v1/um/algo/allAlgoOrders`
- `/papi/v1/um/algo/algoOrder`
- `/papi/v1/um/algo/allOpenOrders`
- `/papi/v1/um/stock/contract`

**CM 交易**
- `/papi/v1/cm/order`
- `/papi/v1/cm/openOrders`
- `/papi/v1/cm/openOrder`
- `/papi/v1/cm/allOrders`
- `/papi/v1/cm/positionRisk`
- `/papi/v1/cm/adlQuantile`
- `/papi/v1/cm/orderAmendment`
- `/papi/v1/cm/userTrades`
- `/papi/v1/cm/forceOrders`
- `/papi/v1/cm/leverage`
- `/papi/v1/cm/positionSide/dual`
- `/papi/v1/cm/conditional/order`
- `/papi/v1/cm/conditional/openOrder`
- `/papi/v1/cm/conditional/openOrders`
- `/papi/v1/cm/conditional/allOrders`
- `/papi/v1/cm/conditional/orderHistory`
- `/papi/v1/cm/conditional/allOpenOrders`

**Margin 交易**
- `/papi/v1/margin/order`
- `/papi/v1/margin/openOrders`
- `/papi/v1/margin/allOrders`
- `/papi/v1/margin/orderList`
- `/papi/v1/margin/openOrderList`
- `/papi/v1/margin/allOrderList`
- `/papi/v1/margin/order/oco`
- `/papi/v1/margin/myTrades`
- `/papi/v1/margin/forceOrders`
- `/papi/v1/margin/allOpenOrders`
- `/papi/v1/marginLoan`
- `/papi/v1/repayLoan`
- `/papi/v1/margin/repay-debt`

**User Data Stream**
- `/papi/v1/listenKey`

### 7.2 Portfolio Margin Pro（20 条 path）

- `/sapi/v1/portfolio/account`
- `/sapi/v2/portfolio/account`
- `/sapi/v1/portfolio/balance`
- `/sapi/v1/portfolio/bnb-transfer`
- `/sapi/v1/portfolio/repay-futures-switch`
- `/sapi/v1/portfolio/auto-collection`
- `/sapi/v1/portfolio/asset-collection`
- `/sapi/v1/portfolio/delta-mode`
- `/sapi/v1/portfolio/earn-asset-balance`
- `/sapi/v1/portfolio/earn-asset-transfer`
- `/sapi/v1/portfolio/repay`
- `/sapi/v1/portfolio/pmLoan`
- `/sapi/v1/portfolio/pmloan-history`
- `/sapi/v1/portfolio/interest-history`
- `/sapi/v1/portfolio/repay-futures-negative-balance`
- `/sapi/v1/portfolio/margin-call-level`
- `/sapi/v1/portfolio/margin-asset-leverage`
- `/sapi/v1/portfolio/collateralRate`
- `/sapi/v2/portfolio/collateralRate`
- `/sapi/v1/portfolio/asset-index-price`

---

## 8. Wallet 钱包（49 条 path）

**账户**
- `/sapi/v1/account/info`
- `/sapi/v1/account/status`
- `/sapi/v1/account/apiTradingStatus`
- `/sapi/v1/account/apiRestrictions`
- `/sapi/v1/accountSnapshot`
- `/sapi/v1/account/enableFastWithdrawSwitch`
- `/sapi/v1/account/disableFastWithdrawSwitch`

**资产**
- `/sapi/v1/asset/assetDetail`
- `/sapi/v1/asset/assetDividend`
- `/sapi/v1/asset/wallet/balance`
- `/sapi/v3/asset/getUserAsset`
- `/sapi/v1/asset/get-funding-asset`
- `/sapi/v1/asset/transfer`
- `/sapi/v1/asset/tradeFee`
- `/sapi/v1/asset/dust`
- `/sapi/v1/asset/dust-btc`
- `/sapi/v1/asset/dribblet`
- `/sapi/v1/asset/dust-convert/convert`
- `/sapi/v1/asset/dust-convert/query-convertible-assets`
- `/sapi/v1/asset/ledger-transfer/cloud-mining/queryByPage`
- `/sapi/v1/asset/custody/transfer-history`
- `/sapi/v1/spot/asset/tags`
- `/sapi/v1/spot/open-symbol-list`
- `/sapi/v1/spot/delist-schedule`
- `/sapi/v1/bnbBurn`

**充提**
- `/sapi/v1/capital/config/getall`
- `/sapi/v1/capital/deposit/address`
- `/sapi/v1/capital/deposit/address/list`
- `/sapi/v1/capital/deposit/hisrec`
- `/sapi/v1/capital/deposit/credit-apply`
- `/sapi/v1/capital/withdraw/address/list`
- `/sapi/v1/capital/withdraw/quota`
- `/sapi/v1/capital/withdraw/apply`
- `/sapi/v1/capital/withdraw/history`

**Travel Rule / 本地合规实体**
- `/sapi/v1/localentity/questionnaire-requirements`
- `/sapi/v1/localentity/country/list`
- `/sapi/v1/localentity/region/list`
- `/sapi/v1/localentity/vasp`
- `/sapi/v1/localentity/deposit/history`
- `/sapi/v2/localentity/deposit/history`
- `/sapi/v1/localentity/deposit/provide-info`
- `/sapi/v2/localentity/deposit/provide-info`
- `/sapi/v1/localentity/withdraw/history`
- `/sapi/v2/localentity/withdraw/history`
- `/sapi/v1/localentity/withdraw/apply`
- `/sapi/v1/localentity/broker/withdraw/apply`
- `/sapi/v1/localentity/broker/deposit/provide-info`
- `/sapi/v1/addressVerify/list`

**系统**
- `/sapi/v1/system/status`

---

## 9. Sub Account 子账户（45 条 path）

**账户管理**
- `/sapi/v1/sub-account/virtualSubAccount`
- `/sapi/v1/sub-account/list`
- `/sapi/v1/sub-account/status`
- `/sapi/v1/sub-account/transaction-statistics`
- `/sapi/v1/sub-account/futures/enable`
- `/sapi/v1/sub-account/eoptions/enable`

**API Key**
- `/sapi/v1/sub-account/subAccountApi`
- `/sapi/v2/sub-account/subAccountApi`
- `/sapi/v1/sub-account/subAccountApi/ipRestriction`
- `/sapi/v2/sub-account/subAccountApi/ipRestriction`
- `/sapi/v1/sub-account/subAccountApi/ipRestriction/ipList`
- `/sapi/v1/sub-account/subAccountApiPermission`

**资产与持仓**
- `/sapi/v1/sub-account/futures/account`
- `/sapi/v2/sub-account/futures/account`
- `/sapi/v1/sub-account/futures/accountSummary`
- `/sapi/v2/sub-account/futures/accountSummary`
- `/sapi/v1/sub-account/margin/account`
- `/sapi/v1/sub-account/margin/accountSummary`
- `/sapi/v1/sub-account/futures/positionRisk`
- `/sapi/v2/sub-account/futures/positionRisk`
- `/sapi/v3/sub-account/assets`
- `/sapi/v4/sub-account/assets`
- `/sapi/v1/sub-account/spotSummary`

**划转**
- `/sapi/v1/sub-account/futures/transfer`
- `/sapi/v1/sub-account/margin/transfer`
- `/sapi/v1/sub-account/futures/internalTransfer`
- `/sapi/v1/sub-account/futures/move-position`
- `/sapi/v1/sub-account/universalTransfer`
- `/sapi/v1/sub-account/sub/transfer/history`
- `/sapi/v1/sub-account/transfer/subUserHistory`
- `/sapi/v1/sub-account/transfer/subToMaster`
- `/sapi/v1/sub-account/transfer/subToSub`

**充提**
- `/sapi/v1/capital/deposit/subAddress`
- `/sapi/v1/capital/deposit/subHisrec`

**Managed Sub-account**
- `/sapi/v1/managed-subaccount/deposit`
- `/sapi/v1/managed-subaccount/deposit/address`
- `/sapi/v1/managed-subaccount/withdraw`
- `/sapi/v1/managed-subaccount/asset`
- `/sapi/v1/managed-subaccount/marginAsset`
- `/sapi/v1/managed-subaccount/fetch-future-asset`
- `/sapi/v1/managed-subaccount/info`
- `/sapi/v1/managed-subaccount/accountSnapshot`
- `/sapi/v1/managed-subaccount/queryTransLogForInvestor`
- `/sapi/v1/managed-subaccount/queryTransLogForTradeParent`
- `/sapi/v1/managed-subaccount/query-trans-log`

---

## 10. Convert 闪兑（9 条 path）

- `GET /sapi/v1/convert/exchangeInfo`
- `GET /sapi/v1/convert/assetInfo`
- `POST /sapi/v1/convert/getQuote`
- `POST /sapi/v1/convert/acceptQuote`
- `GET /sapi/v1/convert/orderStatus`
- `POST /sapi/v1/convert/limit/placeOrder`
- `POST /sapi/v1/convert/limit/cancelOrder`
- `GET /sapi/v1/convert/limit/queryOpenOrders`
- `GET /sapi/v1/convert/tradeFlow`

---

## 11. Simple Earn / Staking / 借贷

### 11.1 Simple Earn（41 条 path）

**BFUSD**
- `/sapi/v1/bfusd/account`
- `/sapi/v1/bfusd/quota`
- `/sapi/v1/bfusd/history/rateHistory`
- `/sapi/v1/bfusd/history/redemptionHistory`
- `/sapi/v1/bfusd/history/rewardsHistory`
- `/sapi/v1/bfusd/history/subscriptionHistory`
- `/sapi/v1/bfusd/subscribe`
- `/sapi/v1/bfusd/redeem`

**活期 Flexible**
- `/sapi/v1/simple-earn/flexible/list`
- `/sapi/v1/simple-earn/flexible/personalLeftQuota`
- `/sapi/v1/simple-earn/flexible/position`
- `/sapi/v1/simple-earn/flexible/subscriptionPreview`
- `/sapi/v1/simple-earn/flexible/subscribe`
- `/sapi/v1/simple-earn/flexible/redeem`
- `/sapi/v1/simple-earn/flexible/setAutoSubscribe`
- `/sapi/v1/simple-earn/flexible/history/collateralRecord`
- `/sapi/v1/simple-earn/flexible/history/redemptionRecord`
- `/sapi/v1/simple-earn/flexible/history/rewardsRecord`
- `/sapi/v1/simple-earn/flexible/history/subscriptionRecord`
- `/sapi/v1/simple-earn/flexible/history/rateHistory`

**定期 Locked**
- `/sapi/v1/simple-earn/locked/list`
- `/sapi/v1/simple-earn/locked/personalLeftQuota`
- `/sapi/v1/simple-earn/locked/position`
- `/sapi/v1/simple-earn/locked/subscriptionPreview`
- `/sapi/v1/simple-earn/locked/subscribe`
- `/sapi/v1/simple-earn/locked/redeem`
- `/sapi/v1/simple-earn/locked/setAutoSubscribe`
- `/sapi/v1/simple-earn/locked/setRedeemOption`
- `/sapi/v1/simple-earn/locked/history/redemptionRecord`
- `/sapi/v1/simple-earn/locked/history/rewardsRecord`
- `/sapi/v1/simple-earn/locked/history/subscriptionRecord`

**账户 / RWUSD / 活动**
- `/sapi/v1/simple-earn/account`
- `/sapi/v1/rwusd/account`
- `/sapi/v1/rwusd/quota`
- `/sapi/v1/rwusd/history/rateHistory`
- `/sapi/v1/rwusd/history/redemptionHistory`
- `/sapi/v1/rwusd/history/rewardsHistory`
- `/sapi/v1/rwusd/history/subscriptionHistory`
- `/sapi/v1/rwusd/subscribe`
- `/sapi/v1/rwusd/redeem`
- `/sapi/v1/earn/arena/activities`

### 11.2 Staking（37 条 path）

**ETH Staking / WBETH**
- `/sapi/v2/eth-staking/account`
- `/sapi/v1/eth-staking/eth/quota`
- `/sapi/v1/eth-staking/eth/history/redemptionHistory`
- `/sapi/v1/eth-staking/eth/history/stakingHistory`
- `/sapi/v1/eth-staking/eth/history/rateHistory`
- `/sapi/v1/eth-staking/eth/history/wbethRewardsHistory`
- `/sapi/v1/eth-staking/wbeth/history/unwrapHistory`
- `/sapi/v1/eth-staking/wbeth/history/wrapHistory`
- `/sapi/v1/eth-staking/eth/redeem`
- `/sapi/v2/eth-staking/eth/stake`
- `/sapi/v1/eth-staking/wbeth/wrap`

**On-chain Yields**
- `/sapi/v1/onchain-yields/account`
- `/sapi/v1/onchain-yields/locked/list`
- `/sapi/v1/onchain-yields/locked/personalLeftQuota`
- `/sapi/v1/onchain-yields/locked/position`
- `/sapi/v1/onchain-yields/locked/subscriptionPreview`
- `/sapi/v1/onchain-yields/locked/subscribe`
- `/sapi/v1/onchain-yields/locked/redeem`
- `/sapi/v1/onchain-yields/locked/setAutoSubscribe`
- `/sapi/v1/onchain-yields/locked/setRedeemOption`
- `/sapi/v1/onchain-yields/locked/history/redemptionRecord`
- `/sapi/v1/onchain-yields/locked/history/rewardsRecord`
- `/sapi/v1/onchain-yields/locked/history/subscriptionRecord`

**Soft Staking**
- `/sapi/v1/soft-staking/list`
- `/sapi/v1/soft-staking/history/rewardsRecord`
- `/sapi/v1/soft-staking/set`

**SOL Staking / BNSOL**
- `/sapi/v1/sol-staking/account`
- `/sapi/v1/sol-staking/sol/quota`
- `/sapi/v1/sol-staking/sol/stake`
- `/sapi/v1/sol-staking/sol/redeem`
- `/sapi/v1/sol-staking/sol/claim`
- `/sapi/v1/sol-staking/sol/history/rateHistory`
- `/sapi/v1/sol-staking/sol/history/bnsolRewardsHistory`
- `/sapi/v1/sol-staking/sol/history/boostRewardsHistory`
- `/sapi/v1/sol-staking/sol/history/redemptionHistory`
- `/sapi/v1/sol-staking/sol/history/stakingHistory`
- `/sapi/v1/sol-staking/sol/history/unclaimedRewards`

### 11.3 Crypto Loan（12 条 path）

- `/sapi/v2/loan/flexible/borrow`
- `/sapi/v2/loan/flexible/repay`
- `/sapi/v2/loan/flexible/adjust/ltv`
- `/sapi/v2/loan/flexible/repay/rate`
- `/sapi/v2/loan/flexible/loanable/data`
- `/sapi/v2/loan/flexible/collateral/data`
- `/sapi/v2/loan/flexible/borrow/history`
- `/sapi/v2/loan/flexible/repay/history`
- `/sapi/v2/loan/flexible/liquidation/history`
- `/sapi/v2/loan/flexible/ltv/adjustment/history`
- `/sapi/v2/loan/flexible/ongoing/orders`
- `/sapi/v2/loan/interestRateHistory`

### 11.4 VIP Loan（14 条 path）

- `/sapi/v1/loan/vip/borrow`
- `/sapi/v1/loan/vip/repay`
- `/sapi/v1/loan/vip/renew`
- `/sapi/v1/loan/vip/request/interestRate`
- `/sapi/v1/loan/vip/interestRateHistory`
- `/sapi/v1/loan/vip/collateral/data`
- `/sapi/v1/loan/vip/collateral/account`
- `/sapi/v1/loan/vip/loanable/data`
- `/sapi/v1/loan/vip/fixed/market`
- `/sapi/v1/loan/vip/fixed/borrow`
- `/sapi/v1/loan/vip/accruedInterest`
- `/sapi/v1/loan/vip/ongoing/orders`
- `/sapi/v1/loan/vip/repay/history`
- `/sapi/v1/loan/vip/request/data`

### 11.5 其他理财产品

| 产品 | 接口 |
|---|---|
| Dual Investment（4） | `/sapi/v1/dci/product/list`、`/accounts`、`/positions`、`/subscribe` |
| Discount Buy（4） | `/sapi/v1/accumulator/product/list`、`/sum-holding`、`/position/list`、`/subscribe` |
| Mining（13） | `/sapi/v1/mining/pub/algoList`、`/coinList`、`/statistics/user/list`、`/statistics/user/status`、`/worker/list`、`/worker/detail`、`/payment/list`、`/payment/other`、`/payment/uid`、`/hash-transfer/config`、`/hash-transfer/config/cancel`、`/hash-transfer/config/details/list`、`/hash-transfer/profit/details` |
| Fiat（5） | `/sapi/v1/fiat/deposit`、`/sapi/v2/fiat/withdraw`、`/sapi/v1/fiat/orders`、`/sapi/v1/fiat/payments`、`/sapi/v1/fiat/get-order-detail` |
| Gift Card（6） | `/sapi/v1/giftcard/createCode`、`/buyCode`、`/redeemCode`、`/verify`、`/buyCode/token-limit`、`/cryptography/rsa-public-key` |
| Pay（1） | `/sapi/v1/pay/transactions` |
| C2C（1） | `/sapi/v1/c2c/orderMatch/listUserOrderHistory` |
| Rebate（1） | `/sapi/v1/rebate/taxQuery` |

---

## 12. Advanced Trading

### 12.1 Algo Trading（12 条 path）

**Spot**
- `POST /sapi/v1/algo/spot/newOrderTwap`
- `POST /sapi/v1/algo/spot/newOrderVp`
- `DELETE /sapi/v1/algo/spot/order`
- `GET /sapi/v1/algo/spot/openOrders`
- `GET /sapi/v1/algo/spot/historicalOrders`
- `GET /sapi/v1/algo/spot/subOrders`

**Futures**
- `POST /sapi/v1/algo/futures/newOrderTwap`
- `POST /sapi/v1/algo/futures/newOrderVp`
- `DELETE /sapi/v1/algo/futures/order`
- `GET /sapi/v1/algo/futures/openOrders`
- `GET /sapi/v1/algo/futures/historicalOrders`
- `GET /sapi/v1/algo/futures/subOrders`

### 12.2 Alpha Trading

**REST（6 条）**
- `/bapi/defi/v1/public/alpha-trade/get-exchange-info`
- `/bapi/defi/v1/public/alpha-trade/agg-trades`
- `/bapi/defi/v1/public/alpha-trade/klines`
- `/bapi/defi/v1/public/alpha-trade/ticker`
- `/bapi/defi/v1/public/alpha-trade/fullDepth`
- `/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list`

**Streams（13 条）**
- `<symbol>@aggTrade`
- `<symbol>@trade`
- `<symbol>@kline_<interval>`
- `<symbol>@miniTicker`
- `<symbol>@ticker`
- `<symbol>@bookTicker`
- `!bookTicker`
- `<symbol>@depth<levels>@<interval>`
- `<symbol>@fulldepth@<interval>`
- `!miniTicker@arr`
- `!ticker@arr`
- `came@allTokens@ticker24`
- `came@<contractAddress>@<chainId>@kline_<interval>`

### 12.3 Copy Trading（2 条）

- `GET /sapi/v1/copyTrading/futures/userStatus`
- `GET /sapi/v1/copyTrading/futures/leadSymbol`

### 12.4 Institutional Loan（15 条）

- `/sapi/v1/margin/loan-group`
- `/sapi/v1/margin/loan-group/edit-member`
- `/sapi/v1/margin/loan-group/borrow`
- `/sapi/v1/margin/loan-group/repay`
- `/sapi/v1/margin/loan-group/borrow-repay`
- `/sapi/v1/margin/loan-group/interest-history`
- `/sapi/v1/margin/loan-group/ltv-details`
- `/sapi/v1/margin/loan-group/max-borrowable`
- `/sapi/v1/margin/loan-group/force-liquidation`
- `/sapi/v1/margin/loan-group/liquidation-transfer-record`
- `/sapi/v1/margin/loan-group/transfer-out`
- `/sapi/v1/margin/loan-group/interest-rebate-balance`
- `/sapi/v1/margin/loan-group/interest-rebate-balance/records`
- `/sapi/v1/margin/loan-groups/activated`
- `/sapi/v1/margin/loan-groups/closed`

### 12.5 Stocks Trading

**REST（16 条）**
- `/sapi/v1/equity/market/exchangeInfo`
- `/sapi/v1/equity/market/tokenized-assets`
- `/sapi/v1/equity/market/quote`
- `/sapi/v1/equity/order/place`
- `/sapi/v1/equity/order/cancel`
- `/sapi/v1/equity/order/cancel-all`
- `/sapi/v1/equity/order/open-orders`
- `/sapi/v1/equity/order/history`
- `/sapi/v1/equity/order/detail`
- `/sapi/v1/equity/trade/history`
- `/sapi/v1/equity/tokenized/mint`
- `/sapi/v1/equity/tokenized/redeem`
- `/sapi/v1/equity/tokenized/convert-status`
- `/sapi/v1/equity/tokenized/history`
- `/sapi/v1/equity/account/disclaimer`
- `/sapi/v1/equity/listenKey`

**Streams（7 条）**
- `/price`
- `/<symbol>@quote`
- `/<symbol>@kline_<interval>`
- `/calendar`
- `/<symbol>@tradability`
- `/<symbol>@tradingStatus`
- `/<listenKey>@orderReport`

---

## 13. VIP & Institutional

### 13.1 CaaS / Broker（26 条）

- `/sapi/v1/broker/subAccount`
- `/sapi/v1/broker/subAccountApi`
- `/sapi/v1/broker/subAccountApi/permission`
- `/sapi/v1/broker/subAccountApi/permission/universalTransfer`
- `/sapi/v1/broker/subAccountApi/ipRestriction`
- `/sapi/v2/broker/subAccountApi/ipRestriction`
- `/sapi/v1/broker/subAccountApi/ipRestriction/ipList`
- `/sapi/v1/broker/subAccount/futures`
- `/sapi/v1/broker/subAccount/bnbBurn/spot`
- `/sapi/v1/broker/subAccount/bnbBurn/marginInterest`
- `/sapi/v1/broker/subAccount/bnbBurn/status`
- `/sapi/v1/broker/subAccount/depositHist`
- `/sapi/v2/broker/subAccount/depositHist`
- `/sapi/v1/broker/subAccount/spotSummary`
- `/sapi/v1/broker/subAccount/marginSummary`
- `/sapi/v3/broker/subAccount/futuresSummary`
- `/sapi/v1/broker/info`
- `/sapi/v1/broker/transfer`
- `/sapi/v1/broker/transfer/futures`
- `/sapi/v1/broker/universalTransfer`
- `/sapi/v1/broker/futures/accountTransfer`
- `/sapi/v1/broker/subAccountApi/commission`
- `/sapi/v1/broker/subAccountApi/commission/futures`
- `/sapi/v1/broker/subAccountApi/commission/coinFutures`
- `/sapi/v1/broker/rebate/recentRecord`
- `/sapi/v1/broker/rebate/futures/recentRecord`

### 13.2 OMS Toolkit（18 条）

- `/sapi/v1/apiReferral/userCustomization`
- `/sapi/v1/apiReferral/customization`
- `/sapi/v1/apiReferral/ifNewUser`
- `/sapi/v1/apiReferral/kickback/recentRecord`
- `/sapi/v1/apiReferral/rebate/recentRecord`
- `/papi/v1/apiReferral/userCustomization`
- `/fapi/v1/apiReferral/userCustomization`
- `/fapi/v1/apiReferral/customization`
- `/fapi/v1/income`
- `/fapi/v1/apiReferral/overview`
- `/fapi/v1/apiReferral/rebateVol`
- `/fapi/v1/apiReferral/traderSummary`
- `/fapi/v1/apiReferral/traderNum`
- `/fapi/v1/apiReferral/tradeVol`
- `/papi/v1/apiReferral/ifNewUser`
- `/fapi/v1/apiReferral/ifNewUser`
- `/v1/api-key/create`
- `/v1/api-key/user-status`

### 13.3 KYC SaaS（12 条）

全部在 `/bapi/ekyc/v2/public/ekyc/customer/`：

`check-kyc-status`、`page-query-rfi-records`、`submit-rfi-record`、`share-kyc-data`、`add-account-info-list`、`query-submit-rfi-result`、`inner-query-kyc-status`、`query-kyc-info`、`query-linked-accounts`、`query-share-data-status`、`refused-kyc-data`、`unlink-kyc-data`

### 13.4 Fund Account（9 条）

- `/sapi/v1/vip/fund-info/fund-info-basic-info`
- `/sapi/v1/vip/fund-info/fund-nav-info`
- `/sapi/v1/vip/fund-info/fund-investor-his-info`
- `/sapi/v1/capital-connect/redemption/calendar`
- `/sapi/v2/portfolio-account/trading-team/portfolio-basic-info`
- `/sapi/v2/portfolio-account/trading-team/portfolio-nav-info`
- `/sapi/v2/portfolio-account/trading-team/investor-portfolio-his-info`
- `/sapi/v1/portfolio-account/investor/portfolio-nav-info`
- `/sapi/v2/capital-connect/trading-team/redemption/calendar`

### 13.5 Link Plus（8 条）

- `/sapi/v1/vip/link-plus/subgroups`
- `/sapi/v1/vip/link-plus/subgroups/{groupId}/accounts`
- `/sapi/v1/vip/link-plus/subgroups/{groupId}/name`
- `/sapi/v1/vip/link-plus/subgroups/detail`
- `/sapi/v1/vip/link-plus/overview`
- `/sapi/v1/vip/liquidity-programs/subgroups/overview`
- `/sapi/v1/vip/liquidity-programs/subgroups/performance`
- `/sapi/v1/vip/liquidity-programs/subgroups/weekly-result`

### 13.6 Spot Block Matching（7 条）

- `/sapi/v1/block-match/order/place`
- `/sapi/v1/block-match/order/take`
- `/sapi/v1/block-match/order/cancel`
- `/sapi/v1/block-match/order/extend`
- `/sapi/v1/block-match/order/query-open-order`
- `/sapi/v1/block-match/order/query-order-history`
- `/sapi/v1/block-match/symbols`

### 13.7 VIP CaaS（6 条）

- `/sapi/v1/vip/caas/commission/fee-groups`
- `/sapi/v1/vip/caas/commission/fee-groups/commission`
- `/sapi/v1/vip/caas/commission/fee-groups/members`
- `/sapi/v1/vip/caas/commission/member-fee-group`
- `/sapi/v1/vip/caas/commission/markup-trade-aggregations`
- `/sapi/v1/vip/caas/commission/markup-trade-details`

### 13.8 VIP Service（9 条）

- `/sapi/v1/vip/vip-portal/futures/ip-whitelists`
- `/sapi/v1/vip/vip-portal/futures/rate-limits/ips`
- `/sapi/v1/vip/vip-portal/futures/rate-limits/ips/pages`
- `/sapi/v1/vip/vip-portal/futures/rate-limits/orders`
- `/sapi/v1/vip/vip-portal/futures/rate-limits/orders/pages`
- `/sapi/v1/vip/liquidity-programs/overview`
- `/sapi/v1/vip/liquidity-programs/performance`
- `/sapi/v1/vip/liquidity-programs/weekly-result`
- `/sapi/v1/commission/queryCommissionFee`

---

## 14. Web3 Prediction Trading（36 + 15）

### REST（36 条）

**市场**
- `/sapi/v1/w3w/wallet/prediction/category/list`
- `/sapi/v1/w3w/wallet/prediction/market/list`
- `/sapi/v1/w3w/wallet/prediction/market/search`
- `/sapi/v1/w3w/wallet/prediction/market/detail`
- `/sapi/v1/w3w/wallet/prediction/order-book`
- `/sapi/v1/w3w/wallet/prediction/order-book/last-trade-price`

**账户/钱包**
- `/sapi/v1/w3w/wallet/prediction/wallet/list`
- `/sapi/v1/w3w/wallet/prediction/pnl/portfolio`
- `/sapi/v1/w3w/wallet/prediction/quota/limit/status`
- `/sapi/v1/w3w/wallet/prediction/balance/payment-options`

**交易**
- `/sapi/v1/w3w/wallet/prediction/trade/get-quote`
- `/sapi/v1/w3w/wallet/prediction/trade/place-order-bundle`
- `/sapi/v1/w3w/wallet/prediction/trade/batch-cancel`

**订单/持仓**
- `/sapi/v1/w3w/wallet/prediction/order/list`
- `/sapi/v1/w3w/wallet/prediction/order/history`
- `/sapi/v1/w3w/wallet/prediction/position/list`
- `/sapi/v1/w3w/wallet/prediction/position/filter`
- `/sapi/v1/w3w/wallet/prediction/position/token`
- `/sapi/v1/w3w/wallet/prediction/pnl/query`
- `/sapi/v1/w3w/wallet/prediction/position/settled-history`
- `/sapi/v1/w3w/wallet/prediction/batch-redeem`
- `/sapi/v1/w3w/wallet/prediction/redeem/status`

**划转**
- `/sapi/v1/w3w/wallet/prediction/transfer/inbound`
- `/sapi/v1/w3w/wallet/prediction/transfer/outbound`
- `/sapi/v1/w3w/wallet/prediction/transfer/list`
- `/sapi/v1/w3w/wallet/prediction/transfer/status`

**做市/OTC**
- `/sapi/v1/w3w/wallet/prediction/deposit/apply`
- `/sapi/v1/w3w/wallet/prediction/withdraw/apply`
- `/sapi/v1/w3w/wallet/prediction/otc/blocktrade/create`
- `/sapi/v1/w3w/wallet/prediction/otc/blocktrade/list`
- `/sapi/v1/w3w/wallet/prediction/otc/blocktrade/detail`
- `/sapi/v1/w3w/wallet/prediction/otc/blocktrade/events`
- `/sapi/v1/w3w/wallet/prediction/otc/blocktrade/preview`
- `/sapi/v1/w3w/wallet/prediction/otc/blocktrade/fulfil`
- `/sapi/v1/w3w/wallet/prediction/otc/blocktrade/remove`
- `/sapi/v1/w3w/wallet/prediction/otc/blocktrade/reserved-balances`

### Streams（15 条）

- `web3_prediction_orderbook_<marketId>`
- `web3_prediction_pm_claim_fail`
- `web3_prediction_pm_claim_partial_success`
- `web3_prediction_pm_claim_success`
- `web3_prediction_pm_limit_order_filled`
- `web3_prediction_pm_limit_order_partial_fill`
- `web3_prediction_pm_limit_submit_fail`
- `web3_prediction_pm_limit_submit_success`
- `web3_prediction_pm_market_buy_fail`
- `web3_prediction_pm_market_buy_success`
- `web3_prediction_pm_market_sell_fail`
- `web3_prediction_pm_market_sell_success`
- `web3_prediction_pm_transfer_fail`
- `web3_prediction_pm_transfer_success`
- `web3_prediction_pm_market_close`

---

## 15. 接入方式与鉴权

### Base URL

| 产品 | REST | WebSocket |
|---|---|---|
| Spot | `https://api.binance.com` | `wss://stream.binance.com:9443` / `:443` |
| Spot 纯行情 | `https://data-api.binance.vision` | 同上 |
| Spot WS API | — | `wss://ws-api.binance.com:443/ws-api/v3` |
| Margin | `https://api.binance.com/sapi/v1/margin` | 行情用 Spot stream |
| USDⓈ-M | `https://fapi.binance.com` | `wss://fstream.binance.com` |
| COIN-M | `https://dapi.binance.com` | `wss://dstream.binance.com` |
| Options | `https://eapi.binance.com` | `wss://nbstream.binance.com/eoptions` |
| Portfolio Margin | `https://papi.binance.com` | 行情用 UM/CM stream |
| Wallet/Sub/Earn | `https://api.binance.com/sapi` | — |
| Alpha | `https://api.binance.com/bapi/defi` | 对应 Alpha stream |
| KYC SaaS | `https://api.binance.com/bapi/ekyc` | — |
| OMS | `https://api.binance.com/v1` | — |
| Prediction | `https://api.binance.com/sapi/v1/w3w` | 对应 Prediction stream |

测试网：
- Spot：`https://testnet.binance.vision`
- U 本位/币本位：`https://testnet.binancefuture.com`

### 鉴权

- Header：`X-MBX-APIKEY: <apiKey>`
- 签名：HMAC SHA256、RSA、Ed25519
- 公共参数：`timestamp`、`recvWindow`
- WebSocket API：`session.logon` 登录，或使用签名订阅
- 用户数据流：Spot/Margin/Futures/Options/PM 使用 `listenKey` 创建、续期、关闭；Spot WS API 还支持 `userDataStream.subscribe`
- 第三方应用授权：Binance OpenAPI 的 OAuth 2.0 / PKCE 流程

### 限频

- Spot：`REQUEST_WEIGHT`、`ORDERS`、`RAW_REQUESTS`
- Futures：按 IP/UID 的 request weight、order rate limit
- 查询接口：`/api/v3/rateLimit/order`、`/fapi/v1/rateLimit/order`、`/papi/v1/rateLimit/order`、`account.rateLimits.orders`
- 每个端点的具体 weight 在文档对应页面标注

### 配套资源

- Postman Collections：`github.com/binance/binance-api-postman`
- Swagger/OpenAPI：`github.com/binance/binance-api-swagger`
- 多语言 Connector：Python、Node.js、Java、Go、Rust、PHP、C#、Ruby、TypeScript
- FIX Connector：Python
- 旧版 Spot 文档：Filters、Enums、Error Codes、Testnet、Demo Mode、FAQ

---

## 16. 按场景选型

| 场景 | 使用产品/接口 |
|---|---|
| 现货行情/K 线/盘口 | Spot REST `/api/v3/*` 或 Spot Streams |
| 现货低延迟下单 | Spot WebSocket API 或 FIX |
| 现货账户、充提、划转 | Wallet `/sapi/v1/capital/*`、`/asset/*` |
| 杠杆借币、逐仓/全仓 | Margin `/sapi/v1/margin/*` |
| U 本位合约 | `/fapi/*` + `fstream` |
| 币本位合约 | `/dapi/*` + `dstream` |
| 期权 | `/eapi/*` + `eoptions` |
| 多账户统一保证金 | Portfolio Margin `/papi/*` |
| 子账户/经纪商 | Sub Account、CaaS |
| 闪兑 | `/sapi/v1/convert/*` |
| 理财/质押/借贷 | Simple Earn、Staking、Crypto/VIP Loan |
| 算法拆单 | Algo Trading `/sapi/v1/algo/*` |
| 做市返佣/机构账户 | OMS、VIP Service、CaaS |
| 预测市场 | Prediction Trading `/sapi/v1/w3w/*` |

---

## 17. 备注

- 旧版 README 还列出 **Auto Invest**、**NFT** 等入口，但新版 Catalog 未单列，使用前需确认对应页面是否仍维护。
- 新版文档为默认文档，旧版 Spot 文档仍可访问，适合查 FIX、SBE 和旧版字段说明。
- 同一路径支持多个方法时，REST 的 POST/GET/DELETE 分别对应下单/查询/撤销；WebSocket API 则是独立 method 名。

相关概览：[[shared/notes/binance-api-catalog-structure-and-endpoint-counts-2026-11]]

