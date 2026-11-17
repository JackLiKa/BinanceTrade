"""Offline unit tests for the round-trip cost model (all figures in bp)."""

from __future__ import annotations

import math

import pytest

from gridtrade.strategy.costs import CostModel, round_trip_cost_bp

MAKER = 2.0
TAKER = 5.0


def model(**overrides: float) -> CostModel:
    values: dict[str, float] = {"maker_fee_bp": MAKER, "taker_fee_bp": TAKER}
    values.update(overrides)
    return CostModel(**values)


def test_round_trip_maker_fees_on_both_legs() -> None:
    cost = CostModel().round_trip_bp(entry_taker=False, exit_taker=False)
    assert cost == pytest.approx(2.0 + 2.0)


def test_round_trip_mixed_and_taker_fees() -> None:
    default = CostModel()
    assert default.round_trip_bp(entry_taker=True, exit_taker=False) == pytest.approx(
        TAKER + MAKER
    )
    assert default.round_trip_bp(entry_taker=False, exit_taker=True) == pytest.approx(
        MAKER + TAKER
    )
    assert default.round_trip_bp(entry_taker=True, exit_taker=True) == pytest.approx(
        TAKER + TAKER
    )


def test_slippage_is_charged_on_both_legs() -> None:
    # 2bp maker in + 2bp maker out + 0.2bp adverse on entry and exit.
    cost = model(slippage_bp=0.2).round_trip_bp(entry_taker=False, exit_taker=False)
    assert cost == pytest.approx(4.0 + 2 * 0.2)


def test_maker_rebate_lowers_the_round_trip() -> None:
    cost = model(maker_fee_bp=-1.0).round_trip_bp(entry_taker=False, exit_taker=False)
    assert cost == pytest.approx(-2.0)


def test_positive_funding_costs_a_long_and_pays_a_short() -> None:
    funding = model(funding_rate_8h=0.0001)
    long_cost = funding.round_trip_bp(
        entry_taker=False, exit_taker=False, hold_hours=8.0, position_side="LONG"
    )
    short_cost = funding.round_trip_bp(
        entry_taker=False, exit_taker=False, hold_hours=8.0, position_side="SHORT"
    )
    assert long_cost == pytest.approx(4.0 + 1.0)  # 8h * 0.0001 * 1e4 = 1bp
    assert short_cost == pytest.approx(4.0 - 1.0)


def test_funding_scales_linearly_with_hold_time() -> None:
    funding = model(funding_rate_8h=0.0001)
    quarter = funding.round_trip_bp(
        entry_taker=False, exit_taker=False, hold_hours=2.0, position_side="LONG"
    )
    assert quarter == pytest.approx(4.0 + 0.25)


def test_negative_funding_rebates_a_long() -> None:
    funding = model(funding_rate_8h=-0.0001)
    cost = funding.round_trip_bp(
        entry_taker=False, exit_taker=False, hold_hours=8.0, position_side="LONG"
    )
    assert cost == pytest.approx(3.0)


def test_breakeven_spacing_is_absolute_cost_clamped_at_zero() -> None:
    normal = CostModel()
    assert normal.breakeven_spacing_bp(entry_taker=False, exit_taker=False) == pytest.approx(4.0)

    # Breakeven is the absolute round trip: a net rebate still has to be
    # "covered" by |cost|, and the result is never negative.
    rebate = model(maker_fee_bp=-10.0, taker_fee_bp=0.0)
    assert rebate.round_trip_bp(entry_taker=False, exit_taker=False) == pytest.approx(-20.0)
    assert rebate.breakeven_spacing_bp(entry_taker=False, exit_taker=False) == pytest.approx(20.0)

    # Negative funding can make the net round trip itself negative; abs() keeps
    # the breakeven requirement non-negative.
    funded = model(maker_fee_bp=0.0, taker_fee_bp=0.0, funding_rate_8h=-0.0001)
    assert funded.round_trip_bp(
        entry_taker=False, exit_taker=False, hold_hours=8.0, position_side="LONG"
    ) == pytest.approx(-1.0)
    assert funded.breakeven_spacing_bp(
        entry_taker=False, exit_taker=False, hold_hours=8.0, position_side="LONG"
    ) == pytest.approx(1.0)


def test_net_edge_subtracts_the_round_trip() -> None:
    default = CostModel()
    assert default.net_edge_bp(10.0, entry_taker=False, exit_taker=False) == pytest.approx(6.0)
    assert default.net_edge_bp(3.0, entry_taker=True, exit_taker=True) == pytest.approx(-7.0)


def test_is_profitable_respects_spacing_and_min_edge() -> None:
    default = CostModel()
    assert default.is_profitable(10.0, entry_taker=False, exit_taker=False)
    assert default.is_profitable(
        10.0, min_edge_bp=6.0, entry_taker=False, exit_taker=False
    )
    assert not default.is_profitable(
        10.0, min_edge_bp=7.0, entry_taker=False, exit_taker=False
    )
    assert not default.is_profitable(3.0, entry_taker=True, exit_taker=True)


def test_illegal_cost_parameters_raise_value_error() -> None:
    with pytest.raises(ValueError, match="taker_fee_bp"):
        CostModel(taker_fee_bp=-1.0)
    with pytest.raises(ValueError, match="slippage_bp"):
        CostModel(slippage_bp=-0.1)
    with pytest.raises(ValueError, match="funding_interval_h"):
        CostModel(funding_interval_h=0.0)
    with pytest.raises(ValueError, match="maker_fee_bp"):
        CostModel(maker_fee_bp=math.nan)


def test_illegal_call_arguments_raise_value_error() -> None:
    default = CostModel()
    with pytest.raises(ValueError, match="spacing_bp"):
        default.net_edge_bp(-1.0, entry_taker=False, exit_taker=False)
    with pytest.raises(ValueError, match="hold_hours"):
        default.round_trip_bp(entry_taker=False, exit_taker=False, hold_hours=-1.0)
    with pytest.raises(ValueError, match="position_side"):
        default.round_trip_bp(entry_taker=False, exit_taker=False, position_side="BOTH")


def test_position_side_is_case_insensitive() -> None:
    funding = model(funding_rate_8h=0.0001)
    long_lower = funding.round_trip_bp(
        entry_taker=False, exit_taker=False, hold_hours=8.0, position_side=" long "
    )
    short_upper = funding.round_trip_bp(
        entry_taker=False, exit_taker=False, hold_hours=8.0, position_side="SHORT"
    )
    assert long_lower == pytest.approx(5.0)
    assert short_upper == pytest.approx(3.0)


def test_describe_exposes_parameters_and_typical_costs() -> None:
    described = model(funding_rate_8h=0.0001, slippage_bp=0.2).describe()
    assert set(described) == {
        "maker_fee_bp",
        "taker_fee_bp",
        "slippage_bp",
        "funding_rate_8h",
        "funding_interval_h",
        "funding_bp_per_8h",
        "round_trip_maker_bp",
        "round_trip_taker_bp",
        "round_trip_maker_1h_bp",
        "round_trip_taker_1h_bp",
        "round_trip_taker_8h_bp",
        "breakeven_spacing_bp",
    }
    assert described["maker_fee_bp"] == pytest.approx(2.0)
    assert described["funding_bp_per_8h"] == pytest.approx(1.0)
    assert described["round_trip_maker_bp"] == pytest.approx(4.4)
    assert described["round_trip_maker_1h_bp"] == pytest.approx(4.4 + 0.125)
    assert described["round_trip_taker_8h_bp"] == pytest.approx(10.4 + 1.0)
    assert described["breakeven_spacing_bp"] == pytest.approx(4.4)


def test_module_level_helper_uses_default_model() -> None:
    assert round_trip_cost_bp(entry_taker=False, exit_taker=False) == pytest.approx(
        CostModel().round_trip_bp(entry_taker=False, exit_taker=False)
    )
    assert round_trip_cost_bp(entry_taker=True, exit_taker=True) == pytest.approx(10.0)


def test_cost_model_is_immutable_and_hashable() -> None:
    default = CostModel()
    assert hash(default)  # frozen dataclass with slots is hashable
    with pytest.raises(AttributeError):
        default.maker_fee_bp = 0.0  # type: ignore[misc]
