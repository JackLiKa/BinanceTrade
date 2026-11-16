"""Ports: the only seams between pure domain logic and I/O.

Strategies see none of these. The engine and OMS depend on the Protocols so the
same strategy runs against simulated, paper and live adapters.
"""

from __future__ import annotations

from typing import Callable, Iterable, Protocol

from .domain.models import Bar, BrokerSnapshot, ExecEvent, Fill, Order, SubmitAck


class ExecutionPort(Protocol):
    """Synchronous order entry.

    ``submit``/``cancel`` must return a broker acknowledgement before returning
    (REST does). Fills and exchange-initiated updates arrive later through the
    event sink, which may be invoked after those calls return.
    """

    def set_event_sink(self, sink: Callable[[ExecEvent], None]) -> None: ...

    def submit(self, order: Order) -> SubmitAck: ...

    def cancel(self, client_id: str) -> bool: ...

    def cancel_group(self, group: str) -> int: ...

    def snapshot(self) -> BrokerSnapshot: ...

    @property
    def position_qty(self) -> float: ...

    @property
    def mark_price(self) -> float: ...


class MarketDataPort(Protocol):
    """Historical replay or live stream, normalized to closed bars."""

    def stream(self) -> Iterable[Bar]: ...

    def funding_settlements(self) -> Iterable[object]: ...


class Clock(Protocol):
    def now(self) -> object: ...
