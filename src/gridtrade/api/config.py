"""Runtime configuration for the HTTP API.

Everything is environment-driven and local by default. The API writes a random
access token to ``var/token`` on first boot instead of shipping a default
credential; the login screen accepts that token.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _token(var_dir: Path) -> str:
    env = os.environ.get("GRIDTRADE_TOKEN", "").strip()
    if env:
        return env
    var_dir.mkdir(parents=True, exist_ok=True)
    path = var_dir / "token"
    if path.exists():
        value = path.read_text().strip()
        if value:
            return value
    value = secrets.token_urlsafe(24)
    path.write_text(value + "\n")
    path.chmod(0o600)
    return value


@dataclass(slots=True)
class Settings:
    data_dir: Path = REPO_ROOT / "research" / "data"
    var_dir: Path = REPO_ROOT / "var"
    web_dir: Path = REPO_ROOT / "web" / "dist"
    symbol: str = "GOOGLUSDT"
    host: str = "127.0.0.1"
    port: int = 8000
    auto_run: bool = True
    secure_cookie: bool = False
    token: str = ""
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.var_dir = Path(self.var_dir)
        self.web_dir = Path(self.web_dir)
        self.var_dir.mkdir(parents=True, exist_ok=True)
        if not self.token:
            self.token = _token(self.var_dir)

    @classmethod
    def from_env(cls) -> Settings:
        origins = os.environ.get(
            "GRIDTRADE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        )
        return cls(
            data_dir=Path(os.environ.get("GRIDTRADE_DATA", REPO_ROOT / "research" / "data")),
            var_dir=Path(os.environ.get("GRIDTRADE_VAR", REPO_ROOT / "var")),
            web_dir=Path(os.environ.get("GRIDTRADE_WEB", REPO_ROOT / "web" / "dist")),
            symbol=os.environ.get("GRIDTRADE_SYMBOL", "GOOGLUSDT"),
            host=os.environ.get("GRIDTRADE_HOST", "127.0.0.1"),
            port=int(os.environ.get("GRIDTRADE_PORT", "8000")),
            auto_run=_env_bool("GRIDTRADE_AUTORUN", True),
            secure_cookie=_env_bool("GRIDTRADE_SECURE_COOKIE", False),
            token=os.environ.get("GRIDTRADE_TOKEN", "").strip(),
            cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        )
