"""Shared research entry points for the CLI, API and tests.

The API must be able to reproduce exactly what the CLI reports, so both call
these functions instead of duplicating the risk-limit and walk-forward logic.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from ..risk.limits import RiskLimits
from ..risk.liquidation import MaintenanceTier
from ..strategy.grid import GridParams, GridStrategy
from .dataset import Dataset
from .engine import BacktestConfig, BacktestResult, ReplayEngine


@dataclass(frozen=True, slots=True)
class ResearchParams:
    capital: float = 10_000.0
    spacing_bp: float = 120.0
    levels: int = 30
    leverage: float = 0.5
    reanchor_bars: int | None = None
    stop_dd: float | None = 0.10
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    slip_bp: float = 0.2
    intrabar: bool = False
    liquidation_enabled: bool = True
    liquidation_fee: float = 0.005
    insurance_fund_balance: float = 0.0
    maintenance_tiers: tuple[MaintenanceTier, ...] | None = None

    def grid_params(self) -> GridParams:
        return GridParams(
            spacing_bp=self.spacing_bp,
            levels=self.levels,
            leverage=self.leverage,
            reanchor_bars=self.reanchor_bars,
        )

    def backtest_config(self) -> BacktestConfig:
        return BacktestConfig(
            capital=self.capital,
            maker_fee=self.maker_fee,
            taker_fee=self.taker_fee,
            slip_bp=self.slip_bp,
            intrabar=self.intrabar,
            stop_dd=self.stop_dd,
            liquidation_enabled=self.liquidation_enabled,
            liquidation_fee=self.liquidation_fee,
            insurance_fund_balance=self.insurance_fund_balance,
            maintenance_tiers=self.maintenance_tiers,
        )


def risk_limits_for(capital: float, price0: float, params: GridParams) -> RiskLimits:
    size = capital * params.leverage / params.levels / price0
    # The full ladder at either extreme is ~1.17x capital; the cap must clear
    # that or the last levels get rejected and the replay quietly shrinks.
    return RiskLimits(
        max_position_qty=size * params.levels * 1.05,
        max_order_notional=size * price0 * 3.0,
        max_gross_notional=capital * params.leverage * 1.3,
        max_open_orders=max(params.levels * 2, 10),
        max_submits_per_minute=120,
        max_price_deviation_bp=params.spacing_bp * (params.levels + 2) * 2.0,
    )


def run_replay(dataset: Dataset, params: ResearchParams) -> BacktestResult:
    if len(dataset.bars) == 0:
        raise ValueError("dataset has no bars")
    grid = params.grid_params()
    strategy = GridStrategy(dataset.symbol, grid)
    limits = risk_limits_for(params.capital, float(dataset.bars["open"].iloc[0]), grid)
    return ReplayEngine(dataset, strategy, params.backtest_config(), limits).run()


def monthly_slices(dataset: Dataset, *, min_days: int = 5) -> list[tuple[str, Dataset]]:
    if len(dataset.bars) == 0:
        return []
    months = sorted(
        dataset.bars["open_time"].dt.tz_localize(None).dt.to_period("M").unique()
    )
    out: list[tuple[str, Dataset]] = []
    for month in months:
        start = pd.Timestamp(month.start_time, tz="UTC")
        end = pd.Timestamp(month.end_time, tz="UTC") + pd.Timedelta(minutes=1)
        sub = dataset.slice(start, end)
        if len(sub.bars) >= min_days * 1440:
            out.append((str(month), sub))
    return out


def walkforward(
    dataset: Dataset,
    params: ResearchParams,
    *,
    min_days: int = 5,
    progress=None,
) -> dict:
    """Fresh anchor and flat inventory at each month open, capital reset."""
    slices = monthly_slices(dataset, min_days=min_days)
    rows: list[dict] = []
    for done, (month, sub) in enumerate(slices, start=1):
        result = run_replay(sub, params)
        rows.append(
            {
                "month": month,
                "ret": result.stats["total_return"],
                "dd": result.stats["max_dd"],
                "trades": result.stats["trades"],
                "fees": result.stats["fees"],
                "funding": result.stats["funding"],
                "halted": result.stats["halted"],
                "liquidated": result.stats.get("liquidated", False),
            }
        )
        if progress is not None:
            progress(done / len(slices), f"{done}/{len(slices)} months")
    if not rows:
        return {
            "rows": [],
            "summary": {
                "months": 0,
                "total_return": 0.0,
                "mean": 0.0,
                "median": 0.0,
                "worst": 0.0,
                "best": 0.0,
                "positive": 0,
                "stops": 0,
            },
        }

    frame = pd.DataFrame(rows)
    compounded = float((1.0 + frame["ret"] / 100.0).prod() - 1.0)
    summary = {
        "months": len(rows),
        "total_return": round(compounded * 100, 2),
        "mean": round(float(frame["ret"].mean()), 2),
        "median": round(float(frame["ret"].median()), 2),
        "worst": round(float(frame["ret"].min()), 2),
        "best": round(float(frame["ret"].max()), 2),
        "positive": int((frame["ret"] > 0).sum()),
        "stops": int(frame["halted"].sum()),
    }
    return {"rows": rows, "summary": summary}


def sweep(
    dataset: Dataset,
    base: ResearchParams,
    *,
    spacings: tuple[float, ...] = (60.0, 90.0, 120.0),
    levels: tuple[int, ...] = (20, 30),
    leverages: tuple[float, ...] = (0.5, 1.0),
    progress=None,
) -> list[dict]:
    combos = [
        (spacing, level, leverage)
        for spacing in spacings
        for level in levels
        for leverage in leverages
    ]
    rows: list[dict] = []
    for done, (spacing, level, leverage) in enumerate(combos, start=1):
        params = replace(
            base, spacing_bp=spacing, levels=level, leverage=leverage
        )
        result = run_replay(dataset, params)
        rows.append(
            {
                "spacing_bp": spacing,
                "levels": level,
                "leverage": leverage,
                "ann_return": result.stats["ann_return"],
                "total_return": result.stats["total_return"],
                "sharpe": result.stats["sharpe"],
                "max_dd": result.stats["max_dd"],
                "trades": result.stats["trades"],
                "fees": result.stats["fees"],
                "funding": result.stats["funding"],
                "halted": result.stats["halted"],
                "liquidated": result.stats.get("liquidated", False),
            }
        )
        if progress is not None:
            progress(done / len(combos), f"{len(rows)}/{len(combos)}")
    return rows
