"""Research CLI: dataset quality, replay, walk-forward and a small sweep.

    PYTHONPATH=src .venv/bin/python -m gridtrade.research.cli dataset --symbol GOOGLUSDT
    PYTHONPATH=src .venv/bin/python -m gridtrade.research.cli replay --spacing-bp 120 --levels 30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .dataset import Dataset
from .runner import ResearchParams, run_replay, sweep, walkforward

DEFAULT_DATA = Path(__file__).resolve().parents[3] / "research" / "data"


def _params(args) -> ResearchParams:
    return ResearchParams(
        capital=args.capital,
        spacing_bp=args.spacing_bp,
        levels=args.levels,
        leverage=args.leverage,
        reanchor_bars=args.reanchor_bars,
        stop_dd=args.stop_dd,
        maker_fee=args.maker_fee,
        taker_fee=args.taker_fee,
        slip_bp=args.slip_bp,
        intrabar=args.intrabar,
    )


def _print_walkforward(dataset: Dataset, params: ResearchParams, min_days: int) -> None:
    report = walkforward(dataset, params, min_days=min_days)
    rows = report["rows"]
    if not rows:
        print("no complete months in range")
        return
    summary = report["summary"]
    print(
        f"grid {params.spacing_bp:g}bp/{params.levels}L/{params.leverage:g}x  "
        f"stop {params.stop_dd:.0%}  {summary['months']} months"
    )
    print(f"{'month':>8} {'ret%':>8} {'dd%':>7} {'trades':>7} {'fees':>7} {'funding':>8} {'stop':>5}")
    for r in rows:
        print(
            f"{r['month']:>8} {r['ret']:>8.2f} {r['dd']:>7.2f} {r['trades']:>7d} "
            f"{r['fees']:>7.1f} {r['funding']:>8.1f} {str(r['halted']):>5}"
        )
    print(
        f"{'mean':>8} {summary['mean']:>8.2f}   med {summary['median']:>6.2f}   "
        f"worst {summary['worst']:>6.2f}   positive {summary['positive']}/{summary['months']}   "
        f"stops {summary['stops']}   total {summary['total_return']:>6.2f}%"
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="gridtrade")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA))
    sub = ap.add_subparsers(dest="cmd", required=True)

    ds = sub.add_parser("dataset", help="print data quality report")
    ds.add_argument("--symbol", default="GOOGLUSDT")
    ds.add_argument("--start")
    ds.add_argument("--end")

    def common(p):
        p.add_argument("--symbol", default="GOOGLUSDT")
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--capital", type=float, default=10_000.0)
        p.add_argument("--spacing-bp", type=float, default=120.0)
        p.add_argument("--levels", type=int, default=30)
        p.add_argument("--leverage", type=float, default=1.0)
        p.add_argument("--reanchor-bars", type=int)
        p.add_argument("--stop-dd", type=float, default=0.10)
        p.add_argument("--maker-fee", type=float, default=0.0002)
        p.add_argument("--taker-fee", type=float, default=0.0005)
        p.add_argument("--slip-bp", type=float, default=0.2)
        p.add_argument("--intrabar", action="store_true")
        p.add_argument("--equity-out")

    rp = sub.add_parser("replay", help="run one grid configuration")
    common(rp)

    sw = sub.add_parser("sweep", help="run a small grid over spacing/levels/leverage")
    common(sw)

    wf = sub.add_parser("walkforward", help="restart the grid at each calendar month")
    common(wf)
    wf.add_argument("--min-days", type=int, default=5)

    args = ap.parse_args(argv)
    if args.cmd == "dataset":
        data = Dataset.load(args.data_dir, args.symbol)
        if args.start or args.end:
            data = data.slice(args.start, args.end)
        print(json.dumps(data.quality(), indent=2))
        return

    data = Dataset.load(args.data_dir, args.symbol)
    if args.start or args.end:
        data = data.slice(args.start, args.end)
    params = _params(args) if args.cmd != "dataset" else None

    if args.cmd == "replay":
        result = run_replay(data, params)
        print(json.dumps(result.summary(), indent=2))
        if args.equity_out:
            result.equity.rename("equity").to_csv(args.equity_out)
            print(f"equity -> {args.equity_out}")
        return

    if args.cmd == "walkforward":
        _print_walkforward(data, params, args.min_days)
        return

    rows = sweep(
        data,
        params,
        spacings=(60.0, 90.0, 120.0),
        levels=(10, 20, 30),
        leverages=(0.5, 1.0),
    )
    rows.sort(key=lambda r: r["ann_return"], reverse=True)
    header = f"{'spacing':>7} {'levels':>6} {'lev':>4} {'ann%':>8} {'dd%':>7} {'trades':>7} {'fees':>8} {'funding':>8} {'halt':>5}"
    print(header)
    for r in rows:
        print(
            f"{r['spacing_bp']:>7.0f} {r['levels']:>6d} {r['leverage']:>4.1f} "
            f"{r['ann_return']:>8.2f} {r['max_dd']:>7.2f} {r['trades']:>7d} "
            f"{r['fees']:>8.1f} {r['funding']:>8.1f} {str(r['halted']):>5}"
        )


if __name__ == "__main__":
    main()
