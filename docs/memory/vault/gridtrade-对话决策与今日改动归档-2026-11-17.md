---
title: gridtrade 对话决策与今日改动归档（2026-11-17）
tags:
  - gridtrade
  - handoff
  - changelog
  - binance
  - gate
  - deployment
verified: true
created: '2026-11-17T17:39:33+08:00'
---

# gridtrade 对话决策与今日改动归档（2026-11-17）

**重点：今天把面板从“单标的回放 + Gate 模拟盘”推进到“11 页、四标的共享保证金组合、Gate 实盘只读+锁定下单、/admin 独立后台、手机 APK 免登录”，并完成 Binance 不可达/澳门资格/Plan B 的结论。详细逐项见仓库 `docs/memory/08-对话与决策日志-2026-11-17.md` 与 `09-今日改动总览-2026-11-17.md`。**

## 用户问题与解决方案（顺序）

1. **APK 免登录 + `.env` 配置 + 实时模拟盘**：服务端 `.env` 加载；APK 构建读 `apk/.env` 生成 `BuildConfig`（服务器+令牌）；Gate 永续公开行情驱动纸面网格，算手续费/资金费，落库 `var/paper.db`。`d854812`。
2. **四标的（SKHY/SPCX/GOOGL/AMGN）混合模拟盘、所有交易数据**：用户选“共享保证金动态分配”，先模拟。多标的组合：共享权益/保证金，独立网格，逐标的资金费/手续费，组合止损。`caef2fa`。
3. **所有接口用官方文档**：对照记忆库 Binance catalog 与 Gate 官方 SDK；新增 07 文档 + `tests/test_external_endpoints.py` 白名单；手续费改用合约 `maker_fee_rate/taker_fee_rate`（-0.75bp/7.5bp）。`791f19f`。
4. **Gate 实盘 + 手动配置保存 `.env`**：Gate 私有只读分析 + 下单/撤单/平仓/杠杆（默认锁定）；`/live` 配置写 `.env`，Secret 不回显；风控上限/紧急停止。`c980d71`；修复非 editable 安装 `.env` 写错位置。
5. **手机加载不出来/性能**：根因是 `/api/market/snapshot` 访问被墙 Binance 阻塞 20s；服务器无 OOM/重启，APK 本身正常。修复 `GRIDTRADE_MARKET_LIVE=0`、失败缓存 60s、1.5s/3s 超时、gzip；overview 0.1s。`bf1c415`。
6. **切换代币合约**：补 SKHY/SPCX/AMGN 数据集（本地抓取上传），顶部交易对下拉 4 个；模拟盘 symbols 在 `.env`，实盘下单在 `/live` 下拉。
7. **服务器连不上 Binance**：广州服务器；DNS 污染（伪造 IP）+ SNI TLS reset；官方无 fapi 替代域名。`7589bfd`。
8. **解决方案**：支持 `GRIDTRADE_PROXY`（CONNECT/SOCKS5），本地代理验证 `source=binance`；但 Binance《Prohibited Use Policy》禁止匿名代理，不建议跑账户。`d8cb139`。
9. **Gate 实盘/后台入口**：Gate USDT 永续可 API 实盘；服务器可直连；面板默认锁定。Gate 网页头像 → API 管理；App 我的 → API 管理。
10. **独立后台 admin/admin**：`/admin` + `/api/admin/*`，PBKDF2 存 `var/admin.db`，独立 `gt_admin` Cookie；实盘/模拟盘配置、令牌轮换、改密、审计。`20b5d91`。
11. **香港 IP / 澳门资格**：check-host 香港节点实测 fapi 公开接口 200（约 65–100ms）；Binance 官方禁止名单（2026-01-05）不含澳门；香港衍生品限制只点名 HK；用户确认永续合约一直在用 → 澳门身份实际可用。
12. **Plan B**：保留广州面板 + 海外执行节点；用户买东京 Lightsail（$5/月），给 SSH，防火墙只放 22/51820 且仅 81.71.71.131；我方搭 WireGuard + 执行节点 + Binance 合约适配器（先测试网，`testnet.binancefuture.com` 从广州可直连 200）。
13. **最新 APK**：17:21 重建安装到 OnePlus PJA110，自动登录、4 交易对、`#/paper`/`#/live` 正常。

## 今日全部改动（摘要）

- 新增：`paper.py`（组合模拟盘）、`live_gate.py`（Gate 实盘）、`admin.py`（后台）、4 组测试、`Paper.tsx`、`Live.tsx`、`web/public/admin/index.html`、07/08/09 文档。
- 修改：`config.py`（.env/Paper/Live/market_live/proxy/env_path）、`app.py`（路由/生命周期/gzip）、`live.py`（超时/失败缓存/代理/offline）、`build.sh`+`MainActivity`（APK 免登录）、`api.ts`/路由/导航、`pyproject.toml`（socksio）、README/.env 模板/.gitignore。
- 测试：**74 passed**；前端 build/typecheck 通过；APK 构建安装通过。
- 部署：服务器 `.env` + systemd `EnvironmentFile`；3 个新数据集；`GRIDTRADE_MARKET_LIVE=0`；今日 11 个主要提交（bcf2804…3552b24，外加归档提交）。
- 线上：面板/后台 HTTP 可用；模拟盘 4 标的 running；实盘未配置/锁定；手机 APK 最新。

## 风险与下一步

- HTTP 明文 + 后台默认 admin/admin：尽快改密与上 HTTPS。
- APK 内嵌令牌：轮换需重打包。
- Binance 实盘适配器未实现；Plan B 需东京节点与测试网 Key。
- 备份 `var/admin.db`、`var/paper.db`、`var/gridtrade.db`。
