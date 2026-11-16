"""Domain types shared by research, simulated execution and the future live runtime.

All types here are broker-agnostic. Exchange quirks live in adapters
(filters, client-order-id limits, rate limits), never in the strategy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TypeAlias


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    POST_ONLY = "GTX"

    @property
    def is_maker_only(self) -> bool:
        return self is TimeInForce.POST_ONLY


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    # Terminal at the exchange is unknown to us: query by client id, never
    # blind-retry, because the order may still be live.
    UNKNOWN = "UNKNOWN"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL

    @property
    def is_live(self) -> bool:
        return not self.is_terminal


_TERMINAL = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
)


def _decimals(value: float) -> int:
    text = f"{value:.12f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


@dataclass(frozen=True, slots=True)
class SymbolFilters:
    """Exchange trading filters plus the minimum needed to validate an order."""

    tick_size: float
    step_size: float
    min_notional: float
    max_orders: int = 200

    @classmethod
    def from_exchange_filters(cls, filters: list[dict]) -> SymbolFilters:
        by_type = {f["filterType"]: f for f in filters}
        price = by_type.get("PRICE_FILTER", {})
        lot = by_type.get("LOT_SIZE", {})
        notional = by_type.get("MIN_NOTIONAL") or by_type.get("NOTIONAL") or {}
        max_orders = by_type.get("MAX_NUM_ORDERS") or by_type.get("MAX_NUM_ALGO_ORDERS") or {}
        return cls(
            tick_size=float(price.get("tickSize", 0.01)),
            step_size=float(lot.get("stepSize", 0.001)),
            min_notional=float(notional.get("notional", notional.get("minNotional", 5.0))),
            max_orders=int(max_orders.get("limit", 200)),
        )

    def align_price(self, price: float, *, up: bool = False) -> float:
        n = price / self.tick_size
        n = math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)
        return round(n * self.tick_size, _decimals(self.tick_size))

    def align_qty(self, qty: float) -> float:
        n = qty / self.step_size
        return round(math.floor(n + 1e-9) * self.step_size, _decimals(self.step_size))

    def notional_ok(self, qty: float, price: float) -> bool:
        return qty > 0 and qty * price >= self.min_notional - 1e-12


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def close_time(self) -> datetime:
        return self.open_time + timedelta(minutes=1)

    @property
    def direction(self) -> int:
        return 1 if self.close >= self.open else -1


@dataclass(frozen=True, slots=True)
class FundingSettlement:
    symbol: str
    time: datetime
    rate: float
    mark_price: float | None = None


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """What a strategy wants. The OMS turns this into an exchange order.

    ``tag`` is the stable identity of a resting slot (for a grid: the
    destination inventory level). Strategies declare the full desired set of
    resting orders; the OMS keeps/cancels/places so the declared set is open.
    Market intents are one-shot (tag used only for dedupe).
    """

    side: Side
    qty: float
    price: float | None = None
    type: OrderType = OrderType.LIMIT
    tif: TimeInForce = TimeInForce.POST_ONLY
    reduce_only: bool = False
    tag: str = ""
    group: str = "default"


@dataclass
class Order:
    client_id: str
    symbol: str
    side: Side
    type: OrderType
    qty: float
    price: float | None
    tif: TimeInForce
    reduce_only: bool
    tag: str
    group: str
    status: OrderStatus = OrderStatus.NEW
    filled_qty: float = 0.0
    avg_price: float = 0.0
    exchange_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    reason: str | None = None

    @property
    def remaining(self) -> float:
        return max(0.0, self.qty - self.filled_qty)

    @property
    def is_open(self) -> bool:
        return self.status.is_live

    @property
    def notional(self) -> float:
        return self.remaining * (self.price or 0.0)


@dataclass(frozen=True, slots=True)
class OrderUpdate:
    """Out-of-band state change reported by an execution adapter."""

    client_id: str
    status: OrderStatus
    filled_qty: float = 0.0
    avg_price: float = 0.0
    ts: datetime | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Fill:
    client_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    ts: datetime
    tag: str = ""
    liquidity: str = "MAKER"


ExecEvent: TypeAlias = Fill | OrderUpdate


@dataclass(frozen=True, slots=True)
class SubmitAck:
    ok: bool
    reason: str = ""
    exchange_id: str | None = None


@dataclass(frozen=True, slots=True)
class Rejection:
    code: str
    detail: str
    tag: str = ""


@dataclass
class Position:
    symbol: str = ""
    qty: float = 0.0
    entry_price: float = 0.0

    def apply(self, side: Side, qty: float, price: float) -> None:
        signed = side.sign * qty
        if self.qty == 0 or self.qty * signed > 0:
            total = abs(self.qty) + qty
            self.entry_price = (
                (self.entry_price * abs(self.qty) + price * qty) / total if total else 0.0
            )
        elif abs(signed) >= abs(self.qty) - 1e-12:
            self.entry_price = price if abs(self.qty + signed) > 1e-12 else 0.0
        self.qty = self.qty + signed
        if abs(self.qty) < 1e-12:
            self.qty = 0.0
            self.entry_price = 0.0

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < 1e-12


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    client_id: str
    status: OrderStatus
    filled_qty: float = 0.0
    avg_price: float = 0.0
    exchange_id: str | None = None


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    orders: tuple[BrokerOrder, ...]
    position_qty: float
    ts: datetime | None = None
