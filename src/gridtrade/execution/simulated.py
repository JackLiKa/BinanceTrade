"""Bar-driven simulated execution: the same port used by replay and paper.

Fill model (deliberately conservative):
  * resting limit orders only fill when the bar's extreme in the bar's
    direction reaches the order price;
  * an up bar (close >= open) can only fill sells, a down bar only buys;
  * market orders sent after a bar closes fill at the next bar's open;
  * fees and slippage are charged on notional per fill.

``intrabar=True`` processes both extremes in path order (down-then-up for an
up bar) and is an optimistic upper bound, not the default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ..risk.liquidation import (
    DEFAULT_MAINTENANCE_TIERS,
    LiquidationEvent,
    liquidation_price,
    maintenance_margin,
)
from ..domain.models import (
    Bar,
    BrokerOrder,
    BrokerSnapshot,
    ExecEvent,
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Side,
    SubmitAck,
    SymbolFilters,
    TimeInForce,
)

_EPS = 1e-12


@dataclass(frozen=True, slots=True)
class SimFees:
    maker: float = 0.0002
    taker: float = 0.0005
    slip_bp: float = 0.2

    @property
    def maker_all_in(self) -> float:
        return self.maker + self.slip_bp / 1e4

    @property
    def taker_all_in(self) -> float:
        return self.taker + self.slip_bp / 1e4


class SimExecution:
    def __init__(
        self,
        symbol: str,
        filters: SymbolFilters,
        fees: SimFees,
        capital: float,
        *,
        intrabar: bool = False,
        max_fills_per_bar: int = 2_000,
        maintenance_tiers=DEFAULT_MAINTENANCE_TIERS,
        liquidation_fee: float = 0.005,
        liquidation_enabled: bool = True,
        insurance_fund_balance: float = 0.0,
    ) -> None:
        self.symbol = symbol
        self.filters = filters
        self.fees = fees
        self.capital = capital
        self.cash = capital
        self.position = 0.0
        self.entry_price = 0.0
        self.fees_paid = 0.0
        self.funding_paid = 0.0
        self.funding_events: list[tuple[datetime | None, float]] = []
        self.fills: list[Fill] = []
        self.intrabar = intrabar
        self.max_fills_per_bar = max_fills_per_bar
        self.truncated_bars = 0
        self.maintenance_tiers = tuple(maintenance_tiers)
        self.liquidation_fee = max(0.0, float(liquidation_fee))
        self.liquidation_enabled = bool(liquidation_enabled)
        self.insurance_fund_balance = max(0.0, float(insurance_fund_balance or 0.0))
        self.liquidated = False
        self.liquidation: LiquidationEvent | None = None

        self._orders: dict[str, Order] = {}
        self._open: set[str] = set()
        self._pending_market: list[str] = []
        self._sink: Callable[[ExecEvent], None] | None = None
        self._bar: Bar | None = None
        self._last_price = 0.0
        self._mark = 0.0

    # -- port ------------------------------------------------------------

    def set_event_sink(self, sink: Callable[[ExecEvent], None]) -> None:
        self._sink = sink

    def submit(self, order: Order) -> SubmitAck:
        if self.liquidated:
            return SubmitAck(False, "account_liquidated")
        if order.type is OrderType.LIMIT and order.tif is TimeInForce.POST_ONLY:
            if order.side is Side.BUY and order.price >= self._last_price - _EPS:
                return SubmitAck(False, "post_only_would_take")
            if order.side is Side.SELL and order.price <= self._last_price + _EPS:
                return SubmitAck(False, "post_only_would_take")
        if order.reduce_only and not self._reduces_only(order):
            return SubmitAck(False, "reduce_only_invalid")

        self._orders[order.client_id] = order
        self._open.add(order.client_id)
        if order.type is OrderType.MARKET:
            self._pending_market.append(order.client_id)
        return SubmitAck(True)

    def cancel(self, client_id: str) -> bool:
        if client_id not in self._open:
            return False
        self._open.discard(client_id)
        if client_id in self._pending_market:
            self._pending_market.remove(client_id)
        return True

    def cancel_group(self, group: str) -> int:
        targets = [cid for cid in self._open if self._orders[cid].group == group]
        for cid in targets:
            self.cancel(cid)
        return len(targets)

    def snapshot(self) -> BrokerSnapshot:
        return BrokerSnapshot(
            orders=tuple(
                BrokerOrder(
                    client_id=o.client_id,
                    status=o.status,
                    filled_qty=o.filled_qty,
                    avg_price=o.avg_price,
                    exchange_id=o.exchange_id,
                )
                for o in self._orders.values()
            ),
            position_qty=self.position,
            ts=self._bar.close_time if self._bar else None,
        )

    @property
    def position_qty(self) -> float:
        return self.position

    @property
    def mark_price(self) -> float:
        return self._mark

    @property
    def equity(self) -> float:
        return self.cash + self.position * self._mark

    @property
    def wallet_balance(self) -> float:
        """Cost-basis wallet balance: initial capital + realized PnL - costs."""
        return self.cash + self.position * self.entry_price

    @property
    def margin_balance(self) -> float:
        """Binance margin balance = wallet balance + unrealized PnL."""
        return self.equity

    @property
    def position_notional(self) -> float:
        return abs(self.position) * self._mark

    @property
    def maintenance_margin(self) -> float:
        return maintenance_margin(self.position_notional, self.maintenance_tiers)

    @property
    def margin_ratio(self) -> float:
        if abs(self.position) <= _EPS:
            return 0.0
        balance = self.margin_balance
        return self.maintenance_margin / balance if balance > 0 else math.inf

    @property
    def liquidation_price(self) -> float | None:
        if abs(self.position) <= _EPS:
            return None
        return liquidation_price(
            1 if self.position > 0 else -1,
            abs(self.position),
            self.entry_price,
            self.wallet_balance,
            self.maintenance_tiers,
        )

    @property
    def open_orders(self) -> tuple[Order, ...]:
        return tuple(self._orders[cid] for cid in self._open)

    # -- replay pump -----------------------------------------------------

    def begin_bar(self, bar: Bar) -> None:
        self._bar = bar
        self._last_price = bar.open
        self._mark = bar.open

    def settle_funding(self, rate: float, price: float | None = None) -> float:
        if self.position == 0:
            return 0.0
        mark = price if price is not None else self._mark
        # Binance convention: a positive rate means longs pay shorts, so the
        # cash change is -position * mark * rate. ``funding_paid`` is signed:
        # positive when paying, negative when receiving.
        payment = self.position * mark * rate
        self.cash -= payment
        self.funding_paid += payment
        if payment:
            self.funding_events.append((self._bar.open_time if self._bar else None, payment))
        return payment

    def match(self) -> list[Fill]:
        if self.liquidated:
            return []
        if self._bar is None:
            raise RuntimeError("begin_bar() must be called before match()")
        produced: list[Fill] = []
        produced.extend(self._fill_pending_market())
        if self.intrabar:
            if self._bar.direction > 0:
                produced.extend(self._sweep(up=False))
                produced.extend(self._sweep(up=True))
            else:
                produced.extend(self._sweep(up=True))
                produced.extend(self._sweep(up=False))
        else:
            produced.extend(self._sweep(up=self._bar.direction > 0))
        return produced

    def check_liquidation(
        self,
        bar: Bar,
        *,
        mark_open: float | None = None,
        mark_high: float | None = None,
        mark_low: float | None = None,
        mark_close: float | None = None,
    ) -> LiquidationEvent | None:
        """Force-close the position if Binance-style maintenance is breached.

        The check uses the bar's extremes for the liquidation trigger (a gap
        through the liquidation price fills at the bar open, never at the
        better liquidation price) and also checks the bar close so a slow
        bleed is caught even if neither extreme is touched.
        """
        if not self.liquidation_enabled or self.liquidated or abs(self.position) <= _EPS:
            return None
        lp = self.liquidation_price
        if lp is None or lp <= 0:
            return None
        mark = self._mark
        if mark <= 0:
            return None
        open_px = mark_open if mark_open is not None else bar.open
        high_px = mark_high if mark_high is not None else bar.high
        low_px = mark_low if mark_low is not None else bar.low
        close_px = mark_close if mark_close is not None else bar.close
        long = self.position > 0
        fill_price: float | None = None
        reason = "maintenance_margin"
        if long:
            if open_px <= lp:
                fill_price, reason = open_px, "gap_through_liquidation"
            elif low_px <= lp:
                fill_price = lp
            elif close_px <= lp:
                fill_price = close_px
        else:
            if open_px >= lp:
                fill_price, reason = open_px, "gap_through_liquidation"
            elif high_px >= lp:
                fill_price = lp
            elif close_px >= lp:
                fill_price = close_px
        close_mark = close_px if close_px > 0 else mark
        wallet = self.wallet_balance
        close_margin_balance = wallet + self.position * (close_mark - self.entry_price)
        close_maintenance = maintenance_margin(abs(self.position) * close_mark, self.maintenance_tiers)
        if fill_price is None and close_margin_balance <= close_maintenance + 1e-9:
            fill_price, reason = close_mark, "maintenance_margin"
        if fill_price is None:
            return None
        return self._liquidate(fill_price, bar.close_time, reason)

    def _liquidate(self, fill_price: float, ts, reason: str) -> LiquidationEvent:
        qty = abs(self.position)
        entry = self.entry_price
        wallet = self.wallet_balance
        notional = qty * fill_price
        fee = notional * self.liquidation_fee
        pnl = self.position * (fill_price - entry)
        cash_after = wallet + pnl - fee
        # Cross margin can leave negative equity only when the price gaps
        # through the liquidation price / liquidation fails.  Binance's
        # insurance fund covers the first part of that shortfall; only the
        # uncovered part becomes the account's negative equity/bad debt.
        bad_debt = max(0.0, -cash_after)
        insurance_covered = min(bad_debt, self.insurance_fund_balance)
        uncovered_bad_debt = max(0.0, bad_debt - insurance_covered)
        cash_after = -uncovered_bad_debt
        event = LiquidationEvent(
            ts=ts,
            symbol=self.symbol,
            side="LONG" if self.position > 0 else "SHORT",
            qty=qty,
            entry_price=entry,
            liquidation_price=float(self.liquidation_price or fill_price),
            fill_price=fill_price,
            wallet_balance=wallet,
            maintenance_margin=maintenance_margin(notional, self.maintenance_tiers),
            margin_balance=wallet + pnl,
            fee=fee,
            bad_debt=bad_debt,
            insurance_covered=insurance_covered,
            uncovered_bad_debt=uncovered_bad_debt,
            reason=reason,
        )
        self.cancel_group("")
        for cid in list(self._open):
            self.cancel(cid)
        self._pending_market.clear()
        self.position = 0.0
        self.entry_price = 0.0
        self.cash = cash_after
        self.fees_paid += fee
        self._last_price = fill_price
        self._mark = fill_price
        self.liquidated = True
        self.liquidation = event
        self.fills.append(
            Fill(
                client_id="liquidation",
                symbol=self.symbol,
                side=Side.SELL if event.side == "LONG" else Side.BUY,
                qty=qty,
                price=fill_price,
                fee=fee,
                ts=ts,
                tag="liquidation",
                liquidity="TAKER",
            )
        )
        return event

    def end_bar(self) -> None:
        if self._bar is None:
            raise RuntimeError("begin_bar() must be called before end_bar()")
        self._last_price = self._bar.close
        self._mark = self._bar.close

    def mark(self, price: float) -> None:
        self._mark = price

    # -- matching internals ----------------------------------------------

    def _fill_pending_market(self) -> list[Fill]:
        if not self._pending_market:
            return []
        out: list[Fill] = []
        pending = list(self._pending_market)
        self._pending_market.clear()
        for cid in pending:
            if cid not in self._open:
                continue
            order = self._orders[cid]
            out.append(self._fill(order, self._bar.open, taker=True))
        return out

    def _sweep(self, up: bool) -> list[Fill]:
        out: list[Fill] = []
        for _ in range(self.max_fills_per_bar):
            candidate: Order | None = None
            for cid in self._open:
                order = self._orders[cid]
                if order.type is not OrderType.LIMIT:
                    continue
                if up:
                    if order.side is not Side.SELL or order.price > self._bar.high + _EPS:
                        continue
                    if candidate is None or order.price < candidate.price:
                        candidate = order
                else:
                    if order.side is not Side.BUY or order.price < self._bar.low - _EPS:
                        continue
                    if candidate is None or order.price > candidate.price:
                        candidate = order
            if candidate is None:
                break
            out.append(self._fill(candidate, candidate.price, taker=False))
        else:
            self.truncated_bars += 1
        return out

    def _fill(self, order: Order, price: float, *, taker: bool) -> Fill:
        qty = order.remaining
        rate = self.fees.taker_all_in if taker else self.fees.maker_all_in
        notional = qty * price
        fee = notional * rate
        signed = order.side.sign * qty
        if order.side is Side.BUY:
            self.cash -= notional + fee
        else:
            self.cash += notional - fee
        self.position += signed
        self._update_entry(order.side, qty, price)
        self.fees_paid += fee

        self._open.discard(order.client_id)
        order.status = OrderStatus.FILLED
        order.filled_qty = order.qty
        order.avg_price = price
        order.updated_at = self._bar.close_time
        fill = Fill(
            client_id=order.client_id,
            symbol=self.symbol,
            side=order.side,
            qty=qty,
            price=price,
            fee=fee,
            ts=self._bar.close_time,
            tag=order.tag,
            liquidity="TAKER" if taker else "MAKER",
        )
        self.fills.append(fill)
        self._last_price = price
        self._mark = price
        if self._sink is not None:
            self._sink(fill)
        return fill

    def _update_entry(self, side: Side, qty: float, price: float) -> None:
        signed = side.sign * qty
        prior = self.position - signed
        if abs(prior) < _EPS:
            self.entry_price = price
        elif prior * signed > 0:
            total = abs(prior) + qty
            self.entry_price = (self.entry_price * abs(prior) + price * qty) / total
        elif abs(self.position) < _EPS:
            self.entry_price = 0.0
        elif self.position * prior < 0:
            self.entry_price = price

    def _reduces_only(self, order: Order) -> bool:
        if self.position == 0:
            return False
        if order.side is Side.BUY and self.position >= 0:
            return False
        if order.side is Side.SELL and self.position <= 0:
            return False
        return order.qty <= abs(self.position) + self.filters.step_size / 2
