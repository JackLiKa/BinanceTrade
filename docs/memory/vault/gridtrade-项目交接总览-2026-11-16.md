---
title: gridtrade 项目交接总览（2026-11-16）
tags:
  - gridtrade
  - handoff
  - deployment
  - webview
  - backtest
verified: true
created: '2026-11-16T19:06:16+08:00'
---

# gridtrade 项目交接总览（2026-11-16）

**重点：项目已完成“引擎修正 → 中文面板 → 真机 APK → 服务器部署 → GitHub 推送”全链路；Web 与 APK 功能测试全部通过。剩余阻塞项是对外访问方式与 APK 默认地址。**

- 代码仓库（public）：https://github.com/JackLiKa/BinanceTrade ，提交 `7a0a604`（main）
- 本地目录：`/Users/user/Dev/bnapi`
- 服务器：`ubuntu@81.71.71.131:22`，Ubuntu 24.04.4，Python 3.12.3，3.7GB 内存，磁盘剩余约 5.7GB
- 服务：systemd `gridtrade`，监听 `127.0.0.1:8000`，开机自启，内存 cgroup 上限 1.8G（实测约 290MB）
- 完整交接文档：仓库 `docs/memory/`（README、架构、进度、部署、测试、问题决策、待办）+ `docs/memory/vault/` 原始笔记

## 一、产品与架构

单用户量化研究面板：FastAPI + SQLite(WAL) + 后台任务队列；React 19 + Vite 6 + Tailwind 4 + lightweight-charts 5；纯 hash 路由；一套 SPA 两种外壳（桌面侧边栏 / 移动底部 5 项导航 + 更多抽屉）。

**硬边界：仅研究与模拟盘。实盘入口可见但锁定（无适配器、无对账、无 listenKey 续期）。**

9 页：`#/overview`、`#/market`、`#/strategy`、`#/backtest`、`#/orders`、`#/positions`、`#/risk`、`#/quality`、`#/settings`。

认证：Bearer / X-API-Token / `gt_token` httpOnly Cookie；WebSocket `?token=`。令牌在 `var/token`（0600，首次启动自动生成），可用 `GRIDTRADE_TOKEN` 覆盖。不要把令牌入库或外传。

关键 API：`/api/health`、`/api/auth/login|logout`、`/api/session`、`/api/dataset/{symbols,quality}`、`/api/market/{snapshot,candles,funding}`、`/api/overview`、`/api/runs/{replay,walkforward,sweep}`、`/api/runs`、`/api/runs/{id}`、`/api/runs/{id}/artifact`（仅 succeeded）、`/api/runs/{id}/cancel`、`/api/risk`、`/api/settings`、`/api/settings/kill-switch`、`/api/audit`、`WS /ws`、`GET /{path}`（SPA 回退）。

数据：GOOGLUSDT 永续 1m，337,778 根（2026-03-26..11-16，约 235 天），718 次资金费，覆盖 100%；`research/data/` 约 14MB，不入库，用 `research/fetch.py --symbol GOOGLUSDT` 拉取。

## 二、本次完成与修复

1. **双引擎 bug 修复**：旧模型跨边界回补价记低一整格（虚假收益），改为状态机撮合（high/low 真正触达才成交，上涨 bar 只卖、下跌 bar 只买）；资金费符号由 `abs(pos)*price*rate` 改为 `cash -= pos*price*rate`。
2. **中文化**：9 页、登录页、命令面板、共享组件、后端模式/任务消息；英文 README 保留 `README.en.md`。
3. **移动 WebView 布局**：360×800 / font_scale 1.3 无横向溢出；fixed 表面不透明；图表时间轴留白；月度表横向滚动。
4. **APK 原生中文化**：首启设置页、错误页、面板菜单、退出确认。
5. **返回键缺陷**：主题为 NoActionBar，原生菜单不可达 → 删除 ActionBar 菜单，改为 `onBackPressed`：有 WebView 历史则后退，否则弹菜单（重新加载/服务器与令牌/退出登录/退出应用）。`MainActivity.java:401/413`。
6. **artifact 409 竞态**：切换历史任务时旧 run 的 succeeded 状态触发新 runId 请求 → `useArtifact(runId, run)` 要求 `run.id === runId && status === 'succeeded'`（`web/src/hooks.ts:103`）。
7. **旧产物残留**：选中已取消/排队任务仍显示上一任务图表 → 未就绪时 `data=null`。
8. **部署**：rsync 到 `~/gridtrade`，venv 安装依赖，上传数据与 `web/dist`，systemd 常驻；SSH 隧道回归 9 页 + 真实回放（14 图）通过，无 4xx/5xx、无异常。
9. **GitHub**：提交 `7a0a604`，125 个文件；`.gitignore` 排除 `var/`、`research/data/`、`.venv/`、`web/node_modules/`、`web/dist/`、`apk/*.jks`、`apk/.idea/`。

## 三、验收结论

- 桌面 Web：9 路由、回放/取消/前向滚动/参数扫描、订单筛选搜索、持仓、风控 kill switch + 审计、质量重扫、设置保存/登出/错误令牌、390px 无溢出、⌘K 面板；全程无异常。
- 真机（OnePlus PJA110，Android 16）：底部导航 + 更多 9 页、行情周期、订单、持仓、风控、设置认证、结果页 14 图、前向滚动、扫描、原生中文页/菜单/返回键；全部通过。
- pytest 最近 53 passed；`pnpm build`（含 tsc）通过。
- 部署实例：服务 active、NRestarts=0、内存约 290MB。

## 四、已知限制（重点）

- APK 默认服务器 `http://10.0.2.2:8000` 仅模拟器可用；真机需手填或 `adb reverse` 后用 127.0.0.1。地址确定后应改 `MainActivity.java:44` 重建。
- `adb reverse` 不随 USB 重连恢复。
- OPPO/OnePlus 直接 `adb install` 会卡安装引导，用 `pm install-create/write/commit`。
- WebView 内容不暴露 UIAutomator，需 `adb forward tcp:9333 localabstract:webview_devtools_remote_<pid>` + CDP。
- 服务器无法访问 `fapi.binance.com`（超时），实时行情回退数据集，K 线延迟明显（约 123 分钟）；非前端 bug。
- 当前未对外暴露；ufw 仅放行 22/80/3010/3000，443 未开；机器上已有 nginx 与其他业务，勿擅改。
- WebView 调试在 release 包中仍开启（`MainActivity.java:252`），分发前关闭。
- 签名密钥未入库；`build.sh` 口令硬编码；换机重建会生成新密钥，旧包需卸载后安装。

## 五、策略研究结论（避免重复踩坑）

修正后静态 120bp/30 格/0.5x + 10% 止损：累计 +8.62%（年化 +13.74%），最大回撤 9.75%，646 笔，资金费净收 $256。但止损 2%/3%/5% 分别为 -1.94%/-2.93%/-5.36% 全部止损，只有 10% 这一档活下来；月度再定锚累计 -6.07%；7/14/30 天再定锚全负；乐观 intrabar 仍负；合成零漂移 GBM 约 -0.4%。**结论：GOOGLUSDT 不存在可部署的分钟级网格正期望；静态正收益是方向性空头库存押注 + 刚好未触发止损，不是 edge。**

## 六、下一步（按优先级）

1. **P0 访问方式**（待用户选择）：域名+HTTPS（推荐，需 DNS 与 443 放行、`GRIDTRADE_SECURE_COOKIE=1`）／开放 IP:8000（明文，仅临时）／仅 SSH 隧道。
2. **P0 APK 默认地址**：改用正式地址重建、安装、回归。
3. **P1 实时行情**：解决服务器出口或换行情源，并验证 data source 与延迟。
4. **P1 测试资产化 + CI**：把 `/tmp/gtweb/*.mjs` CDP 脚本整理进 `tests/e2e/`；GitHub Actions 跑 pytest 与 web build。
5. **P2 运维**：备份 `var/`、日志轮转、内存/磁盘监控、令牌轮换、关闭 WebView 调试、保存 keystore。

## 七、最小恢复步骤（新电脑）

```bash
git clone https://github.com/JackLiKa/BinanceTrade.git
cd BinanceTrade
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python research/fetch.py --symbol GOOGLUSDT   # 需可访问 Binance
cd web && pnpm install && pnpm build && cd ..
.venv/bin/python -m gridtrade.api
# 打开 http://127.0.0.1:8000，令牌在 var/token
```

构建 APK 需 ANDROID_HOME、build-tools 36.0.0、android-34、JDK 21，然后 `./apk/build.sh`。

