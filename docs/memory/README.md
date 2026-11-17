# 开发交接与记忆文档

**重点：这套文档是给“换一台电脑继续开发”用的。** 它记录了项目现状、架构、部署位置、测试方法、已修问题、未完成事项和原始记忆笔记。仓库是公开的，因此**任何令牌、私钥、密码都不会写入这里**。

- 代码仓库：<https://github.com/JackLiKa/BinanceTrade>
- 当前提交：以 `git log -1` 为准（本文档首次提交为 `7a0a604`）
- 在线实例：`http://81.71.71.131:8000`（**明文 HTTP，临时**；令牌在服务器 `var/token`）
- 实时组合模拟盘：`#/paper`，4 标的共享保证金，数据源 Gate 永续公开接口，费率取自合约；配置在服务器 `.env`，状态在 `var/paper.db`
- 外部接口：见 07，`tests/test_external_endpoints.py` 强制只允许官方且已登记的接口
- 实盘：`#/live` 配置写入服务器 `.env`；只读分析可用，下单默认锁定（`GRIDTRADE_LIVE_TRADING=0`）
- 文档更新时间：2026-11-17（Asia/Macau）
- 本地开发目录：`/Users/user/Dev/bnapi`

## 阅读顺序

1. [01 项目总览与架构](01-项目总览与架构.md)：先看边界、技术栈、目录、页面、API、认证、数据与回测模型。
2. [02 开发进度与变更记录](02-开发进度与变更记录.md)：已经完成了什么、在哪个提交、验证到什么程度。
3. [03 部署与运维手册](03-部署与运维手册.md)：服务器位置、systemd、更新流程、访问方式、备份。
4. [04 测试手册](04-测试手册.md)：桌面 Web 与真机 APK 的可复现测试步骤和易误判点。
5. [05 问题与决策记录](05-问题与决策记录.md)：修过的缺陷、已知限制、策略研究结论、关键设计取舍。
6. [06 下一步与待办](06-下一步与待办.md)：按优先级排列的剩余工作。
7. [07 外部接口清单与官方文档对照](07-外部接口清单与官方文档对照.md)：所有交易所接口的官方文档与自动校验。
7. [vault/](vault/)：DSH 记忆库的原始笔记（含自动捕获的会话记录），内容未改写。

## 换电脑后的最小恢复步骤

前置：macOS（或 Linux）、Python 3.12、Node 20+、pnpm、Android SDK（只有构建 APK 需要）。

```bash
git clone https://github.com/JackLiKa/BinanceTrade.git
cd BinanceTrade

# 后端
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'

# 行情数据（仓库不包含；需要能访问 fapi.binance.com 的网络）
.venv/bin/python research/fetch.py --symbol GOOGLUSDT

# 前端（web/dist 不在仓库里，必须构建）
cd web && pnpm install && pnpm build && cd ..

# 启动
.venv/bin/python -m gridtrade.api
# 浏览器打开 http://127.0.0.1:8000，令牌在 var/token
```

**重点：`var/token`、`research/data/`、`web/dist/`、`.venv/`、`apk/*.jks` 都不在仓库中。** 令牌会在首次启动时自动生成；数据用 `research/fetch.py` 拉取；APK 签名密钥若不随仓库迁移，重新构建会生成新密钥（旧 APK 将无法覆盖安装新签名包）。

## 仓库结构

```
src/gridtrade/          # 领域、策略、执行、风控、研究、API
  api/                  # FastAPI 应用、任务队列、SQLite store、配置
  research/             # 回放/前向滚动/扫描的 CLI 与产物
web/                    # React 19 + Vite + Tailwind SPA
apk/                    # Android WebView 壳与手动构建脚本
research/               # 数据拉取与旧版回测脚本（数据目录被忽略）
tests/                  # pytest（引擎、OMS、风控、模拟、存储、策略）
docs/                   # 截图与本文档
var/                    # 运行期 SQLite、令牌（被忽略）
```

## 相关原始笔记（vault 摘录）

- [项目交接总览（主文档）](vault/gridtrade-项目交接总览-2026-11-16.md)
- [实时模拟盘与 APK 免登录（2026-11-17）](vault/gridtrade-实时模拟盘与-apk-免登录-2026-11-17.md)
- [四标的共享保证金组合模拟盘（2026-11-17）](vault/gridtrade-四标的共享保证金组合模拟盘-2026-11-17.md)
- [外部接口审计与手续费来源（2026-11-17）](vault/gridtrade-外部接口审计与手续费来源-2026-11-17.md)
- [实盘接入：Gate 只读分析与锁定下单（2026-11-17）](vault/gridtrade-实盘接入-gate-只读-锁定下单-2026-11-17.md)
- [手机首屏性能定位与修复（2026-11-17）](vault/gridtrade-手机首屏性能定位与修复-2026-11-17.md)
- [真机测试结论与修复](vault/gridtrade-web-apk-真机测试结论与修复-2026-11-16.md)
- [中文化完成](vault/gridtrade-panel-中文化完成-ui-readme.md)
- [移动端 WebView 布局与验收](vault/gridtrade-panel-mobile-webview-layout-fixes-and-acceptance-setup.md)
- [GOOGLUSDT 网格回测：成交 bug 与负期望](vault/googlusdt-minute-grid-backtest-fill-bug-and-negative-expectancy.md)
- [Binance API 接口清单（调研）](vault/binance-api-full-endpoint-catalog-2026-11.md)
