# 原始记忆笔记索引（vault）

> **用途**：`docs/memory/vault/` 是 DSH 记忆库原始笔记的**原样快照**（含自动捕获的会话流水）。本文件只做索引与导读，**不改写原文**。
> **读者**：想追溯结论原始出处、想看未经整理的第一手记录的人。
> **最后核实**：2026-11-17 · 逐篇通读（19 篇），基准 `9a5cc4f`
> **相关文档**：[README 索引](../README.md) · [01 项目总览](../01-项目总览.md) · [09 策略研究结论](../09-策略研究结论.md) · [10 问题与决策记录](../10-问题与决策记录.md) · [13 历史归档](../13-历史归档.md)
> **可信度**：索引 **A**（逐篇核对）；笔记内容本身**不作质量担保**，冲突处一律以 `docs/memory/` 整理文档为准。

## 阅读须知（重要）

1. **vault 里的内容可能过时。** 它记录的是当时的状态（例如"9 页"、"53 passed"、"实盘无适配器"）。凡与整理文档冲突，**以整理文档为准**，冲突清单见 [10 §5](../10-问题与决策记录.md#5-本次核实发现的旧文档错误)。
2. **vault 内部几乎无交叉链接**：全库只有 **1 条** `[[wiki 链接]]`（`binance-api-full-endpoint-catalog-2026-11.md` → `binance-api-catalog-structure-and-endpoint-counts-2026-11.md`）。所以这份索引是唯一的导航。
3. **文件名 ≠ 写作时间**：文件名日期、frontmatter `created`、`updated`、文件 mtime 四者经常不同（文件是批量落盘的，mtime 统一为 `2026-11-17 21:10`）。引用时间请用 frontmatter `created`。
4. **5 篇 `auto-capture/` 用 UUID 命名**，看不出内容，只能靠本索引。
5. **vault 内的相对链接会 404**：这些笔记是按"记忆库根目录"写的相对路径（如 `web/src/pages/Backtest.tsx`、`.plugins/memory/...`、`.gitignore`），在 `docs/memory/vault/` 下解析不到。共 6 条（`auto-capture/b3c31c29…`、`c06d39d9…`、`session-fdec4544…`）。**这是历史记录的原样，不做修正**；要看真实文件请从仓库根找，要看整理结论请看 `docs/memory/` 对应文档。

## 统计

| 指标 | 值 |
| --- | --- |
| 文件总数 | **19**（根目录 14 + `auto-capture/` 5） |
| 总行数 | **2,071** |
| 总字节 | **112,346** |
| 汉字数 | **9,670** |
| 最大单篇 | `binance-api-full-endpoint-catalog-2026-11.md`（1,225 行，占 59.1%） |
| `[[wiki 链接]]` | 1 条 |
| `verified: true` | 9 篇 |
| created 范围 | 2026-11-16 11:34:13 ~ 2026-11-17 17:39:33（约 30 小时） |

## 逐篇索引

### 根目录（14 篇）

| 文件 | 类型 | created | 一句话摘要 | 关键结论 |
| --- | --- | --- | --- | --- |
| `binance-api-catalog-structure-and-endpoint-counts-2026-11.md` | 调研 | 11-16 11:34 | Binance 新版文档目录结构概览 | 46 schema / **984 path** / 1,079 operation；5 大类；base `/api/v3`+`/sapi`、`/fapi`、`/dapi`、`/eapi`、`/papi` |
| `binance-api-full-endpoint-catalog-2026-11.md` | 调研 | 11-16 11:36 | 全量接口清单（1,225 行） | USDⓈ-M REST **83**、WS API 18、Streams 20；测试网 `testnet.binancefuture.com` |
| `googlusdt-minute-grid-backtest-fill-bug-and-negative-expectancy.md` | 调研+缺陷 | 11-16 12:39 | GOOGLUSDT 分钟级网格回测与两个 bug | 修正后静态 +8.62%（年化 13.74%）是刀锋；**无可部署正期望** |
| `gridtrade-panel-mobile-webview-layout-fixes-and-acceptance-setup.md` | 验收备忘（英文） | 11-16 13:58 | 移动 WebView 布局修复与 CDP 验收口径 | `min-width: 0` 修 416 vs 360；`setVisibleLogicalRange`；9 路由 `scrollWidth==clientWidth` |
| `gridtrade-panel-中文化完成-ui-readme.md` | 验收 | 11-16 14:10 | 9 页 + 登录页 + 组件中文化完成 | `pnpm typecheck` 通过；**53 passed**；产物 `index-f91rO3P2.js` |
| `gridtrade-web-apk-真机测试结论与修复-2026-11-16.md` | 验收+缺陷 | 11-16 14:46 | 桌面 CDP + 真机全功能验收与 4 项修复 | 9 页全过；修 artifact 409、旧产物残留、返回键、原生中文 |
| `gridtrade-项目交接总览-2026-11-16.md` | 交接（主文档） | 11-16 19:06（updated 11-17 13:00） | 全链路已完成、公网运行，唯一 P0 是 HTTP→HTTPS | 公网 `http://81.71.71.131:8000`；Ubuntu 24.04.4；53 passed；APK 25,409 字节 |
| `gridtrade-实时模拟盘与-apk-免登录-2026-11-17.md` | 决策 | 11-17 13:56 | 第 10 页 `/paper` 实时模拟盘 + APK 构建期注入免登录 | 57 passed；`var/paper.db`；3s REST 轮询；APK 令牌编译进包 |
| `gridtrade-四标的共享保证金组合模拟盘-2026-11-17.md` | 决策 | 11-17 14:14 | 单标的升级为四标的共享保证金组合 | `CAPITAL=10000/LEVERAGE=2/SPACING_BP=10/LEVELS=20/STOP_DD=10`；58 passed；AMGN 24h 成交额约 $1k |
| `gridtrade-外部接口审计与手续费来源-2026-11-17.md` | 审计 | 11-17 14:31 | 外部调用只走官方接口 + 手续费改取合约费率 | Binance 7 个 `/fapi` + Gate 3 个 `/futures`；maker **-0.75bp**、taker **7.5bp**；61 passed |
| `gridtrade-实盘接入-gate-只读-锁定下单-2026-11-17.md` | 决策 | 11-17 14:43 | Gate 私有接口只读分析 + 默认锁定下单 | `GRIDTRADE_LIVE_TRADING=0`；HMAC_SHA512；68 passed |
| `gridtrade-手机首屏性能定位与修复-2026-11-17.md` | 缺陷 | 11-17 14:56 | 首屏卡顿根因是被墙 Binance 超时 | overview **19–21s → 0.09–0.14s**；JS 595KB→177KB gzip |
| `gridtrade-独立管理后台-admin-2026-11-17.md` | 决策 | 11-17 15:32 | 与面板令牌分离的 `/admin` 后台 | PBKDF2 200k；`gt_admin` 12h；失败 5 次锁 30s；74 tests |
| `gridtrade-对话决策与今日改动归档-2026-11-17.md` | 交接/归档 | 11-17 17:39 | 13 条"问题→方案"时序 + 全部改动摘要 | 11 页；11 个主要提交；74 passed |

### `auto-capture/`（5 篇，会话流水）

| 文件 | created | 摘要 |
| --- | --- | --- |
| `session-fdec4544-f7a5-4c47-8bc7-a81f43375d21.md` | 11-16 11:35（updated 19:03） | 11-16 全天 17 个 turn 的捕获：Binance 接口调研 → VPS 容量/经济性 → 成交价 bug 定位 → 模块化单体架构建议 → 9 页开发与中文化 → 推送 GitHub（`7a0a604`，125 文件）。**信息密度最高的一篇** |
| `8297d94b-115d-4cda-acf2-9c14873a5b74.md` | 11-16 14:03 | 子代理把 `Strategy.tsx`/`Settings.tsx` 中文化 |
| `c06d39d9-76f2-4778-8a1a-595cad70b857.md` | 11-16 14:04 | 子代理把 `Orders.tsx`/`Positions.tsx` 中文化（订单状态映射） |
| `b3c31c29-392d-498e-8367-425286093933.md` | 11-16 14:05 | 子代理把 `Backtest.tsx`（约 854 行）中文化 |
| `session-52ed4189-d7bb-49a2-9aa3-0c1db3593fe6.md` | 11-16 14:49 | 调研：`binance-connector-python` vs Java connector 架构差异 |

## 按主题交叉索引

| 主题 | 相关笔记 |
| --- | --- |
| 架构与交接 | `gridtrade-项目交接总览-2026-11-16`、`gridtrade-对话决策与今日改动归档-2026-11-17`、`auto-capture/session-fdec4544…`（turn 12 架构建议） |
| 实时模拟盘 | `gridtrade-实时模拟盘与-apk-免登录`、`gridtrade-四标的共享保证金组合模拟盘`、`gridtrade-外部接口审计与手续费来源` |
| 实盘 Gate | `gridtrade-实盘接入-gate-只读-锁定下单`、`gridtrade-外部接口审计与手续费来源`、`gridtrade-独立管理后台-admin` |
| 部署与网络封锁 | `gridtrade-项目交接总览-2026-11-16`（部署段）、`gridtrade-对话决策与今日改动归档`（DNS/SNI、香港 IP、Plan B） |
| 性能 | `gridtrade-手机首屏性能定位与修复` |
| APK / 移动端 | `gridtrade-web-apk-真机测试结论与修复-2026-11-16`、`gridtrade-panel-mobile-webview-layout-fixes…`、`gridtrade-实时模拟盘与-apk-免登录` |
| 前端 / 中文化 | `gridtrade-panel-中文化完成-ui-readme`、`gridtrade-panel-mobile-webview-layout-fixes…`、3 篇中文化 auto-capture |
| 策略研究 | `googlusdt-minute-grid-backtest-fill-bug-and-negative-expectancy`、`auto-capture/session-fdec4544…`（turn 3–11 容量与成本推演） |
| Binance API 调研 | 两篇 `binance-api-*`、`auto-capture/session-52ed4189…` |
| 管理后台 | `gridtrade-独立管理后台-admin-2026-11-17`、`gridtrade-对话决策与今日改动归档` |

## 已知冲突与过时内容（摘要）

| 主题 | 冲突/过时 | 以谁为准 |
| --- | --- | --- |
| 页面数量 | 交接总览写 **9 页**；归档写 **11 页** | **11 页**（`web/src/router.ts:3`）→ [01 §5](../01-项目总览.md#5-页面地图) |
| 实盘能力 | 交接总览写"无适配器/无对账"；实盘接入笔记写已实现只读+下单（锁定） | 后者 → [05](../05-模拟盘与实盘接入.md) |
| 手续费口径 | 早期固定 2/5bp；审计后改交易所费率 -0.75bp/7.5bp | 后者 → [11](../11-外部接口清单.md) |
| 测试数 | 52 → 53 → 57 → 58 → 61 → 68 → 74 | 不是矛盾，是时间线；当前 **74** → [08 §2](../08-测试与验收.md#2-自动化测试pytest) |
| 提交号 | `7a0a604`（11-16 推送点）被当成"最新" | 当前 `9a5cc4f` → [13 §1](../13-历史归档.md#1-提交时间线) |
| APK 默认地址 | `10.0.2.2` / 硬编码公网地址 | 最终形态是 `apk/.env` 注入 → [06](../06-前端与APK.md) |
| 登录账号 vs 部署目录 | `wmac@` 登录，但所有路径是 `/home/ubuntu/...` | **未解释的矛盾，需现场确认** → [07 §1](../07-部署与运维.md#1-服务器与网络) |
| 资金费符号 | 旧笔记按 `abs(pos)` 描述 | 正确为 `cash -= pos*price*rate` → [09 §2](../09-策略研究结论.md#2-两个必须知道的建模-bug) |

完整清单（12 条，含每条的代码出处）见 [10 §5](../10-问题与决策记录.md#5-本次核实发现的旧文档错误)。

## 信息缺口（笔记没写清、接手会踩坑）

| 领域 | 缺什么 |
| --- | --- |
| 部署 | `wmac` 与 `/home/ubuntu` 的关系、sudo 密码存放、nginx 现有站点、logrotate 配置 |
| 数据 | 4 标的数据集的文件名/大小/时间范围/上传路径（只有 GOOGLUSDT 有精确口径）；`/api/dataset/quality` 阈值规则 |
| 策略 | 四标的组合期望值完全未验证；AMGN 风险的处置方式未定；资金费近似误差量级未量化；纸面成交的乐观偏差未量化 |
| 实盘 | 真实 Gate Key 未创建，真实账户/最小张数/对账/熔断全部未验证；Binance 适配器未实现 |
| 前端 | `Paper.tsx`/`Live.tsx`/`admin/index.html` 中文化完成度无记录；新 APK 体积/签名 keystore 备份位置无记录 |
| 文档 | 笔记大量引用 `docs/memory/07..09`（旧版，已被本套替代）；`auto-capture` 中 `session-fdec…` turn 14 工具列表被截断，该轮动作不可还原 |

> 这些缺口已按优先级整理进 [12 待办与路线图](../12-待办与路线图.md)；能补的补，补不了的在那里标了"需现场确认"。

| `gridtrade-google-oauth-与行情黑屏修复-2026-11-18.md` | 登录/性能 | 11-18 | Google Device Flow + 黑屏根因/懒加载 + APK v0.3.0 |
