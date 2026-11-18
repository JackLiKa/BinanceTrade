from __future__ import annotations

import math

import numpy as np
import pandas as pd


def compute_stats(
    equity: pd.Series,
    *,
    capital: float,
    trades: int,
    fees_paid: float,
    funding_paid: float,
    turnover: float,
    inv_notional_sum: float,
    bars: int,
    halted: bool,
    liquidated: bool = False,
    liquidation_price: float | None = None,
    liquidation_time: str | None = None,
    bad_debt: float = 0.0,
) -> dict:
    if len(equity) == 0:
        return {"total_return": 0.0, "ann_return": 0.0, "max_dd": 0.0, "sharpe": 0.0}

    final = float(equity.iloc[-1])
    total = final / capital - 1.0
    span_days = (equity.index[-1] - equity.index[0]).total_seconds() / 86400
    years = max(span_days / 365.25, 1e-9)
    ann = (1.0 + total) ** (1.0 / years) - 1.0 if total > -1.0 else -1.0

    peak = equity.cummax()
    # Account-equity drawdown is deliberately NOT capped at 100%: cross
    # margin can produce negative equity after a gap through the liquidation
    # price.  That is bad debt, not a recoverable return.
    max_dd = float((1.0 - equity / peak).max())

    daily = equity.resample("1D").last().dropna()
    dret = daily.pct_change().dropna()
    sharpe = 0.0
    if len(dret) > 2 and dret.std() > 0:
        sharpe = float(dret.mean() / dret.std() * math.sqrt(365))

    return {
        "total_return": round(total * 100, 2),
        "ann_return": round(ann * 100, 2),
        "max_dd": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "final_equity": round(final, 2),
        "trades": int(trades),
        "fees": round(fees_paid, 2),
        "funding": round(funding_paid, 2),
        "funding_pct_of_capital": round(funding_paid / capital * 100, 2),
        "turnover_x": round(turnover / capital, 2),
        "avg_inventory_pct": round(inv_notional_sum / max(bars, 1) / capital * 100, 2),
        "halted": bool(halted),
        "liquidated": bool(liquidated),
        "liquidation_price": liquidation_price,
        "liquidation_time": liquidation_time,
        "bad_debt": round(float(bad_debt), 2),
        "bad_debt_pct": round(float(bad_debt) / capital * 100, 2) if capital else 0.0,
    }
