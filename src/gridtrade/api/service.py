"""Research-facing operations and chart-ready payloads for the HTTP API.

The CLI and the API share ``research.runner`` so a run started from the panel
produces the same numbers as the command line. Everything returned here is
derived from local Parquet datasets or the engine's own result objects.
"""

from __future__ import annotations

import asyncio
import math
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np
import pandas as pd

from ..research.dataset import Dataset
from ..risk.liquidation import MaintenanceTier, tiers_from_brackets
from ..research.runner import (
    ResearchParams,
    risk_limits_for,
    run_replay,
    sweep,
    walkforward,
)
from ..strategy.grid import GridParams
from .live import LiveMarket

INTERVALS: dict[str, str | None] = {
    "1m": None,
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
MAX_FILLS = 5_000


def _iso(ts: Any) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    if isinstance(ts, str):
        return ts
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.isoformat().replace("+00:00", "Z")


def _epoch(ts: Any) -> int:
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return int(stamp.timestamp())


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class ResearchService:
    def __init__(self, data_dir: str | Path, live: LiveMarket) -> None:
        self.data_dir = Path(data_dir)
        self.live = live
        self._cache: dict[str, tuple[float, Dataset]] = {}
        self._lock = threading.Lock()

    # -- datasets ---------------------------------------------------------

    def symbols(self) -> list[str]:
        return sorted(path.name[: -len("_1m.parquet")] for path in self.data_dir.glob("*_1m.parquet"))

    def _binance_risk(self, symbol: str, params: ResearchParams) -> ResearchParams:
        """Use the symbol's real Binance leverage bracket/fee when reachable.

        If the Tokyo node is unavailable, keep the fallback bracket and make the
        artifact's params show that no live bracket was applied.
        """
        if not self.live.node_url:
            return params
        try:
            with httpx.Client(
                base_url=self.live.node_url,
                timeout=httpx.Timeout(6.0, connect=2.0),
                headers={"User-Agent": "gridtrade/0.1 research-risk"},
            ) as client:
                bracket_response = client.get(
                    "/market/leverage-bracket", params={"symbol": symbol}
                )
                bracket_response.raise_for_status()
                bracket_payload = bracket_response.json()
                rows = bracket_payload.get("brackets") or []
                tiers = tiers_from_brackets(rows)
                fee = params.liquidation_fee
                insurance = params.insurance_fund_balance
                try:
                    insurance_response = client.get(
                        "/market/insurance-balance", params={"symbol": symbol}
                    )
                    insurance_response.raise_for_status()
                    assets = (insurance_response.json() or {}).get("assets") or []
                    usdt = next(
                        (row for row in assets if str(row.get("asset", "")).upper() == "USDT"),
                        None,
                    )
                    if usdt:
                        insurance = float(usdt.get("marginBalance") or 0.0)
                except (ValueError, TypeError, httpx.HTTPError):
                    pass
                try:
                    contract_response = client.get(
                        "/market/contract", params={"symbol": symbol}
                    )
                    contract_response.raise_for_status()
                    raw_fee = (contract_response.json() or {}).get("liquidation_fee")
                    if raw_fee is not None and float(raw_fee) >= 0:
                        fee = float(raw_fee)
                except (ValueError, TypeError, httpx.HTTPError):
                    pass
                if rows:
                    return replace(
                        params,
                        maintenance_tiers=tiers,
                        liquidation_fee=fee,
                        insurance_fund_balance=insurance,
                    )
        except (ValueError, TypeError, httpx.HTTPError):
            return params
        return params

    def _mtime(self, symbol: str) -> float:
        stamps = []
        for suffix in ("_1m.parquet", "_funding.parquet", "_meta.json"):
            path = self.data_dir / f"{symbol}{suffix}"
            if path.exists():
                stamps.append(path.stat().st_mtime)
        return max(stamps) if stamps else 0.0

    def dataset(self, symbol: str) -> Dataset:
        if symbol not in self.symbols():
            raise KeyError(symbol)
        mtime = self._mtime(symbol)
        with self._lock:
            cached = self._cache.get(symbol)
            if cached is not None and cached[0] >= mtime:
                return cached[1]
            dataset = Dataset.load(self.data_dir, symbol)
            self._cache[symbol] = (mtime, dataset)
            return dataset

    def dataset_quality(self, symbol: str) -> dict[str, Any]:
        dataset = self.dataset(symbol)
        quality = dataset.quality()
        meta = dataset.meta or {}
        filters = dataset.filters
        quality["filters"] = {
            "tick_size": filters.tick_size,
            "step_size": filters.step_size,
            "min_notional": filters.min_notional,
            "max_orders": filters.max_orders,
        }
        quality["contract"] = {
            "contract_type": meta.get("contract_type"),
            "underlying_type": meta.get("underlying_type"),
            "onboard": _iso(pd.Timestamp(meta["onboard"], unit="ms"))
            if meta.get("onboard")
            else None,
            "funding_interval_hours": meta.get("funding_interval_hours"),
        }
        quality["schedule"] = self._schedule(meta)

        bars = dataset.bars
        gaps = bars["open_time"].diff().dt.total_seconds().div(60).dropna()
        expected = int(quality["expected_bars"])
        quality.update(
            {
                "coverage_pct": round(100.0 * quality["bars"] / expected, 3) if expected else None,
                "gap_count": int((gaps > 1).sum()),
                "median_gap_minutes": round(float(gaps.median()), 2) if len(gaps) else None,
                "price_min": round(float(bars["low"].min()), 4),
                "price_max": round(float(bars["high"].max()), 4),
                "last_close": round(float(bars["close"].iloc[-1]), 4),
                "bytes": sum(
                    path.stat().st_size
                    for path in (
                        self.data_dir / f"{symbol}_1m.parquet",
                        self.data_dir / f"{symbol}_funding.parquet",
                    )
                    if path.exists()
                ),
            }
        )
        return quality

    def _schedule(self, meta: dict[str, Any]) -> dict[str, Any]:
        markets = (meta.get("trading_schedule") or {}).get("marketSchedules") or {}
        sessions: list[dict[str, Any]] = []
        for market, payload in markets.items():
            for session in (payload or {}).get("sessions", [])[:400]:
                start = session.get("startTime")
                end = session.get("endTime")
                if not start or not end:
                    continue
                sessions.append(
                    {
                        "market": market,
                        "start": _iso(pd.Timestamp(start, unit="ms")),
                        "end": _iso(pd.Timestamp(end, unit="ms")),
                        "type": session.get("type", "UNKNOWN"),
                    }
                )
        sessions.sort(key=lambda item: item["start"] or "")
        no_trading = [item for item in sessions if item["type"] != "REGULAR"][-12:]
        return {
            "sessions": len(sessions),
            "no_trading_recent": no_trading,
            "markets": sorted(markets),
        }

    # -- market data ------------------------------------------------------

    async def market_snapshot(self, symbol: str) -> dict[str, Any]:
        snapshot = await self.live.snapshot(symbol)
        interval = None
        try:
            dataset = await asyncio.to_thread(self.dataset, symbol)
            interval = (dataset.meta or {}).get("funding_interval_hours")
        except KeyError:
            dataset = None
        if snapshot.get("source") in {"binance", "node"}:
            snapshot["funding_interval_hours"] = interval
            return snapshot

        if dataset is None or len(dataset.bars) == 0:
            return snapshot

        bars = dataset.bars
        last = bars.iloc[-1]
        close = float(last["close"])
        window = bars[bars["open_time"] >= last["open_time"] - pd.Timedelta(hours=24)]
        first_close = float(window["open"].iloc[0]) if len(window) else close
        return {
            **snapshot,
            "mark_price": close,
            "last_price": close,
            "change_24h_pct": round((close / first_close - 1) * 100, 3) if first_close else None,
            "high_24h": float(window["high"].max()) if len(window) else None,
            "low_24h": float(window["low"].min()) if len(window) else None,
            "volume_24h": float(window["volume"].sum()) if len(window) else None,
            "quote_volume_24h": None,
            "last_funding_rate": float(dataset.funding["funding_rate"].iloc[-1])
            if len(dataset.funding)
            else None,
            "next_funding_time": None,
            "funding_interval_hours": interval,
            "as_of": _iso(last["open_time"]),
            "bar_age_minutes": int(
                (pd.Timestamp.now(tz="UTC") - pd.Timestamp(last["open_time"]).tz_convert("UTC"))
                .total_seconds()
                // 60
            ),
            "source": "dataset",
        }

    def candles(
        self,
        symbol: str,
        *,
        interval: str,
        limit: int,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        if interval not in INTERVALS:
            raise ValueError(f"unsupported interval {interval}")
        dataset = self.dataset(symbol)
        bars = dataset.bars
        mask = pd.Series(True, index=bars.index)
        if start:
            mask &= bars["open_time"] >= pd.Timestamp(start, tz="UTC")
        if end:
            mask &= bars["open_time"] <= pd.Timestamp(end, tz="UTC")
        frame = bars.loc[mask, ["open_time", "open", "high", "low", "close", "volume"]]
        rule = INTERVALS[interval]
        if rule and len(frame):
            frame = (
                frame.set_index("open_time")
                .resample(rule, label="left", closed="left")
                .agg(
                    open=("open", "first"),
                    high=("high", "max"),
                    low=("low", "min"),
                    close=("close", "last"),
                    volume=("volume", "sum"),
                )
                .dropna(subset=["open"])
                .reset_index()
            )
        frame = frame.tail(limit)
        points = [
            [
                _epoch(row.open_time),
                round(float(row.open), 8),
                round(float(row.high), 8),
                round(float(row.low), 8),
                round(float(row.close), 8),
                round(float(row.volume), 4),
            ]
            for row in frame.itertuples(index=False)
        ]
        return {
            "symbol": symbol,
            "interval": interval,
            "count": len(points),
            "from": points[0][0] if points else None,
            "to": points[-1][0] if points else None,
            "candles": points,
        }

    async def market_candles(
        self,
        symbol: str,
        *,
        interval: str,
        limit: int,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """K-lines with the freshest available source.

        The Tokyo node can reach Binance while this host often cannot, so when a
        node is configured and no explicit historical window is requested we ask
        it for real-time bars and only then fall back to the local dataset.
        """
        if self.live.node_enabled and not start and not end:
            live = await self.live.node_candles(symbol, interval, limit)
            if live is not None:
                return live
        return await asyncio.to_thread(
            self.candles, symbol, interval=interval, limit=limit, start=start, end=end
        )

    async def market_funding(self, symbol: str, *, limit: int = 300) -> dict[str, Any]:
        if self.live.node_enabled:
            live = await self.live.node_funding(symbol, limit)
            if live is not None:
                points = live["funding"]
                rates = [float(row[1]) for row in points if len(row) > 1]
                interval = 8.0
                per_day = 24.0 / interval
                mean = sum(rates) / len(rates) if rates else 0.0
                ordered = sorted(rates)
                if ordered:
                    middle = len(ordered) // 2
                    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
                else:
                    median = 0.0
                last = (
                    datetime.fromtimestamp(int(points[-1][0]), tz=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                    if points
                    else None
                )
                summary = {
                    "count": len(rates),
                    "mean_rate": round(mean, 8),
                    "median_rate": round(median, 8),
                    "positive_pct": round(sum(1 for rate in rates if rate > 0) / len(rates) * 100, 1) if rates else 0.0,
                    "annualized_pct": round(mean * per_day * 365 * 100, 2),
                    "interval_hours": interval,
                    "last": last,
                }
                return {
                    "symbol": symbol,
                    "count": len(points),
                    "funding": points,
                    "summary": summary,
                    "source": "node",
                }
        return await asyncio.to_thread(self.funding, symbol, limit=limit)

    def funding(self, symbol: str, *, limit: int = 300) -> dict[str, Any]:
        dataset = self.dataset(symbol)
        frame = dataset.funding.tail(max(1, min(limit, 2_000)))
        has_mark = "mark_price" in frame.columns
        points = []
        for row in frame.itertuples(index=False):
            points.append(
                [
                    _epoch(row.funding_time),
                    round(float(row.funding_rate), 10),
                    round(float(getattr(row, "mark_price", 0.0)), 8) if has_mark else None,
                ]
            )
        rates = frame["funding_rate"].astype(float)
        interval = float((dataset.meta or {}).get("funding_interval_hours") or 8)
        per_day = 24.0 / interval if interval > 0 else 3.0
        summary = {
            "count": int(len(rates)),
            "mean_rate": round(float(rates.mean()), 8) if len(rates) else 0.0,
            "median_rate": round(float(rates.median()), 8) if len(rates) else 0.0,
            "positive_pct": round(float((rates > 0).mean() * 100), 1) if len(rates) else 0.0,
            "annualized_pct": round(float(rates.mean() * per_day * 365 * 100), 2)
            if len(rates)
            else 0.0,
            "interval_hours": interval,
            "last": _iso(dataset.funding["funding_time"].iloc[-1]) if len(frame) else None,
        }
        return {"symbol": symbol, "summary": summary, "funding": points}

    # -- jobs -------------------------------------------------------------

    def _slice(self, symbol: str, start: str | None, end: str | None) -> Dataset:
        dataset = self.dataset(symbol)
        if start or end:
            dataset = dataset.slice(start, end)
        if len(dataset.bars) == 0:
            raise ValueError("selected date range has no bars")
        return dataset

    def replay_job(
        self, symbol: str, params: ResearchParams, start: str | None = None, end: str | None = None
    ) -> Callable:
        def run(progress) -> dict[str, Any]:
            started = datetime.now(timezone.utc)
            progress(0.05, "loading dataset")
            dataset = self._slice(symbol, start, end)
            progress(0.12, f"{len(dataset.bars):,} bars")
            risk_params = self._binance_risk(dataset.symbol, params)
            result = run_replay(dataset, risk_params)
            progress(0.82, "packing artifacts")
            artifact = replay_artifact(dataset, risk_params, result, started)
            progress(0.95, "writing")
            return artifact

        return run

    def walkforward_job(
        self,
        symbol: str,
        params: ResearchParams,
        min_days: int,
        start: str | None = None,
        end: str | None = None,
    ) -> Callable:
        def run(progress) -> dict[str, Any]:
            started = datetime.now(timezone.utc)
            progress(0.04, "loading dataset")
            dataset = self._slice(symbol, start, end)
            risk_params = self._binance_risk(dataset.symbol, params)
            report = walkforward(
                dataset,
                risk_params,
                min_days=min_days,
                progress=lambda value, message: progress(0.05 + value * 0.82, message),
            )
            progress(0.9, "packing artifacts")
            return walkforward_artifact(dataset, risk_params, report, min_days, started)

        return run

    def sweep_job(
        self,
        symbol: str,
        params: ResearchParams,
        axes: dict[str, Any],
        start: str | None = None,
        end: str | None = None,
    ) -> Callable:
        def run(progress) -> dict[str, Any]:
            started = datetime.now(timezone.utc)
            progress(0.04, "loading dataset")
            dataset = self._slice(symbol, start, end)
            rows = sweep(
                dataset,
                params,
                spacings=tuple(axes["spacings"]),
                levels=tuple(axes["levels"]),
                leverages=tuple(axes["leverages"]),
                progress=lambda value, message: progress(0.05 + value * 0.82, message),
            )
            rows.sort(key=lambda row: row["ann_return"], reverse=True)
            progress(0.9, "packing artifacts")
            return sweep_artifact(dataset, params, rows, axes, started)

        return run

    def risk_profile(self, capital: float, symbol: str, params: GridParams) -> dict[str, Any]:
        dataset = self.dataset(symbol)
        price = float(dataset.bars["close"].iloc[-1])
        limits = risk_limits_for(capital, price, params)
        return {
            "price": price,
            "limits": asdict(limits),
            "unit_notional": round(capital * params.leverage / params.levels, 2),
            "max_gross_leverage": round(limits.max_gross_notional / capital, 2),
            "ladder_extreme_notional": round(
                capital * params.leverage * (params.levels + 1) / (2 * params.levels), 2
            ),
        }


# -- payload builders ------------------------------------------------------


def _downsample(times: np.ndarray, values: np.ndarray, cap: int) -> np.ndarray:
    n = len(values)
    if n <= cap:
        return np.arange(n)
    stride = math.ceil(n / cap)
    index = np.arange(0, n, stride)
    if index[-1] != n - 1:
        index = np.append(index, n - 1)
    return index


def _downsample_min(times: np.ndarray, values: np.ndarray, cap: int) -> np.ndarray:
    n = len(values)
    if n <= cap:
        return np.arange(n)
    size = math.ceil(n / cap)
    trimmed = n - n % size
    picks = [0]
    if trimmed:
        block = values[:trimmed].reshape(-1, size)
        offsets = np.argmin(block, axis=1) + np.arange(0, trimmed, size)
        picks.extend(int(offset) for offset in offsets)
    if trimmed < n:
        picks.append(int(np.argmin(values[trimmed:]) + trimmed))
    if picks[-1] != n - 1:
        picks.append(n - 1)
    return np.unique(picks)


def _month_rows(result, capital: float) -> list[dict[str, Any]]:
    equity = result.equity
    fills: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for fill in result.fills:
        stamp = pd.Timestamp(fill.ts)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        key = stamp.tz_convert("UTC").strftime("%Y-%m")
        slot = fills[key]
        slot[0] += 1
        slot[1] += abs(fill.fee)

    funding: dict[str, float] = defaultdict(float)
    for stamp, payment in getattr(result, "funding_events", []):
        if stamp is None:
            continue
        funding[pd.Timestamp(stamp).strftime("%Y-%m")] += float(payment)

    rows: list[dict[str, Any]] = []
    previous = capital
    periods = list(equity.groupby(equity.index.tz_localize(None).to_period("M")))
    for position, (period, series) in enumerate(periods):
        last = float(series.iloc[-1])
        peak = series.cummax()
        drawdown = (
            float((1.0 - series / peak.replace(0, np.nan)).max() * 100)
            if float(peak.max()) > 0
            else 0.0
        )
        key = str(period)
        trades, fees = fills.get(key, [0, 0.0])
        rows.append(
            {
                "month": key,
                "ret": round((last / previous - 1.0) * 100, 2) if previous else 0.0,
                "dd": round(drawdown, 2),
                "trades": int(trades),
                "fees": round(fees, 2),
                "funding": round(funding.get(key, 0.0), 2),
                "funding_income": round(-funding.get(key, 0.0), 2),
                "halted": bool(result.halted and position == len(periods) - 1),
            }
        )
        previous = last
    return rows


def replay_artifact(
    dataset: Dataset,
    params: ResearchParams,
    result,
    started: datetime,
) -> dict[str, Any]:
    equity = result.equity
    values = equity.to_numpy(dtype=float)
    times = equity.index.asi8 // 1_000_000_000
    index = _downsample(times, values, 1_200)
    equity_points = [
        [_epoch(equity.index[i]), round(float(values[i]), 2)] for i in index
    ]

    peak = np.maximum.accumulate(values)
    drawdown = (values / peak - 1.0) * 100.0
    dd_index = _downsample_min(times, drawdown, 900)
    dd_points = [
        [_epoch(equity.index[i]), round(float(drawdown[i]), 2)] for i in dd_index
    ]

    fills = sorted(result.fills, key=lambda fill: pd.Timestamp(fill.ts))
    truncated = len(fills) > MAX_FILLS
    if truncated:
        fills = fills[-MAX_FILLS:]
    fill_rows = [
        {
            "ts": _iso(fill.ts),
            "side": fill.side.value,
            "qty": round(float(fill.qty), 8),
            "price": round(float(fill.price), 8),
            "fee": round(float(fill.fee), 6),
            "tag": fill.tag,
            "liquidity": fill.liquidity,
            "client_id": fill.client_id,
        }
        for fill in fills
    ]

    counts = Counter(order.status.value for order in result.orders)
    reasons = Counter(
        order.reason for order in result.orders if order.status.value == "REJECTED" and order.reason
    )
    open_orders = [
        {
            "client_id": order.client_id,
            "side": order.side.value,
            "type": order.type.value,
            "qty": round(float(order.qty), 8),
            "price": round(float(order.price), 8) if order.price else None,
            "filled_qty": round(float(order.filled_qty), 8),
            "tag": order.tag,
            "status": order.status.value,
        }
        for order in result.orders
        if order.is_open
    ][:60]

    stats = dict(result.stats)
    stats.update(
        {
            "final_position": round(float(result.final_position), 8),
            "strategy_state": result.strategy_state,
            "bars": int(len(dataset.bars)),
            "start": _iso(dataset.bars["open_time"].iloc[0]),
            "end": _iso(dataset.bars["open_time"].iloc[-1]),
        }
    )

    return {
        "kind": "replay",
        "meta": {
            "symbol": dataset.symbol,
            "params": asdict(params),
            "generated_at": started.isoformat(timespec="seconds"),
            "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
            "bars": int(len(dataset.bars)),
            "start": _iso(dataset.bars["open_time"].iloc[0]),
            "end": _iso(dataset.bars["open_time"].iloc[-1]),
        },
        "summary": stats,
        "capital": params.capital,
        "equity": {
            "points": equity_points,
            "sampled_from": int(len(equity)),
            "first": equity_points[0][0] if equity_points else None,
            "last": equity_points[-1][0] if equity_points else None,
        },
        "drawdown": {"points": dd_points},
        "months": _month_rows(result, params.capital),
        "fills": fill_rows,
        "fills_truncated": truncated,
        "orders": {
            "counts": dict(counts),
            "rejection_reasons": [
                {"reason": reason, "count": count} for reason, count in reasons.most_common(8)
            ],
            "open": open_orders,
        },
    }


def walkforward_artifact(
    dataset: Dataset,
    params: ResearchParams,
    report: dict[str, Any],
    min_days: int,
    started: datetime,
) -> dict[str, Any]:
    rows = report["rows"]
    cumulative = []
    factor = 1.0
    for row in rows:
        factor *= 1.0 + row["ret"] / 100.0
        end = pd.Period(row["month"], freq="M").end_time
        cumulative.append([_epoch(pd.Timestamp(end, tz="UTC")), round((factor - 1.0) * 100, 2)])
    return {
        "kind": "walkforward",
        "meta": {
            "symbol": dataset.symbol,
            "params": asdict(params),
            "min_days": min_days,
            "generated_at": started.isoformat(timespec="seconds"),
            "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
            "bars": int(len(dataset.bars)),
            "start": _iso(dataset.bars["open_time"].iloc[0]),
            "end": _iso(dataset.bars["open_time"].iloc[-1]),
        },
        "summary": report["summary"],
        "rows": rows,
        "cumulative": cumulative,
    }


def sweep_artifact(
    dataset: Dataset,
    params: ResearchParams,
    rows: list[dict[str, Any]],
    axes: dict[str, Any],
    started: datetime,
) -> dict[str, Any]:
    return {
        "kind": "sweep",
        "meta": {
            "symbol": dataset.symbol,
            "params": asdict(params),
            "axes": axes,
            "generated_at": started.isoformat(timespec="seconds"),
            "duration_s": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
            "bars": int(len(dataset.bars)),
            "start": _iso(dataset.bars["open_time"].iloc[0]),
            "end": _iso(dataset.bars["open_time"].iloc[-1]),
        },
        "summary": {
            "combos": len(rows),
            "best": rows[0] if rows else None,
            "worst": rows[-1] if rows else None,
            "positive": sum(1 for row in rows if row["ann_return"] > 0),
        },
        "rows": rows,
    }
