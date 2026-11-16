"""Grid backtest on GOOGLUSDT 1m bars with real funding settlements.

Model: state-machine grid. One order rests on each adjacent level k
(anchor + k*step). A sell fills only when the bar's high reaches level k+1's
price; a buy fills only when the low reaches level k-1's price. Inventory is
-level*size, so one full traversal up and back captures exactly one step.
Equity is marked at each bar close.

Conservative fill rule (default): within a bar only the extreme in the bar's
direction can trade, so no intrabar round trips. Set --intrabar to process
both extremes (optimistic upper bound).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
MAKER_FEE = 0.0002  # 2 bp
TAKER_FEE = 0.0005  # 5 bp
SLIP_BP = 0.2       # half spread + latency, per fill


@dataclass
class Config:
    spacing_bp: float
    levels: int
    leverage: float          # position cap as multiple of capital
    fee: float = MAKER_FEE
    slip_bp: float = SLIP_BP
    pen_bp: float = 0.0      # price must trade through the level by this much
                             # before we assume our resting order fills
    stop_dd: float = 0.10    # flatten and stop when equity drawdown > this
    intrabar: bool = False


def _clamp(i: int, n: int) -> int:
    return max(-n, min(n, i))


def run(k: pd.DataFrame, funding: pd.DataFrame, cfg: Config, capital: float = 10_000.0) -> dict:
    o = k["open"].to_numpy()
    h = k["high"].to_numpy()
    l = k["low"].to_numpy()
    c = k["close"].to_numpy()
    n = len(c)

    anchor = o[0]
    step = anchor * cfg.spacing_bp / 1e4
    size = capital * cfg.leverage / cfg.levels / anchor  # base qty per level
    fee = cfg.fee + cfg.slip_bp / 1e4

    cash = capital
    pos = 0.0
    peak = capital
    max_dd = 0.0
    fees_paid = 0.0
    funding_paid = 0.0
    trades = 0
    stopped = False
    inv_notional_sum = 0.0
    at_cap_bars = 0
    equity = np.empty(n)

    fund_idx = np.searchsorted(k["open_time"].to_numpy(), funding["funding_time"].to_numpy(), side="right") - 1
    rates = funding["funding_rate"].to_numpy()
    fi = 0

    level = 0  # inventory = -level*size; one resting order per adjacent level
    pen = anchor * cfg.pen_bp / 1e4

    def fill(direction: int, price: float) -> None:
        nonlocal cash, pos, fees_paid, trades
        qty = size * direction
        notional = abs(qty * price)
        cash -= qty * price
        cash -= notional * fee
        fees_paid += notional * fee
        pos += qty
        trades += 1

    for i in range(n):
        # funding settles at this bar
        while fi < len(fund_idx) and fund_idx[fi] == i:
            if pos != 0:
                pay = pos * c[i] * rates[fi]
                cash -= pay
                funding_paid += pay
            fi += 1

        if not stopped:
            # State machine: one order rests on each adjacent level; only the
            # extreme in the bar's direction may trade, so a fill requires the
            # price to actually reach that level's price.
            if cfg.intrabar:
                extremes = (h[i], l[i]) if c[i] >= o[i] else (l[i], h[i])
                for ext in extremes:
                    while level < cfg.levels and ext >= anchor + (level + 1) * step + pen:
                        level += 1
                        fill(-1, anchor + level * step)
                    while level > -cfg.levels and ext <= anchor + (level - 1) * step - pen:
                        level -= 1
                        fill(+1, anchor + level * step)
            elif c[i] >= o[i]:
                while level < cfg.levels and h[i] >= anchor + (level + 1) * step + pen:
                    level += 1
                    fill(-1, anchor + level * step)
            else:
                while level > -cfg.levels and l[i] <= anchor + (level - 1) * step - pen:
                    level -= 1
                    fill(+1, anchor + level * step)

            eq = cash + pos * c[i]
            dd = 1 - eq / peak
            if dd > max_dd:
                max_dd = dd
            if dd > cfg.stop_dd:
                cash -= abs(pos) * c[i] * TAKER_FEE
                fees_paid += abs(pos) * c[i] * TAKER_FEE
                cash += pos * c[i]
                pos = 0.0
                stopped = True
                eq = cash

            peak = max(peak, eq)
            inv_notional_sum += abs(pos) * c[i]
            if abs(level) >= cfg.levels:
                at_cap_bars += 1

        equity[i] = cash + pos * c[i]

    ret = equity[-1] / capital - 1
    years = (k["open_time"].iloc[-1] - k["open_time"].iloc[0]).total_seconds() / (365.25 * 86400)
    eqs = pd.Series(equity)
    daily = eqs.iloc[::1440]
    dret = daily.pct_change().dropna()
    sharpe = dret.mean() / dret.std() * np.sqrt(365) if dret.std() > 0 else 0.0
    return {
        **asdict(cfg),
        "total_return": round(ret * 100, 2),
        "ann_return": round(((1 + ret) ** (1 / years) - 1) * 100, 2),
        "max_dd": round(max_dd * 100, 2),
        "sharpe": round(float(sharpe), 2),
        "trades": trades,
        "fees": round(fees_paid, 1),
        "funding": round(funding_paid, 1),
        "final_equity": round(float(equity[-1]), 1),
        "stopped": stopped,
        "avg_inv_pct": round(inv_notional_sum / n / capital * 100, 1),
        "at_cap_pct": round(at_cap_bars / n * 100, 1),
    }


def walkforward(k: pd.DataFrame, f: pd.DataFrame, cfg: Config, capital: float = 10_000.0) -> pd.DataFrame:
    """Restart the grid at each calendar month open (fresh anchor, flat inventory)."""
    k = k.assign(month=k["open_time"].dt.to_period("M"))
    rows = []
    for month, sl in k.groupby("month"):
        if len(sl) < 1440 * 5:
            continue
        fl = f[(f["funding_time"] >= sl["open_time"].iloc[0]) & (f["funding_time"] <= sl["open_time"].iloc[-1])]
        r = run(sl.reset_index(drop=True), fl.reset_index(drop=True), cfg, capital)
        rows.append({
            "month": str(month),
            "ret_pct": r["total_return"],
            "dd_pct": r["max_dd"],
            "trades": r["trades"],
            "fees": r["fees"],
            "funding": r["funding"],
            "stopped": r["stopped"],
            "at_cap_pct": r["at_cap_pct"],
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="GOOGLUSDT")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--intrabar", action="store_true")
    ap.add_argument("--walkforward", action="store_true")
    ap.add_argument("--fee", type=float, default=MAKER_FEE)
    ap.add_argument("--slip", type=float, default=SLIP_BP)
    ap.add_argument("--pen", type=float, default=0.0)
    args = ap.parse_args()

    k = pd.read_parquet(DATA / f"{args.symbol}_1m.parquet").sort_values("open_time")
    f = pd.read_parquet(DATA / f"{args.symbol}_funding.parquet").sort_values("funding_time")

    if args.walkforward:
        configs = [Config(60, 20, 1.0, fee=args.fee, slip_bp=args.slip, pen_bp=args.pen),
                   Config(90, 20, 1.0, fee=args.fee, slip_bp=args.slip, pen_bp=args.pen),
                   Config(120, 30, 1.0, fee=args.fee, slip_bp=args.slip, pen_bp=args.pen),
                   Config(120, 20, 0.5, fee=args.fee, slip_bp=args.slip, pen_bp=args.pen)]
        for cfg in configs:
            wf = walkforward(k, f, cfg)
            print(f"\n=== spacing {cfg.spacing_bp}bp levels {cfg.levels} lev {cfg.leverage} "
                  f"fee {cfg.fee*1e4:.1f}bp slip {cfg.slip_bp}bp pen {cfg.pen_bp}bp")
            print(wf.to_string(index=False))
            print(f"  mean {wf.ret_pct.mean():+.2f}%  median {wf.ret_pct.median():+.2f}%  "
                  f"worst {wf.ret_pct.min():+.2f}%  months>0 {(wf.ret_pct>0).sum()}/{len(wf)}")
        return

    if not args.sweep:
        cfg = Config(60, 20, 1.0, intrabar=args.intrabar)
        print(json.dumps(run(k, f, cfg), indent=2))
        return

    rows = []
    for spacing in [10, 20, 30, 45, 60, 90, 120]:
        for levels in [10, 20, 30]:
            for lev in [0.5, 1.0, 2.0]:
                rows.append(run(k, f, Config(spacing, levels, lev, intrabar=args.intrabar)))
    df = pd.DataFrame(rows).sort_values("ann_return", ascending=False)
    out = DATA / f"{args.symbol}_grid_sweep{'_intrabar' if args.intrabar else ''}.csv"
    df.to_csv(out, index=False)
    cols = ["spacing_bp", "levels", "leverage", "ann_return", "max_dd", "sharpe",
            "trades", "fees", "funding", "stopped", "at_cap_pct"]
    print(df[cols].to_string(index=False))
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
