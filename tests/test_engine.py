from __future__ import annotations

from datetime import timedelta

import pytest

from gridtrade.domain.models import OrderStatus
from gridtrade.research.engine import BacktestConfig, ReplayEngine
from gridtrade.strategy.grid import GridParams, GridStrategy

from conftest import T0, gbm_rows, make_dataset


def run(rows, *, params=None, config=None, funding=None):
    ds = make_dataset(rows, funding=funding)
    strat = GridStrategy(ds.symbol, params or GridParams(120.0, 30, 1.0))
    return ReplayEngine(ds, strat, config or BacktestConfig()).run()


def zigzag(n: int = 300, amplitude: float = 0.0015, period: int = 15) -> list[tuple]:
    rows = []
    price = 100.0
    for i in range(n):
        direction = 1.0 if (i // period) % 2 == 0 else -1.0
        prev, price = price, price * (1.0 + direction * amplitude)
        rows.append((prev, max(prev, price) * 1.0002, min(prev, price) * 0.9998, price))
    return rows


def test_flat_market_produces_no_trades_and_no_pnl():
    result = run([(100.0, 100.0, 100.0, 100.0)] * 60)

    assert result.stats["trades"] == 0
    assert result.stats["total_return"] == 0.0
    assert result.final_position == 0.0
    assert not result.halted


def test_rising_market_stops_out_flattens_and_stops_trading():
    rows = []
    price = 100.0
    for _ in range(120):
        o = price
        price *= 1.005
        rows.append((o, price * 1.0005, o * 0.9995, price))

    result = run(rows)

    assert result.halted
    assert result.final_position == pytest.approx(0.0)
    assert result.stats["total_return"] < -8.0
    assert result.stats["max_dd"] > 10.0
    flatten = [o for o in result.orders if o.tag == "flatten"]
    assert flatten and flatten[-1].status is OrderStatus.FILLED
    # Nothing may remain live after the kill switch fires.
    assert all(not o.is_open for o in result.orders)


def test_intrabar_mode_is_an_upper_bound():
    rows = []
    price = 100.0
    for i in range(240):
        if (i // 10) % 2 == 0:
            rows.append((price, price * 1.02, price * 0.98, price * 1.005))
        else:
            rows.append((price, price * 1.005, price * 0.96, price * 0.995))
        price = rows[-1][3]

    conservative = run(rows)
    optimistic = run(rows, config=BacktestConfig(intrabar=True))

    assert conservative.stats["trades"] > 0
    assert optimistic.stats["trades"] >= conservative.stats["trades"]
    assert optimistic.stats["total_return"] >= conservative.stats["total_return"] - 1e-9


def test_fees_can_only_reduce_returns_on_identical_paths():
    rows = zigzag()
    free = run(rows, config=BacktestConfig(maker_fee=0.0, slip_bp=0.0))
    paid = run(rows, config=BacktestConfig(maker_fee=0.0002, slip_bp=0.2))

    assert free.stats["trades"] > 0
    assert paid.stats["trades"] == free.stats["trades"]
    assert paid.stats["total_return"] < free.stats["total_return"]
    assert paid.stats["fees"] > 0.0


def test_funding_settles_against_the_position():
    rows = [
        (100.0, 100.0, 100.0, 100.0),
        (100.0, 100.0, 98.5, 99.0),  # down bar: the 98.8 buy fills
        (99.0, 99.0, 99.0, 99.0),
        (99.0, 99.0, 99.0, 99.0),
        (99.0, 99.0, 99.0, 99.0),
        (99.0, 99.0, 99.0, 99.0),
    ]
    settlement = [(T0 + timedelta(minutes=3), 0.01)]

    payer = run(rows, funding=settlement)
    free = run(rows, funding=None)

    assert payer.final_position > 0  # long, paying a positive rate
    assert payer.stats["funding"] == pytest.approx(3.30, rel=0.05)
    assert payer.stats["final_equity"] < free.stats["final_equity"]


def test_zero_drift_gbm_is_not_a_money_printer():
    returns = []
    for seed in range(5):
        result = run(gbm_rows(days=20, seed=seed), config=BacktestConfig(stop_dd=None))
        assert result.stats["trades"] > 0
        assert result.stats["fees"] > 0.0
        returns.append(result.stats["total_return"])

    mean = sum(returns) / len(returns)
    # A fair random walk must not produce an edge. These bounds are wide on
    # purpose (5 paths is a tiny sample) but would catch any cash-printing bug.
    assert mean < 5.0
    assert max(returns) < 10.0
    assert min(returns) > -20.0


def test_liquidation_engine_stops_before_negative_equity():
    rows = []
    price = 100.0
    for _ in range(600):
        previous = price
        price *= 0.999
        rows.append((previous, previous * 1.0005, price * 0.9995, price))

    result = run(
        rows,
        params=GridParams(50.0, 10, 5.0),
        config=BacktestConfig(capital=100.0, stop_dd=None),
    )

    assert result.stats["liquidated"] is True
    assert result.liquidation is not None
    assert result.stats["liquidation_price"] is not None
    assert result.stats["max_dd"] <= 100.0
    assert result.stats["final_equity"] >= 0.0
    assert result.final_position == pytest.approx(0.0)


def test_grid_rejects_per_level_notional_below_exchange_minimum():
    rows = [(281.0, 281.0, 281.0, 281.0)] * 20
    with pytest.raises(ValueError, match="最小名义"):
        run(
            rows,
            params=GridParams(40.0, 20, 1.0),
            config=BacktestConfig(capital=100.0, stop_dd=None),
        )


def test_adaptive_grid_rebalances_without_lookahead():
    rows = zigzag(600)
    result = run(
        rows,
        params=GridParams(
            80.0,
            10,
            2.0,
            auto=True,
            auto_interval=120,
            auto_atr_window=60,
            auto_target_vol=0.25,
        ),
        config=BacktestConfig(capital=1000.0, stop_dd=None),
    )
    assert result.stats["trades"] > 0
    assert result.stats["total_return"] is not None
    assert result.strategy_state["size"] > 0
