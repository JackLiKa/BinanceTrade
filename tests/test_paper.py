"""Paper-trading engine tests: deterministic ticks, fees, funding and stop."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from gridtrade.api.config import PaperConfig
from gridtrade.api.paper import PaperEngine


class FakeFeed:
    def __init__(self, mark: float = 100.0) -> None:
        self.mark = mark
        self.funding_rows: list[dict[str, float | str]] = []
        self.next_apply = int(time.time()) + 3_600

    def contract(self) -> dict[str, float | int | str]:
        return {
            "order_price_round": "0.01",
            "quanto_multiplier": "0.01",
            "order_size_min": 1,
            "funding_next_apply": self.next_apply,
            "funding_interval": 28_800,
            "mark_price": str(self.mark),
        }

    def ticker(self) -> dict[str, float | str]:
        return {
            "mark_price": str(self.mark),
            "index_price": str(self.mark),
            "funding_rate": "0.0001",
            "change_percentage": "0.5",
        }

    def funding(self, limit: int = 10) -> list[dict[str, float | str]]:
        return self.funding_rows


def make_engine(tmp_path: Path, **config: float | int | str) -> tuple[PaperEngine, FakeFeed]:
    values: dict[str, float | int | str] = {
        "capital": 10_000.0,
        "leverage": 2.0,
        "spacing_bp": 100.0,
        "levels": 10,
        "maker_fee_bp": 2.0,
        "taker_fee_bp": 5.0,
        "stop_dd_pct": 0.0,
        "poll_seconds": 3_600.0,
        "autostart": False,
        "symbol": "TEST_USDT",
    }
    values.update(config)
    cfg = PaperConfig(**values)
    feed = FakeFeed()
    engine = PaperEngine(cfg, tmp_path, feed=feed)
    engine.start(reset=True, background=False)
    return engine, feed


def test_grid_fills_charge_fees_and_realize_pnl(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    assert engine.account.unit == pytest.approx(20.0)
    assert engine.account.anchor == pytest.approx(100.0)

    feed.mark = 99.0
    engine.tick()
    account = engine.account
    assert account.position == pytest.approx(20.0)
    assert account.avg_entry == pytest.approx(99.0)
    assert account.fees == pytest.approx(20 * 99 * 0.0002)
    assert account.cash == pytest.approx(10_000 - 20 * 99 * 0.0002)

    feed.mark = 100.5
    engine.tick()
    assert account.position == pytest.approx(0.0)
    assert account.realized == pytest.approx(20.0)
    assert account.fees == pytest.approx(20 * 99 * 0.0002 + 20 * 100 * 0.0002)
    assert engine.equity == pytest.approx(10_000 + 20 - 20 * 99 * 0.0002 - 20 * 100 * 0.0002)

    snapshot = engine.snapshot()
    assert snapshot["source"] == "gate"
    assert snapshot["account"]["return_pct"] == pytest.approx(
        (engine.equity / 10_000 - 1) * 100
    )
    assert snapshot["grid"]["buy_price"] == pytest.approx(99.0)
    assert snapshot["grid"]["sell_price"] == pytest.approx(101.0)
    assert len(snapshot["fills"]) == 2


def test_funding_long_pays_and_short_receives(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    account = engine.account
    feed.mark = 99.5
    account.position = 20.0
    account.avg_entry = 100.0
    when = int(time.time()) - 1
    account.funding_next = when
    feed.funding_rows = [{"t": when, "r": "0.0001"}]
    cash_before = account.cash

    engine.tick()
    payment = 20 * 99.5 * 0.0001
    assert account.funding == pytest.approx(payment)
    assert account.cash == pytest.approx(cash_before - payment)
    assert account.funding_next == when + 28_800
    assert engine.snapshot()["funding"][0]["rate"] == pytest.approx(0.0001)

    engine2, feed2 = make_engine(tmp_path / "short")
    account2 = engine2.account
    feed2.mark = 100.5
    account2.position = -20.0
    account2.avg_entry = 100.0
    when2 = int(time.time()) - 1
    account2.funding_next = when2
    feed2.funding_rows = [{"t": when2, "r": "0.0001"}]
    cash2 = account2.cash

    engine2.tick()
    payment2 = -20 * 100.5 * 0.0001
    assert account2.funding == pytest.approx(payment2)
    assert account2.cash == pytest.approx(cash2 - payment2)


def test_stop_loss_flattens_and_persists(tmp_path: Path) -> None:
    engine, feed = make_engine(
        tmp_path,
        capital=1_000.0,
        leverage=1.0,
        stop_dd_pct=1.0,
    )
    feed.mark = 99.0
    engine.tick()
    assert engine.account.position > 0

    feed.mark = 90.0
    engine.tick()
    assert engine.status == "halted"
    assert engine.account.position == pytest.approx(0.0)
    assert engine.last_error is not None and "止损" in engine.last_error

    reloaded = PaperEngine(engine.config, tmp_path, feed=feed)
    assert reloaded.status == "halted"
    assert reloaded.account.position == pytest.approx(0.0)
    assert reloaded.account.cash == pytest.approx(engine.account.cash)


def test_reset_reanchors_and_clears_history(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    feed.mark = 99.0
    engine.tick()
    assert engine.account.position != 0

    feed.mark = 120.0
    state = engine.reset()
    assert state["account"]["position"] == pytest.approx(0.0)
    assert state["account"]["cash"] == pytest.approx(10_000.0)
    assert state["grid"]["anchor"] == pytest.approx(120.0)
    assert state["fills"] == []
