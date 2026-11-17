---
title: gridtrade 独立管理后台（/admin）2026-11-17
tags:
  - gridtrade
  - admin
  - security
  - gate
  - deployment
verified: true
created: '2026-11-17T15:32:03+08:00'
---

# 独立管理后台（/admin，admin/admin 预设）

**重点：新增与面板令牌完全分离的管理后台 `GET /admin`，默认账号/密码 `admin`/`admin`；可管理 Gate 实盘凭据与限额、模拟盘标的与参数、启停/重置、轮换面板令牌、修改密码、查看审计。配置写入服务器 `.env`，管理员密码哈希存 `var/admin.db`。**

## 认证与安全

- 账号密码：PBKDF2-HMAC-SHA256（200k 轮）+ 随机盐，存 `var/admin.db`；首次启动自动创建 `admin/admin`。
- 会话：httpOnly Cookie `gt_admin`，SameSite=Strict，12 小时；内存会话表；登录失败 5 次锁定 30 秒。
- 与面板 token 认证完全独立；`/api/admin/*` 不经过 `require_token`。
- 默认密码登录后页面显示警告；修改密码需当前密码，新密码 ≥5 位且不能仍是 `admin`。
- 风险：HTTP 下账号密码明文；公网使用必须尽快 HTTPS 并修改默认密码。

## 后端

- `src/gridtrade/api/admin.py`：
  - `AdminAuth`：默认账号、登录/会话/登出、改密、失败限流；
  - `AdminService`：概览（模拟盘权益/状态、实盘 masked config、审计、令牌后四位、env 路径）、保存实盘配置（写 `.env`、更新 LiveService）、保存模拟盘配置（写 `.env`、`paper.reset(overrides)` 重建组合）、启动/停止/重置、轮换面板令牌（更新 `var/token` 与 `.env` 的 `GRIDTRADE_TOKEN`）、修改密码。
- `app.py` 新路由：`POST /api/admin/login|logout`、`GET /api/admin/me|overview|audit`、`POST /api/admin/live|paper|paper/action|token/rotate|password`；`GET /admin` 返回 `web/dist/admin/index.html`（无缓存）。
- 实盘下单仍受原总开关/风控/紧急停止约束；后台不会绕过。

## 前端

- `web/public/admin/index.html`（Vite 构建复制到 `web/dist/admin/`），独立深色后台页：登录、概览卡片、实盘表单、模拟盘表单与启停/重置、安全（轮换令牌/改密）、审计表；15s 轮询。
- 令牌轮换只显示一次，并提示 APK 需重新打包；默认密码显示警告横幅。

## 验证

- 74 tests（新增 6 个后台用例：默认登录/会话、改密、实盘写入 `.env`、下单确认、模拟盘 symbols/reset、令牌轮换）。
- 本地与公网：`/admin` 200；`admin/admin` 登录成功，`default_password=true`；错误密码 401；概览显示模拟盘 running/4 标的、实盘未配置；未登录 `/api/admin/overview` 401。
- 主面板 token 与 APK 不受后台新增影响。

## 后续

- 首次登录改密；上 HTTPS；把 `var/admin.db` 纳入备份。
