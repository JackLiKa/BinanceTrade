from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from gridtrade.domain.models import OrderStatus, Side
from gridtrade.risk.limits import DrawdownGuard, RiskEngine, RiskLimits

from conftest import T0

MARK = 100.0


def limits(**overrides) -> RiskLimits:
    base = dict(
        max_position_qty=100.0,
        max_order_notional=50_000.0,
        max_gross_notional=20_000.0,
        max_open_orders=2,
        max_submits_per_minute=2,
        max_price_deviation_bp=50.0,
    )
    base.update(overrides)
    return RiskLimits(**base)


def check(engine: RiskEngine, **kwargs):
    args = dict(
        side=Side.BUY,
        qty=1.0,
        price=100.0,
        reduce_only=False,
        position_qty=0.0,
        mark_price=MARK,
        open_orders=(),
        now=T0,
    )
    args.update(kwargs)
    return engine.check(**args)


def open_order(remaining: float = 100.0, price: float = 100.0):
    return SimpleNamespace(remaining=remaining, price=price, status=OrderStatus.NEW)


def test_limits_require_positive_sizes():
    with pytest.raises(ValueError):
        limits(max_position_qty=0.0)


def test_position_cap():
    engine = RiskEngine(limits())
    assert check(engine, qty=100.0) is None
    rejection = check(engine, qty=101.0)
    assert rejection is not None and rejection.code == "max_position"


def test_reduce_only_is_never_blocked_by_caps_or_rate():
    engine = RiskEngine(limits())
    assert check(engine, side=Side.SELL, qty=50.0, reduce_only=True, position_qty=100.0) is None


def test_reduce_only_cannot_flip_or_open_the_position():
    engine = RiskEngine(limits())
    flip = check(engine, side=Side.SELL, qty=2.0, reduce_only=True, position_qty=1.0)
    assert flip is not None and flip.code == "reduce_only_flip"

    flat = check(engine, side=Side.SELL, qty=1.0, reduce_only=True, position_qty=0.0)
    assert flat is not None and flat.code == "reduce_only_flat"


def test_price_deviation():
    engine = RiskEngine(limits())
    assert check(engine, price=100.5) is None
    rejection = check(engine, price=101.0)
    assert rejection is not None and rejection.code == "price_deviation"


def test_order_notional_cap():
    engine = RiskEngine(limits(max_order_notional=1_000.0))
    rejection = check(engine, qty=11.0)
    assert rejection is not None and rejection.code == "max_order_notional"


def test_gross_notional_cap():
    engine = RiskEngine(limits(max_gross_notional=15_000.0))
    rejection = check(engine, qty=60.0, open_orders=(open_order(),))
    assert rejection is not None and rejection.code == "max_gross_notional"


def test_open_order_count_cap():
    engine = RiskEngine(limits())
    orders = (open_order(1.0), open_order(1.0))
    rejection = check(engine, open_orders=orders)
    assert rejection is not None and rejection.code == "max_open_orders"


def test_submit_rate_limit_uses_a_rolling_minute():
    engine = RiskEngine(limits())
    engine.record_submit(T0)
    engine.record_submit(T0 + timedelta(seconds=10))
    rejection = check(engine, now=T0 + timedelta(seconds=20))
    assert rejection is not None and rejection.code == "order_rate"
    assert check(engine, now=T0 + timedelta(seconds=61)) is None


def test_drawdown_guard_latches():
    guard = DrawdownGuard(0.10)
    assert not guard.update(10_000.0)
    assert not guard.update(9_001.0)
    assert guard.drawdown == pytest.approx(0.0999, rel=1e-3)

    assert guard.update(8_999.0)
    assert guard.drawdown > 0.10
    # Once halted it stays halted even after a recovery.
    assert guard.update(12_000.0)
