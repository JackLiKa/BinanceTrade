from __future__ import annotations

import pytest

from gridtrade.domain.models import Order, OrderStatus, OrderType, Side, TimeInForce
from gridtrade.execution.simulated import SimExecution, SimFees

from conftest import FILTERS, make_bar


def mk_order(
    cid: str,
    side: Side,
    price: float | None,
    qty: float = 1.0,
    *,
    type: OrderType = OrderType.LIMIT,
    tif: TimeInForce = TimeInForce.POST_ONLY,
    reduce_only: bool = False,
    tag: str = "t",
    group: str = "g",
) -> Order:
    return Order(
        client_id=cid,
        symbol="TESTUSDT",
        side=side,
        type=type,
        qty=qty,
        price=price,
        tif=tif,
        reduce_only=reduce_only,
        tag=tag,
        group=group,
    )


def port(**kwargs) -> SimExecution:
    return SimExecution("TESTUSDT", FILTERS, SimFees(), 10_000.0, **kwargs)


def test_up_bar_fills_only_sells():
    p = port()
    p.begin_bar(make_bar(100.0, 106.0, 99.0, 105.0))
    assert p.submit(mk_order("s", Side.SELL, 101.0)).ok
    assert p.submit(mk_order("b", Side.BUY, 99.5)).ok

    fills = p.match()

    assert [f.side for f in fills] == [Side.SELL]
    assert p.position == pytest.approx(-1.0)
    # The bar traded down to 99 but the conservative rule forbids the buy:
    # an up bar's only trustworthy extreme is the high.
    assert "b" in {o.client_id for o in p.open_orders}


def test_down_bar_fills_only_buys():
    p = port()
    p.begin_bar(make_bar(100.0, 100.5, 95.0, 96.0))
    p.submit(mk_order("s", Side.SELL, 101.0))
    p.submit(mk_order("b", Side.BUY, 96.0))

    fills = p.match()

    assert [f.side for f in fills] == [Side.BUY]
    assert p.position == pytest.approx(1.0)


def test_intrabar_processes_both_extremes_and_reports_optimistic_round_trip():
    p = port(intrabar=True)
    p.begin_bar(make_bar(100.0, 106.0, 95.0, 105.0))
    p.submit(mk_order("b", Side.BUY, 95.0))
    p.submit(mk_order("s", Side.SELL, 101.0))

    fills = p.match()

    assert [f.side for f in fills] == [Side.BUY, Side.SELL]
    assert p.position == pytest.approx(0.0)
    assert p.cash > 10_000.0


def test_post_only_crossing_is_rejected():
    p = port()
    p.begin_bar(make_bar(100.0, 101.0, 99.0, 100.0))

    assert not p.submit(mk_order("s", Side.SELL, 99.99)).ok
    assert not p.submit(mk_order("b", Side.BUY, 100.01)).ok
    assert p.submit(mk_order("b", Side.BUY, 99.99)).ok


def test_market_order_fills_at_next_bar_open_as_taker():
    p = port()
    p.begin_bar(make_bar(100.0, 101.0, 99.0, 100.0))
    p.submit(mk_order("m", Side.BUY, None, type=OrderType.MARKET, tif=TimeInForce.IOC))

    p.end_bar()
    p.begin_bar(make_bar(102.0, 103.0, 101.0, 102.0))
    fills = p.match()

    assert len(fills) == 1
    assert fills[0].price == pytest.approx(102.0)
    assert fills[0].liquidity == "TAKER"
    assert p.position == pytest.approx(1.0)


def test_reduce_only_semantics():
    p = port()
    p.begin_bar(make_bar(100.0, 100.2, 98.5, 99.0))
    p.submit(mk_order("b", Side.BUY, 98.8))
    p.match()
    assert p.position == pytest.approx(1.0)

    assert not p.submit(mk_order("b2", Side.BUY, 98.0, reduce_only=True)).ok
    assert not p.submit(mk_order("s2", Side.SELL, 102.0, qty=2.0, reduce_only=True)).ok
    assert p.submit(mk_order("s1", Side.SELL, 102.0, reduce_only=True)).ok
    p.cancel("s1")

    p.end_bar()
    p.begin_bar(make_bar(99.0, 106.0, 98.9, 105.0))
    p.submit(mk_order("x", Side.SELL, 105.0, qty=2.0))
    p.match()
    assert p.position == pytest.approx(-1.0)

    # The halt path: a market buy must reduce a short, not be rejected.
    p.submit(
        mk_order(
            "flat",
            Side.BUY,
            None,
            qty=1.0,
            type=OrderType.MARKET,
            tif=TimeInForce.IOC,
            reduce_only=True,
        )
    )
    p.end_bar()
    p.begin_bar(make_bar(105.0, 106.0, 104.0, 105.0))
    p.match()
    assert p.position == pytest.approx(0.0)


def test_funding_sign_follows_binance_convention():
    long = port()
    long.begin_bar(make_bar(101.0, 101.0, 100.0, 100.5))
    long.submit(mk_order("b", Side.BUY, 100.0, tif=TimeInForce.GTC))
    long.match()
    assert long.position == pytest.approx(1.0)

    before = long.cash
    cost = long.settle_funding(0.001, 100.0)  # positive rate: longs pay
    assert cost == pytest.approx(0.1)
    assert long.funding_paid == pytest.approx(0.1)
    assert long.cash == pytest.approx(before - 0.1)

    short = port()
    short.begin_bar(make_bar(99.5, 100.0, 99.5, 100.0))
    short.submit(mk_order("s", Side.SELL, 100.0, tif=TimeInForce.GTC))
    short.match()
    assert short.position == pytest.approx(-1.0)

    before = short.cash
    short.settle_funding(0.001, 100.0)  # positive rate: shorts receive
    assert short.funding_paid == pytest.approx(-0.1)
    assert short.cash == pytest.approx(before + 0.1)


def test_fill_is_emitted_to_the_sink_and_fee_is_charged():
    p = port()
    seen = []
    p.set_event_sink(seen.append)
    p.begin_bar(make_bar(100.0, 101.0, 99.0, 100.5))
    p.submit(mk_order("s", Side.SELL, 100.5))
    p.match()

    assert len(seen) == 1
    assert seen[0].fee == pytest.approx(100.5 * SimFees().maker_all_in)
    assert seen[0].client_id == "s"


def test_cancel_is_idempotent_and_removes_from_open_orders():
    p = port()
    p.begin_bar(make_bar(100.0, 101.0, 99.0, 100.0))
    p.submit(mk_order("s", Side.SELL, 101.0))
    assert p.cancel("s")
    assert not p.cancel("s")
    assert p.open_orders == ()
    assert p.match() == []


def test_snapshot_reports_terminal_and_position_state():
    p = port()
    p.begin_bar(make_bar(100.0, 101.0, 99.0, 100.0))
    p.submit(mk_order("s", Side.SELL, 101.0))
    p.match()

    snap = p.snapshot()
    assert snap.position_qty == pytest.approx(-1.0)
    assert snap.orders[0].status is OrderStatus.FILLED
