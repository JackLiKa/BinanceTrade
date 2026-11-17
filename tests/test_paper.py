"""Paper-trading engine tests: multi-symbol portfolio, fees, funding, stop."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from gridtrade.api.config import PaperConfig
from gridtrade.api.paper import PaperEngine


class FakeFeed:
    def __init__(self, exchange_fees: bool = False) -> None:
        self.exchange_fees = exchange_fees
        self.marks = {"AAA_USDT": 100.0, "BBB_USDT": 50.0}
        self.funding_rows: dict[str, list[dict[str, float | str]]] = {
            "AAA_USDT": [],
            "BBB_USDT": [],
        }
        self.next_apply = int(time.time()) + 3_600

    def contract(self, symbol: str) -> dict[str, float | int | str]:
        data: dict[str, float | int | str] = {
            "order_price_round": "0.01",
            "quanto_multiplier": "0.01",
            "order_size_min": 1,
            "funding_next_apply": self.next_apply,
            "funding_interval": 28_800,
        }
        if self.exchange_fees:
            data["maker_fee_rate"] = "-0.0001"
            data["taker_fee_rate"] = "0.0006"
        return data

    def tickers(self, symbols: list[str]) -> list[dict[str, float | str]]:
        return [
            {
                "contract": symbol,
                "mark_price": str(self.marks[symbol]),
                "index_price": str(self.marks[symbol]),
                "funding_rate": "0.0001",
                "change_percentage": "0.5",
            }
            for symbol in symbols
        ]

    def funding(self, symbol: str, limit: int = 10) -> list[dict[str, float | str]]:
        return self.funding_rows.get(symbol, [])


def make_engine(tmp_path: Path, **config: object) -> tuple[PaperEngine, FakeFeed]:
    values: dict[str, object] = {
        "capital": 10_000.0,
        "leverage": 2.0,
        "spacing_bp": 100.0,
        "levels": 10,
        "maker_fee_bp": 2.0,
        "taker_fee_bp": 5.0,
        "slippage_bp": 0.0,
        "stop_dd_pct": 0.0,
        "poll_seconds": 3_600.0,
        "autostart": False,
        "symbols": ["AAA_USDT", "BBB_USDT"],
    }
    values.update(config)
    feed = FakeFeed(exchange_fees=bool(values.pop("exchange_fees", False)))
    engine = PaperEngine(PaperConfig(**values), tmp_path, feed=feed)
    engine.start(reset=True, background=False)
    return engine, feed


def test_portfolio_sizing_and_shared_fees(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    assert set(engine.state) == {"AAA_USDT", "BBB_USDT"}
    assert engine.state["AAA_USDT"].unit == pytest.approx(10.0)
    assert engine.state["BBB_USDT"].unit == pytest.approx(20.0)

    feed.marks["AAA_USDT"] = 99.0
    feed.marks["BBB_USDT"] = 49.5
    engine.tick()
    account = engine.account
    aaa = engine.state["AAA_USDT"]
    bbb = engine.state["BBB_USDT"]
    assert aaa.position == pytest.approx(10.0)
    assert bbb.position == pytest.approx(20.0)
    fee_aaa = 10 * 99 * 0.0002
    fee_bbb = 20 * 49.5 * 0.0002
    assert account.fees == pytest.approx(fee_aaa + fee_bbb)
    assert account.cash == pytest.approx(10_000 - fee_aaa - fee_bbb)
    assert engine.equity == pytest.approx(account.cash)

    feed.marks["AAA_USDT"] = 100.5
    engine.tick()
    assert aaa.position == pytest.approx(0.0)
    assert account.realized == pytest.approx(10.0)

    snapshot = engine.snapshot()
    assert snapshot["symbols"] == ["AAA_USDT", "BBB_USDT"]
    assert snapshot["account"]["gross_notional"] > 0
    assert len(snapshot["portfolio"]) == 2
    assert snapshot["portfolio"][1]["unit"] == pytest.approx(20.0)
    assert len(snapshot["fills"]) == 3
    assert {fill["symbol"] for fill in snapshot["fills"]} == {"AAA_USDT", "BBB_USDT"}


def test_shared_margin_cap_blocks_overexposure(tmp_path: Path) -> None:
    engine, _ = make_engine(tmp_path)
    state = engine.state["AAA_USDT"]
    engine.equity = 1_000.0
    engine.config.leverage = 2.0  # cap = 2000
    engine.gross = 1_900.0
    assert engine._has_margin(state, 100.0, 0.5) is True  # 1950 <= 2000
    engine.gross = 1_980.0
    assert engine._has_margin(state, 100.0, 0.5) is False  # 2030 > 2000


def test_funding_per_symbol_and_net_cost(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    aaa = engine.state["AAA_USDT"]
    bbb = engine.state["BBB_USDT"]
    aaa.position, aaa.avg_entry = 10.0, 100.0
    bbb.position, bbb.avg_entry = -20.0, 50.0
    when = int(time.time()) - 1
    aaa.funding_next = when
    bbb.funding_next = when
    feed.funding_rows["AAA_USDT"] = [{"t": when, "r": "0.0001"}]
    feed.funding_rows["BBB_USDT"] = [{"t": when, "r": "0.0001"}]
    feed.marks["AAA_USDT"] = 99.5  # between grid levels, no fill
    feed.marks["BBB_USDT"] = 50.5
    cash_before = engine.account.cash

    engine.tick()
    payment_aaa = 10 * 99.5 * 0.0001  # long pays
    payment_bbb = -20 * 50.5 * 0.0001  # short receives
    assert engine.account.funding == pytest.approx(payment_aaa + payment_bbb)
    assert engine.account.cash == pytest.approx(cash_before - payment_aaa - payment_bbb)
    snapshot = engine.snapshot()
    assert {row["symbol"] for row in snapshot["funding"]} == {"AAA_USDT", "BBB_USDT"}
    assert aaa.funding_next == when + 28_800
    assert bbb.funding_next == when + 28_800


def test_portfolio_stop_flattens_all_and_persists(tmp_path: Path) -> None:
    engine, feed = make_engine(
        tmp_path,
        capital=1_000.0,
        leverage=1.0,
        levels=10,
        stop_dd_pct=1.0,
    )
    feed.marks["AAA_USDT"] = 99.0
    feed.marks["BBB_USDT"] = 49.5
    engine.tick()
    assert engine.state["AAA_USDT"].position > 0
    assert engine.state["BBB_USDT"].position > 0

    feed.marks["AAA_USDT"] = 80.0
    feed.marks["BBB_USDT"] = 40.0
    engine.tick()
    assert engine.status == "halted"
    assert all(abs(state.position) <= 1e-9 for state in engine.state.values())
    assert "止损" in (engine.last_error or "")
    stop_fills = [row for row in engine.snapshot()["fills"] if row["reason"] == "stop"]
    assert len(stop_fills) == 2

    reloaded = PaperEngine(engine.config, tmp_path, feed=feed)
    assert reloaded.status == "halted"
    assert all(abs(state.position) <= 1e-9 for state in reloaded.state.values())
    assert reloaded.account.cash == pytest.approx(engine.account.cash)


def test_exchange_fee_rates_are_used_when_available(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path, exchange_fees=True)
    fee_state = engine.state["AAA_USDT"]
    assert fee_state.maker_fee == pytest.approx(-0.0001)
    assert fee_state.taker_fee == pytest.approx(0.0006)

    feed.marks["AAA_USDT"] = 99.0
    engine.tick()
    rebate = 10 * 99 * -0.0001
    assert engine.account.fees == pytest.approx(rebate)  # negative fee = rebate
    assert engine.account.cash == pytest.approx(10_000 - rebate)

    row = next(item for item in engine.snapshot()["portfolio"] if item["symbol"] == "AAA_USDT")
    assert row["maker_fee_bp"] == pytest.approx(-1.0)
    assert row["taker_fee_bp"] == pytest.approx(6.0)
    assert row["fee_source"] == "exchange"


def test_reset_reanchors_all_symbols(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path)
    feed.marks["AAA_USDT"] = 99.0
    engine.tick()
    assert engine.state["AAA_USDT"].position != 0

    feed.marks["AAA_USDT"] = 120.0
    feed.marks["BBB_USDT"] = 60.0
    state = engine.reset()
    assert state["account"]["cash"] == pytest.approx(10_000.0)
    assert state["account"]["equity"] == pytest.approx(10_000.0)
    assert state["fills"] == []
    anchors = {row["symbol"]: row["anchor"] for row in state["portfolio"]}
    assert anchors["AAA_USDT"] == pytest.approx(120.0)
    assert anchors["BBB_USDT"] == pytest.approx(60.0)


def test_slippage_makes_fill_prices_worse(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path, slippage_bp=2.0)
    # AAA grid: anchor 100, step 1 -> buy at 99; BBB: anchor 50, step 0.5 -> sell at 50.5.
    feed.marks["AAA_USDT"] = 99.0
    feed.marks["BBB_USDT"] = 50.5

    engine.tick()

    fills = {row["symbol"]: row for row in engine.snapshot()["fills"]}
    buy, sell = fills["AAA_USDT"], fills["BBB_USDT"]
    assert buy["side"] == "BUY"
    assert buy["price"] == pytest.approx(99.0 * (1 + 2.0 / 1e4))
    assert buy["price"] > 99.0  # pays up
    assert sell["side"] == "SELL"
    assert sell["price"] == pytest.approx(50.5 * (1 - 2.0 / 1e4))
    assert sell["price"] < 50.5  # sells low

    buy_slip = 10 * 99.0 * 2.0 / 1e4
    sell_slip = 20 * 50.5 * 2.0 / 1e4
    assert buy["slip"] == pytest.approx(buy_slip)
    assert sell["slip"] == pytest.approx(sell_slip)
    assert engine.account.slippage == pytest.approx(buy_slip + sell_slip)
    assert engine.state["AAA_USDT"].slippage == pytest.approx(buy_slip)
    assert engine.state["BBB_USDT"].slippage == pytest.approx(sell_slip)


def test_snapshot_reports_slippage_and_cost_breakdown(tmp_path: Path) -> None:
    engine, feed = make_engine(tmp_path, slippage_bp=2.0)
    feed.marks["AAA_USDT"] = 99.0
    feed.marks["BBB_USDT"] = 50.5
    engine.tick()

    snapshot = engine.snapshot()
    account = snapshot["account"]
    assert account["slippage"] == pytest.approx(
        10 * 99.0 * 2.0 / 1e4 + 20 * 50.5 * 2.0 / 1e4
    )
    assert account["fees"] > 0.0
    assert "funding" in account
    assert snapshot["config"]["slippage_bp"] == pytest.approx(2.0)

    cost = snapshot["cost"]
    assert cost["maker_fee_bp"] == pytest.approx(2.0)
    assert cost["taker_fee_bp"] == pytest.approx(5.0)
    assert cost["slippage_bp"] == pytest.approx(2.0)
    assert cost["spacing_bp"] == pytest.approx(100.0)
    # maker/maker: 2 + 2 fees + 2 * 2bp slippage = 8bp.
    assert cost["round_trip_bp"] == pytest.approx(8.0)
    assert cost["breakeven_spacing_bp"] == pytest.approx(8.0)
    assert cost["net_edge_bp"] == pytest.approx(92.0)
    assert cost["is_profitable"] is True
    assert set(cost["symbols"]) == {"AAA_USDT", "BBB_USDT"}

    portfolio = {row["symbol"]: row for row in snapshot["portfolio"]}
    assert portfolio["AAA_USDT"]["slippage"] == pytest.approx(10 * 99.0 * 2.0 / 1e4)
    assert portfolio["BBB_USDT"]["slippage"] == pytest.approx(20 * 50.5 * 2.0 / 1e4)


LEGACY_SCHEMA = """
CREATE TABLE paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL,
    config TEXT NOT NULL,
    cash REAL NOT NULL,
    realized REAL NOT NULL DEFAULT 0,
    fees REAL NOT NULL DEFAULT 0,
    funding REAL NOT NULL DEFAULT 0,
    peak_equity REAL NOT NULL,
    started_at TEXT,
    updated_at TEXT,
    last_error TEXT,
    equity REAL NOT NULL DEFAULT 0,
    gross REAL NOT NULL DEFAULT 0
);
CREATE TABLE paper_symbols (
    symbol TEXT PRIMARY KEY,
    mark REAL NOT NULL DEFAULT 0,
    index_price REAL NOT NULL DEFAULT 0,
    change_pct REAL,
    funding_rate REAL NOT NULL DEFAULT 0,
    anchor REAL NOT NULL DEFAULT 0,
    step REAL NOT NULL DEFAULT 0,
    unit REAL NOT NULL DEFAULT 0,
    tick_size REAL NOT NULL DEFAULT 0.01,
    step_size REAL NOT NULL DEFAULT 0.01,
    min_qty REAL NOT NULL DEFAULT 0.01,
    position REAL NOT NULL DEFAULT 0,
    avg_entry REAL NOT NULL DEFAULT 0,
    maker_fee REAL,
    taker_fee REAL,
    funding_next INTEGER,
    funding_interval INTEGER NOT NULL DEFAULT 28800
);
CREATE TABLE paper_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    qty REAL NOT NULL,
    fee REAL NOT NULL,
    realized REAL NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE paper_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    equity REAL NOT NULL,
    gross REAL NOT NULL,
    drawdown REAL NOT NULL
);
CREATE TABLE paper_funding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rate REAL NOT NULL,
    payment REAL NOT NULL,
    position REAL NOT NULL,
    mark REAL NOT NULL
);
"""


def test_legacy_paper_db_is_migrated_in_place(tmp_path: Path) -> None:
    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(LEGACY_SCHEMA)

    engine = PaperEngine(
        PaperConfig(
            capital=10_000.0,
            leverage=2.0,
            spacing_bp=100.0,
            levels=10,
            slippage_bp=2.0,
            autostart=False,
            symbols=["AAA_USDT"],
        ),
        tmp_path,
        feed=FakeFeed(),
    )

    with sqlite3.connect(db_path) as conn:
        account_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_account)")}
        symbol_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_symbols)")}
        fill_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_fills)")}
    assert "slippage" in account_columns
    assert "slippage" in symbol_columns
    assert "slip" in fill_columns

    # The migrated schema is usable end to end, not just altered.
    engine.start(reset=True, background=False)
    assert engine.status == "running"
    assert engine.account.slippage == pytest.approx(0.0)
    engine.stop()
