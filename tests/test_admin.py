"""Admin console tests: default account, sessions, password, config writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from gridtrade.api.admin import AdminAuth, AdminError, AdminService
from gridtrade.api.config import LiveConfig, PaperConfig, Settings


class FakeStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def audit(self, action: str, detail: str, *, actor: str = "local") -> None:
        self.events.append((action, detail))

    def list_audit(self, *, limit: int = 60) -> list[dict]:
        return [{"ts": "2026-01-01T00:00:00Z", "action": a, "detail": d} for a, d in self.events[-limit:]]


class FakeLive:
    def __init__(self) -> None:
        self.config: LiveConfig | None = None

    def masked_config(self) -> dict:
        cfg = self.config or LiveConfig()
        return {
            "enabled": cfg.enabled,
            "trading_enabled": cfg.trading_enabled,
            "configured": cfg.configured,
            "api_key_hint": "…" + cfg.api_key[-4:] if cfg.api_key else "",
            "max_notional": cfg.max_notional,
            "max_order_notional": cfg.max_order_notional,
            "max_position_notional": cfg.max_position_notional,
            "max_open_orders": cfg.max_open_orders,
        }

    def update_config(self, config: LiveConfig) -> None:
        self.config = config


class FakePaper:
    def __init__(self) -> None:
        self.resets: list[dict] = []

    def snapshot(self) -> dict:
        return {
            "status": "running",
            "symbols": ["AAA_USDT", "BBB_USDT"],
            "account": {"equity": 10_000.0, "fees": 0.0, "funding": 0.0, "realized": 0.0},
            "config": {"symbols": ["AAA_USDT", "BBB_USDT"], "capital": 10_000, "levels": 20},
        }

    def reset(self, overrides: dict | None = None) -> dict:
        self.resets.append(overrides or {})
        return self.snapshot()

    def start(self, **_: object) -> dict:
        return self.snapshot()

    def stop(self) -> dict:
        return self.snapshot()


def make_service(tmp_path: Path) -> tuple[AdminService, FakeLive, FakePaper, FakeStore]:
    settings = Settings(
        data_dir=tmp_path / "data",
        var_dir=tmp_path / "var",
        web_dir=tmp_path / "dist",
        token="panel-token",
        env_path=tmp_path / ".env",
        live=LiveConfig(),
        paper=PaperConfig(),
    )
    store = FakeStore()
    live = FakeLive()
    paper = FakePaper()
    service = AdminService(settings, store, live, paper)
    return service, live, paper, store


def test_default_credentials_and_session(tmp_path: Path) -> None:
    auth = AdminAuth(tmp_path / "admin.db")
    assert auth.username() == "admin"
    assert auth.default_password() is True

    with pytest.raises(AdminError):
        auth.login("admin", "wrong")

    token = auth.login("admin", "admin")
    assert auth.check(token) is True
    auth.logout(token)
    assert auth.check(token) is False


def test_password_change_rejects_default_and_old_password(tmp_path: Path) -> None:
    auth = AdminAuth(tmp_path / "admin.db")
    token = auth.login("admin", "admin")
    with pytest.raises(AdminError):
        auth.change_password(token, "admin", "admin")
    with pytest.raises(AdminError):
        auth.change_password(token, "wrong", "newpass")
    auth.change_password(token, "admin", "newpass")
    assert auth.default_password() is False
    with pytest.raises(AdminError):
        auth.login("admin", "admin")
    assert auth.login("admin", "newpass")


def test_admin_can_write_live_config_to_env(tmp_path: Path) -> None:
    service, live, _, _ = make_service(tmp_path)
    config = service.save_live(
        {
            "api_key": "abc123",
            "api_secret": "secret",
            "enabled": True,
            "max_notional": 3210,
            "max_order_notional": 123,
        }
    )
    assert config["enabled"] is True
    assert live.config is not None and live.config.api_key == "abc123"
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GATE_API_KEY=abc123" in text
    assert "GATE_API_SECRET=secret" in text
    assert "GRIDTRADE_LIVE_ENABLED=1" in text
    assert "GRIDTRADE_LIVE_MAX_NOTIONAL=3210" in text


def test_admin_trading_requires_confirmation(tmp_path: Path) -> None:
    service, _, _, _ = make_service(tmp_path)
    service.save_live({"api_key": "abc", "api_secret": "secret", "enabled": True})
    with pytest.raises(AdminError):
        service.save_live({"trading_enabled": True})
    service.save_live({"trading_enabled": True, "confirm_trading": True})
    assert "GRIDTRADE_LIVE_TRADING=1" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_admin_can_update_paper_symbols_and_reset(tmp_path: Path) -> None:
    service, _, paper, _ = make_service(tmp_path)
    result = service.save_paper(
        {"symbols": ["SKHY_USDT", "GOOGL_USDT"], "capital": 5000, "levels": 10}
    )
    assert result["config"] is not None
    assert paper.resets[-1]["symbols"] == ["SKHY_USDT", "GOOGL_USDT"]
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GRIDTRADE_PAPER_SYMBOLS=SKHY_USDT,GOOGL_USDT" in text
    assert "GRIDTRADE_PAPER_CAPITAL=5000.0" in text


def test_token_rotation_updates_var_and_env(tmp_path: Path) -> None:
    service, _, _, _ = make_service(tmp_path)
    result = service.rotate_token()
    token = result["token"]
    assert (tmp_path / "var" / "token").read_text(encoding="utf-8").strip() == token
    assert f"GRIDTRADE_TOKEN={token}" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert service.settings.token == token
