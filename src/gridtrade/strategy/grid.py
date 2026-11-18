"""Minute-level inventory grid expressed against the Strategy interface.

Inventory level L means position = -L * size. Two orders rest around L:
a buy at anchor + (L-1)*step and a sell at anchor + (L+1)*step. A fill moves
inventory by one level and the OMS reconciles the new adjacent pair.

The strategy derives its level from actual position, not from a counter, so
partial fills and external reconciliation cannot desynchronize it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.models import Bar, Fill, OrderIntent, OrderType, Side, TimeInForce
from .base import Strategy, StrategyContext
from .costs import CostModel

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class GridParams:
    spacing_bp: float = 120.0
    levels: int = 30
    leverage: float = 1.0
    reanchor_bars: int | None = None
    group: str = "grid"
    min_edge_bp: float = 0.0

    def __post_init__(self) -> None:
        if self.spacing_bp <= 0:
            raise ValueError("spacing_bp must be positive")
        if self.levels <= 0:
            raise ValueError("levels must be positive")
        if self.leverage <= 0:
            raise ValueError("leverage must be positive")
        if self.min_edge_bp < 0:
            raise ValueError("min_edge_bp must be non-negative")


class GridStrategy(Strategy):
    def __init__(
        self,
        symbol: str,
        params: GridParams,
        *,
        cost_model: CostModel | None = None,
    ) -> None:
        self.symbol = symbol
        self.params = params
        self._cost_model = cost_model if cost_model is not None else CostModel()
        self.anchor: float = 0.0
        self.step: float = 0.0
        self.size: float = 0.0
        self.level: int = 0
        self._bars = 0
        self._pending_reanchor = False

    @property
    def group(self) -> str:
        return f"{self.params.group}:{self.symbol}"

    @property
    def strategy_id(self) -> str:
        p = self.params
        return f"grid/{p.spacing_bp:g}bp/{p.levels}L/{p.leverage:g}x"

    def on_start(self, ctx: StrategyContext) -> list[OrderIntent]:
        self._validate_cost()
        self._reset(ctx.mark_price, ctx)
        return self._plan()

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[OrderIntent]:
        if self._pending_reanchor:
            if abs(ctx.position_qty) > self._half_size():
                return [self._flatten_intent(ctx)]
            self._pending_reanchor = False
            self._reset(ctx.mark_price, ctx)
            return self._plan()

        if self.params.reanchor_bars:
            self._bars += 1
            if self._bars >= self.params.reanchor_bars:
                self._bars = 0
                if abs(ctx.position_qty) > self._half_size():
                    self._pending_reanchor = True
                    return [self._flatten_intent(ctx)]
                self._reset(bar.close, ctx)
                return self._plan()

        return self._plan()

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> list[OrderIntent]:
        if self.size > 0:
            self.level = int(round(-ctx.position_qty / self.size))
        if self._pending_reanchor:
            return []
        return self._plan()

    def on_stop(self, ctx: StrategyContext) -> list[OrderIntent]:
        if abs(ctx.position_qty) <= _EPS:
            return []
        return [self._flatten_intent(ctx)]

    def state(self) -> dict:
        return {
            "anchor": self.anchor,
            "step": self.step,
            "level": self.level,
            "size": self.size,
            "grid_inventory": -self.level * self.size,
            "reanchor_pending": self._pending_reanchor,
        }

    def cost_report(self) -> dict[str, Any]:
        """Round-trip cost accounting for the configured spacing.

        The grid normally rests POST_ONLY orders on both legs, so the headline
        ``round_trip_bp`` uses maker fees for entry and exit (that is also what
        the ``min_edge_bp`` guard checks). ``round_trip_taker_bp`` gives the
        taker/taker variant for comparison. Example with the default model
        (2bp maker) and ``spacing_bp=10``: ``round_trip_bp == 4.0``,
        ``breakeven_spacing_bp == 4.0`` and ``net_edge_bp == 6.0``.
        """
        model = self._cost_model
        spacing = self.params.spacing_bp
        return {
            **model.describe(),
            "spacing_bp": spacing,
            "round_trip_bp": model.round_trip_bp(entry_taker=False, exit_taker=False),
            "round_trip_taker_bp": model.round_trip_bp(entry_taker=True, exit_taker=True),
            "breakeven_spacing_bp": model.breakeven_spacing_bp(
                entry_taker=False, exit_taker=False
            ),
            "net_edge_bp": model.net_edge_bp(spacing, entry_taker=False, exit_taker=False),
            "is_profitable": model.is_profitable(
                spacing,
                min_edge_bp=self.params.min_edge_bp,
                entry_taker=False,
                exit_taker=False,
            ),
            "min_edge_bp": self.params.min_edge_bp,
        }

    def describe(self) -> dict[str, Any]:
        """Strategy description for artifacts/logs, including the ``cost`` block."""
        p = self.params
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "spacing_bp": p.spacing_bp,
            "levels": p.levels,
            "leverage": p.leverage,
            "min_edge_bp": p.min_edge_bp,
            "state": self.state(),
            "cost": self.cost_report(),
        }

    def _validate_cost(self) -> None:
        """Refuse to start when spacing cannot pay the round trip plus a margin.

        Only active when ``min_edge_bp > 0``; the default of 0 keeps every
        pre-existing behaviour byte-for-byte. Example message:
        ``spacing 5bp <= round-trip 4bp + min edge 2bp``.
        """
        min_edge = self.params.min_edge_bp
        if min_edge <= 0:
            return
        spacing = self.params.spacing_bp
        round_trip = self._cost_model.round_trip_bp(entry_taker=False, exit_taker=False)
        if spacing <= round_trip + min_edge:
            raise ValueError(
                f"spacing {spacing:g}bp <= round-trip {round_trip:g}bp + min edge {min_edge:g}bp"
            )

    def _reset(self, anchor: float, ctx: StrategyContext) -> None:
        self.anchor = anchor
        self.step = anchor * self.params.spacing_bp / 1e4
        self.size = self._unit_size(ctx.equity, anchor, ctx)
        self.level = 0

    def _unit_size(self, equity: float, anchor: float, ctx: StrategyContext) -> float:
        if equity <= 0 or anchor <= 0:
            return 0.0
        qty = equity * self.params.leverage / self.params.levels / anchor
        aligned = ctx.filters.align_qty(qty)
        notional = aligned * anchor
        if aligned <= 0 or notional + 1e-9 < ctx.filters.min_notional:
            raise ValueError(
                f"每格名义 ${notional:.4f} 低于交易所最小名义 ${ctx.filters.min_notional:g}"
                f"（{self.params.levels} 层、{self.params.leverage:g}x）；"
                "请提高本金/杠杆或降低层数"
            )
        return aligned

    def _half_size(self) -> float:
        return 0.5 * self.size

    def _plan(self) -> list[OrderIntent]:
        if self.size <= 0:
            return []
        out: list[OrderIntent] = []
        if self.level < self.params.levels:
            out.append(
                OrderIntent(
                    side=Side.SELL,
                    qty=self.size,
                    price=self.anchor + (self.level + 1) * self.step,
                    tif=TimeInForce.POST_ONLY,
                    tag=f"lvl{self.level + 1:+d}",
                    group=self.group,
                )
            )
        if self.level > -self.params.levels:
            out.append(
                OrderIntent(
                    side=Side.BUY,
                    qty=self.size,
                    price=self.anchor + (self.level - 1) * self.step,
                    tif=TimeInForce.POST_ONLY,
                    tag=f"lvl{self.level - 1:+d}",
                    group=self.group,
                )
            )
        return out

    def _flatten_intent(self, ctx: StrategyContext) -> OrderIntent:
        side = Side.SELL if ctx.position_qty > 0 else Side.BUY
        return OrderIntent(
            side=side,
            qty=abs(ctx.position_qty),
            price=None,
            type=OrderType.MARKET,
            tif=TimeInForce.IOC,
            reduce_only=True,
            tag="flatten",
            group=self.group,
        )
