"""Transaction-cost model for a round trip, expressed in basis points (bp).

One basis point is ``1e-4`` of notional. ``CostModel`` answers the question a
grid trader actually cares about: *does one grid spacing pay for opening and
closing the position?* The round trip is entry fee + exit fee + adverse
slippage on both legs + funding carried while the position is open.

Sign convention: a positive return value is a cost, a negative value is a net
rebate. For funding, a positive rate means longs pay shorts, so a LONG round
trip costs and a SHORT round trip earns (its contribution flips sign).

The model is frozen and hashable: a backtest or the live paper engine can store
one instance, log ``describe()`` into an artifact, and never worry about it
mutating underfoot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["CostModel", "round_trip_cost_bp"]

_POSITION_SIDES = frozenset({"LONG", "SHORT"})


def _check_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


def _check_spacing(spacing_bp: float) -> None:
    """Reject a spacing that is negative or not a real number."""
    _check_finite("spacing_bp", spacing_bp)
    if spacing_bp < 0:
        raise ValueError(f"spacing_bp must be non-negative, got {spacing_bp!r}")


def _normalize_side(position_side: str) -> str:
    side = position_side.strip().upper()
    if side not in _POSITION_SIDES:
        raise ValueError(f"position_side must be LONG or SHORT, got {position_side!r}")
    return side


@dataclass(frozen=True, slots=True)
class CostModel:
    """Fees, slippage and funding for one open+close round trip, in bp.

    ``maker_fee_bp`` may be negative: exchanges pay a rebate for providing
    liquidity. ``slippage_bp`` is one-way and always applied adversely, so a
    round trip pays it twice. ``funding_rate_8h`` is the rate for one funding
    interval and ``funding_interval_h`` says how long that interval is.

    Example: with the defaults plus 0.2bp slippage, a maker/maker round trip
    costs ``2 + 2 + 2*0.2 = 4.4bp``. With a taker exit it costs
    ``2 + 5 + 0.4 = 7.4bp``.
    """

    maker_fee_bp: float = 2.0
    taker_fee_bp: float = 5.0
    slippage_bp: float = 0.0
    funding_rate_8h: float = 0.0
    funding_interval_h: float = 8.0

    def __post_init__(self) -> None:
        _check_finite("maker_fee_bp", self.maker_fee_bp)
        _check_finite("taker_fee_bp", self.taker_fee_bp)
        _check_finite("slippage_bp", self.slippage_bp)
        _check_finite("funding_rate_8h", self.funding_rate_8h)
        _check_finite("funding_interval_h", self.funding_interval_h)
        if self.taker_fee_bp < 0:
            raise ValueError(f"taker_fee_bp must be non-negative, got {self.taker_fee_bp!r}")
        if self.slippage_bp < 0:
            raise ValueError(f"slippage_bp must be non-negative, got {self.slippage_bp!r}")
        if self.funding_interval_h <= 0:
            raise ValueError(
                f"funding_interval_h must be positive, got {self.funding_interval_h!r}"
            )

    # -- core ------------------------------------------------------------

    def round_trip_bp(
        self,
        *,
        entry_taker: bool,
        exit_taker: bool,
        hold_hours: float = 0.0,
        position_side: str = "LONG",
    ) -> float:
        """Total cost (bp) of opening and closing one position.

        ``entry_taker``/``exit_taker`` pick taker instead of maker fees for that
        leg. Slippage is charged on both legs. Funding is scaled linearly by
        ``hold_hours / funding_interval_h`` and its sign follows
        ``position_side`` (positive rate: LONG pays, SHORT receives).

        Examples with ``CostModel(maker_fee_bp=2, taker_fee_bp=5)``:
        maker in / maker out = ``4.0``; maker in / taker out = ``7.0``; both
        taker = ``10.0``. With ``slippage_bp=0.2`` both taker = ``10.4``. With
        ``funding_rate_8h=0.0001`` held 8h, LONG = ``11.0`` and SHORT =
        ``9.0`` (funding contributes +1bp / -1bp).
        """
        _check_finite("hold_hours", hold_hours)
        if hold_hours < 0:
            raise ValueError(f"hold_hours must be non-negative, got {hold_hours!r}")
        side = _normalize_side(position_side)

        entry_fee_bp = self.taker_fee_bp if entry_taker else self.maker_fee_bp
        exit_fee_bp = self.taker_fee_bp if exit_taker else self.maker_fee_bp
        slippage_bp = 2.0 * self.slippage_bp
        funding_bp = hold_hours / self.funding_interval_h * self.funding_rate_8h * 1e4
        if side == "SHORT":
            funding_bp = -funding_bp
        return entry_fee_bp + exit_fee_bp + slippage_bp + funding_bp

    def breakeven_spacing_bp(
        self,
        *,
        entry_taker: bool,
        exit_taker: bool,
        hold_hours: float = 0.0,
        position_side: str = "LONG",
    ) -> float:
        """Smallest grid spacing (bp) that merely covers the round trip.

        This is ``max(0, abs(round_trip_bp(...)))``: the absolute cost, so a
        negative funding rebate or maker rebate still has to be covered by its
        magnitude and the answer is never negative. Example: maker/maker with
        no slippage gives ``4.0``; the default 120bp grid spacing clears it
        easily. A rebate of -2bp per leg gives ``abs(-4) = 4.0`` as well.
        """
        cost = self.round_trip_bp(
            entry_taker=entry_taker,
            exit_taker=exit_taker,
            hold_hours=hold_hours,
            position_side=position_side,
        )
        return max(0.0, abs(cost))

    def net_edge_bp(
        self,
        spacing_bp: float,
        *,
        entry_taker: bool,
        exit_taker: bool,
        hold_hours: float = 0.0,
        position_side: str = "LONG",
    ) -> float:
        """Edge per grid round trip: ``spacing_bp - round_trip_bp(...)``.

        Example: spacing 10bp, maker/maker cost 4bp -> ``6.0``. A negative
        spacing is rejected because it has no trading meaning. If funding is a
        net income for the selected side the edge can exceed the spacing (see
        ``round_trip_bp`` negative returns).
        """
        _check_spacing(spacing_bp)
        return spacing_bp - self.round_trip_bp(
            entry_taker=entry_taker,
            exit_taker=exit_taker,
            hold_hours=hold_hours,
            position_side=position_side,
        )

    def is_profitable(
        self,
        spacing_bp: float,
        *,
        min_edge_bp: float = 0.0,
        entry_taker: bool,
        exit_taker: bool,
        hold_hours: float = 0.0,
        position_side: str = "LONG",
    ) -> bool:
        """True when ``net_edge_bp >= min_edge_bp``.

        Example: spacing 10bp and maker/maker cost 4bp gives 6bp of edge, so
        ``is_profitable(10, ...)`` is True while
        ``is_profitable(10, min_edge_bp=6, ...)`` is still True but
        ``min_edge_bp=7`` is False.
        """
        _check_finite("min_edge_bp", min_edge_bp)
        return (
            self.net_edge_bp(
                spacing_bp,
                entry_taker=entry_taker,
                exit_taker=exit_taker,
                hold_hours=hold_hours,
                position_side=position_side,
            )
            >= min_edge_bp
        )

    # -- flattening for artifacts ----------------------------------------

    def describe(self) -> dict[str, float]:
        """Flatten the model and a few typical round-trip costs into a dict.

        The grid strategy and the paper engine put this into their snapshot /
        artifact so a reader can compare "spacing in use" against "cost to
        beat" without recomputing anything. Keys:
        ``maker_fee_bp``, ``taker_fee_bp``, ``slippage_bp``,
        ``funding_rate_8h``, ``funding_interval_h``, ``funding_bp_per_8h``,
        ``round_trip_maker_bp``, ``round_trip_taker_bp``,
        ``round_trip_maker_1h_bp``, ``round_trip_taker_1h_bp``,
        ``round_trip_taker_8h_bp`` and ``breakeven_spacing_bp``.

        Example: ``CostModel().describe()["round_trip_maker_bp"] == 4.0``.
        """
        return {
            "maker_fee_bp": self.maker_fee_bp,
            "taker_fee_bp": self.taker_fee_bp,
            "slippage_bp": self.slippage_bp,
            "funding_rate_8h": self.funding_rate_8h,
            "funding_interval_h": self.funding_interval_h,
            "funding_bp_per_8h": self.funding_rate_8h * 1e4,
            "round_trip_maker_bp": self.round_trip_bp(entry_taker=False, exit_taker=False),
            "round_trip_taker_bp": self.round_trip_bp(entry_taker=True, exit_taker=True),
            "round_trip_maker_1h_bp": self.round_trip_bp(
                entry_taker=False, exit_taker=False, hold_hours=1.0
            ),
            "round_trip_taker_1h_bp": self.round_trip_bp(
                entry_taker=True, exit_taker=True, hold_hours=1.0
            ),
            "round_trip_taker_8h_bp": self.round_trip_bp(
                entry_taker=True, exit_taker=True, hold_hours=8.0
            ),
            "breakeven_spacing_bp": self.breakeven_spacing_bp(
                entry_taker=False, exit_taker=False
            ),
        }


def round_trip_cost_bp(
    *,
    entry_taker: bool,
    exit_taker: bool,
    hold_hours: float = 0.0,
    position_side: str = "LONG",
) -> float:
    """Module-level shortcut for ``CostModel().round_trip_bp(...)``.

    Example: ``round_trip_cost_bp(entry_taker=False, exit_taker=False) == 4.0``
    using the default 2bp maker fee on both legs.
    """
    return CostModel().round_trip_bp(
        entry_taker=entry_taker,
        exit_taker=exit_taker,
        hold_hours=hold_hours,
        position_side=position_side,
    )
