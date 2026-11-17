from __future__ import annotations

import pytest

from gridtrade.domain.models import Fill, OrderType, Side, TimeInForce
from gridtrade.strategy.base import StrategyContext
from gridtrade.strategy.grid import GridParams, GridStrategy

from conftest import FILTERS, T0, make_bar

SYMBOL = "TESTUSDT"


def ctx(*, mark: float = 100.0, pos: float = 0.0, equity: float = 10_000.0) -> StrategyContext:
    return StrategyContext(
        symbol=SYMBOL,
        now=T0,
        mark_price=mark,
        position_qty=pos,
        equity=equity,
        filters=FILTERS,
    )


def strategy(spacing: float = 120.0, levels: int = 30, reanchor_bars: int | None = None) -> GridStrategy:
    return GridStrategy(
        SYMBOL, GridParams(spacing_bp=spacing, levels=levels, leverage=1.0, reanchor_bars=reanchor_bars)
    )


def test_on_start_rests_one_order_each_side_of_the_anchor():
    s = strategy()
    intents = s.on_start(ctx(mark=100.0))

    by_side = {i.side: i for i in intents}
    assert set(by_side) == {Side.BUY, Side.SELL}
    assert by_side[Side.SELL].price == pytest.approx(101.2)
    assert by_side[Side.BUY].price == pytest.approx(98.8)
    assert by_side[Side.SELL].qty == pytest.approx(3.33)
    assert by_side[Side.SELL].tif is TimeInForce.POST_ONLY
    assert by_side[Side.SELL].tag == "lvl+1"
    assert by_side[Side.BUY].tag == "lvl-1"


def test_size_respects_filters_and_never_rounds_up():
    s = strategy(levels=7)
    s.on_start(ctx(mark=100.0))
    # 10000 / 7 / 100 = 14.2857 -> aligned down to 14.28
    assert s.size == pytest.approx(14.28)


def test_a_buy_fill_shifts_the_adjacent_pair_one_level_down():
    s = strategy()
    s.on_start(ctx(mark=100.0))
    fill = Fill(
        client_id="c",
        symbol=SYMBOL,
        side=Side.BUY,
        qty=s.size,
        price=98.8,
        fee=0.0,
        ts=T0,
        tag="lvl-1",
    )

    intents = s.on_fill(fill, ctx(mark=98.8, pos=s.size))

    by_side = {i.side: i for i in intents}
    assert s.level == -1
    assert by_side[Side.SELL].price == pytest.approx(100.0)
    assert by_side[Side.BUY].price == pytest.approx(97.6)


def test_ladder_is_clamped_at_the_extremes():
    s = strategy(levels=30)
    s.on_start(ctx(mark=100.0))

    s.level = 30
    assert {i.side for i in s.on_bar(make_bar(100, 100, 100, 100), ctx(pos=-30 * s.size))} == {Side.BUY}

    s.level = -30
    assert {i.side for i in s.on_bar(make_bar(100, 100, 100, 100), ctx(pos=30 * s.size))} == {Side.SELL}


def test_reanchor_moves_the_grid_when_flat():
    s = strategy(reanchor_bars=1)
    s.on_start(ctx(mark=100.0))

    intents = s.on_bar(make_bar(110, 111, 109, 110, i=1), ctx(mark=110.0, pos=0.0))

    assert s.anchor == pytest.approx(110.0)
    assert sorted(i.price for i in intents) == pytest.approx([108.68, 111.32])


def test_reanchor_flattens_first_then_rebuilds():
    s = strategy(reanchor_bars=1)
    s.on_start(ctx(mark=100.0))

    flatten = s.on_bar(make_bar(110, 111, 109, 110, i=1), ctx(mark=110.0, pos=10.0))
    assert len(flatten) == 1
    assert flatten[0].type is OrderType.MARKET
    assert flatten[0].reduce_only
    assert flatten[0].side is Side.SELL
    assert s.state()["reanchor_pending"]

    rebuilt = s.on_bar(make_bar(110, 111, 109, 110, i=2), ctx(mark=110.0, pos=0.0))
    assert not s.state()["reanchor_pending"]
    assert s.anchor == pytest.approx(110.0)
    assert len(rebuilt) == 2


def test_on_stop_flattens_only_when_carrying_inventory():
    s = strategy()
    s.on_start(ctx(mark=100.0))

    assert s.on_stop(ctx(pos=0.0)) == []

    intents = s.on_stop(ctx(pos=-5.0))
    assert len(intents) == 1
    assert intents[0].side is Side.BUY
    assert intents[0].qty == pytest.approx(5.0)
    assert intents[0].type is OrderType.MARKET


def test_state_is_serializable():
    s = strategy()
    s.on_start(ctx(mark=100.0))
    state = s.state()
    assert state["anchor"] == pytest.approx(100.0)
    assert state["level"] == 0
    assert state["grid_inventory"] == 0.0
    assert isinstance(state, dict)


def test_min_edge_guard_rejects_spacing_below_round_trip_cost():
    # Default CostModel: 2bp maker on both legs -> 4bp round trip.
    s = GridStrategy(
        SYMBOL,
        GridParams(spacing_bp=5.0, levels=30, leverage=1.0, min_edge_bp=2.0),
    )
    with pytest.raises(ValueError, match=r"spacing 5bp <= round-trip 4bp"):
        s.on_start(ctx(mark=100.0))


def test_min_edge_guard_passes_and_cost_report_is_exposed():
    s = GridStrategy(
        SYMBOL,
        GridParams(spacing_bp=10.0, levels=30, leverage=1.0, min_edge_bp=2.0),
    )
    intents = s.on_start(ctx(mark=100.0))
    assert len(intents) == 2

    report = s.cost_report()
    assert report["spacing_bp"] == pytest.approx(10.0)
    assert report["round_trip_bp"] == pytest.approx(4.0)
    assert report["breakeven_spacing_bp"] == pytest.approx(4.0)
    assert report["net_edge_bp"] == pytest.approx(6.0)
    assert report["is_profitable"] is True
    assert report["min_edge_bp"] == pytest.approx(2.0)

    description = s.describe()
    assert description["symbol"] == SYMBOL
    assert description["cost"]["spacing_bp"] == pytest.approx(10.0)
    assert description["cost"]["is_profitable"] is True


def test_default_min_edge_keeps_legacy_behaviour():
    # min_edge_bp defaults to 0: even a 1bp spacing starts without validation.
    s = GridStrategy(SYMBOL, GridParams(spacing_bp=1.0, levels=30, leverage=1.0))
    assert len(s.on_start(ctx(mark=100.0))) == 2
    assert s.cost_report()["is_profitable"] is False
