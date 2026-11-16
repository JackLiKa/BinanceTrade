"""Order management: intent -> order lifecycle, idempotency and reconciliation.

Contract with strategies: a strategy declares the full desired set of resting
orders for its group, keyed by stable ``tag``. ``sync`` cancels anything in the
group that is no longer declared, keeps orders whose economics still match and
places the rest. Repeating the same declaration is a no-op.

Client order ids are deterministic hashes of (symbol, group, tag, generation).
A retry of the same intent therefore produces the same id, which is what makes
"did my order reach the exchange?" recoverable instead of a coin flip.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

from ..domain.models import (
    Fill,
    Order,
    OrderIntent,
    OrderStatus,
    OrderType,
    OrderUpdate,
    Rejection,
    Side,
    SymbolFilters,
    TimeInForce,
)
from ..ports import ExecutionPort
from ..risk.limits import RiskEngine
from ..strategy.base import StrategyContext

_SIZE_EPS = 1e-9
_PRICE_EPS = 1e-9


@dataclass
class SyncReport:
    submitted: list[Order] = field(default_factory=list)
    canceled: list[str] = field(default_factory=list)
    kept: int = 0
    rejected: list[Rejection] = field(default_factory=list)


@dataclass
class ReconcileReport:
    unknown_at_broker: list[str] = field(default_factory=list)
    missing_at_broker: list[str] = field(default_factory=list)
    position_mismatch: tuple[float, float] | None = None

    @property
    def ok(self) -> bool:
        return not (self.unknown_at_broker or self.missing_at_broker or self.position_mismatch)


def client_order_id(symbol: str, group: str, tag: str, generation: int) -> str:
    raw = f"{symbol}|{group}|{tag}|{generation}".encode()
    return "gt-" + hashlib.sha1(raw).hexdigest()[:16]


class OMS:
    def __init__(
        self,
        port: ExecutionPort,
        risk: RiskEngine,
        filters: SymbolFilters,
        symbol: str,
    ) -> None:
        self.port = port
        self.risk = risk
        self.filters = filters
        self.symbol = symbol
        self._orders: dict[str, Order] = {}
        self._gen: dict[tuple[str, str], int] = {}
        self._position = 0.0
        self.fills: list[Fill] = []
        self.orphan_fills: list[Fill] = []
        self.on_fill: Callable[[Fill], None] | None = None
        port.set_event_sink(self._on_event)

    # -- queries ---------------------------------------------------------

    def order(self, client_id: str) -> Order | None:
        return self._orders.get(client_id)

    def orders(self) -> tuple[Order, ...]:
        return tuple(self._orders.values())

    def open_orders(self, group: str | None = None) -> tuple[Order, ...]:
        return tuple(
            o
            for o in self._orders.values()
            if o.is_open and (group is None or o.group == group)
        )

    def open_for(self, group: str) -> dict[str, Order]:
        return {o.tag: o for o in self.open_orders(group)}

    # -- strategy-facing -------------------------------------------------

    def sync(self, group: str, intents: list[OrderIntent], ctx: StrategyContext) -> SyncReport:
        report = SyncReport()
        market = [i for i in intents if i.type is OrderType.MARKET]
        resting = [i for i in intents if i.type is OrderType.LIMIT]

        desired: dict[str, OrderIntent] = {}
        for intent in resting:
            if not intent.tag:
                report.rejected.append(Rejection("missing_tag", "resting order needs tag"))
                continue
            if intent.tag in desired:
                report.rejected.append(
                    Rejection("duplicate_tag", "two intents share a tag", intent.tag)
                )
                continue
            price = self.filters.align_price(
                intent.price or 0.0, up=intent.side is Side.SELL
            )
            qty = self.filters.align_qty(intent.qty)
            if price <= 0:
                report.rejected.append(Rejection("bad_price", "price <= 0", intent.tag))
                continue
            if not self.filters.notional_ok(qty, price):
                report.rejected.append(
                    Rejection(
                        "min_notional",
                        f"{qty}x{price} < {self.filters.min_notional}",
                        intent.tag,
                    )
                )
                continue
            normalized = OrderIntent(
                side=intent.side,
                qty=qty,
                price=price,
                type=OrderType.LIMIT,
                tif=intent.tif,
                reduce_only=intent.reduce_only,
                tag=intent.tag,
                group=group,
            )
            desired[intent.tag] = normalized

        open_now = self.open_for(group)
        to_cancel = [
            o
            for o in open_now.values()
            if o.tag not in desired or not self._same(o, desired[o.tag])
        ]
        for order in to_cancel:
            self._cancel(order)
            report.canceled.append(order.client_id)

        # Canceled orders free their risk budget immediately.
        surviving = [o for o in ctx.open_orders if o.client_id not in {c.client_id for c in to_cancel}]
        for intent in desired.values():
            existing = self.open_for(group).get(intent.tag)
            if existing is not None:
                report.kept += 1
                continue
            order, rejection = self._place(intent, ctx, surviving)
            if order is None:
                report.rejected.append(rejection or Rejection("rejected", "unknown", intent.tag))
                continue
            surviving.append(order)
            report.submitted.append(order)

        for intent in market:
            existing = self.open_for(group).get(intent.tag)
            if existing is not None:
                report.kept += 1
                continue
            order, rejection = self._place(intent, ctx, surviving)
            if order is None:
                report.rejected.append(rejection or Rejection("rejected", "unknown", intent.tag))
                continue
            surviving.append(order)
            report.submitted.append(order)

        return report

    def flatten(self, group: str, ctx: StrategyContext) -> SyncReport:
        if abs(ctx.position_qty) <= self.filters.step_size / 2:
            return SyncReport()
        side = Side.SELL if ctx.position_qty > 0 else Side.BUY
        intent = OrderIntent(
            side=side,
            qty=abs(ctx.position_qty),
            type=OrderType.MARKET,
            tif=TimeInForce.IOC,
            reduce_only=True,
            tag="flatten",
            group=group,
        )
        return self.sync(group, [intent], ctx)

    def cancel_group(self, group: str) -> int:
        canceled = 0
        for order in self.open_orders(group):
            self._cancel(order)
            canceled += 1
        return canceled

    # -- execution events ------------------------------------------------

    def _on_event(self, event: Fill | OrderUpdate) -> None:
        if isinstance(event, Fill):
            self._apply_fill(event)
        else:
            self._apply_update(event)

    def _apply_fill(self, fill: Fill) -> None:
        order = self._orders.get(fill.client_id)
        if order is None:
            self.orphan_fills.append(fill)
            return
        total = order.filled_qty + fill.qty
        if total > 0:
            order.avg_price = (order.avg_price * order.filled_qty + fill.price * fill.qty) / total
        order.filled_qty = total
        order.updated_at = fill.ts
        if order.remaining <= _SIZE_EPS:
            order.filled_qty = order.qty
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        self._position += fill.side.sign * fill.qty
        if abs(self._position) < _SIZE_EPS:
            self._position = 0.0
        self.fills.append(fill)
        if self.on_fill is not None:
            self.on_fill(fill)

    def _apply_update(self, update: OrderUpdate) -> None:
        order = self._orders.get(update.client_id)
        if order is None:
            return
        order.status = update.status
        order.filled_qty = update.filled_qty
        order.avg_price = update.avg_price
        order.reason = update.reason or order.reason
        order.updated_at = update.ts

    # -- reconciliation --------------------------------------------------

    def reconcile(self, snapshot) -> ReconcileReport:
        """Compare local state to the exchange and repair only safe deltas.

        Missing local orders become UNKNOWN (query, never blind-retry); broker
        orders we never sent are canceled; a position mismatch is reported for
        the caller to halt on, not silently adopted.
        """
        report = ReconcileReport()
        broker = {b.client_id: b for b in snapshot.orders}

        for client_id, order in list(self._orders.items()):
            if order.is_open and client_id not in broker:
                order.status = OrderStatus.UNKNOWN
                report.missing_at_broker.append(client_id)

        for client_id, remote in broker.items():
            local = self._orders.get(client_id)
            if local is None:
                report.unknown_at_broker.append(client_id)
                try:
                    self.port.cancel(client_id)
                except Exception:
                    pass
                continue
            self._apply_update(
                OrderUpdate(
                    client_id=client_id,
                    status=remote.status,
                    filled_qty=remote.filled_qty,
                    avg_price=remote.avg_price,
                    ts=snapshot.ts,
                    reason="reconcile",
                )
            )

        tolerance = self.filters.step_size / 2
        if abs(snapshot.position_qty - self._position) > tolerance:
            report.position_mismatch = (self._position, snapshot.position_qty)
        return report

    # -- internals -------------------------------------------------------

    def _place(
        self, intent: OrderIntent, ctx: StrategyContext, already_open: list
    ) -> tuple[Order | None, Rejection | None]:
        rejection = self.risk.check(
            side=intent.side,
            qty=intent.qty,
            price=intent.price,
            reduce_only=intent.reduce_only,
            position_qty=ctx.position_qty,
            mark_price=ctx.mark_price,
            open_orders=tuple(already_open),
            now=ctx.now,
        )
        if rejection is not None:
            return None, Rejection(rejection.code, rejection.detail, intent.tag)

        key = (intent.group, intent.tag)
        generation = self._gen.get(key, 0)
        self._gen[key] = generation + 1
        client_id = client_order_id(self.symbol, intent.group, intent.tag, generation)
        order = Order(
            client_id=client_id,
            symbol=self.symbol,
            side=intent.side,
            type=intent.type,
            qty=intent.qty,
            price=intent.price,
            tif=intent.tif,
            reduce_only=intent.reduce_only,
            tag=intent.tag,
            group=intent.group,
            created_at=ctx.now,
            updated_at=ctx.now,
        )
        ack = self.port.submit(order)
        if not ack.ok:
            order.status = OrderStatus.REJECTED
            order.reason = ack.reason
            self._orders[client_id] = order
            return None, Rejection("exchange_reject", ack.reason, intent.tag)
        order.exchange_id = ack.exchange_id
        self.risk.record_submit(ctx.now)
        self._orders[client_id] = order
        return order, None

    def _cancel(self, order: Order) -> None:
        if not order.is_open:
            return
        if self.port.cancel(order.client_id):
            order.status = OrderStatus.CANCELED

    def _same(self, order: Order, intent: OrderIntent) -> bool:
        return (
            order.side is intent.side
            and order.type is intent.type
            and order.tif is intent.tif
            and order.reduce_only is intent.reduce_only
            and abs(order.remaining - intent.qty) <= _SIZE_EPS
            and (order.price or 0.0) == (intent.price or 0.0)
        )
