"""Offline tests for the order/position reconciler and alerting."""

from __future__ import annotations

import json
from typing import Any

import pytest

from gridtrade.api.binance_reconcile import Alert, Ledger, Reconciler


class FakeClient:
    def __init__(self, orders: list[dict[str, Any]], positions: list[dict[str, Any]]) -> None:
        self._orders = orders
        self._positions = positions

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return list(self._orders)

    def positions_nonzero(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return list(self._positions)


class BoomClient(FakeClient):
    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        raise RuntimeError("tunnel down")


def make_recon(
    tmp_path,
    orders: list[dict[str, Any]] | None = None,
    positions: list[dict[str, Any]] | None = None,
    *,
    client: Any = None,
    **kwargs: Any,
) -> Reconciler:
    fake = client or FakeClient(orders or [], positions or [])
    ledger = Ledger(str(tmp_path / "ledger.json"))
    alert_log = str(tmp_path / "alerts.jsonl")
    return Reconciler(
        lambda: fake,
        ledger=ledger,
        alert_log=alert_log,
        **kwargs,
    )


def kinds(alerts: list[Alert]) -> list[str]:
    return [alert.kind for alert in alerts]


def test_clean_state_emits_nothing(tmp_path) -> None:
    recon = make_recon(tmp_path)
    assert recon.run_once() == []
    assert recon.alerts() == []
    assert recon.last_error is None


def test_unexpected_exchange_order_is_critical(tmp_path) -> None:
    recon = make_recon(
        tmp_path,
        orders=[{"orderId": 1, "symbol": "DOGEUSDT", "price": "0.05", "origQty": "100"}],
    )
    assert "unexpected_order" in kinds(recon.run_once())
    assert recon.alerts()[0]["level"] == "critical"


def test_ledger_order_missing_on_exchange_is_warn_and_marked_vanished(tmp_path) -> None:
    recon = make_recon(tmp_path)
    recon.ledger.record_order({"orderId": 42, "symbol": "DOGEUSDT", "status": "NEW"})
    assert "order_vanished" in kinds(recon.run_once())
    assert recon.ledger.open_entries() == {}
    assert recon.ledger.all_entries()["42"]["status"] == "VANISHED"


def test_known_ledger_order_is_not_flagged(tmp_path) -> None:
    recon = make_recon(
        tmp_path,
        orders=[{"orderId": 7, "symbol": "DOGEUSDT", "price": "0.05", "origQty": "10"}],
    )
    recon.ledger.record_order({"orderId": 7, "symbol": "DOGEUSDT", "status": "NEW"})
    assert recon.run_once() == []


def test_too_many_orders(tmp_path) -> None:
    orders = [
        {"orderId": index, "symbol": "DOGEUSDT", "price": "0.05", "origQty": "1"}
        for index in range(5)
    ]
    recon = make_recon(tmp_path, orders=orders, max_open_orders=2)
    for order in orders:
        recon.ledger.record_order({**order, "status": "NEW"})
    found = kinds(recon.run_once())
    assert "too_many_orders" in found


def test_order_notional_limit(tmp_path) -> None:
    order = {"orderId": 1, "symbol": "DOGEUSDT", "price": "10", "origQty": "100"}
    recon = make_recon(tmp_path, orders=[order], max_order_notional=50.0)
    recon.ledger.record_order({**order, "status": "NEW"})
    assert "order_notional" in kinds(recon.run_once())


def test_position_notional_limit(tmp_path) -> None:
    position = {"symbol": "DOGEUSDT", "positionAmt": "1000", "markPrice": "0.05"}
    recon = make_recon(tmp_path, positions=[position], max_position_notional=10.0)
    assert "position_notional" in kinds(recon.run_once())


def test_liquidation_distance_is_critical(tmp_path) -> None:
    position = {
        "symbol": "DOGEUSDT",
        "positionAmt": "10",
        "markPrice": "100",
        "liquidationPrice": "96",
    }
    recon = make_recon(tmp_path, positions=[position])
    found = kinds(recon.run_once())
    assert "liquidation_risk" in found


def test_unreachable_exchange_emits_warn(tmp_path) -> None:
    recon = make_recon(tmp_path, client=BoomClient([], []))
    found = kinds(recon.run_once())
    assert found == ["unreachable"]
    assert "tunnel down" in (recon.last_error or "")


def test_critical_alert_auto_engages_kill_switch(tmp_path) -> None:
    kill = tmp_path / "KILL"
    recon = make_recon(
        tmp_path,
        orders=[{"orderId": 1, "symbol": "DOGEUSDT", "price": "1", "origQty": "1"}],
        auto_kill_file=str(kill),
    )
    recon.run_once()
    assert kill.exists()


def test_alerts_are_ring_buffered_and_written_to_jsonl(tmp_path) -> None:
    recon = make_recon(
        tmp_path,
        orders=[{"orderId": 1, "symbol": "DOGEUSDT", "price": "1", "origQty": "1"}],
        ring_size=3,
    )
    recon.run_once()
    recon.run_once()
    assert len(recon.alerts(limit=10)) == 2  # one alert per run
    lines = (tmp_path / "alerts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == "unexpected_order"


def test_alert_as_dict_is_json_serialisable() -> None:
    alert = Alert(ts=1.0, level="warn", kind="x", message="y", details={"a": 1})
    assert json.loads(json.dumps(alert.as_dict()))["level"] == "warn"


def test_reconciler_start_stop_is_idempotent(tmp_path) -> None:
    recon = make_recon(tmp_path)
    recon.start(interval_s=60)
    recon.start(interval_s=60)  # second call must not spawn another thread
    recon.stop()
    assert recon._thread is not None
