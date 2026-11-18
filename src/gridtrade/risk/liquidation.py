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


# Fallback table copied from Binance's low-notional bracket shape (the
# GOOGLUSDT bracket observed on 2026-11-18).  The API path should replace it
# with the live ``/fapi/v1/leverageBracket`` response for the actual symbol.
DEFAULT_MAINTENANCE_TIERS: tuple[MaintenanceTier, ...] = (
    MaintenanceTier(50_000.0, 0.010, 0.0),
    MaintenanceTier(200_000.0, 0.020, 500.0),
    MaintenanceTier(400_000.0, 0.025, 1_500.0),
    MaintenanceTier(1_000_000.0, 0.0333, 4_820.0),
    MaintenanceTier(5_000_000.0, 0.050, 21_520.0),
    MaintenanceTier(15_000_000.0, 0.100, 271_520.0),
    MaintenanceTier(1e18, 0.250, 2_521_520.0),
)


def tiers_from_brackets(rows: list[dict]) -> tuple[MaintenanceTier, ...]:
    """Convert Binance ``/fapi/v1/leverageBracket`` rows to our tier table."""
    tiers: list[MaintenanceTier] = []
    for row in rows:
        try:
            cap = float(row.get("notional_cap", row.get("notionalCap", 0)) or 0)
            mmr = float(row.get("mmr", row.get("maintMarginRatio", 0)) or 0)
            cum = float(row.get("cum", 0) or 0)
        except (TypeError, ValueError):
            continue
        if mmr <= 0:
            continue
        tiers.append(MaintenanceTier(cap if cap > 0 else 1e18, mmr, cum))
    if not tiers:
        return DEFAULT_MAINTENANCE_TIERS
    tiers.sort(key=lambda tier: tier.notional_cap)
    if tiers[-1].notional_cap < 1e17:
        tiers.append(MaintenanceTier(1e18, tiers[-1].mmr, tiers[-1].maintenance_amount))
    return tuple(tiers)


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


def cross_liquidation_price(
    side: int,
    qty: float,
    entry_price: float,
    wallet_balance: float,
    other_maintenance: float = 0.0,
    other_unpnl: float = 0.0,
    cum: float = 0.0,
    mmr: float = 0.0,
) -> float | None:
    """Binance cross-margin liquidation price for one contract.

    Official form (one-way mode):

    LP1 = (WB - TMM1 + UPNL1 + cum - Side1*Position1*EP1)
          / (Position1*MMR - Side1*Position1)

    ``other_maintenance`` is TMM1, ``other_unpnl`` is UPNL1; for isolated or a
    single-symbol account both are zero.
    """
    position = abs(float(qty))
    if position <= 0 or entry_price <= 0:
        return None
    sign = 1 if side >= 0 else -1
    numerator = (
        wallet_balance
        - other_maintenance
        + other_unpnl
        + cum
        - sign * position * entry_price
    )
    denominator = position * mmr - sign * position
    if abs(denominator) < _EPS:
        return None
    price = numerator / denominator
    return price if price > 0 else None


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
