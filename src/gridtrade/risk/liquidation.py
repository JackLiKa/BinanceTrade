"""Binance-style USDⓈ-M margin and forced-liquidation math.

The simulator uses the same pieces Binance exposes for USDT-margined
perpetuals:

* maintenance margin tiers: ``maintenance = notional * mmr - maintenance_amount``
* cross/isolated margin balance: ``wallet_balance + unrealized_pnl``
* liquidation when margin balance reaches maintenance margin
* liquidation price derived from that equality
* a liquidation fee and a hard equity floor (bad debt is never allowed to
  become a recoverable negative balance)

The tier table is deliberately a *conservative* default rather than a promise
that it matches every symbol's live leverage bracket.  The exchange bracket
can be supplied per venue later; the formulas stay the same.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_EPS = 1e-12


@dataclass(frozen=True, slots=True)
class MaintenanceTier:
    """One Binance leverage-bracket row.

    ``notional_cap`` is the upper notional bound (inclusive).  ``mmr`` is the
    maintenance-margin rate.  ``maintenance_amount`` is Binance's cumulative
    maintenance amount (``cum``) for that tier.
    """

    notional_cap: float
    mmr: float
    maintenance_amount: float = 0.0


# Conservative low-notional USDT-M brackets.  Tier 1 is 2.5%, which is stricter
# than BTCUSDT but appropriate for the tokenized-equity perps used here.
DEFAULT_MAINTENANCE_TIERS: tuple[MaintenanceTier, ...] = (
    MaintenanceTier(50_000.0, 0.025, 0.0),
    MaintenanceTier(100_000.0, 0.030, 250.0),
    MaintenanceTier(500_000.0, 0.050, 2_250.0),
    MaintenanceTier(1_000_000.0, 0.100, 27_250.0),
    MaintenanceTier(math.inf, 0.125, 52_250.0),
)


def select_tier(notional: float, tiers: tuple[MaintenanceTier, ...] = DEFAULT_MAINTENANCE_TIERS) -> MaintenanceTier:
    value = abs(float(notional))
    for tier in tiers:
        if value <= tier.notional_cap + _EPS:
            return tier
    return tiers[-1]


def maintenance_margin(
    notional: float,
    tiers: tuple[MaintenanceTier, ...] = DEFAULT_MAINTENANCE_TIERS,
) -> float:
    value = abs(float(notional))
    if value <= 0:
        return 0.0
    tier = select_tier(value, tiers)
    return max(0.0, value * tier.mmr - tier.maintenance_amount)


def maintenance_rate(
    notional: float,
    tiers: tuple[MaintenanceTier, ...] = DEFAULT_MAINTENANCE_TIERS,
) -> float:
    value = abs(float(notional))
    if value <= 0:
        return 0.0
    return maintenance_margin(value, tiers) / value


def liquidation_price(
    side: int,
    qty: float,
    entry_price: float,
    wallet_balance: float,
    tiers: tuple[MaintenanceTier, ...] = DEFAULT_MAINTENANCE_TIERS,
) -> float | None:
    """Return the mark price at which margin balance == maintenance margin.

    ``side`` is +1 for long and -1 for short.  For one position this is the
    same equation Binance uses for cross margin (and for isolated margin when
    the isolated wallet is passed as ``wallet_balance``):

    long:  (qty*entry - wallet - maintenance_amount) / (qty*(1-mmr))
    short: (wallet + qty*entry + maintenance_amount) / (qty*(1+mmr))

    The tier can change as the liquidation price changes, so the tier is
    re-evaluated until it is stable (normally one or two iterations).
    """
    quantity = abs(float(qty))
    if quantity <= 0 or entry_price <= 0:
        return None
    sign = 1 if side >= 0 else -1
    notional_guess = quantity * max(entry_price, 1e-12)
    price: float | None = None
    for _ in range(8):
        tier = select_tier(notional_guess, tiers)
        if sign > 0:
            numerator = quantity * entry_price - wallet_balance - tier.maintenance_amount
            denominator = quantity * (1.0 - tier.mmr)
            price = numerator / denominator if denominator > 0 else None
        else:
            numerator = wallet_balance + quantity * entry_price + tier.maintenance_amount
            denominator = quantity * (1.0 + tier.mmr)
            price = numerator / denominator if denominator > 0 else None
        if price is None or price <= 0:
            return max(0.0, price) if price is not None else None
        next_notional = quantity * price
        if abs(next_notional - notional_guess) < 1e-9:
            return price
        notional_guess = next_notional
    return price


@dataclass(frozen=True, slots=True)
class LiquidationEvent:
    ts: object
    symbol: str
    side: str
    qty: float
    entry_price: float
    liquidation_price: float
    fill_price: float
    wallet_balance: float
    maintenance_margin: float
    margin_balance: float
    fee: float
    bad_debt: float
    reason: str

    def as_dict(self) -> dict:
        return {
            "ts": self.ts.isoformat() if hasattr(self.ts, "isoformat") else self.ts,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "liquidation_price": self.liquidation_price,
            "fill_price": self.fill_price,
            "wallet_balance": self.wallet_balance,
            "maintenance_margin": self.maintenance_margin,
            "margin_balance": self.margin_balance,
            "fee": self.fee,
            "bad_debt": self.bad_debt,
            "reason": self.reason,
        }
