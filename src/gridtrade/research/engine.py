"""Event-driven replay: the same Strategy/OMS/port wiring as paper and live.

Bar n is completed, then the strategy acts and its orders become active for
bar n+1. Fills inside a bar are delivered immediately, so a strategy can place
the next adjacent order and be swept again within the same bar -- which is how
a real grid loses money in a fast move, and why the simulation is not allowed
to cheat by smoothing that away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..domain.models import Bar, Fill, Order
from ..execution.oms import OMS
from ..execution.simulated import SimExecution, SimFees
from ..risk.limits import DrawdownGuard, RiskEngine, RiskLimits
from ..strategy.base import Strategy, StrategyContext
from .dataset import Dataset
from .metrics import compute_stats


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    capital: float = 10_000.0
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005
    slip_bp: float = 0.2
    intrabar: bool = False
    stop_dd: float | None = 0.10
    liquidation_enabled: bool = True
    liquidation_fee: float = 0.005


@dataclass
class BacktestResult:
    symbol: str
    strategy_id: str
    equity: pd.Series
    fills: list[Fill] = field(default_factory=list)
    orders: tuple[Order, ...] = ()
    stats: dict = field(default_factory=dict)
    halted: bool = False
    final_position: float = 0.0
    strategy_state: dict = field(default_factory=dict)
    funding_events: list[tuple[datetime | None, float]] = field(default_factory=list)
    liquidation: dict | None = None

    def summary(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy_id,
            **self.stats,
            "final_position": round(self.final_position, 8),
            "liquidation": self.liquidation,
            "strategy_state": self.strategy_state,
        }


def default_risk_limits(capital: float, first_price: float) -> RiskLimits:
    return RiskLimits(
        max_position_qty=capital * 5.0 / first_price,
        max_order_notional=capital * 0.5,
        max_gross_notional=capital * 5.0,
        max_open_orders=200,
        max_submits_per_minute=120,
        max_price_deviation_bp=200.0,
    )


class ReplayEngine:
    def __init__(
        self,
        dataset: Dataset,
        strategy: Strategy,
        config: BacktestConfig | None = None,
        risk_limits: RiskLimits | None = None,
    ) -> None:
        if len(dataset.bars) == 0:
            raise ValueError("dataset has no bars")
        self.dataset = dataset
        self.strategy = strategy
        self.config = config or BacktestConfig()
        self.filters = dataset.filters
        self.port = SimExecution(
            dataset.symbol,
            self.filters,
            SimFees(
                maker=self.config.maker_fee,
                taker=self.config.taker_fee,
                slip_bp=self.config.slip_bp,
            ),
            self.config.capital,
            intrabar=self.config.intrabar,
            liquidation_enabled=self.config.liquidation_enabled,
            liquidation_fee=self.config.liquidation_fee,
        )
        first_price = float(dataset.bars["open"].iloc[0])
        self.risk = RiskEngine(risk_limits or default_risk_limits(self.config.capital, first_price))
        self.oms = OMS(self.port, self.risk, self.filters, dataset.symbol)
        self.oms.on_fill = self._on_fill
        self.guard = (
            DrawdownGuard(self.config.stop_dd) if self.config.stop_dd is not None else None
        )
        self._halted = False
        self._liquidation: dict | None = None

    def run(self) -> BacktestResult:
        rows = list(self.dataset.bars.itertuples(index=False))
        n = len(rows)
        equity = np.empty(n, dtype=float)
        inv_notional = 0.0
        turnover = 0.0

        first = rows[0]
        bar0 = self._bar(first)
        self.port.begin_bar(bar0)
        self.port.mark(bar0.open)
        start_ctx = self._ctx_ts(bar0.open_time, bar0.open)
        self.oms.sync(self.strategy.group, self.strategy.on_start(start_ctx), start_ctx)

        fund_times = list(self.dataset.funding["funding_time"])
        fund_rates = list(self.dataset.funding["funding_rate"])
        fi = 0

        for i, row in enumerate(rows):
            bar = self._bar(row)
            self.port.begin_bar(bar)
            while fi < len(fund_times) and fund_times[fi] <= bar.open_time:
                self.port.settle_funding(float(fund_rates[fi]), bar.open)
                fi += 1

            self.port.match()
            liquidation_event = self.port.check_liquidation(bar)
            self.port.end_bar()
            equity[i] = self.port.equity
            inv_notional += abs(self.port.position) * bar.close

            if liquidation_event is not None:
                self._halted = True
                self._liquidation = liquidation_event.as_dict()
                self.oms.cancel_group(self.strategy.group)
                continue
            if self.guard is not None:
                if self.guard.halted:
                    continue
                if self.guard.update(self.port.equity):
                    self._halt(bar)
                    continue

            ctx = self._ctx(bar)
            plan = self.strategy.on_bar(bar, ctx)
            self.oms.sync(self.strategy.group, plan, ctx)

        for fill in self.port.fills:
            turnover += abs(fill.qty * fill.price)

        series = pd.Series(equity, index=pd.DatetimeIndex(self.dataset.bars["open_time"]))
        stats = compute_stats(
            series,
            capital=self.config.capital,
            trades=len(self.port.fills),
            fees_paid=self.port.fees_paid,
            funding_paid=self.port.funding_paid,
            turnover=turnover,
            inv_notional_sum=inv_notional,
            bars=n,
            halted=self._halted,
            liquidated=self.port.liquidated,
            liquidation_price=(self._liquidation or {}).get("liquidation_price"),
            liquidation_time=(self._liquidation or {}).get("ts"),
        )
        return BacktestResult(
            symbol=self.dataset.symbol,
            strategy_id=self.strategy.strategy_id,
            equity=series,
            fills=list(self.port.fills),
            orders=self.oms.orders(),
            stats=stats,
            halted=self._halted,
            final_position=self.port.position,
            strategy_state=self.strategy.state(),
            funding_events=list(self.port.funding_events),
            liquidation=self._liquidation,
        )

    def _halt(self, bar: Bar) -> None:
        self._halted = True
        self.oms.cancel_group(self.strategy.group)
        self.oms.flatten(self.strategy.group, self._ctx(bar))

    def _on_fill(self, fill: Fill) -> None:
        if self._halted:
            return
        ctx = self._ctx_ts(fill.ts, self.port.mark_price)
        plan = self.strategy.on_fill(fill, ctx)
        if plan:
            self.oms.sync(self.strategy.group, plan, ctx)

    def _ctx(self, bar: Bar) -> StrategyContext:
        return self._ctx_ts(bar.close_time, bar.close)

    def _ctx_ts(self, now, mark: float) -> StrategyContext:
        return StrategyContext(
            symbol=self.dataset.symbol,
            now=now,
            mark_price=mark,
            position_qty=self.port.position_qty,
            equity=self.port.equity,
            filters=self.filters,
            open_orders=self.oms.open_orders(),
        )

    def _bar(self, row) -> Bar:
        return Bar(
            symbol=self.dataset.symbol,
            open_time=row.open_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(getattr(row, "volume", 0.0) or 0.0),
        )
