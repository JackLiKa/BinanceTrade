"""Live Gate integration tests: signing, env persistence, analysis, locks."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from gridtrade.api import live_gate
from gridtrade.api.config import LiveConfig
from gridtrade.api.live_gate import (
    GatePrivateClient,
    LiveLocked,
    LiveRejected,
    LiveService,
    write_env_file,
)


class FakeClient:
    def __init__(self) -> None:
        self.orders: list[dict] = []
        self.cancelled: list[str] = []
        self.account_data = {
            "currency": "USDT",
            "total": "1000",
            "available": "800",
            "unrealised_pnl": "20",
            "maintenance_margin": "10",
            "position_margin": "100",
            "order_margin": "5",
        }
        self.position_data = [
            {
                "contract": "BTC_USDT",
                "size": 2,
                "mark_price": "100",
                "entry_price": "90",
                "liq_price": "50",
                "leverage": 5,
                "margin": "40",
                "unrealised_pnl": "20",
                "realised_pnl": "0",
            }
        ]
        self.contract_data = [
            {
                "name": "BTC_USDT",
                "quanto_multiplier": "0.01",
                "order_size_min": 1,
                "order_price_round": "0.1",
            }
        ]

    def close(self) -> None:
        pass

    def account(self) -> dict:
        return dict(self.account_data)

    def positions(self) -> list[dict]:
        return [dict(row) for row in self.position_data]

    def open_orders(self) -> list[dict]:
        return []

    def my_trades(self, limit: int = 50) -> list[dict]:
        return [
            {"contract": "BTC_USDT", "size": 2, "price": "95", "fee": "-0.05", "role": "maker"},
            {"contract": "BTC_USDT", "size": -1, "price": "100", "fee": "-0.04", "role": "taker"},
            {"contract": "BTC_USDT", "size": 1, "price": "98", "fee": "-0.03", "role": "maker"},
        ]

    def account_book(self, limit: int = 100) -> list[dict]:
        return [
            {"type": "pnl", "change": "5", "contract": "BTC_USDT"},
            {"type": "fee", "change": "-1", "contract": "BTC_USDT"},
            {"type": "fund", "change": "-0.2", "contract": "BTC_USDT"},
        ]

    def fee(self) -> list[dict]:
        return [{"contract": "BTC_USDT", "maker_fee_rate": "-0.0001", "taker_fee_rate": "0.0005"}]

    def contracts(self) -> list[dict]:
        return [dict(row) for row in self.contract_data]

    def ticker(self, contract: str) -> dict:
        return {"contract": contract, "mark_price": "100", "index_price": "100"}

    def create_order(self, body: dict) -> dict:
        self.orders.append(body)
        return {"id": 123, **body}

    def cancel_order(self, order_id: str) -> dict:
        self.cancelled.append(order_id)
        return {"id": order_id, "status": "finished"}

    def set_leverage(self, contract: str, leverage: int) -> dict:
        return {"contract": contract, "leverage": leverage}


def service(**overrides) -> LiveService:
    values = {
        "enabled": True,
        "trading_enabled": False,
        "api_key": "key-123456",
        "api_secret": "secret",
        "max_notional": 5000,
        "max_order_notional": 1000,
        "max_position_notional": 3000,
        "max_open_orders": 20,
    }
    values.update(overrides)
    fake = FakeClient()
    svc = LiveService(LiveConfig(**values), client_factory=lambda *_: fake)
    return svc


def test_api_v4_signature_matches_official_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_gate.time, "time", lambda: 1794900000.5)
    client = GatePrivateClient("key", "secret")
    headers = client._sign("GET", "/futures/usdt/accounts", "", "", "1794900000.5")
    body = ""
    payload = hashlib.sha512(body.encode()).hexdigest()
    message = f"GET\n/futures/usdt/accounts\n\n{payload}\n1794900000.5"
    expected = hmac.new(b"secret", message.encode(), hashlib.sha512).hexdigest()
    assert headers == {"KEY": "key", "Timestamp": "1794900000.5", "SIGN": expected}
    client.close()


def test_env_file_updates_and_preserves_comments(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# keep me\nGRIDTRADE_TOKEN=abc\nGATE_API_KEY=old\n", encoding="utf-8")
    write_env_file(
        path,
        {
            "GATE_API_KEY": "new",
            "GATE_API_SECRET": "sec",
            "GRIDTRADE_LIVE_ENABLED": "1",
            "GRIDTRADE_TOKEN": None,
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "GATE_API_KEY=new" in text
    assert "GATE_API_SECRET=sec" in text
    assert "GRIDTRADE_LIVE_ENABLED=1" in text
    assert "GRIDTRADE_TOKEN" not in text
    assert oct(path.stat().st_mode & 0o777) == oct(0o600)


def test_snapshot_builds_analysis_and_warnings() -> None:
    svc = service(max_notional=1.0, max_position_notional=1.0)
    snapshot = svc.snapshot(force=True)
    analysis = snapshot["analysis"]
    assert analysis["equity"] == pytest.approx(1000)
    assert analysis["gross_notional"] == pytest.approx(2.0)  # 2 contracts × 100 × 0.01
    assert analysis["realized"] == pytest.approx(5)
    assert analysis["fees_paid"] == pytest.approx(1)
    assert analysis["funding_paid"] == pytest.approx(0.2)
    assert analysis["open_orders"] == 0
    assert len(snapshot["positions"]) == 1
    assert any("总名义" in warning for warning in analysis["warnings"])
    assert snapshot["config"]["api_key_hint"] == "…3456"
    assert "api_secret" not in snapshot["config"]


def test_orders_are_locked_until_explicitly_enabled() -> None:
    svc = service(trading_enabled=False)
    with pytest.raises(LiveLocked):
        svc.place_order("BTC_USDT", 1)
    with pytest.raises(LiveLocked):
        svc.cancel_order("123")


def test_order_limits_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = service(trading_enabled=True, max_order_notional=0.5)
    with pytest.raises(LiveRejected):
        svc.place_order("BTC_USDT", 1)  # 1 × 100 × 0.01 = 1.0 > 0.5


def test_order_inside_limits_is_sent() -> None:
    svc = service(trading_enabled=True, max_order_notional=1000, max_notional=1000)
    result = svc.place_order("BTC_USDT", 1, price="100", tif="gtc")
    assert result["id"] == 123
    assert result["contract"] == "BTC_USDT"
    fake = svc._client
    assert fake is not None
    assert fake.orders[0]["size"] == 1


def test_connection_uses_private_account() -> None:
    svc = service()
    result = svc.test_connection()
    assert result["ok"] is True
    assert result["total"] == pytest.approx(1000)
