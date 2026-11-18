"""Login gate for the TradingWorkstation project on tw.jacklika.com.

Password + Google OAuth (reusing the panel's registered Google Web client),
with a first-login flow that asks an allowed Gmail user to create a password.
Only ``TRADING_ALLOWED_EMAILS`` may use Google login.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

SESSION_TTL = 30 * 24 * 3600
PBKDF2_ROUNDS = 200_000
COOKIE = "tw_session"
SCHEMA = """
CREATE TABLE IF NOT EXISTS tw_users (
    email TEXT PRIMARY KEY COLLATE NOCASE,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tw_sessions (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tw_pending (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    next_path TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tw_codes (
    code TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    next_path TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def safe_next(value: str | None) -> str:
    candidate = (value or "/TradingWorkstation").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/TradingWorkstation"
    return candidate[:500]


class TwAuthStore:
    def __init__(self, db_path: Path, allowed_emails: list[str]) -> None:
        self.db_path = Path(db_path)
        self.allowed = {email.strip().lower() for email in allowed_emails if email.strip()}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def allowed_email(self, email: str) -> bool:
        return email.strip().lower() in self.allowed

    def has_password(self, email: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM tw_users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return row is not None

    def set_password(self, email: str, password: str) -> None:
        address = email.strip().lower()
        salt = secrets.token_hex(16)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tw_users(email, salt, password_hash, created_at) VALUES(?, ?, ?, ?)"
                " ON CONFLICT(email) DO UPDATE SET salt = excluded.salt, password_hash = excluded.password_hash",
                (address, salt, _hash(password, salt), _iso()),
            )
            conn.commit()

    def verify(self, email: str, password: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT salt, password_hash FROM tw_users WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        if row is None:
            return False
        return hmac.compare_digest(_hash(password, row["salt"]), row["password_hash"])

    def change_password(self, email: str, current: str, new: str) -> bool:
        if not self.verify(email, current):
            return False
        self.set_password(email, new)
        return True

    def create_session(self, email: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM tw_sessions WHERE expires_at < ?", (now,))
            conn.execute(
                "INSERT INTO tw_sessions(token, email, expires_at) VALUES(?, ?, ?)",
                (token, email.strip().lower(), now + SESSION_TTL),
            )
            conn.commit()
        return token

    def session_email(self, token: str) -> str | None:
        if not token:
            return None
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT email, expires_at FROM tw_sessions WHERE token = ?", (token,)
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) < now:
                conn.execute("DELETE FROM tw_sessions WHERE token = ?", (token,))
                conn.commit()
                return None
        return str(row["email"])

    def revoke(self, token: str) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM tw_sessions WHERE token = ?", (token,))
            conn.commit()

    def create_pending(self, email: str, next_path: str, ttl: int = 900) -> str:
        token = secrets.token_urlsafe(24)
        with self._connect() as conn:
            conn.execute("DELETE FROM tw_pending WHERE expires_at < ?", (time.time(),))
            conn.execute(
                "INSERT INTO tw_pending(token, email, next_path, expires_at) VALUES(?, ?, ?, ?)",
                (token, email.strip().lower(), safe_next(next_path), time.time() + ttl),
            )
            conn.commit()
        return token

    def consume_pending(self, token: str) -> tuple[str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT email, next_path, expires_at FROM tw_pending WHERE token = ?", (token,)
            ).fetchone()
            conn.execute("DELETE FROM tw_pending WHERE token = ?", (token,))
            conn.commit()
        if row is None or float(row["expires_at"]) < time.time():
            return None
        return str(row["email"]), str(row["next_path"])

    def create_code(self, email: str, next_path: str, ttl: int = 180) -> str:
        code = secrets.token_urlsafe(24)
        with self._connect() as conn:
            conn.execute("DELETE FROM tw_codes WHERE expires_at < ?", (time.time(),))
            conn.execute(
                "INSERT INTO tw_codes(code, email, next_path, expires_at) VALUES(?, ?, ?, ?)",
                (code, email.strip().lower(), safe_next(next_path), time.time() + ttl),
            )
            conn.commit()
        return code

    def consume_code(self, code: str) -> tuple[str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT email, next_path, expires_at FROM tw_codes WHERE code = ?", (code,)
            ).fetchone()
            conn.execute("DELETE FROM tw_codes WHERE code = ?", (code,))
            conn.commit()
        if row is None or float(row["expires_at"]) < time.time():
            return None
        return str(row["email"]), str(row["next_path"])


def login_page(*, next_path: str = "/TradingWorkstation", error: str = "") -> str:
    next_value = html.escape(safe_next(next_path), quote=True)
    error_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
    google_url = "/__tw_auth/google/start?next=" + quote(next_value)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TradingWorkstation 登录</title>
<style>
:root{{color-scheme:dark}} body{{margin:0;background:#0b0e11;color:#eaecef;font:14px/1.5 -apple-system,"Segoe UI","PingFang SC",sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.box{{width:min(380px,calc(100vw - 32px));background:#151a21;border:1px solid #2b3139;border-radius:16px;padding:26px}}
h1{{font-size:18px;margin:0 0 4px}} p{{color:#848e9c;font-size:12px;margin:0 0 18px}}
label{{display:block;font-size:12px;color:#848e9c;margin:12px 0 5px}}
input{{width:100%;height:38px;border-radius:8px;border:1px solid #2b3139;background:#1c222b;color:#eaecef;padding:0 10px;box-sizing:border-box}}
button{{width:100%;height:40px;margin-top:16px;border:0;border-radius:8px;background:#fcd535;color:#0b0e11;font-weight:700;font-size:13px;cursor:pointer}}
.g{{display:flex;align-items:center;justify-content:center;gap:8px;height:42px;border:1px solid #2b3139;border-radius:8px;background:#1c222b;color:#eaecef;text-decoration:none;font-size:13px}}
.g svg{{width:17px;height:17px}} .err{{background:#2a1216;border:1px solid #5c2029;color:#f6465d;padding:8px 10px;border-radius:8px;font-size:12px;margin:10px 0}}
.hr{{display:flex;align-items:center;gap:8px;color:#5e6673;font-size:10px;margin:16px 0}} .hr:before,.hr:after{{content:"";flex:1;height:1px;background:#2b3139}}
</style></head><body><form class="box" method="post" action="/__tw_auth/login">
<h1>TradingWorkstation</h1><p>使用账号密码登录；首次使用请先通过 Gmail 创建密码。</p>
{error_html}
<a class="g" href="{google_url}"><svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>使用 Gmail 登录</a>
<div class="hr">或账号密码</div>
<input type="hidden" name="next" value="{next_value}">
<label>邮箱</label><input name="email" type="email" autocomplete="username" required>
<label>密码</label><input name="password" type="password" autocomplete="current-password" required>
<button type="submit">登录</button>
<p style="text-align:center;margin:12px 0 0"><a href="/__tw_auth/change-password" style="color:#fcd535;text-decoration:none">修改密码</a></p>
</form></body></html>"""


def set_password_page(*, token: str, next_path: str = "/TradingWorkstation", error: str = "") -> str:
    next_value = html.escape(safe_next(next_path), quote=True)
    token_value = html.escape(token, quote=True)
    error_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>创建密码</title>
<style>
body{{margin:0;background:#0b0e11;color:#eaecef;font:14px/1.5 -apple-system,"Segoe UI","PingFang SC",sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.box{{width:min(380px,calc(100vw - 32px));background:#151a21;border:1px solid #2b3139;border-radius:16px;padding:26px}}
h1{{font-size:18px;margin:0 0 4px}} p{{color:#848e9c;font-size:12px;margin:0 0 14px}}
label{{display:block;font-size:12px;color:#848e9c;margin:12px 0 5px}}
input{{width:100%;height:38px;border-radius:8px;border:1px solid #2b3139;background:#1c222b;color:#eaecef;padding:0 10px;box-sizing:border-box}}
button{{width:100%;height:40px;margin-top:16px;border:0;border-radius:8px;background:#fcd535;color:#0b0e11;font-weight:700;font-size:13px;cursor:pointer}}
.err{{background:#2a1216;border:1px solid #5c2029;color:#f6465d;padding:8px 10px;border-radius:8px;font-size:12px;margin:10px 0}}
</style></head><body><form class="box" method="post" action="/__tw_auth/set-password">
<h1>创建登录密码</h1><p>Gmail 已验证。设置密码后即可用邮箱 + 密码登录。</p>{error_html}
<input type="hidden" name="token" value="{token_value}"><input type="hidden" name="next" value="{next_value}">
<label>新密码（至少 8 位）</label><input name="password" type="password" minlength="8" required>
<label>确认密码</label><input name="password2" type="password" minlength="8" required>
<button type="submit">创建密码并登录</button>
</form></body></html>"""


def change_password_page(*, email: str, next_path: str = "/TradingWorkstation", error: str = "", ok: str = "") -> str:
    next_value = html.escape(safe_next(next_path), quote=True)
    email_value = html.escape(email, quote=True)
    notice = f'<div class="ok">{html.escape(ok)}</div>' if ok else ""
    error_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>修改密码</title>
<style>
body{{margin:0;background:#0b0e11;color:#eaecef;font:14px/1.5 -apple-system,"Segoe UI","PingFang SC",sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.box{{width:min(400px,calc(100vw - 32px));background:#151a21;border:1px solid #2b3139;border-radius:16px;padding:26px}}
h1{{font-size:18px;margin:0 0 4px}} p{{color:#848e9c;font-size:12px;margin:0 0 14px}}
label{{display:block;font-size:12px;color:#848e9c;margin:12px 0 5px}}
input{{width:100%;height:38px;border-radius:8px;border:1px solid #2b3139;background:#1c222b;color:#eaecef;padding:0 10px;box-sizing:border-box}}
button{{width:100%;height:40px;margin-top:16px;border:0;border-radius:8px;background:#fcd535;color:#0b0e11;font-weight:700;font-size:13px;cursor:pointer}}
a{{display:block;text-align:center;margin-top:12px;color:#fcd535;font-size:12px;text-decoration:none}}
.err{{background:#2a1216;border:1px solid #5c2029;color:#f6465d;padding:8px 10px;border-radius:8px;font-size:12px;margin:10px 0}}
.ok{{background:#0f2119;border:1px solid #0ecb81;color:#7ce5b6;padding:8px 10px;border-radius:8px;font-size:12px;margin:10px 0}}
</style></head><body><form class="box" method="post" action="/__tw_auth/change-password">
<h1>修改登录密码</h1><p>{email_value}</p>{notice}{error_html}
<input type="hidden" name="next" value="{next_value}">
<label>当前密码</label><input name="current" type="password" autocomplete="current-password" required>
<label>新密码（至少 8 位）</label><input name="new" type="password" minlength="8" required>
<label>确认新密码</label><input name="new2" type="password" minlength="8" required>
<button type="submit">保存新密码</button>
<a href="{next_value}">返回 TradingWorkstation</a>
</form></body></html>"""
