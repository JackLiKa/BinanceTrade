"""Fetch Binance mark-price 1m klines for local replay datasets.

The Tokyo node exposes ``/market/mark-klines`` because the mainland host
cannot reach fapi.binance.com directly.  Mark-price klines are what Binance
uses for liquidation triggers, so replay should use them instead of last-price
OHLC whenever available.

Usage:
    GRIDTRADE_BINANCE_NODE_URL=http://10.66.0.2:8100 \
        .venv/bin/python research/fetch_mark.py --symbol GOOGLUSDT
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import httpx
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="GOOGLUSDT")
    ap.add_argument("--node", default=os.environ.get("GRIDTRADE_BINANCE_NODE_URL", "http://10.66.0.2:8100"))
    args = ap.parse_args()

    bar_path = DATA / f"{args.symbol}_1m.parquet"
    bars = pd.read_parquet(bar_path, columns=["open_time"])
    start = int(pd.Timestamp(bars["open_time"].iloc[0]).timestamp() * 1000)
    end = int(pd.Timestamp(bars["open_time"].iloc[-1]).timestamp() * 1000)
    rows: list[list] = []
    cursor = start
    print(f"{args.symbol}: mark klines {bars['open_time'].iloc[0]} → {bars['open_time'].iloc[-1]}")
    with httpx.Client(base_url=args.node.rstrip("/"), timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        while cursor <= end:
            response = client.get(
                "/market/mark-klines",
                params={"symbol": args.symbol, "interval": "1m", "startTime": cursor, "limit": 1500},
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("candles") or []
            if not batch:
                break
            rows.extend(batch)
            last_open = int(batch[-1][0])
            if len(batch) < 1500 or last_open <= cursor:
                break
            cursor = last_open + 60_000
            if len(rows) % 30_000 < 1500:
                print(f"  {len(rows):,} bars")
            time.sleep(0.04)
    if not rows:
        raise SystemExit("no mark klines returned")
    df = pd.DataFrame(
        rows,
        columns=[
            "open_time", "mark_open", "mark_high", "mark_low", "mark_close",
            "ignore", "close_time", "ignore2", "trades", "ignore3", "ignore4", "ignore5",
        ],
    )
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    for column in ("mark_open", "mark_high", "mark_low", "mark_close"):
        df[column] = df[column].astype(float)
    out = df[["open_time", "mark_open", "mark_high", "mark_low", "mark_close"]].drop_duplicates("open_time")
    out = out[(out["open_time"] >= bars["open_time"].iloc[0]) & (out["open_time"] <= bars["open_time"].iloc[-1])]
    out.to_parquet(DATA / f"{args.symbol}_mark_1m.parquet", index=False)
    print(f"saved {len(out):,} mark bars -> {DATA}/{args.symbol}_mark_1m.parquet")


if __name__ == "__main__":
    main()
