"""Real-time paper trading for a multi-symbol inventory grid portfolio.

Market data comes from Gate.io USDT-margined perpetual futures (public REST,
reachable from the cloud host where Binance futures is blocked). One shared
account holds cash, fees, funding and equity; every symbol runs its own grid but
all of them consume the same margin pool. Funding is settled per symbol at the
contract's funding interval and fees are charged per fill.

The engine deliberately has no exchange credentials: it never places an order.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..strategy.costs import CostModel
from ..risk.liquidation import (
    DEFAULT_MAINTENANCE_TIERS,
    MaintenanceTier,
    maintenance_margin,
    tiers_from_brackets,
)
from .config import PaperConfig

_EPS = 1e-9

#: Chinese labels for the four grid actions (mirrors the Binance adapter).
PAPER_ACTION_LABELS = {
    "OPEN_LONG": "开多",
    "OPEN_SHORT": "开空",
    "CLOSE_LONG": "平多",
    "CLOSE_SHORT": "平空",
}


def _paper_action(side: str, before: float, after: float) -> str:
    """Classify one paper fill as open/close long/short from the position change.

    The inventory grid is symmetric: buying below the anchor opens long
    (or closes a short), selling above opens short (or closes a long). A fill
    that crosses zero is labelled by its net effect.
    """
    if side == "BUY":
        if before >= -_EPS:
            return "OPEN_LONG"
        return "OPEN_LONG" if after > _EPS else "CLOSE_SHORT"
    if before <= _EPS:
        return "OPEN_SHORT"
    return "OPEN_SHORT" if after < -_EPS else "CLOSE_LONG"

_FILL_LIMIT = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL,
    config TEXT NOT NULL,
    cash REAL NOT NULL,
    realized REAL NOT NULL DEFAULT 0,
    fees REAL NOT NULL DEFAULT 0,
    funding REAL NOT NULL DEFAULT 0,
    slippage REAL NOT NULL DEFAULT 0,
    peak_equity REAL NOT NULL,
    started_at TEXT,
    updated_at TEXT,
    last_error TEXT,
    equity REAL NOT NULL DEFAULT 0,
    gross REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS paper_symbols (
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
    slippage REAL NOT NULL DEFAULT 0,
    funding_next INTEGER,
    funding_interval INTEGER NOT NULL DEFAULT 28800
);

CREATE TABLE IF NOT EXISTS paper_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    qty REAL NOT NULL,
    fee REAL NOT NULL,
    realized REAL NOT NULL,
    slip REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_fills_ts ON paper_fills(id DESC);

CREATE TABLE IF NOT EXISTS paper_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    equity REAL NOT NULL,
    gross REAL NOT NULL,
    drawdown REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_equity_ts ON paper_equity(id DESC);

CREATE TABLE IF NOT EXISTS paper_funding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rate REAL NOT NULL,
    payment REAL NOT NULL,
    position REAL NOT NULL,
    mark REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    ended_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    capital REAL NOT NULL DEFAULT 0,
    equity REAL NOT NULL DEFAULT 0,
    return_pct REAL NOT NULL DEFAULT 0,
    max_dd_pct REAL NOT NULL DEFAULT 0,
    fees REAL NOT NULL DEFAULT 0,
    funding REAL NOT NULL DEFAULT 0,
    slippage REAL NOT NULL DEFAULT 0,
    fills INTEGER NOT NULL DEFAULT 0,
    config TEXT NOT NULL DEFAULT '{}'
);
"""


def _iso(ts: float | int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _floor_to(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(int(value / step + 1e-9) * step, 12)


def _round_to(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(round(value / step) * step, 12)


class Feed(Protocol):
    def contract(self, symbol: str) -> dict[str, Any]: ...

    def tickers(self, symbols: list[str]) -> list[dict[str, Any]]: ...

    def funding(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]: ...


class GateFeed:
    """Public Gate.io USDT perpetual futures market data."""

    BASE = "https://api.gateio.ws/api/v4"

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=self.BASE,
            timeout=httpx.Timeout(8.0, connect=4.0),
            headers={"User-Agent": "gridtrade/0.1 paper"},
        )

    def contract(self, symbol: str) -> dict[str, Any]:
        response = self._client.get(f"/futures/usdt/contracts/{symbol}")
        response.raise_for_status()
        return response.json()

    def tickers(self, symbols: list[str]) -> list[dict[str, Any]]:
        response = self._client.get("/futures/usdt/tickers")
        response.raise_for_status()
        wanted = {name.upper() for name in symbols}
        return [row for row in response.json() if str(row.get("contract", "")).upper() in wanted]

    def funding(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        response = self._client.get(
            "/futures/usdt/funding_rate",
            params={"contract": symbol, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()


class NodeFeed:
    """Public Binance USDⓈ-M market data via the Tokyo execution node.

    Used when ``GRIDTRADE_PAPER_SOURCE=binance``; no Binance API keys are needed
    because the adapter only reads public market endpoints.
    """

    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(10.0, connect=4.0),
            headers={"User-Agent": "gridtrade/0.1 paper-node"},
        )

    @staticmethod
    def _binance(symbol: str) -> str:
        return symbol.strip().upper().replace("_", "")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise RuntimeError(f"node market error: {payload}")
        return payload

    def contract(self, symbol: str) -> dict[str, Any]:
        return self._get("/market/contract", {"symbol": self._binance(symbol)})

    def tickers(self, symbols: list[str]) -> list[dict[str, Any]]:
        originals = {self._binance(symbol): symbol for symbol in symbols}
        payload = self._get(
            "/market/tickers", {"symbols": ",".join(originals.keys())}
        )
        rows = []
        for row in payload.get("tickers") or []:
            item = dict(row)
            item["contract"] = originals.get(str(row.get("contract") or "").upper(), row.get("contract"))
            rows.append(item)
        return rows

    def leverage_bracket(self, symbol: str) -> tuple[MaintenanceTier, ...] | None:
        payload = self._get("/market/leverage-bracket", {"symbol": self._binance(symbol)})
        rows = payload.get("brackets") or []
        return tiers_from_brackets(rows) if rows else None

    def funding(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        payload = self._get(
            "/market/funding", {"symbol": self._binance(symbol), "limit": limit}
        )
        rows = []
        for row in payload.get("funding") or []:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                rows.append({"t": int(row[0]), "r": float(row[1])})
        return rows

    def close(self) -> None:
        self._client.close()


@dataclass(slots=True)
class SymbolState:
    symbol: str
    mark: float = 0.0
    index_price: float = 0.0
    change_pct: float | None = None
    funding_rate: float = 0.0
    anchor: float = 0.0
    step: float = 0.0
    unit: float = 0.0
    tick_size: float = 0.01
    step_size: float = 0.01
    min_qty: float = 0.01
    position: float = 0.0
    avg_entry: float = 0.0
    maker_fee: float | None = None
    taker_fee: float | None = None
    slippage: float = 0.0
    funding_next: int | None = None
    funding_interval: int = 28_800
    maintenance_tiers: tuple[MaintenanceTier, ...] = DEFAULT_MAINTENANCE_TIERS
    liquidation_fee_bp: float = 150.0

    def grid(self) -> tuple[float, float]:
        if self.unit <= 0:
            return self.mark, self.mark
        level = int(round(-self.position / self.unit))
        return (
            _round_to(self.anchor + (level - 1) * self.step, self.tick_size),
            _round_to(self.anchor + (level + 1) * self.step, self.tick_size),
        )

    @property
    def unrealized(self) -> float:
        if not self.position:
            return 0.0
        return self.position * (self.mark - self.avg_entry)


@dataclass(slots=True)
class PortfolioAccount:
    cash: float
    realized: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    slippage: float = 0.0
    peak_equity: float = 0.0


class PaperEngine:
    def __init__(
        self,
        config: PaperConfig,
        var_dir: Path,
        *,
        feed: Feed | None = None,
        db_name: str = "paper.db",
    ) -> None:
        self.config = config
        self.var_dir = Path(var_dir)
        self.var_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.var_dir / db_name
        self._feed: Feed | None = feed
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_snapshot = 0.0
        self.account = PortfolioAccount(cash=config.capital)
        self.state: dict[str, SymbolState] = {}
        self.status = "stopped"
        self.started_at: str | None = None
        self.last_tick_at: str | None = None
        self.last_error: str | None = None
        self.equity = config.capital
        self.gross = 0.0
        self.liquidation: dict[str, Any] | None = None
        self.wallet_balance = config.capital
        self.maintenance_margin = 0.0
        self._init_db()
        self._load()

    # -- lifecycle -------------------------------------------------------

    def feed(self) -> Feed:
        if self._feed is None:
            if self.config.source == "binance" and self.config.node_url:
                self._feed = NodeFeed(self.config.node_url)
            else:
                self._feed = GateFeed()
        return self._feed

    def autostart(self) -> None:
        """Resume in the background: market latency must not block app startup."""
        if not (self.config.enabled and self.config.autostart):
            return
        if self.status == "running":
            self._spawn()
            return
        if self.started_at:
            self._spawn()
            return
        threading.Thread(target=self._boot, name="paper-boot", daemon=True).start()

    def _boot(self) -> None:
        while True:
            try:
                self.start(reset=True)
                return
            except Exception as exc:
                with self._lock:
                    self.last_error = f"模拟盘启动失败: {exc}"[:300]
                    self.status = "stopped"
                    self._save()
            if self._stop.wait(15):
                return

    def start(
        self,
        *,
        reset: bool = False,
        overrides: dict[str, Any] | None = None,
        background: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if overrides:
                self.config = replace(
                    self.config, **{k: v for k, v in overrides.items() if hasattr(self.config, k)}
                )
            if reset or not self.started_at:
                self._open()
            self.status = "running"
            self._stop.clear()
            self.last_error = None
            if not self.started_at:
                self.started_at = _iso(time.time())
            self._save()
        if background:
            self._spawn()
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=6)
        self._thread = None
        with self._lock:
            if self.status == "running":
                self.status = "stopped"
            self._save()
        return self.snapshot()

    def close(self) -> None:
        """Stop the worker without changing the persisted status (restart-safe)."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=6)
        self._thread = None
        with self._lock:
            self._save()
        feed = self._feed
        close = getattr(feed, "close", None)
        if callable(close):
            close()

    def reset(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        self._archive_run("reset")
        if self.status == "running":
            self.stop()
        with self._lock:
            if overrides:
                self.config = replace(
                    self.config, **{k: v for k, v in overrides.items() if hasattr(self.config, k)}
                )
        self._open()
        with self._lock:
            self.status = "stopped"
            self.started_at = _iso(time.time())
            self._save()
        return self.snapshot()

    def _spawn(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="paper-engine", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                with self._lock:
                    self.last_error = str(exc)[:300]
                    self._save()
            with self._lock:
                running = self.status == "running"
                poll = max(1.0, self.config.poll_seconds)
            if not running:
                return
            if self._stop.wait(poll):
                return

    # -- market tick -----------------------------------------------------

    def tick(self) -> None:
        with self._lock:
            if self.status != "running":
                return
            symbols = list(self.state)
            feed = self.feed()
        rows = feed.tickers(symbols)
        by_symbol = {str(row.get("contract", "")).upper(): row for row in rows}
        now = time.time()
        with self._lock:
            for symbol, state in self.state.items():
                row = by_symbol.get(symbol)
                if not row:
                    continue
                state.mark = _float(row.get("mark_price"), state.mark)
                state.index_price = _float(row.get("index_price"), state.index_price)
                change = row.get("change_percentage")
                state.change_pct = _float(change) if change is not None else None
                state.funding_rate = _float(row.get("funding_rate"), state.funding_rate)
            self.last_tick_at = _iso(now)
            for state in self.state.values():
                self._match(state, now)
            self._mark_equity()
            self._settle_funding(now)
            self._mark_equity()
            self._update_margin()
            self._check_liquidation(now)
            if self.status == "running":
                self._check_stop()
            self._save()
            self._snapshot_if_due(now)

    def _match(self, state: SymbolState, now: float) -> None:
        if state.unit <= 0 or state.mark <= 0:
            return
        max_position = state.unit * self.config.levels
        for _ in range(_FILL_LIMIT):
            buy, sell = state.grid()
            if state.mark <= buy + _EPS and state.position + state.unit <= max_position + _EPS:
                side, price, qty = "BUY", buy, state.unit
            elif state.mark >= sell - _EPS and state.position - state.unit >= -max_position - _EPS:
                side, price, qty = "SELL", sell, state.unit
            else:
                return
            if not self._has_margin(state, self._slipped_price(side, price), qty):
                return
            self._fill(state, side, price, qty, self._maker_rate(state), "grid", now)

    def _has_margin(self, state: SymbolState, price: float, qty: float) -> bool:
        """Shared margin: projected gross notional may not exceed equity * leverage."""
        cap = max(0.0, self.equity) * self.config.leverage
        projected = self.gross + abs(qty) * price
        return projected <= cap * 1.0001 + _EPS

    def _maker_rate(self, state: SymbolState) -> float:
        if state.maker_fee is not None:
            return state.maker_fee
        return self.config.maker_fee_bp / 1e4

    def _taker_rate(self, state: SymbolState) -> float:
        if state.taker_fee is not None:
            return state.taker_fee
        return self.config.taker_fee_bp / 1e4

    @property
    def _slippage_rate(self) -> float:
        return max(0.0, self.config.slippage_bp) / 1e4

    def _slipped_price(self, side: str, price: float) -> float:
        """Execution price after adverse slippage: buys pay up, sells sell low."""
        rate = self._slippage_rate
        if rate <= 0:
            return price
        return price * (1 + rate) if side.upper() == "BUY" else price * (1 - rate)

    def _fill(
        self,
        state: SymbolState,
        side: str,
        price: float,
        qty: float,
        fee_rate: float,
        reason: str,
        now: float,
    ) -> None:
        account = self.account
        ref_price = price
        price = self._slipped_price(side, ref_price)
        slip = abs(qty) * abs(price - ref_price)
        signed = qty if side == "BUY" else -qty
        before = state.position
        fee = abs(signed) * price * fee_rate
        account.cash -= fee
        account.fees += fee
        account.slippage += slip
        state.slippage += slip
        realized = 0.0
        if abs(state.position) <= _EPS or (state.position > 0) == (signed > 0):
            new_position = state.position + signed
            if abs(new_position) > _EPS:
                state.avg_entry = (
                    abs(state.position) * state.avg_entry + abs(signed) * price
                ) / abs(new_position)
            state.position = new_position
        else:
            closed = min(abs(signed), abs(state.position))
            realized = closed * (price - state.avg_entry) * (1 if state.position > 0 else -1)
            account.cash += realized
            account.realized += realized
            new_position = state.position + signed
            if abs(new_position) <= _EPS:
                state.avg_entry = 0.0
            elif (new_position > 0) != (state.position > 0):
                state.avg_entry = price
            state.position = new_position
        action = _paper_action(side, before, state.position)
        self.gross = self._gross()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO paper_fills (ts, symbol, side, price, qty, fee, realized, slip,"
                " reason, action) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _iso(now),
                    state.symbol,
                    side,
                    price,
                    round(qty, 12),
                    fee,
                    realized,
                    slip,
                    reason,
                    action,
                ),
            )

    def _funding_rate_at(self, symbol: str, ts: int) -> float | None:
        try:
            rows = self.feed().funding(symbol, limit=10)
        except Exception:
            return None
        best: tuple[float, float] | None = None
        for row in rows:
            when = _float(row.get("t"))
            if when <= 0:
                continue
            distance = abs(when - ts)
            if distance <= 900 and (best is None or distance < best[0]):
                best = (distance, _float(row.get("r")))
        return best[1] if best else None

    def _settle_funding(self, now: float) -> None:
        for state in self.state.values():
            next_apply = state.funding_next
            if not next_apply or now < next_apply:
                continue
            rate = self._funding_rate_at(state.symbol, next_apply)
            if rate is None:
                rate = state.funding_rate
            payment = state.position * state.mark * rate
            self.account.cash -= payment
            self.account.funding += payment
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO paper_funding (ts, symbol, rate, payment, position, mark)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (_iso(next_apply), state.symbol, rate, payment, state.position, state.mark),
                )
            state.funding_next = int(next_apply + state.funding_interval)

    def _gross(self) -> float:
        return sum(abs(state.position) * state.mark for state in self.state.values())

    @staticmethod
    def _resolve_tiers(feed: Feed, symbol: str) -> tuple[MaintenanceTier, ...]:
        """Use the exchange's real bracket; fall back safely if unavailable."""
        if not isinstance(feed, NodeFeed):
            return DEFAULT_MAINTENANCE_TIERS
        try:
            return feed.leverage_bracket(symbol) or DEFAULT_MAINTENANCE_TIERS
        except Exception:  # noqa: BLE001 - optional exchange detail
            return DEFAULT_MAINTENANCE_TIERS

    def _mark_equity(self) -> None:
        unrealized = sum(state.unrealized for state in self.state.values())
        self.gross = self._gross()
        self.equity = self.account.cash + unrealized
        self.account.peak_equity = max(self.account.peak_equity, self.equity)

    def _update_margin(self) -> None:
        wallet = self.account.cash
        maintenance = 0.0
        for state in self.state.values():
            if abs(state.position) <= _EPS:
                continue
            wallet += state.position * state.avg_entry
            maintenance += maintenance_margin(
                abs(state.position) * state.mark, state.maintenance_tiers
            )
        self.wallet_balance = wallet
        self.maintenance_margin = maintenance

    def _check_liquidation(self, now: float) -> None:
        """Binance-style cross-margin liquidation for the shared paper account."""
        if self.status != "running" or self.maintenance_margin <= 0:
            return
        if self.equity > self.maintenance_margin + 1e-9:
            return
        positions = [state for state in self.state.values() if abs(state.position) > _EPS]
        if not positions:
            return
        equity_before = self.equity
        maintenance = self.maintenance_margin
        positions_snapshot = [
            {
                "symbol": state.symbol,
                "qty": round(state.position, 12),
                "mark": state.mark,
                "avg_entry": state.avg_entry,
            }
            for state in positions
        ]
        fees = 0.0
        for state in positions:
            qty = abs(state.position)
            notional = qty * state.mark
            side = "SELL" if state.position > 0 else "BUY"
            self._fill(state, side, state.mark, qty, self._taker_rate(state), "liquidation", now)
            fee = notional * max(0.0, state.liquidation_fee_bp) / 1e4
            self.account.cash -= fee
            self.account.fees += fee
            fees += fee
        bad_debt = max(0.0, -self.account.cash)
        # Keep negative cash/equity when a gap creates bad debt.  Normal
        # liquidations leave a non-negative balance; do not hide the edge case.
        self._mark_equity()
        self.liquidation = {
            "ts": _iso(now),
            "reason": "maintenance_margin",
            "equity_before": round(equity_before, 6),
            "maintenance_margin": round(maintenance, 6),
            "cash_after": round(self.account.cash, 6),
            "bad_debt": round(bad_debt, 6),
            "liquidation_fee": round(fees, 6),
            "positions": positions_snapshot,
        }
        self.status = "halted"
        self.last_error = (
            f"爆仓强平：权益 ${equity_before:.2f} <= 维持保证金 ${maintenance:.2f}；"
            f"强平费 ${fees:.2f}，坏账 ${bad_debt:.2f}"
        )
        self._mark_equity()
        self._stop.set()
        self._archive_run("liquidation")
        self._save()

    def _check_stop(self) -> None:
        limit = self.config.stop_dd_pct
        account = self.account
        if limit <= 0 or account.peak_equity <= 0:
            return
        drawdown = (account.peak_equity - self.equity) / account.peak_equity * 100
        if drawdown < limit:
            return
        for state in self.state.values():
            if abs(state.position) <= _EPS:
                continue
            side = "SELL" if state.position > 0 else "BUY"
            qty = abs(state.position)
            price = _round_to(state.mark, state.tick_size)
            self._fill(state, side, price, qty, self._taker_rate(state), "stop", time.time())
        self.status = "halted"
        self.last_error = f"组合回撤触发 {limit:g}% 止损，已全部平仓并暂停"
        self._mark_equity()
        self._stop.set()
        self._archive_run("stop")

    def _snapshot_if_due(self, now: float) -> None:
        if now - self._last_snapshot < 15:
            return
        self._last_snapshot = now
        drawdown = 0.0
        if self.account.peak_equity > 0:
            drawdown = (self.account.peak_equity - self.equity) / self.account.peak_equity * 100
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO paper_equity (ts, equity, gross, drawdown) VALUES (?, ?, ?, ?)",
                (_iso(now), self.equity, self.gross, drawdown),
            )
            conn.execute(
                "DELETE FROM paper_equity WHERE id <= (SELECT MAX(id) - 20000 FROM paper_equity)"
            )

    # -- account state ---------------------------------------------------

    def _open(self) -> None:
        feed = self.feed()
        symbols = [s.strip().upper() for s in self.config.symbols if s.strip()]
        if not symbols:
            raise ValueError("模拟盘未配置标的（GRIDTRADE_PAPER_SYMBOLS）")
        contracts = {symbol: feed.contract(symbol) for symbol in symbols}
        rows = feed.tickers(symbols)
        by_symbol = {str(row.get("contract", "")).upper(): row for row in rows}
        cfg = self.config
        budget = cfg.capital * cfg.leverage / max(1, len(symbols) * max(1, cfg.levels))
        states: dict[str, SymbolState] = {}
        for symbol in symbols:
            contract = contracts[symbol]
            row = by_symbol.get(symbol)
            if not row:
                raise RuntimeError(f"没有 {symbol} 的行情")
            mark = _float(row.get("mark_price"))
            if mark <= 0:
                raise RuntimeError(f"{symbol} 行情不可用（mark_price=0）")
            tick = _float(contract.get("order_price_round"), 0.01)
            mult = _float(contract.get("quanto_multiplier"), 0.01)
            min_qty = max(mult, _float(contract.get("order_size_min"), 1) * mult)
            step = _round_to(mark * cfg.spacing_bp / 1e4, tick)
            if step < tick:
                raise ValueError(f"{symbol} 间距 {cfg.spacing_bp:g}bp 小于最小价格变动 {tick:g}")
            unit = _floor_to(budget / mark, mult)
            if unit < min_qty:
                unit = min_qty
            maker_fee = taker_fee = None
            if cfg.use_exchange_fees:
                maker_fee = _opt_float(contract.get("maker_fee_rate"))
                taker_fee = _opt_float(contract.get("taker_fee_rate"))
            change = row.get("change_percentage")
            states[symbol] = SymbolState(
                symbol=symbol,
                mark=mark,
                index_price=_float(row.get("index_price"), mark),
                change_pct=_float(change) if change is not None else None,
                funding_rate=_float(row.get("funding_rate")),
                anchor=mark,
                step=step,
                unit=unit,
                tick_size=tick,
                step_size=mult,
                min_qty=min_qty,
                maker_fee=maker_fee,
                taker_fee=taker_fee,
                funding_next=int(contract.get("funding_next_apply") or 0) or None,
                funding_interval=int(contract.get("funding_interval") or 28_800),
                maintenance_tiers=self._resolve_tiers(feed, symbol),
                liquidation_fee_bp=(
                    float(contract.get("liquidation_fee") or 0.0) * 1e4
                    if float(contract.get("liquidation_fee") or 0.0) > 0
                    else self.config.liquidation_fee_bp
                ),
            )
        self.state = states
        self.account = PortfolioAccount(cash=float(cfg.capital), peak_equity=float(cfg.capital))
        self.equity = float(cfg.capital)
        self.gross = 0.0
        self.liquidation = None
        self.wallet_balance = float(cfg.capital)
        self.maintenance_margin = 0.0
        self.started_at = _iso(time.time())
        self.last_error = None
        self.last_tick_at = _iso(time.time())
        self._last_snapshot = 0.0
        with self._connect() as conn:
            conn.execute("DELETE FROM paper_fills")
            conn.execute("DELETE FROM paper_equity")
            conn.execute("DELETE FROM paper_funding")
            conn.execute("DELETE FROM paper_symbols")
        self._save()

    # -- persistence -----------------------------------------------------

    def _archive_run(self, reason: str) -> None:
        """Persist a summary of the current run so resets never lose history."""
        if not self.started_at:
            return
        account = self.account
        capital = float(self.config.capital) or 1.0
        peak = float(account.peak_equity) or capital
        drawdown = max(0.0, (peak - self.equity) / peak * 100) if peak > 0 else 0.0
        try:
            with self._connect() as conn:
                fills = conn.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0]
                conn.execute(
                    "INSERT INTO paper_runs (started_at, ended_at, reason, status, capital,"
                    " equity, return_pct, max_dd_pct, fees, funding, slippage, fills, config)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self.started_at,
                        _iso(time.time()),
                        reason,
                        self.status,
                        float(self.config.capital),
                        round(self.equity, 6),
                        round((self.equity / capital - 1) * 100, 4),
                        round(drawdown, 4),
                        round(account.fees, 8),
                        round(account.funding, 8),
                        round(account.slippage, 8),
                        int(fills),
                        json.dumps(asdict(self.config), sort_keys=True),
                    ),
                )
        except Exception:  # noqa: BLE001 - archiving must never break trading
            self.last_error = "run archive failed"

    def runs(self, limit: int = 30) -> list[dict[str, Any]]:
        """Archived run summaries, newest first, for post-hoc review."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM paper_runs ORDER BY id DESC LIMIT ?", (int(limit),)
                ).fetchall()
        except Exception:  # noqa: BLE001
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["config"] = json.loads(item.get("config") or "{}")
            except ValueError:
                item["config"] = {}
            out.append(item)
        return out

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            legacy = "paper_account" in tables and "paper_symbols" not in tables
            if legacy:
                for table in ("paper_account", "paper_fills", "paper_equity", "paper_funding"):
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_symbols)")}
            for column in ("maker_fee", "taker_fee"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE paper_symbols ADD COLUMN {column} REAL")
            if "slippage" not in columns:
                conn.execute(
                    "ALTER TABLE paper_symbols ADD COLUMN slippage REAL NOT NULL DEFAULT 0"
                )
            account_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_account)")}
            if "slippage" not in account_columns:
                conn.execute(
                    "ALTER TABLE paper_account ADD COLUMN slippage REAL NOT NULL DEFAULT 0"
                )
            fill_columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_fills)")}
            if "slip" not in fill_columns:
                conn.execute("ALTER TABLE paper_fills ADD COLUMN slip REAL NOT NULL DEFAULT 0")
            if "action" not in fill_columns:
                conn.execute("ALTER TABLE paper_fills ADD COLUMN action TEXT NOT NULL DEFAULT ''")
            conn.commit()

    def _save(self) -> None:
        account = self.account
        payload = (
            self.status,
            json.dumps(asdict(self.config), sort_keys=True),
            account.cash,
            account.realized,
            account.fees,
            account.funding,
            account.slippage,
            account.peak_equity,
            self.started_at,
            _iso(time.time()),
            self.last_error,
            self.equity,
            self.gross,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO paper_account (id, status, config, cash, realized, fees, funding,"
                " slippage, peak_equity, started_at, updated_at, last_error, equity, gross) VALUES"
                " (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET status=excluded.status, config=excluded.config,"
                " cash=excluded.cash, realized=excluded.realized, fees=excluded.fees,"
                " funding=excluded.funding, slippage=excluded.slippage,"
                " peak_equity=excluded.peak_equity, started_at=excluded.started_at,"
                " updated_at=excluded.updated_at, last_error=excluded.last_error,"
                " equity=excluded.equity, gross=excluded.gross",
                payload,
            )
            for state in self.state.values():
                conn.execute(
                    "INSERT INTO paper_symbols (symbol, mark, index_price, change_pct, funding_rate,"
                    " anchor, step, unit, tick_size, step_size, min_qty, position, avg_entry,"
                    " maker_fee, taker_fee, slippage, funding_next, funding_interval)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(symbol) DO UPDATE SET mark=excluded.mark,"
                    " index_price=excluded.index_price, change_pct=excluded.change_pct,"
                    " funding_rate=excluded.funding_rate, anchor=excluded.anchor, step=excluded.step,"
                    " unit=excluded.unit, tick_size=excluded.tick_size, step_size=excluded.step_size,"
                    " min_qty=excluded.min_qty, position=excluded.position,"
                    " avg_entry=excluded.avg_entry, maker_fee=excluded.maker_fee,"
                    " taker_fee=excluded.taker_fee, slippage=excluded.slippage,"
                    " funding_next=excluded.funding_next,"
                    " funding_interval=excluded.funding_interval",
                    (
                        state.symbol,
                        state.mark,
                        state.index_price,
                        state.change_pct,
                        state.funding_rate,
                        state.anchor,
                        state.step,
                        state.unit,
                        state.tick_size,
                        state.step_size,
                        state.min_qty,
                        state.position,
                        state.avg_entry,
                        state.maker_fee,
                        state.taker_fee,
                        state.slippage,
                        state.funding_next,
                        state.funding_interval,
                    ),
                )
            if self.state:
                placeholders = ",".join("?" * len(self.state))
                conn.execute(
                    f"DELETE FROM paper_symbols WHERE symbol NOT IN ({placeholders})",
                    tuple(self.state),
                )
            else:
                conn.execute("DELETE FROM paper_symbols")

    def _load(self) -> None:
        initial_source = self.config.source
        initial_node_url = self.config.node_url
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
            symbol_rows = conn.execute("SELECT * FROM paper_symbols").fetchall()
        if row is None:
            self.equity = self.config.capital
            return
        self.status = row["status"]
        try:
            stored = json.loads(row["config"])
            allowed = {k: v for k, v in stored.items() if hasattr(self.config, k)}
            self.config = replace(self.config, **allowed)
        except (ValueError, TypeError):
            pass
        # Data source is deployment configuration, not run state: keep the
        # current env choice even when the database was written by GateFeed.
        self.config = replace(
            self.config, source=initial_source, node_url=initial_node_url
        )
        self.account = PortfolioAccount(
            cash=row["cash"],
            realized=row["realized"],
            fees=row["fees"],
            funding=row["funding"],
            slippage=row["slippage"],
            peak_equity=row["peak_equity"],
        )
        self.equity = row["equity"]
        self.gross = row["gross"]
        self.started_at = row["started_at"]
        self.last_error = row["last_error"]
        self.last_tick_at = row["updated_at"]
        states: dict[str, SymbolState] = {}
        for symbol_row in symbol_rows:
            states[symbol_row["symbol"]] = SymbolState(
                symbol=symbol_row["symbol"],
                mark=symbol_row["mark"],
                index_price=symbol_row["index_price"],
                change_pct=symbol_row["change_pct"],
                funding_rate=symbol_row["funding_rate"],
                anchor=symbol_row["anchor"],
                step=symbol_row["step"],
                unit=symbol_row["unit"],
                tick_size=symbol_row["tick_size"],
                step_size=symbol_row["step_size"],
                min_qty=symbol_row["min_qty"],
                position=symbol_row["position"],
                avg_entry=symbol_row["avg_entry"],
                maker_fee=symbol_row["maker_fee"],
                taker_fee=symbol_row["taker_fee"],
                slippage=symbol_row["slippage"],
                funding_next=symbol_row["funding_next"],
                funding_interval=symbol_row["funding_interval"],
            )
        self.state = states

    # -- read models -----------------------------------------------------

    def cost_report(self) -> dict[str, Any]:
        """Round-trip cost estimate for the live paper parameters, in bp.

        The grid rests POST_ONLY orders on both legs, so the headline
        ``round_trip_bp`` is maker/maker; ``round_trip_taker_bp`` covers the
        stop/flatten path. Funding is the mean current rate over the symbols,
        normalised to an 8h interval, and per-symbol rows use each contract's
        own funding interval. This block lets the UI answer "does the current
        ``spacing_bp`` still cover fees + slippage + funding?".
        """
        cfg = self.config
        rates = [state.funding_rate for state in self.state.values()]
        funding = sum(rates) / len(rates) if rates else 0.0
        model = CostModel(
            maker_fee_bp=float(cfg.maker_fee_bp),
            taker_fee_bp=max(0.0, float(cfg.taker_fee_bp)),
            slippage_bp=max(0.0, float(cfg.slippage_bp)),
            funding_rate_8h=funding,
            funding_interval_h=8.0,
        )
        spacing_bp = float(cfg.spacing_bp)
        report: dict[str, Any] = {
            **model.describe(),
            "spacing_bp": spacing_bp,
            "round_trip_bp": model.round_trip_bp(entry_taker=False, exit_taker=False),
            "round_trip_taker_bp": model.round_trip_bp(entry_taker=True, exit_taker=True),
            "breakeven_spacing_bp": model.breakeven_spacing_bp(
                entry_taker=False, exit_taker=False
            ),
            "net_edge_bp": model.net_edge_bp(spacing_bp, entry_taker=False, exit_taker=False),
            "is_profitable": model.is_profitable(
                spacing_bp, entry_taker=False, exit_taker=False
            ),
            "symbols": {},
        }
        per_symbol: dict[str, dict[str, Any]] = {}
        for state in self.state.values():
            interval_h = max(1.0, state.funding_interval / 3600.0)
            symbol_spacing_bp = (
                state.step / state.mark * 1e4
                if state.mark > 0 and state.step > 0
                else spacing_bp
            )
            symbol_model = CostModel(
                maker_fee_bp=model.maker_fee_bp,
                taker_fee_bp=model.taker_fee_bp,
                slippage_bp=model.slippage_bp,
                funding_rate_8h=state.funding_rate,
                funding_interval_h=interval_h,
            )
            per_symbol[state.symbol] = {
                "spacing_bp": symbol_spacing_bp,
                "round_trip_bp": symbol_model.round_trip_bp(
                    entry_taker=False, exit_taker=False
                ),
                "round_trip_taker_bp": symbol_model.round_trip_bp(
                    entry_taker=True, exit_taker=True
                ),
                "breakeven_spacing_bp": symbol_model.breakeven_spacing_bp(
                    entry_taker=False, exit_taker=False
                ),
                "net_edge_bp": symbol_model.net_edge_bp(
                    symbol_spacing_bp, entry_taker=False, exit_taker=False
                ),
                "is_profitable": symbol_model.is_profitable(
                    symbol_spacing_bp, entry_taker=False, exit_taker=False
                ),
                "funding_rate": state.funding_rate,
                "funding_interval_h": interval_h,
                "slippage": state.slippage,
            }
        report["symbols"] = per_symbol
        return report

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            account = self.account
            equity = float(getattr(self, "equity", account.cash))
            unrealized = sum(state.unrealized for state in self.state.values())
            wallet = account.cash + sum(state.position * state.avg_entry for state in self.state.values())
            maintenance = sum(
                maintenance_margin(abs(state.position) * state.mark, state.maintenance_tiers)
                for state in self.state.values()
                if abs(state.position) > _EPS
            )
            margin_ratio = maintenance / equity if equity > 0 else None
            drawdown = 0.0
            if account.peak_equity > 0:
                drawdown = (account.peak_equity - equity) / account.peak_equity * 100
            portfolio: list[dict[str, Any]] = []
            for state in self.state.values():
                buy, sell = state.grid()
                level = int(round(-state.position / state.unit)) if state.unit else 0
                portfolio.append(
                    {
                        "symbol": state.symbol,
                        "mark_price": state.mark,
                        "index_price": state.index_price,
                        "change_24h_pct": state.change_pct,
                        "funding_rate": state.funding_rate,
                        "next_funding_time": _iso(state.funding_next),
                        "position": state.position,
                        "avg_entry": state.avg_entry,
                        "unrealized": state.unrealized,
                        "notional": abs(state.position) * state.mark,
                        "anchor": state.anchor,
                        "step": state.step,
                        "unit": state.unit,
                        "level": level,
                        "buy_price": buy,
                        "sell_price": sell,
                        "max_position": state.unit * self.config.levels,
                        "maker_fee_bp": (state.maker_fee if state.maker_fee is not None else self.config.maker_fee_bp / 1e4) * 1e4,
                        "taker_fee_bp": (state.taker_fee if state.taker_fee is not None else self.config.taker_fee_bp / 1e4) * 1e4,
                        "fee_source": "exchange" if state.maker_fee is not None else "config",
                        "slippage": state.slippage,
                        "maintenance_margin": maintenance_margin(
                            abs(state.position) * state.mark, state.maintenance_tiers
                        ),
                        "liquidation_fee_bp": state.liquidation_fee_bp,
                    }
                )
            with self._connect() as conn:
                fills = [
                    dict(r)
                    for r in conn.execute("SELECT * FROM paper_fills ORDER BY id DESC LIMIT 60")
                ]
                funding = [
                    dict(r)
                    for r in conn.execute("SELECT * FROM paper_funding ORDER BY id DESC LIMIT 30")
                ]
                equity_rows = [
                    [r["ts"], r["equity"]]
                    for r in conn.execute(
                        "SELECT ts, equity FROM paper_equity ORDER BY id DESC LIMIT 600"
                    )
                ]
            equity_rows.reverse()
            return {
                "enabled": self.config.enabled,
                "status": self.status,
                "symbols": list(self.state),
                "source": self.config.source,
                "last_tick_at": self.last_tick_at,
                "last_error": self.last_error,
                "config": asdict(self.config),
                "account": {
                    "capital": self.config.capital,
                    "cash": account.cash,
                    "equity": equity,
                    "unrealized": unrealized,
                    "realized": account.realized,
                    "fees": account.fees,
                    "funding": account.funding,
                    "slippage": account.slippage,
                    "gross_notional": self.gross,
                    "margin_used": self.gross / max(1.0, self.config.leverage),
                    "wallet_balance": wallet,
                    "maintenance_margin": maintenance,
                    "margin_ratio": margin_ratio,
                    "liquidation_fee_bp": self.config.liquidation_fee_bp,
                    "leverage": self.config.leverage,
                    "peak_equity": account.peak_equity,
                    "drawdown_pct": drawdown,
                    "return_pct": (equity / self.config.capital - 1) * 100
                    if self.config.capital
                    else 0.0,
                },
                "portfolio": portfolio,
                "liquidation": self.liquidation,
                "fills": fills,
                "funding": funding,
                "equity": equity_rows,
                "cost": self.cost_report(),
            }
