"""Synthetic fixtures. Tests never read research/data so they stay hermetic."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from gridtrade.domain.models import Bar, SymbolFilters
from gridtrade.research.dataset import Dataset

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
FILTERS = SymbolFilters(tick_size=0.01, step_size=0.01, min_notional=5.0)


def make_bar(
    o: float,
    h: float,
    l: float,
    c: float,
    *,
    i: int = 0,
    volume: float = 100.0,
    symbol: str = "TESTUSDT",
    start: datetime = T0,
) -> Bar:
    return Bar(
        symbol=symbol,
        open_time=start + timedelta(minutes=i),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=volume,
    )


def make_dataset(
    rows: list[tuple[float, float, float, float]],
    *,
    funding: list[tuple[datetime, float]] | None = None,
    filters: SymbolFilters = FILTERS,
    symbol: str = "TESTUSDT",
    start: datetime = T0,
) -> Dataset:
    times = [start + timedelta(minutes=i) for i in range(len(rows))]
    bars = pd.DataFrame(
        {
            "open_time": pd.to_datetime(times, utc=True),
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [100.0] * len(rows),
        }
    )
    if funding:
        fund = pd.DataFrame(
            {
                "funding_time": pd.to_datetime([f[0] for f in funding], utc=True),
                "funding_rate": [f[1] for f in funding],
            }
        )
    else:
        fund = pd.DataFrame(
            {
                "funding_time": pd.Series([], dtype="datetime64[ns, UTC]"),
                "funding_rate": pd.Series([], dtype=float),
            }
        )
    return Dataset(symbol=symbol, bars=bars, funding=fund, filters=filters, meta={})


def gbm_rows(
    days: int = 30,
    *,
    sigma_daily: float = 0.0184,
    start: float = 100.0,
    seed: int = 0,
    drift_daily: float = 0.0,
) -> list[tuple[float, float, float, float]]:
    """Zero-drift GBM with per-minute vol matched to a daily figure."""
    n = days * 1440
    rng = np.random.default_rng(seed)
    step_sigma = sigma_daily / math.sqrt(1440)
    close = start * np.exp(np.cumsum(rng.normal(drift_daily / n, step_sigma, n)))
    open_ = np.concatenate([[start], close[:-1]])
    wick = np.abs(rng.normal(0.0, 2e-4, n))
    high = np.maximum(open_, close) * (1.0 + wick)
    low = np.minimum(open_, close) * (1.0 - wick)
    return list(zip(open_.tolist(), high.tolist(), low.tolist(), close.tolist()))
