"""Minute-level inventory grid expressed against the Strategy interface.

Inventory level L means position = -L * size. Two orders rest around L:
a buy at anchor + (L-1)*step and a sell at anchor + (L+1)*step. A fill moves
inventory by one level and the OMS reconciles the new adjacent pair.

The strategy derives its level from actual position, not from a counter, so
partial fills and external reconciliation cannot desynchronize it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Bar, Fill, OrderIntent, OrderType, Side, TimeInForce
from .base import Strategy, StrategyContext

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class GridParams:
    spacing_bp: float = 120.0
    levels: int = 30
    leverage: float = 1.0
    reanchor_bars: int | None = None
    group: str = "grid"

    def __post_init__(self) -> None:
        if self.spacing_bp <= 0:
            raise ValueError("spacing_bp must be positive")
        if self.levels <= 0:
            raise ValueError("levels must be positive")
        if self.leverage <= 0:
            raise ValueError("leverage must be positive")


class GridStrategy(Strategy):
    def __init__(self, symbol: str, params: GridParams) -> None:
        self.symbol = symbol
        self.params = params
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

    def _reset(self, anchor: float, ctx: StrategyContext) -> None:
        self.anchor = anchor
        self.step = anchor * self.params.spacing_bp / 1e4
        self.size = self._unit_size(ctx.equity, anchor, ctx)
        self.level = 0

    def _unit_size(self, equity: float, anchor: float, ctx: StrategyContext) -> float:
        if equity <= 0 or anchor <= 0:
            return 0.0
        qty = equity * self.params.leverage / self.params.levels / anchor
        return ctx.filters.align_qty(qty)

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
