"""Strategy interface: pure decision logic, no I/O, no clocks, no sleeps.

A strategy declares the desired set of resting orders for its group. The OMS
reconciles that declaration against what is actually open. Returning an empty
list means "cancel everything in my group".

This is the same object in replay, paper and live. Anything that differs
between those modes belongs in an ExecutionPort, never here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..domain.models import Bar, Fill, Order, OrderIntent, SymbolFilters


@dataclass(frozen=True, slots=True)
class StrategyContext:
    symbol: str
    now: datetime
    mark_price: float
    position_qty: float
    equity: float
    filters: SymbolFilters
    open_orders: tuple[Order, ...] = ()

    def open_for(self, group: str) -> tuple[Order, ...]:
        return tuple(o for o in self.open_orders if o.group == group)


class Strategy(ABC):
    """Callbacks run synchronously inside the event loop.

    ``on_start`` is called once before the first bar with the first tradeable
    price. ``on_bar`` runs after each completed bar and its intents become
    active for the next bar. ``on_fill`` runs as soon as a fill is acked,
    before the current bar finishes, and may emit replacement orders that are
    fillable in the same bar (this models a grid sweep, warts included).
    """

    @property
    @abstractmethod
    def group(self) -> str: ...

    @property
    @abstractmethod
    def strategy_id(self) -> str: ...

    def on_start(self, ctx: StrategyContext) -> list[OrderIntent]:
        return []

    def on_bar(self, bar: Bar, ctx: StrategyContext) -> list[OrderIntent]:
        return []

    def on_fill(self, fill: Fill, ctx: StrategyContext) -> list[OrderIntent]:
        return []

    def on_stop(self, ctx: StrategyContext) -> list[OrderIntent]:
        return []

    def state(self) -> dict:
        return {}
