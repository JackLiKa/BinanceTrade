"""Canonical research datasets: loading, slicing and quality checks.

Bars and funding live in Parquet; queries are columnar and never touch the
trading journal. A dataset is immutable and cheap to slice, so research runs
cannot corrupt live state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd

from ..domain.models import Bar, FundingSettlement, SymbolFilters

BAR_COLUMNS = ("open_time", "open", "high", "low", "close", "volume")
FUNDING_COLUMNS = ("funding_time", "funding_rate")


def _utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


@dataclass(frozen=True)
class Dataset:
    symbol: str
    bars: pd.DataFrame
    funding: pd.DataFrame
    filters: SymbolFilters
    meta: dict
    mark: pd.DataFrame | None = None

    @classmethod
    def load(cls, data_dir: str | Path, symbol: str) -> Dataset:
        root = Path(data_dir)
        bars = pd.read_parquet(root / f"{symbol}_1m.parquet").sort_values("open_time")
        funding = pd.read_parquet(root / f"{symbol}_funding.parquet").sort_values("funding_time")
        mark_path = root / f"{symbol}_mark_1m.parquet"
        mark = pd.read_parquet(mark_path).sort_values("open_time") if mark_path.exists() else None
        meta_path = root / f"{symbol}_meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        filters = SymbolFilters.from_exchange_filters(meta.get("filters", []))
        if mark is not None and len(mark):
            bars = bars.merge(mark, on="open_time", how="left")
            for column in ("mark_open", "mark_high", "mark_low", "mark_close"):
                if column in bars.columns:
                    bars[column] = bars[column].fillna(bars["close"])
        for column in BAR_COLUMNS:
            if column not in bars.columns:
                raise ValueError(f"{symbol} bars missing column {column}")
        for column in FUNDING_COLUMNS:
            if column not in funding.columns:
                raise ValueError(f"{symbol} funding missing column {column}")
        return cls(
            symbol=symbol,
            bars=bars.reset_index(drop=True),
            funding=funding.reset_index(drop=True),
            filters=filters,
            meta=meta,
            mark=mark,
        )

    def slice(self, start=None, end=None) -> Dataset:
        mask = pd.Series(True, index=self.bars.index)
        if start is not None:
            mask &= self.bars["open_time"] >= _utc(start)
        if end is not None:
            mask &= self.bars["open_time"] < _utc(end)
        bars = self.bars[mask].reset_index(drop=True)
        fund = self.funding
        if len(bars):
            f_mask = (fund["funding_time"] >= bars["open_time"].iloc[0]) & (
                fund["funding_time"] <= bars["open_time"].iloc[-1]
            )
            fund = fund[f_mask].reset_index(drop=True)
        else:
            fund = fund.iloc[0:0]
        mark = self.mark
        if mark is not None and len(bars):
            f_mask = (mark["open_time"] >= bars["open_time"].iloc[0]) & (
                mark["open_time"] <= bars["open_time"].iloc[-1]
            )
            mark = mark[f_mask].reset_index(drop=True)
        elif mark is not None:
            mark = mark.iloc[0:0]
        return Dataset(self.symbol, bars, fund, self.filters, self.meta, mark)

    def iter_bars(self) -> Iterator[Bar]:
        for row in self.bars.itertuples(index=False):
            yield Bar(
                symbol=self.symbol,
                open_time=row.open_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=float(getattr(row, "volume", 0.0)),
            )

    def iter_funding(self) -> Iterator[FundingSettlement]:
        for row in self.funding.itertuples(index=False):
            yield FundingSettlement(
                symbol=self.symbol,
                time=row.funding_time,
                rate=float(row.funding_rate),
                mark_price=float(getattr(row, "mark_price", 0.0)) or None,
            )

    def quality(self) -> dict:
        bars = self.bars
        ts = bars["open_time"]
        step = ts.diff().dt.total_seconds().div(60).dropna()
        expected = int((ts.iloc[-1] - ts.iloc[0]).total_seconds() // 60) + 1 if len(ts) else 0
        bad_ohlc = (
            (bars["high"] < bars[["open", "close"]].max(axis=1))
            | (bars["low"] > bars[["open", "close"]].min(axis=1))
            | (bars["high"] < bars["low"])
        ).sum()
        funding = self.funding
        gaps = funding["funding_time"].diff().dt.total_seconds().div(3600).dropna()
        return {
            "symbol": self.symbol,
            "bars": int(len(bars)),
            "start": str(ts.iloc[0]) if len(ts) else None,
            "end": str(ts.iloc[-1]) if len(ts) else None,
            "expected_bars": expected,
            "missing_bars": max(0, expected - int(len(bars))),
            "duplicate_timestamps": int(ts.duplicated().sum()),
            "out_of_order": bool((step < 0).any()),
            "max_gap_minutes": int(step.max()) if len(step) else 0,
            "zero_volume_pct": round(float((bars["volume"] == 0).mean() * 100), 2),
            "bad_ohlc": int(bad_ohlc),
            "funding_settlements": int(len(funding)),
            "funding_median_interval_hours": round(float(gaps.median()), 2) if len(gaps) else None,
            "funding_max_interval_hours": round(float(gaps.max()), 2) if len(gaps) else None,
            "last_funding": str(funding["funding_time"].iloc[-1]) if len(funding) else None,
        }
