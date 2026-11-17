---
title: gridtrade 实盘接入（Gate，只读+锁定下单）2026-11-17
tags:
  - gridtrade
  - live-trading
  - gate
  - env
  - security
verified: true
created: '2026-11-17T14:43:51+08:00'
---

# gridtrade 实盘接入（Gate，只读分析 + 下单默认锁定）

**重点：已接入 Gate USDT 永续实盘私有接口，支持页面手动配置 API Key/Secret 并写回服务器 `.env`，提供余额/持仓/挂单/成交/资金流水/盈亏分析；下单、撤单、平仓、杠杆代码已实现，但默认锁定（`GRIDTRADE_LIVE_TRADING=0`），未配置 Key 时不会发起任何私有写请求。**

## 配置方式（用户操作）

- 页面 `#/live`：填 Gate API Key / Secret、启用同步、限额（总名义/单笔/单标的/最大挂单）、可选“允许实盘下单”。
- 保存即写服务器 `.env`（0600），只回显 Key 后四位，Secret 永不回传；提供“测试连接”“刷新账户”“清除凭据”。
- `.env` 路径解析：`GRIDTRADE_ENV_FILE` → 工作目录含 `pyproject.toml`/`src/gridtrade` 时的 `cwd/.env`（systemd WorkingDirectory 即部署根）→ 包内 `REPO_ROOT/.env`。修复了非 editable 安装时误写入 `.venv` 的问题。
- Gate Key 建议：只读分析只开读取；要下单才开合约交易，关闭提现，IP 白名单 `81.71.71.131`。

## 后端

- 新模块 `src/gridtrade/api/live_gate.py`：
  - `GatePrivateClient`：官方 APIv4 签名 `HMAC_SHA512(secret, method\npath\nquery\nsha512(body)\ntimestamp)`，头 `KEY/Timestamp/SIGN`；私有读 `accounts/positions/orders/my_trades/account_book/fee`；写 `POST orders`、`DELETE orders/{id}`、`POST positions/{contract}/leverage`；公开 `contracts/tickers` 不签名。
  - `LiveService`：10s 快照缓存；分析权益/可用/未实现/已实现/手续费/资金费/总名义/净敞口/维持保证金率/挂单名义，并对限额与保证金率给出告警。
  - 下单前置校验：已配置、`enabled`、`trading_enabled`（否则 403）、单笔 ≤ 单笔上限、组合总名义 ≤ 上限、单标的名义 ≤ 上限、挂单数 ≤ 上限、权益 20 倍、面板紧急停止（409）。
  - `write_env_file`：保留注释与其他键，原子写入并 0600；`None` 表示删除该键。
- `app.py`：`/api/live`、`/api/live/sync`、`/api/live/config`（GET/POST）、`/api/live/test`、`/api/live/orders`（POST）、`/api/live/orders/{id}`（DELETE）、`/api/live/positions/{contract}/close`；全部需要面板令牌；配置/下单写审计日志；`MODES.live` 改为可用。
- 测试 `tests/test_live_gate.py` 7 个：官方签名公式、`.env` 保留注释/删除键/0600、分析聚合与告警、下单锁定、单笔上限、限额内下单、连接测试。全量 **68 passed**。
- 外部接口审计扩展到 `live_gate.py`，私有路径登记在 `docs/memory/07`，未登记路径测试失败。

## 前端

- 新第 11 页 `#/live`：配置表单（Key/Secret/同步开关/下单开关/限额）、账户卡片、持仓表、挂单（撤单）、最近成交、资金流水（pnl/fee/fund）、风控上限、下单面板（锁定不可用）。
- 未配置时显示创建 Key 的步骤与权限建议；下单开关需 `window.confirm` 二次确认，默认关。
- 桌面与 390px 移动视口无横向溢出；公网页面未配置状态验证通过，无 4xx/异常。

## 验证

- 本地/服务器用假 Key 保存：`.env` 正确写入 `/home/ubuntu/gridtrade/.env`（保留 13 行模拟盘配置），刷新返回 Gate `Invalid key provided`（鉴权链路生效），`POST /api/live/orders` 返回 403“下单已锁定”。
- 清除凭据后 `.env` 删除 GATE 键、保留模拟盘配置，实盘回到未配置；模拟盘四标的仍运行。
- 真实密钥尚未创建，因此尚未验证真实账户数据与下单；需用户完成后做最小张数验证。

## 安全边界

- 下单总开关默认 0；未显式开启前不会发送真实订单。
- Secret 不写日志、不出现在 API 响应；页面只显示 `…后四位`。
- 实盘仅支持 Gate（服务器可访问）；Binance 合约接口在服务器不可达，暂不能做实盘。
