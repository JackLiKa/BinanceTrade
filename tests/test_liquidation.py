"""Binance-style maintenance margin and forced-liquidation tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gridtrade.domain.models import Bar, SymbolFilters
from gridtrade.execution.simulated import SimExecution, SimFees
from gridtrade.research.metrics import compute_stats
from gridtrade.risk.liquidation import (
    DEFAULT_MAINTENANCE_TIERS,
    cross_liquidation_price,
    liquidation_price,
    maintenance_margin,
    tiers_from_brackets,
)
import pandas as pd

FILTERS = SymbolFilters(tick_size=0.01, step_size=0.01, min_notional=5.0)


def bar(open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        "TESTUSDT",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        open_,
        high,
        low,
        close,
        1.0,
    )


def test_maintenance_margin_tiers_are_positive_and_capped_by_equity_formula() -> None:
    assert maintenance_margin(1_000.0) == pytest.approx(10.0)
    assert maintenance_margin(0.0) == 0.0
    # Tier 2 uses the cumulative Binance maintenance amount.
    assert maintenance_margin(100_000.0) == pytest.approx(1_500.0)
    assert liquidation_price(1, 1.0, 100.0, 10.0) == pytest.approx(90.9090909091, rel=1e-8)
    assert liquidation_price(-1, 1.0, 100.0, 10.0) == pytest.approx(108.9108910891, rel=1e-8)


def test_long_position_is_force_closed_and_cannot_keep_trading() -> None:
    port = SimExecution("TESTUSDT", FILTERS, SimFees(maker=0.0, taker=0.0, slip_bp=0.0), 10.0)
    port.position = 1.0
    port.entry_price = 100.0
    port.cash = -90.0  # wallet balance = 10, exactly 10x leverage
    port._mark = 100.0
    lp = port.liquidation_price
    assert lp is not None and 0 < lp < 100

    event = port.check_liquidation(bar(100.0, 101.0, lp - 1.0, 95.0))

    assert event is not None
    assert event.reason == "maintenance_margin"
    assert port.liquidated is True
    assert port.position == 0.0
    assert port.cash >= 0.0
    assert port.liquidation is event
    assert port.maintenance_margin == 0.0


def test_gap_through_liquidation_uses_worse_open_and_floors_equity() -> None:
    port = SimExecution("TESTUSDT", FILTERS, SimFees(maker=0.0, taker=0.0, slip_bp=0.0), 10.0)
    port.position = 1.0
    port.entry_price = 100.0
    port.cash = -90.0
    port._mark = 100.0

    event = port.check_liquidation(bar(80.0, 82.0, 79.0, 81.0))

    assert event is not None
    assert event.reason == "gap_through_liquidation"
    assert event.fill_price == 80.0
    assert event.bad_debt > 0
    assert port.cash < 0.0


def test_short_position_liquidates_on_up_gap() -> None:
    port = SimExecution("TESTUSDT", FILTERS, SimFees(maker=0.0, taker=0.0, slip_bp=0.0), 10.0)
    port.position = -1.0
    port.entry_price = 100.0
    port.cash = 110.0  # wallet = 10 after selling one unit
    port._mark = 100.0
    lp = port.liquidation_price
    assert lp is not None and lp > 100

    event = port.check_liquidation(bar(100.0, lp + 1.0, 99.0, 105.0))

    assert event is not None
    assert event.side == "SHORT"
    assert port.liquidated is True
    assert port.position == 0.0
    assert port.cash >= 0.0


def test_metrics_reports_negative_equity_drawdown_as_bad_debt() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC")
    equity = pd.Series([100.0, 20.0, -10.0, 5.0], index=index)
    stats = compute_stats(
        equity,
        capital=100.0,
        trades=1,
        fees_paid=0.0,
        funding_paid=0.0,
        turnover=0.0,
        inv_notional_sum=0.0,
        bars=4,
        halted=True,
        liquidated=True,
        liquidation_price=12.0,
        liquidation_time="2026-01-03T00:00:00+00:00",
        bad_debt=10.0,
    )
    assert stats["max_dd"] > 100.0  # negative cross-margin equity is bad debt
    assert stats["bad_debt"] > 0.0
    assert stats["liquidated"] is True
    assert stats["liquidation_price"] == 12.0


def test_paper_engine_force_liquidates_shared_margin(tmp_path) -> None:
    import time

    from test_paper import make_engine

    engine, _feed = make_engine(
        tmp_path,
        capital=100.0,
        leverage=10.0,
        levels=10,
        spacing_bp=100.0,
        stop_dd_pct=0.0,
        symbols=["AAA_USDT"],
    )
    state = engine.state["AAA_USDT"]
    state.position = 10.0
    state.avg_entry = 100.0
    state.mark = 80.0
    engine.account.cash = -900.0  # wallet = 100, equity = -100 at mark 80
    engine._mark_equity()
    engine._update_margin()
    engine._check_liquidation(time.time())

    assert engine.status == "halted"
    assert state.position == 0.0
    assert engine.liquidation is not None
    assert engine.liquidation["maintenance_margin"] > 0
    snap = engine.snapshot()
    assert snap["liquidation"] is not None
    assert snap["account"]["maintenance_margin"] == 0.0


def test_binance_leverage_bracket_maps_to_tiers() -> None:
    rows = [
        {"bracket": 1, "notional_cap": 50_000, "mmr": 0.01, "cum": 0.0},
        {"bracket": 2, "notional_cap": 200_000, "mmr": 0.02, "cum": 500.0},
    ]
    tiers = tiers_from_brackets(rows)
    assert tiers[0].notional_cap == 50_000
    assert tiers[0].mmr == 0.01
    assert tiers[0].maintenance_amount == 0.0
    assert tiers[1].mmr == 0.02
    assert tiers[1].maintenance_amount == 500.0
    assert tiers[-1].notional_cap < float("inf")  # JSON-safe


def test_binance_cross_margin_formula_example() -> None:
    # Binance-style cross-margin example: BTCUSDT long 20 @ 100,000,
    # wallet 50,000, other maintenance 2,232.5, other UPNL -2,500,
    # cum 1,975, MMR 0.67% -> LP 98,296.46.
    price = cross_liquidation_price(
        1, 20.0, 100_000.0, 50_000.0, 2_232.5, -2_500.0, 1_975.0, 0.0067
    )
    assert price == pytest.approx(98_296.46, rel=1e-6)
