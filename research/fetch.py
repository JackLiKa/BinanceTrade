"""Fetch GOOGLUSDT perpetual market data from Binance USDⓈ-M futures.

Usage: .venv/bin/python research/fetch.py [--symbol GOOGLUSDT]
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

BASE = "https://fapi.binance.com"
DATA = Path(__file__).resolve().parent / "data"


def get(path: str, **params) -> object:
    url = BASE + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                wait = 2 ** attempt
                print(f"  rate limited, sleeping {wait}s")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"failed: {url}")


def fetch_klines(symbol: str, start: int) -> pd.DataFrame:
    rows = []
    cursor = start
    while True:
        batch = get(
            "/fapi/v1/klines",
            symbol=symbol,
            interval="1m",
            startTime=cursor,
            limit=1500,
        )
        if not batch:
            break
        rows.extend(batch)
        last_open = int(batch[-1][0])
        if len(batch) < 1500:
            break
        cursor = last_open + 60_000
        if len(rows) % 30_000 < 1500:
            print(f"  klines {len(rows)} last={pd.to_datetime(last_open, unit='ms', utc=True)}")
        time.sleep(0.12)

    df = pd.DataFrame(
        rows,
        columns=[
            "open_time", "open", "high", "low", "close", "volume", "close_time",
            "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
        ],
    )
    for c in ["open", "high", "low", "close", "volume", "quote_volume",
              "taker_buy_base", "taker_buy_quote"]:
        df[c] = df[c].astype(float)
    df["trades"] = df["trades"].astype(int)
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"].astype("int64"), unit="ms", utc=True)
    return df.drop(columns=["ignore"])


def fetch_funding(symbol: str, start: int) -> pd.DataFrame:
    rows = []
    cursor = start
    while True:
        batch = get("/fapi/v1/fundingRate", symbol=symbol, startTime=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1]["fundingTime"]) + 1
        time.sleep(0.12)
    df = pd.DataFrame(rows)
    df["funding_rate"] = df["fundingRate"].astype(float)
    df["funding_time"] = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True)
    df["mark_price"] = df["markPrice"].astype(float)
    return df[["funding_time", "funding_rate", "mark_price", "rateType"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="GOOGLUSDT")
    args = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)

    info = get("/fapi/v1/exchangeInfo")
    sym = next(s for s in info["symbols"] if s["symbol"] == args.symbol)
    onboard = int(sym["onboardDate"])
    print(f"{args.symbol}: onboard {pd.to_datetime(onboard, unit='ms', utc=True)}")

    print("fetching 1m klines...")
    k = fetch_klines(args.symbol, onboard)
    k.to_parquet(DATA / f"{args.symbol}_1m.parquet", index=False)
    print(f"  saved {len(k)} bars -> {DATA}/{args.symbol}_1m.parquet")

    print("fetching funding history...")
    f = fetch_funding(args.symbol, onboard)
    f.to_parquet(DATA / f"{args.symbol}_funding.parquet", index=False)
    print(f"  saved {len(f)} settlements")

    schedule = get("/fapi/v1/tradingSchedule")
    meta = {
        "symbol": args.symbol,
        "onboard": onboard,
        "contract_type": sym["contractType"],
        "underlying_type": sym["underlyingType"],
        "filters": sym["filters"],
        "rate_limits": info["rateLimits"],
        "funding_info": [x for x in get("/fapi/v1/fundingInfo") if x["symbol"] == args.symbol],
        "trading_schedule": schedule,
        "funding_interval_hours": 8,
    }
    (DATA / f"{args.symbol}_meta.json").write_text(json.dumps(meta, indent=2))
    print("  saved meta")


if __name__ == "__main__":
    main()
