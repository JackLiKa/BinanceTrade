"""Google OAuth (device authorization grant) + per-user panel sessions.

The production panel is currently served over plain HTTP, and Google rejects
non-HTTPS OAuth redirect URIs. Device flow avoids that limitation: the browser
only opens Google's HTTPS verification page, while the backend polls Google's
token endpoint. No redirect URI is required.

Flow:
1. ``POST /api/auth/google/start`` -> Google device code, returns a short code.
2. User opens https://www.google.com/device and enters the code.
3. Frontend polls ``POST /api/auth/google/poll``; the backend exchanges the
   device code for an access token, reads userinfo, checks the admin allowlist,
   and creates a 30-day panel session cookie.

Only verified Google emails explicitly enabled in ``/admin`` may log in.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "openid email profile"
SESSION_TTL = 30 * 24 * 3600
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS google_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS google_users (
    email TEXT PRIMARY KEY COLLATE NOCASE,
    name TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    added_by TEXT NOT NULL DEFAULT 'admin',
    active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS google_sessions (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("邮箱格式不正确")
    return email


@dataclass(frozen=True)
class GoogleConfig:
    enabled: bool
    client_id: str
    client_secret: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


class GoogleAuthError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GoogleAuthStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(google_users)")}
            if "is_admin" not in columns:
                conn.execute("ALTER TABLE google_users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # -- config ---------------------------------------------------------

    def config(self) -> GoogleConfig:
        with self._connect() as conn:
            rows = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM google_settings")}
        client_id = (rows.get("client_id") or os.environ.get("GOOGLE_CLIENT_ID", "")).strip()
        client_secret = (rows.get("client_secret") or os.environ.get("GOOGLE_CLIENT_SECRET", "")).strip()
        if "enabled" in rows:
            enabled = rows["enabled"] == "1"
        else:
            enabled = bool(client_id and client_secret)
        return GoogleConfig(enabled=enabled and bool(client_id and client_secret), client_id=client_id, client_secret=client_secret)

    def set_config(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        enabled: bool | None = None,
        clear_secret: bool = False,
    ) -> GoogleConfig:
        values: dict[str, str] = {}
        if client_id is not None:
            values["client_id"] = client_id.strip()
        if clear_secret:
            values["client_secret"] = ""
        elif client_secret is not None and client_secret.strip():
            values["client_secret"] = client_secret.strip()
        if enabled is not None:
            values["enabled"] = "1" if enabled else "0"
        if values:
            with self._connect() as conn:
                for key, value in values.items():
                    conn.execute(
                        "INSERT INTO google_settings(key, value) VALUES(?, ?)"
                        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value),
                    )
                conn.commit()
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass
        return self.config()

    # -- allowlist ------------------------------------------------------

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT email, name, added_at, added_by, active, is_admin FROM google_users ORDER BY email"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_user(
        self,
        email: str,
        name: str = "",
        added_by: str = "admin",
        is_admin: bool = False,
    ) -> dict[str, Any]:
        address = normalize_email(email)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO google_users(email, name, added_at, added_by, active, is_admin)"
                " VALUES(?, ?, ?, ?, 1, ?)"
                " ON CONFLICT(email) DO UPDATE SET name = excluded.name, active = 1,"
                " is_admin = MAX(google_users.is_admin, excluded.is_admin)",
                (address, name.strip()[:120], _iso(), added_by, 1 if is_admin else 0),
            )
            conn.commit()
        return {"email": address, "name": name.strip()[:120], "active": True, "is_admin": is_admin}

    def remove_user(self, email: str) -> bool:
        address = normalize_email(email)
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM google_users WHERE email = ?", (address,))
            conn.execute("DELETE FROM google_sessions WHERE email = ?", (address,))
            conn.commit()
        return cursor.rowcount > 0

    def is_allowed(self, email: str) -> bool:
        address = email.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM google_users WHERE email = ? AND active = 1", (address,)
            ).fetchone()
        return row is not None

    def is_admin(self, email: str) -> bool:
        address = email.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM google_users WHERE email = ? AND active = 1 AND is_admin = 1",
                (address,),
            ).fetchone()
        return row is not None

    def set_admin(self, email: str, enabled: bool) -> bool:
        address = normalize_email(email)
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE google_users SET is_admin = ? WHERE email = ?",
                (1 if enabled else 0, address),
            )
            conn.commit()
        return cursor.rowcount > 0

    # -- sessions -------------------------------------------------------

    def create_session(self, email: str, ttl: int = SESSION_TTL) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM google_sessions WHERE expires_at < ?", (now,))
            conn.execute(
                "INSERT INTO google_sessions(token, email, created_at, expires_at) VALUES(?, ?, ?, ?)",
                (token, email.strip().lower(), _iso(), now + ttl),
            )
            conn.commit()
        return token

    def session_email(self, token: str) -> str | None:
        if not token:
            return None
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT email, expires_at FROM google_sessions WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) < now:
                conn.execute("DELETE FROM google_sessions WHERE token = ?", (token,))
                conn.commit()
                return None
            if not self.is_allowed(str(row["email"])):
                return None
        return str(row["email"])

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM google_sessions WHERE token = ?", (token,))
            conn.commit()


@dataclass
class _Flow:
    device_code: str
    user_code: str
    verification_url: str
    expires_at: float
    interval: float
    status: str = "pending"
    email: str = ""
    name: str = ""
    picture: str = ""
    error: str = ""
    token: str = ""


class GoogleDeviceFlow:
    def __init__(
        self,
        store: GoogleAuthStore,
        client: httpx.Client | None = None,
        *,
        relay_url: str = "",
        relay_token: str = "",
    ) -> None:
        self.store = store
        self._client = client
        self._lock = threading.RLock()
        self._flows: dict[str, _Flow] = {}
        # Guangzhou cannot reach Google directly; the Tokyo node can relay the
        # three fixed OAuth endpoints over the WireGuard tunnel.
        self.relay_url = relay_url.rstrip("/")
        self.relay_token = relay_token

    def _headers(self) -> dict[str, str]:
        return {"X-Relay-Token": self.relay_token} if self.relay_token else {}

    def _device_url(self) -> str:
        return f"{self.relay_url}/device/code" if self.relay_url else DEVICE_CODE_URL

    def _token_url(self) -> str:
        return f"{self.relay_url}/token" if self.relay_url else TOKEN_URL

    def _userinfo_url(self) -> str:
        return f"{self.relay_url}/userinfo" if self.relay_url else USERINFO_URL

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0))
        return self._client

    def start(self) -> dict[str, Any]:
        config = self.store.config()
        if not config.configured:
            raise GoogleAuthError("Google 登录尚未配置（需要 Client ID/Secret）", 503)
        if not config.enabled:
            raise GoogleAuthError("Google 登录未启用", 503)
        try:
            response = self._http().post(
                self._device_url(),
                data={"client_id": config.client_id, "scope": SCOPE},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise GoogleAuthError(f"无法连接 Google：{exc}", 502) from exc
        if response.status_code != 200:
            raise GoogleAuthError(f"Google 设备码请求失败：{response.status_code}", 502)
        payload = response.json()
        if "device_code" not in payload or "user_code" not in payload:
            raise GoogleAuthError("Google 返回的设备码格式异常", 502)
        flow_id = secrets.token_urlsafe(18)
        expires_in = max(60, int(payload.get("expires_in", 1800)))
        interval = max(5, int(payload.get("interval", 5)))
        verification = str(payload.get("verification_url") or payload.get("verification_uri") or "https://www.google.com/device")
        flow = _Flow(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_url=verification,
            expires_at=time.time() + expires_in,
            interval=interval,
        )
        with self._lock:
            self._flows[flow_id] = flow
        return {
            "flow_id": flow_id,
            "user_code": flow.user_code,
            "verification_url": flow.verification_url,
            "expires_in": expires_in,
            "interval": interval,
        }

    def poll(self, flow_id: str) -> dict[str, Any]:
        with self._lock:
            flow = self._flows.get(flow_id)
            if flow is None:
                raise GoogleAuthError("登录流程不存在或已过期，请重新发起", 404)
            if flow.status == "ok":
                return {"status": "ok", "email": flow.email, "name": flow.name, "picture": flow.picture, "session_token": flow.token}
            if flow.status not in ("pending",):
                return {"status": flow.status, "email": flow.email, "error": flow.error}
            if time.time() > flow.expires_at:
                flow.status = "expired"
                return {"status": "expired", "error": "授权码已过期，请重新发起登录"}
            config = self.store.config()
            if not config.configured:
                raise GoogleAuthError("Google 登录尚未配置", 503)
            try:
                response = self._http().post(
                    self._token_url(),
                    data={
                        "client_id": config.client_id,
                        "client_secret": config.client_secret,
                        "device_code": flow.device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    headers=self._headers(),
                )
            except httpx.HTTPError as exc:
                return {"status": "pending", "error": f"等待 Google（{exc}）"}
            payload = response.json() if response.content else {}
            error = str(payload.get("error") or "")
            if error in ("authorization_pending", "slow_down"):
                if error == "slow_down":
                    flow.interval = min(30.0, flow.interval + 5)
                return {"status": "pending", "interval": int(flow.interval)}
            if error in ("access_denied", "expired_token"):
                flow.status = "denied" if error == "access_denied" else "expired"
                flow.error = "用户拒绝了授权" if error == "access_denied" else "授权码已过期"
                return {"status": flow.status, "error": flow.error}
            if error:
                flow.status = "error"
                flow.error = f"Google 返回错误：{error}"
                return {"status": "error", "error": flow.error}
            access_token = str(payload.get("access_token") or "")
            if not access_token:
                flow.status = "error"
                flow.error = "Google 未返回 access_token"
                return {"status": "error", "error": flow.error}
            try:
                info_response = self._http().get(
                    self._userinfo_url(),
                    headers={**self._headers(), "Authorization": f"Bearer {access_token}"},
                )
                info = info_response.json()
            except httpx.HTTPError as exc:
                return {"status": "pending", "error": f"读取 Google 账号失败：{exc}"}
            email = str(info.get("email") or "").strip().lower()
            if not email:
                flow.status = "error"
                flow.error = "Google 账号没有返回邮箱"
                return {"status": "error", "error": flow.error}
            if info.get("email_verified") is False:
                flow.status = "error"
                flow.error = "Google 邮箱未验证"
                return {"status": "error", "error": flow.error}
            flow.email = email
            flow.name = str(info.get("name") or "")
            flow.picture = str(info.get("picture") or "")
            if not self.store.is_allowed(email):
                flow.status = "not_allowed"
                flow.error = f"{email} 不在后台允许名单中"
                return {"status": "not_allowed", "email": email, "error": flow.error}
            flow.token = self.store.create_session(email)
            flow.status = "ok"
            return {"status": "ok", "email": email, "name": flow.name, "picture": flow.picture, "session_token": flow.token}

    def cleanup(self) -> None:
        now = time.time()
        with self._lock:
            for flow_id in [key for key, flow in self._flows.items() if flow.expires_at + 3600 < now]:
                self._flows.pop(flow_id, None)
