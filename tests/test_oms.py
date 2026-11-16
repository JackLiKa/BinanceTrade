from __future__ import annotations

import pytest

from gridtrade.domain.models import (
    BrokerOrder,
    BrokerSnapshot,
    OrderIntent,
    OrderStatus,
    Side,
    TimeInForce,
)
from gridtrade.execution.oms import OMS, SyncReport
from gridtrade.execution.simulated import SimExecution, SimFees
from gridtrade.risk.limits import RiskEngine, RiskLimits
from gridtrade.strategy.base import StrategyContext

from conftest import FILTERS, T0, make_bar

SYMBOL = "TESTUSDT"


def build() -> tuple[OMS, SimExecution]:
    port = SimExecution(SYMBOL, FILTERS, SimFees(), 10_000.0)
    port.begin_bar(make_bar(100.0, 100.0, 100.0, 100.0))
    limits = RiskLimits(
        max_position_qty=10_000.0,
        max_order_notional=5_000.0,
        max_gross_notional=100_000.0,
        max_open_orders=50,
        max_submits_per_minute=1_000,
        max_price_deviation_bp=1_000.0,
    )
    return OMS(port, RiskEngine(limits), FILTERS, SYMBOL), port


def ctx(oms: OMS, *, mark: float = 100.0, pos: float = 0.0) -> StrategyContext:
    return StrategyContext(
        symbol=SYMBOL,
        now=T0,
        mark_price=mark,
        position_qty=pos,
        equity=10_000.0,
        filters=FILTERS,
        open_orders=oms.open_orders(),
    )


def intent(side: Side, price: float | None, *, qty: float = 1.0, tag: str = "x", **kw) -> OrderIntent:
    return OrderIntent(side=side, qty=qty, price=price, tag=tag, group="g", **kw)


def pair(sell: float = 101.0, buy: float = 99.0, qty: float = 1.0) -> list[OrderIntent]:
    return [
        intent(Side.SELL, sell, qty=qty, tag="up", tif=TimeInForce.POST_ONLY),
        intent(Side.BUY, buy, qty=qty, tag="down", tif=TimeInForce.POST_ONLY),
    ]


def test_sync_places_declared_pair():
    oms, port = build()
    report = oms.sync("g", pair(), ctx(oms))

    assert isinstance(report, SyncReport)
    assert len(report.submitted) == 2
    assert report.rejected == []
    assert {o.tag for o in oms.open_orders("g")} == {"up", "down"}
    assert len(port.open_orders) == 2


def test_sync_is_idempotent():
    oms, port = build()
    oms.sync("g", pair(), ctx(oms))
    ids = {o.client_id for o in oms.open_orders("g")}

    report = oms.sync("g", pair(), ctx(oms))

    assert report.submitted == []
    assert report.kept == 2
    assert {o.client_id for o in oms.open_orders("g")} == ids
    assert len(port.open_orders) == 2


def test_price_change_cancels_and_replaces():
    oms, _ = build()
    oms.sync("g", pair(101.0, 99.0), ctx(oms))
    old = {o.client_id for o in oms.open_orders("g")}

    report = oms.sync("g", pair(102.0, 98.0), ctx(oms))

    assert len(report.canceled) == 2
    assert len(report.submitted) == 2
    new = {o.client_id for o in oms.open_orders("g")}
    assert new.isdisjoint(old)
    assert {o.price for o in oms.open_orders("g")} == {102.0, 98.0}


def test_empty_declaration_cancels_everything():
    oms, _ = build()
    oms.sync("g", pair(), ctx(oms))

    report = oms.sync("g", [], ctx(oms))

    assert len(report.canceled) == 2
    assert oms.open_orders("g") == ()


def test_duplicate_tag_is_rejected_without_placing():
    oms, _ = build()
    intents = [
        intent(Side.SELL, 101.0, tag="same", tif=TimeInForce.POST_ONLY),
        intent(Side.BUY, 99.0, tag="same", tif=TimeInForce.POST_ONLY),
    ]

    report = oms.sync("g", intents, ctx(oms))

    assert [r.code for r in report.rejected] == ["duplicate_tag"]
    assert len(report.submitted) == 1


def test_untagged_resting_intent_is_rejected():
    oms, _ = build()
    report = oms.sync(
        "g", [intent(Side.SELL, 101.0, tag="", tif=TimeInForce.POST_ONLY)], ctx(oms)
    )
    assert [r.code for r in report.rejected] == ["missing_tag"]


def test_min_notional_and_post_only_rejections():
    oms, port = build()
    tiny = [intent(Side.SELL, 100.01, qty=0.01, tag="a", tif=TimeInForce.POST_ONLY)]
    crossing = [intent(Side.SELL, 99.99, tag="b", tif=TimeInForce.POST_ONLY)]

    assert [r.code for r in oms.sync("g", tiny, ctx(oms)).rejected] == ["min_notional"]
    report = oms.sync("g", crossing, ctx(oms))
    assert [r.code for r in report.rejected] == ["exchange_reject"]
    assert port.open_orders == ()


def test_risk_rejects_oversized_order():
    oms, port = build()
    huge = [intent(Side.BUY, 100.0, qty=10_000.0, tag="h", tif=TimeInForce.POST_ONLY)]

    report = oms.sync("g", huge, ctx(oms))

    assert [r.code for r in report.rejected] == ["max_order_notional"]
    assert port.open_orders == ()


def test_generation_changes_client_id_after_a_fill():
    oms, port = build()
    oms.sync("g", [intent(Side.SELL, 101.0, tag="up", tif=TimeInForce.POST_ONLY)], ctx(oms))
    first = oms.open_orders("g")[0].client_id

    port.end_bar()
    port.begin_bar(make_bar(100.0, 106.0, 99.0, 105.0))
    port.match()
    oms.sync("g", [], ctx(oms))
    assert oms.order(first).status is OrderStatus.FILLED

    oms.sync(
        "g",
        [intent(Side.SELL, 104.0, tag="up", tif=TimeInForce.POST_ONLY)],
        ctx(oms, mark=105.0),
    )
    current = oms.open_orders("g")[0].client_id
    assert current != first

    port.end_bar()
    port.begin_bar(make_bar(101.0, 105.0, 100.5, 104.8))
    port.match()
    report = oms.reconcile(port.snapshot())
    assert report.ok
    assert oms.order(current).status is OrderStatus.FILLED


def test_reconcile_flags_missing_and_unknown():
    oms, _ = build()
    oms.sync("g", pair(), ctx(oms))
    local_ids = {o.client_id for o in oms.open_orders("g")}

    report = oms.reconcile(BrokerSnapshot(orders=(), position_qty=0.0))

    assert set(report.missing_at_broker) == local_ids
    assert all(oms.order(cid).status is OrderStatus.UNKNOWN for cid in local_ids)

    ghost = BrokerSnapshot(
        orders=(
            BrokerOrder(
                client_id="gt-not-ours",
                status=OrderStatus.NEW,
                filled_qty=0.0,
                avg_price=0.0,
            ),
        ),
        position_qty=0.0,
    )
    report = oms.reconcile(ghost)
    assert report.unknown_at_broker == ["gt-not-ours"]
    assert not report.ok


def test_reconcile_reports_position_mismatch():
    oms, _ = build()
    report = oms.reconcile(BrokerSnapshot(orders=(), position_qty=5.0))
    assert report.position_mismatch == (0.0, 5.0)


def test_flatten_sends_a_reduce_only_market_order():
    oms, port = build()
    port.position = 2.0

    report = oms.flatten("g", ctx(oms, pos=2.0))

    assert len(report.submitted) == 1
    order = report.submitted[0]
    assert order.reduce_only
    assert order.price is None
    assert order.qty == pytest.approx(2.0)
    assert order.side is Side.SELL


def test_flatten_is_a_noop_when_flat():
    oms, _ = build()
    assert oms.flatten("g", ctx(oms, pos=0.0)).submitted == []
