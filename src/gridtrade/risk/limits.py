"""Pre-trade limits and the account-level drawdown kill switch.

The in-process checks protect against strategy bugs (size explosion, price
fat fingers, order spam). A separate watchdog process must repeat the account
level checks in production; this module only owns the in-process half.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..domain.models import Rejection, Side


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_position_qty: float
    max_order_notional: float
    max_gross_notional: float
    max_open_orders: int = 200
    max_submits_per_minute: int = 60
    max_price_deviation_bp: float = 100.0

    def __post_init__(self) -> None:
        for name in ("max_position_qty", "max_order_notional", "max_gross_notional"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass
class RiskEngine:
    limits: RiskLimits
    _submits: deque[datetime] = field(default_factory=deque)

    def check(
        self,
        *,
        side: Side,
        qty: float,
        price: float | None,
        reduce_only: bool,
        position_qty: float,
        mark_price: float,
        open_orders: tuple[object, ...],
        now: datetime | None = None,
    ) -> Rejection | None:
        if qty <= 0:
            return Rejection("qty_nonpositive", f"qty={qty}")

        ref_price = price if price is not None else mark_price
        if ref_price <= 0:
            return Rejection("bad_price", f"price={ref_price}")

        if price is not None and mark_price > 0:
            deviation_bp = abs(price / mark_price - 1.0) * 1e4
            if deviation_bp > self.limits.max_price_deviation_bp:
                return Rejection(
                    "price_deviation",
                    f"{deviation_bp:.1f}bp from mark {mark_price}",
                )

        delta = side.sign * qty
        if reduce_only:
            if abs(position_qty) < 1e-12:
                return Rejection("reduce_only_flat", "no position to reduce")
            after = position_qty + delta
            if after * position_qty < 0:
                return Rejection(
                    "reduce_only_flip", f"pos {position_qty} delta {delta} would cross zero"
                )
            # Reducing exposure must never be blocked by size or rate caps.
            return None
        if abs(position_qty + delta) > self.limits.max_position_qty + 1e-9:
            return Rejection(
                "max_position",
                f"{abs(position_qty + delta):.6f} > {self.limits.max_position_qty:.6f}",
            )

        notional = qty * ref_price
        if notional > self.limits.max_order_notional + 1e-9:
            return Rejection("max_order_notional", f"{notional:.2f}")

        gross = sum(
            abs(getattr(o, "remaining", 0.0)) * (getattr(o, "price", None) or mark_price)
            for o in open_orders
            if getattr(o, "status", None) is None or getattr(o.status, "is_live", False)
        )
        if gross + notional > self.limits.max_gross_notional + 1e-9:
            return Rejection("max_gross_notional", f"{gross + notional:.2f}")

        if len(open_orders) >= self.limits.max_open_orders:
            return Rejection("max_open_orders", f"{len(open_orders)}")

        if now is not None and self._recent_submits(now) >= self.limits.max_submits_per_minute:
            return Rejection("order_rate", f"{self.limits.max_submits_per_minute}/min")

        return None

    def _recent_submits(self, now: datetime) -> int:
        cutoff = now - timedelta(minutes=1)
        while self._submits and self._submits[0] < cutoff:
            self._submits.popleft()
        return len(self._submits)

    def record_submit(self, now: datetime) -> None:
        self._submits.append(now)


@dataclass
class DrawdownGuard:
    """Flatten-and-halt when equity drawdown from peak exceeds the limit."""

    max_dd: float
    peak: float = 0.0
    halted: bool = False
    drawdown: float = 0.0

    def update(self, equity: float) -> bool:
        if self.halted:
            return True
        self.peak = max(self.peak, equity)
        self.drawdown = 0.0 if self.peak <= 0 else max(0.0, 1.0 - equity / self.peak)
        if self.drawdown > self.max_dd:
            self.halted = True
        return self.halted
