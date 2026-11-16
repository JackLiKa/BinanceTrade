from __future__ import annotations

import pytest

from gridtrade.domain.models import Position, Side, SymbolFilters
from gridtrade.execution.oms import client_order_id


def test_align_price_rounds_toward_the_safe_side():
    f = SymbolFilters(tick_size=0.01, step_size=0.01, min_notional=5.0)
    # Buys round down, sells round up: a rounding error must never cross the book.
    assert f.align_price(100.004) == pytest.approx(100.00)
    assert f.align_price(100.004, up=True) == pytest.approx(100.01)
    assert f.align_price(100.006, up=True) == pytest.approx(100.01)


def test_align_qty_never_rounds_up():
    f = SymbolFilters(tick_size=0.01, step_size=0.1, min_notional=5.0)
    assert f.align_qty(1.29) == pytest.approx(1.2)
    assert f.align_qty(1.20) == pytest.approx(1.2)
    assert f.align_qty(0.09) == 0.0


def test_notional_check():
    f = SymbolFilters(tick_size=0.01, step_size=0.01, min_notional=5.0)
    assert f.notional_ok(0.05, 100.0)
    assert not f.notional_ok(0.04, 100.0)
    assert not f.notional_ok(0.0, 100.0)


def test_client_order_id_is_stable_short_and_collision_resistant():
    a = client_order_id("GOOGLUSDT", "grid:GOOGLUSDT", "lvl+1", 0)
    b = client_order_id("GOOGLUSDT", "grid:GOOGLUSDT", "lvl+1", 0)
    c = client_order_id("GOOGLUSDT", "grid:GOOGLUSDT", "lvl+1", 1)
    assert a == b
    assert a != c
    assert len(a) <= 36
    assert a.startswith("gt-")


def test_position_average_and_flip():
    p = Position(symbol="X")
    p.apply(Side.BUY, 1.0, 100.0)
    p.apply(Side.BUY, 1.0, 110.0)
    assert p.qty == pytest.approx(2.0)
    assert p.entry_price == pytest.approx(105.0)

    p.apply(Side.SELL, 3.0, 120.0)
    assert p.qty == pytest.approx(-1.0)
    assert p.entry_price == pytest.approx(120.0)

    p.apply(Side.BUY, 1.0, 90.0)
    assert p.is_flat
    assert p.entry_price == 0.0
