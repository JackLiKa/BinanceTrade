"""Paper-trading engine tests: multi-symbol portfolio, fees, funding, stop."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from gridtrade.api.config import PaperConfig
from gridtrade.api.paper import PaperEngine


class FakeFeed:
    def __init__(self, exchange_fees: bool = False) -> None:
        self.exchange_fees = exchange_fees
        self.marks = {"AAA_USDT": 100.0, "BBB_USDT": 50.0}
        self.funding_rows: dict[str, list[dict[str, float | str]]] = {
            "AAA_USDT": [],
            "BBB_USDT": [],
        }
        self.next_apply = int(time.time()) + 3_600

    def contract(self, symbol: str) -> dict[str, float | int | str]:
        data: dict[str, float | int | str] = {
            "order_price_round": "0.01",
            "quanto_multiplier": "0.01",
            "order_size_min": 1,
            "funding_next_apply": self.next_apply,
            "funding_interval": 28_800,
        }
        if self.exchange_fees:
            data["maker_fee_rate"] = "-0.0001"
            data["taker_fee_rate"] = "0.0006"
        return data

    def tickers(self, symbols: list[str]) -> list[dict[str, float | str]]:
        return [
            {
                "contract": symbol,
                "mark_price": str(self.marks[symbol]),
                "index_price": str(self.marks[symbol]),
                "funding_rate": "0.0001",
                "change_percentage": "0.5",
            }
            for symbol in symbols
        ]

    def funding(self, symbol: str, limit: int = 10) -> list[dict[str, float | str]]:
        return self.funding_rows.get(symbol, [])


def make_engine(tmp_path: Path, **config: object) -> tuple[PaperEngine, FakeFeed]:
    values: dict[str, object] = {
        "capital": 10_000.0,
        "leverage": 2.0,
        "spacing_bp": 100.0,
        "levels": 10,
        "maker_fee_bp": 2.0,
        "taker_fee_bp": 5.0,
        "stop_dd_pct": 0.0,
        "poll_seconds": 3_600.0,
        "autostart": False,
        "symbols": ["AAA_USDT", "BBB_USDT"],
    }
    values.update(config)
    feed = FakeFeed(exchange_fees=bool(values.pop("exchange_fees", False)))
    engine = PaperEngine(PaperConfig(**values), tmp_path, feed=feed)
    engine.start(reset=True, background=False)
    return engine, feed


def test_portfolio_sizing_and_shared_fees(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    assert set(engine.state) == {"AAA_USDT", "BBB_USDT"}
    assert engine.state["AAA_USDT"].unit == pytest.approx(10.0)
    assert engine.state["BBB_USDT"].unit == pytest.approx(20.0)

    feed.marks["AAA_USDT"] = 99.0
    feed.marks["BBB_USDT"] = 49.5
    engine.tick()
    account = engine.account
    aaa = engine.state["AAA_USDT"]
    bbb = engine.state["BBB_USDT"]
    assert aaa.position == pytest.approx(10.0)
    assert bbb.position == pytest.approx(20.0)
    fee_aaa = 10 * 99 * 0.0002
    fee_bbb = 20 * 49.5 * 0.0002
    assert account.fees == pytest.approx(fee_aaa + fee_bbb)
    assert account.cash == pytest.approx(10_000 - fee_aaa - fee_bbb)
    assert engine.equity == pytest.approx(account.cash)

    feed.marks["AAA_USDT"] = 100.5
    engine.tick()
    assert aaa.position == pytest.approx(0.0)
    assert account.realized == pytest.approx(10.0)

    snapshot = engine.snapshot()
    assert snapshot["symbols"] == ["AAA_USDT", "BBB_USDT"]
    assert snapshot["account"]["gross_notional"] > 0
    assert len(snapshot["portfolio"]) == 2
    assert snapshot["portfolio"][1]["unit"] == pytest.approx(20.0)
    assert len(snapshot["fills"]) == 3
    assert {fill["symbol"] for fill in snapshot["fills"]} == {"AAA_USDT", "BBB_USDT"}


def test_shared_margin_cap_blocks_overexposure(tmp_path: Path) -> None:
    engine, _ = make_engine(tmp_path)
    state = engine.state["AAA_USDT"]
    engine.equity = 1_000.0
    engine.config.leverage = 2.0  # cap = 2000
    engine.gross = 1_900.0
    assert engine._has_margin(state, 100.0, 0.5) is True  # 1950 <= 2000
    engine.gross = 1_980.0
    assert engine._has_margin(state, 100.0, 0.5) is False  # 2030 > 2000


def test_funding_per_symbol_and_net_cost(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    aaa = engine.state["AAA_USDT"]
    bbb = engine.state["BBB_USDT"]
    aaa.position, aaa.avg_entry = 10.0, 100.0
    bbb.position, bbb.avg_entry = -20.0, 50.0
    when = int(time.time()) - 1
    aaa.funding_next = when
    bbb.funding_next = when
    feed.funding_rows["AAA_USDT"] = [{"t": when, "r": "0.0001"}]
    feed.funding_rows["BBB_USDT"] = [{"t": when, "r": "0.0001"}]
    feed.marks["AAA_USDT"] = 99.5  # between grid levels, no fill
    feed.marks["BBB_USDT"] = 50.5
    cash_before = engine.account.cash

    engine.tick()
    payment_aaa = 10 * 99.5 * 0.0001  # long pays
    payment_bbb = -20 * 50.5 * 0.0001  # short receives
    assert engine.account.funding == pytest.approx(payment_aaa + payment_bbb)
    assert engine.account.cash == pytest.approx(cash_before - payment_aaa - payment_bbb)
    snapshot = engine.snapshot()
    assert {row["symbol"] for row in snapshot["funding"]} == {"AAA_USDT", "BBB_USDT"}
    assert aaa.funding_next == when + 28_800
    assert bbb.funding_next == when + 28_800


def test_portfolio_stop_flattens_all_and_persists(tmp_path: Path) -> None:
    engine, feed = make_engine(
        tmp_path,
        capital=1_000.0,
        leverage=1.0,
        levels=10,
        stop_dd_pct=1.0,
    )
    feed.marks["AAA_USDT"] = 99.0
    feed.marks["BBB_USDT"] = 49.5
    engine.tick()
    assert engine.state["AAA_USDT"].position > 0
    assert engine.state["BBB_USDT"].position > 0

    feed.marks["AAA_USDT"] = 80.0
    feed.marks["BBB_USDT"] = 40.0
    engine.tick()
    assert engine.status == "halted"
    assert all(abs(state.position) <= 1e-9 for state in engine.state.values())
    assert "止损" in (engine.last_error or "")
    stop_fills = [row for row in engine.snapshot()["fills"] if row["reason"] == "stop"]
    assert len(stop_fills) == 2

    reloaded = PaperEngine(engine.config, tmp_path, feed=feed)
    assert reloaded.status == "halted"
    assert all(abs(state.position) <= 1e-9 for state in reloaded.state.values())
    assert reloaded.account.cash == pytest.approx(engine.account.cash)


def test_exchange_fee_rates_are_used_when_available(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path, exchange_fees=True)
    fee_state = engine.state["AAA_USDT"]
    assert fee_state.maker_fee == pytest.approx(-0.0001)
    assert fee_state.taker_fee == pytest.approx(0.0006)

    feed.marks["AAA_USDT"] = 99.0
    engine.tick()
    rebate = 10 * 99 * -0.0001
    assert engine.account.fees == pytest.approx(rebate)  # negative fee = rebate
    assert engine.account.cash == pytest.approx(10_000 - rebate)

    row = next(item for item in engine.snapshot()["portfolio"] if item["symbol"] == "AAA_USDT")
    assert row["maker_fee_bp"] == pytest.approx(-1.0)
    assert row["taker_fee_bp"] == pytest.approx(6.0)
    assert row["fee_source"] == "exchange"


def test_reset_reanchors_all_symbols(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    feed.marks["AAA_USDT"] = 99.0
    engine.tick()
    assert engine.state["AAA_USDT"].position != 0

    feed.marks["AAA_USDT"] = 120.0
    feed.marks["BBB_USDT"] = 60.0
    state = engine.reset()
    assert state["account"]["cash"] == pytest.approx(10_000.0)
    assert state["account"]["equity"] == pytest.approx(10_000.0)
    assert state["fills"] == []
    anchors = {row["symbol"]: row["anchor"] for row in state["portfolio"]}
    assert anchors["AAA_USDT"] == pytest.approx(120.0)
    assert anchors["BBB_USDT"] == pytest.approx(60.0)
