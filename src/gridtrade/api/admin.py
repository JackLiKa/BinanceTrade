"""Standalone admin console: account login, panel settings, safe operator actions.

The admin console is deliberately separate from the panel token auth: it has its
own username/password (preset ``admin`` / ``admin``) and its own httpOnly session
cookie. The default password must be changed after first login; the page shows a
warning until it is.

Admin writes go through the same live/paper services used by the panel, so all
existing locks (paper, live trading, risk limits, kill switch) still apply.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import LiveConfig, Settings
from .live_gate import LiveError, LiveService, write_env_file

ADMIN_COOKIE = "gt_admin"
SESSION_TTL = 12 * 3600
PBKDF2_ROUNDS = 200_000
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_user (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS
    ).hex()


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class AdminError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class AdminAuth:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, tuple[int, float]] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT id FROM admin_user WHERE id = 1").fetchone()
            if row is None:
                salt = secrets.token_hex(16)
                conn.execute(
                    "INSERT INTO admin_user (id, username, salt, password_hash, updated_at)"
                    " VALUES (1, ?, ?, ?, ?)",
                    (DEFAULT_USERNAME, salt, _hash(DEFAULT_PASSWORD, salt), _iso()),
                )
            conn.commit()

    def _row(self) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM admin_user WHERE id = 1").fetchone()
        assert row is not None
        return row

    def default_password(self) -> bool:
        row = self._row()
        return hmac.compare_digest(row["password_hash"], _hash(DEFAULT_PASSWORD, row["salt"]))

    def username(self) -> str:
        return str(self._row()["username"])

    def login(self, username: str, password: str, *, client: str = "") -> str:
        now = time.time()
        with self._lock:
            count, until = self._failures.get(client, (0, 0.0))
            if until > now:
                raise AdminError("尝试次数过多，请稍后再试", 429)
            row = self._row()
            ok = hmac.compare_digest(username.strip(), row["username"]) and hmac.compare_digest(
                _hash(password, row["salt"]), row["password_hash"]
            )
            if not ok:
                self._failures[client] = (count + 1, now if count + 1 < 5 else now + 30)
                raise AdminError("账号或密码错误", 401)
            self._failures.pop(client, None)
            token = secrets.token_urlsafe(32)
            self._sessions[token] = now + SESSION_TTL
            return token

    def check(self, token: str | None) -> bool:
        if not token:
            return False
        now = time.time()
        with self._lock:
            expiry = self._sessions.get(token)
            if expiry is None:
                return False
            if expiry < now:
                self._sessions.pop(token, None)
                return False
            return True

    def logout(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def change_password(self, token: str, current: str, new: str) -> None:
        if not self.check(token):
            raise AdminError("登录已过期", 401)
        if len(new) < 5:
            raise AdminError("新密码至少 5 位")
        if new == DEFAULT_PASSWORD:
            raise AdminError("不能继续使用默认密码 admin")
        row = self._row()
        if not hmac.compare_digest(_hash(current, row["salt"]), row["password_hash"]):
            raise AdminError("当前密码不正确", 403)
        salt = secrets.token_hex(16)
        with self._connect() as conn:
            conn.execute(
                "UPDATE admin_user SET salt = ?, password_hash = ?, updated_at = ? WHERE id = 1",
                (salt, _hash(new, salt), _iso()),
            )
            conn.commit()


class AdminService:
    def __init__(
        self,
        settings: Settings,
        store: Any,
        live_service: LiveService,
        paper: Any,
        auth: AdminAuth | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.live_service = live_service
        self.paper = paper
        self.auth = auth or AdminAuth(settings.var_dir / "admin.db")

    # -- overview --------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        paper = self.paper.snapshot()
        return {
            "version": "0.1.0",
            "env_path": str(self.settings.env_path),
            "token_hint": "…" + self.settings.token[-4:] if self.settings.token else "",
            "default_password": self.auth.default_password(),
            "admin_username": self.auth.username(),
            "symbols": paper.get("symbols", []),
            "paper": {
                "status": paper.get("status"),
                "symbols": paper.get("symbols", []),
                "equity": (paper.get("account") or {}).get("equity"),
                "fees": (paper.get("account") or {}).get("fees"),
                "funding": (paper.get("account") or {}).get("funding"),
                "realized": (paper.get("account") or {}).get("realized"),
                "config": paper.get("config"),
            },
            "live": self.live_service.masked_config(),
            "audit": self.store.list_audit(limit=30) if hasattr(self.store, "list_audit") else [],
        }

    # -- live config -----------------------------------------------------

    def save_live(self, payload: dict[str, Any]) -> dict[str, Any]:
        cfg: LiveConfig = self.settings.live
        updates: dict[str, str | None] = {}
        if payload.get("clear_credentials"):
            cfg = replace(cfg, api_key="", api_secret="")
            updates["GATE_API_KEY"] = None
            updates["GATE_API_SECRET"] = None
        if payload.get("api_key") is not None:
            value = str(payload["api_key"]).strip()
            cfg = replace(cfg, api_key=value)
            updates["GATE_API_KEY"] = value or None
        if payload.get("api_secret") is not None:
            value = str(payload["api_secret"]).strip()
            cfg = replace(cfg, api_secret=value)
            updates["GATE_API_SECRET"] = value or None
        if payload.get("enabled") is not None:
            cfg = replace(cfg, enabled=bool(payload["enabled"]))
            updates["GRIDTRADE_LIVE_ENABLED"] = "1" if payload["enabled"] else "0"
        if payload.get("trading_enabled") is not None:
            trading = bool(payload["trading_enabled"])
            if trading and not payload.get("confirm_trading"):
                raise AdminError("开启实盘下单需要二次确认")
            if trading and not cfg.configured:
                raise AdminError("先保存 API Key/Secret 再开启下单")
            cfg = replace(cfg, trading_enabled=trading)
            updates["GRIDTRADE_LIVE_TRADING"] = "1" if trading else "0"
        for field, env in (
            ("max_notional", "GRIDTRADE_LIVE_MAX_NOTIONAL"),
            ("max_order_notional", "GRIDTRADE_LIVE_MAX_ORDER_NOTIONAL"),
            ("max_position_notional", "GRIDTRADE_LIVE_MAX_POSITION_NOTIONAL"),
            ("max_open_orders", "GRIDTRADE_LIVE_MAX_OPEN_ORDERS"),
        ):
            if payload.get(field) is not None:
                value = float(payload[field]) if field != "max_open_orders" else int(payload[field])
                cfg = replace(cfg, **{field: value})  # type: ignore[arg-type]
                updates[env] = str(value)
        if updates:
            write_env_file(self.settings.env_path, updates)
        self.settings.live = cfg
        self.live_service.update_config(cfg)
        self.store.audit("admin.live_config", "updated")
        return self.live_service.masked_config()

    # -- paper config ----------------------------------------------------

    def save_paper(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.settings.paper
        updates: dict[str, str | None] = {}
        overrides: dict[str, Any] = {}
        if payload.get("symbols") is not None:
            raw = payload["symbols"]
            symbols = [str(item).strip().upper() for item in raw if str(item).strip()]
            if not symbols:
                raise AdminError("至少需要一个标的")
            overrides["symbols"] = symbols
            updates["GRIDTRADE_PAPER_SYMBOLS"] = ",".join(symbols)
        for field, env in (
            ("capital", "GRIDTRADE_PAPER_CAPITAL"),
            ("leverage", "GRIDTRADE_PAPER_LEVERAGE"),
            ("spacing_bp", "GRIDTRADE_PAPER_SPACING_BP"),
            ("levels", "GRIDTRADE_PAPER_LEVELS"),
            ("stop_dd_pct", "GRIDTRADE_PAPER_STOP_DD_PCT"),
            ("maker_fee_bp", "GRIDTRADE_PAPER_MAKER_FEE_BP"),
            ("taker_fee_bp", "GRIDTRADE_PAPER_TAKER_FEE_BP"),
            ("poll_seconds", "GRIDTRADE_PAPER_POLL_SECONDS"),
        ):
            if payload.get(field) is not None:
                value = float(payload[field]) if field != "levels" else int(payload[field])
                overrides[field] = value
                updates[env] = str(value)
        if updates:
            write_env_file(self.settings.env_path, updates)
        if overrides:
            self.settings.paper = replace(current, **overrides)
            self.paper.reset(overrides)
        self.store.audit("admin.paper_config", f"symbols={len(self.settings.paper.symbols)}")
        snapshot = self.paper.snapshot()
        return {"config": snapshot.get("config"), "status": snapshot.get("status")}

    def paper_action(self, action: str) -> dict[str, Any]:
        if action == "start":
            snapshot = self.paper.start(reset=False)
        elif action == "stop":
            snapshot = self.paper.stop()
        elif action == "reset":
            snapshot = self.paper.reset()
        else:
            raise AdminError("未知操作")
        self.store.audit(f"admin.paper_{action}", "ok")
        return {"status": snapshot.get("status")}

    # -- token / password ------------------------------------------------

    def rotate_token(self) -> dict[str, Any]:
        token = secrets.token_urlsafe(24)
        token_path = self.settings.var_dir / "token"
        token_path.write_text(token + "\n", encoding="utf-8")
        token_path.chmod(0o600)
        write_env_file(self.settings.env_path, {"GRIDTRADE_TOKEN": token})
        self.settings.token = token
        self.store.audit("admin.token_rotate", "rotated")
        return {"token": token}

    def change_password(self, token: str | None, current: str, new: str) -> None:
        assert token is not None
        self.auth.change_password(token, current, new)
        self.store.audit("admin.password_change", "ok")
