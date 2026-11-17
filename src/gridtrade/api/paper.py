"""Real-time paper trading for a single inventory grid.

Market data comes from Gate.io USDT-margined perpetual futures (public REST,
reachable from the cloud host where Binance futures is blocked). The engine
polls the mark price, fills resting grid orders at their limit price, charges
maker/taker fees, settles funding at the contract's funding interval, and keeps
account/fills/equity/funding history in SQLite so a restart resumes the account.

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

from .config import PaperConfig

_EPS = 1e-9
_FILL_LIMIT = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL,
    config TEXT NOT NULL,
    cash REAL NOT NULL,
    position REAL NOT NULL,
    avg_entry REAL NOT NULL,
    peak_equity REAL NOT NULL,
    realized REAL NOT NULL DEFAULT 0,
    fees REAL NOT NULL DEFAULT 0,
    funding REAL NOT NULL DEFAULT 0,
    anchor REAL NOT NULL DEFAULT 0,
    step REAL NOT NULL DEFAULT 0,
    unit REAL NOT NULL DEFAULT 0,
    funding_next INTEGER,
    funding_interval INTEGER NOT NULL DEFAULT 28800,
    started_at TEXT,
    updated_at TEXT,
    last_error TEXT,
    mark REAL NOT NULL DEFAULT 0,
    equity REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS paper_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    qty REAL NOT NULL,
    fee REAL NOT NULL,
    realized REAL NOT NULL,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_fills_ts ON paper_fills(id DESC);

CREATE TABLE IF NOT EXISTS paper_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    equity REAL NOT NULL,
    mark REAL NOT NULL,
    position REAL NOT NULL,
    drawdown REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_equity_ts ON paper_equity(id DESC);

CREATE TABLE IF NOT EXISTS paper_funding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    rate REAL NOT NULL,
    payment REAL NOT NULL,
    position REAL NOT NULL,
    mark REAL NOT NULL
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


def _floor_to(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(int(value / step + 1e-9) * step, 12)


def _round_to(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(round(value / step) * step, 12)


class Feed(Protocol):
    def contract(self) -> dict[str, Any]: ...

    def ticker(self) -> dict[str, Any]: ...

    def funding(self, limit: int = 10) -> list[dict[str, Any]]: ...


class GateFeed:
    """Public Gate.io USDT perpetual futures market data."""

    BASE = "https://api.gateio.ws/api/v4"

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._client = httpx.Client(
            base_url=self.BASE,
            timeout=httpx.Timeout(6.0, connect=4.0),
            headers={"User-Agent": "gridtrade/0.1 paper"},
        )

    def contract(self) -> dict[str, Any]:
        response = self._client.get(f"/futures/usdt/contracts/{self.symbol}")
        response.raise_for_status()
        return response.json()

    def ticker(self) -> dict[str, Any]:
        response = self._client.get("/futures/usdt/tickers", params={"contract": self.symbol})
        response.raise_for_status()
        rows = response.json()
        if not rows:
            raise RuntimeError(f"no ticker for {self.symbol}")
        return rows[0]

    def funding(self, limit: int = 10) -> list[dict[str, Any]]:
        response = self._client.get(
            "/futures/usdt/funding_rate",
            params={"contract": self.symbol, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()


@dataclass(slots=True)
class PaperAccount:
    cash: float
    position: float = 0.0
    avg_entry: float = 0.0
    peak_equity: float = 0.0
    realized: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    anchor: float = 0.0
    step: float = 0.0
    unit: float = 0.0
    funding_next: int | None = None
    funding_interval: int = 28_800


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
        self._last_contract = 0.0
        self.mark = 0.0
        self.index_price = 0.0
        self.change_24h_pct: float | None = None
        self.funding_rate = 0.0
        self.tick_tick = 0.0
        self.last_tick_at: str | None = None
        self.last_error: str | None = None
        self.status = "stopped"
        self.account = PaperAccount(cash=config.capital)
        self.tick_size = 0.01
        self.step_size = 0.01
        self.min_qty = 0.01
        self.started_at: str | None = None
        self._init_db()
        self._load()

    # -- lifecycle -------------------------------------------------------

    def feed(self) -> Feed:
        if self._feed is None:
            self._feed = GateFeed(self.config.symbol)
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
                self.config = replace(self.config, **{k: v for k, v in overrides.items() if hasattr(self.config, k)})
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
        if isinstance(feed, GateFeed):
            feed.close()

    def reset(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.status == "running":
            self.stop()
        with self._lock:
            if overrides:
                self.config = replace(self.config, **{k: v for k, v in overrides.items() if hasattr(self.config, k)})
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
            feed = self.feed()
        ticker = feed.ticker()
        now = time.time()
        with self._lock:
            self.mark = _float(ticker.get("mark_price"), self.mark)
            self.index_price = _float(ticker.get("index_price"), self.index_price)
            change = ticker.get("change_percentage")
            self.change_24h_pct = _float(change) if change is not None else None
            self.funding_rate = _float(ticker.get("funding_rate"), self.funding_rate)
            self.last_tick_at = _iso(now)
            self.tick_tick = now
            self._match(now)
            self._settle_funding(now)
            self._mark_equity()
            self._check_stop()
            self._save()
            self._snapshot_if_due(now)

    def _grid(self) -> tuple[float, float]:
        account = self.account
        unit = account.unit
        if unit <= 0:
            return self.mark, self.mark
        level = int(round(-account.position / unit))
        return (
            _round_to(account.anchor + (level - 1) * account.step, self.tick_size),
            _round_to(account.anchor + (level + 1) * account.step, self.tick_size),
        )

    def _match(self, now: float) -> None:
        account = self.account
        if account.unit <= 0 or self.mark <= 0:
            return
        max_position = account.unit * self.config.levels
        for _ in range(_FILL_LIMIT):
            buy, sell = self._grid()
            if self.mark <= buy + _EPS and account.position + account.unit <= max_position + _EPS:
                self._fill("BUY", buy, account.unit, self.config.maker_fee_bp / 1e4, "grid", now)
            elif self.mark >= sell - _EPS and account.position - account.unit >= -max_position - _EPS:
                self._fill("SELL", sell, account.unit, self.config.maker_fee_bp / 1e4, "grid", now)
            else:
                return

    def _fill(self, side: str, price: float, qty: float, fee_rate: float, reason: str, now: float) -> None:
        account = self.account
        signed = qty if side == "BUY" else -qty
        fee = abs(signed) * price * fee_rate
        account.cash -= fee
        account.fees += fee
        realized = 0.0
        if abs(account.position) <= _EPS or (account.position > 0) == (signed > 0):
            new_position = account.position + signed
            if abs(new_position) > _EPS:
                account.avg_entry = (
                    abs(account.position) * account.avg_entry + abs(signed) * price
                ) / abs(new_position)
            account.position = new_position
        else:
            closed = min(abs(signed), abs(account.position))
            realized = closed * (price - account.avg_entry) * (1 if account.position > 0 else -1)
            account.cash += realized
            account.realized += realized
            new_position = account.position + signed
            if abs(new_position) <= _EPS:
                account.avg_entry = 0.0
            elif (new_position > 0) != (account.position > 0):
                account.avg_entry = price
            account.position = new_position
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO paper_fills (ts, side, price, qty, fee, realized, reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_iso(now), side, price, round(qty, 12), fee, realized, reason),
            )

    def _settle_funding(self, now: float) -> None:
        account = self.account
        next_apply = account.funding_next
        if not next_apply or now < next_apply:
            return
        rate = self._funding_rate_at(next_apply)
        if rate is None:
            rate = self.funding_rate
        payment = account.position * self.mark * rate
        account.cash -= payment
        account.funding += payment
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO paper_funding (ts, rate, payment, position, mark) VALUES (?, ?, ?, ?, ?)",
                (_iso(next_apply), rate, payment, account.position, self.mark),
            )
        account.funding_next = int(next_apply + account.funding_interval)
        self.last_error = None

    def _funding_rate_at(self, ts: int) -> float | None:
        try:
            rows = self.feed().funding(limit=10)
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

    def _mark_equity(self) -> None:
        account = self.account
        unrealized = account.position * (self.mark - account.avg_entry) if account.position else 0.0
        equity = account.cash + unrealized
        account.peak_equity = max(account.peak_equity, equity)
        self.equity = equity

    def _check_stop(self) -> None:
        account = self.account
        limit = self.config.stop_dd_pct
        if limit <= 0 or account.peak_equity <= 0 or abs(account.position) <= _EPS:
            return
        drawdown = (account.peak_equity - self.equity) / account.peak_equity * 100
        if drawdown < limit:
            return
        side = "SELL" if account.position > 0 else "BUY"
        qty = abs(account.position)
        price = _round_to(self.mark, self.tick_size)
        self._fill(side, price, qty, self.config.taker_fee_bp / 1e4, "stop", time.time())
        self.status = "halted"
        self.last_error = f"触发 {limit:g}% 止损，已平仓并暂停"
        self._mark_equity()
        self._stop.set()

    def _snapshot_if_due(self, now: float) -> None:
        if now - self._last_snapshot < 15:
            return
        self._last_snapshot = now
        drawdown = 0.0
        if self.account.peak_equity > 0:
            drawdown = (self.account.peak_equity - self.equity) / self.account.peak_equity * 100
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO paper_equity (ts, equity, mark, position, drawdown) VALUES (?, ?, ?, ?, ?)",
                (_iso(now), self.equity, self.mark, self.account.position, drawdown),
            )
            conn.execute(
                "DELETE FROM paper_equity WHERE id <= (SELECT MAX(id) - 20000 FROM paper_equity)"
            )

    # -- account state ---------------------------------------------------

    def _open(self) -> None:
        feed = self.feed()
        contract = feed.contract()
        ticker = feed.ticker()
        mark = _float(ticker.get("mark_price"))
        if mark <= 0:
            raise RuntimeError("行情不可用（mark_price=0）")
        self.tick_size = _float(contract.get("order_price_round"), 0.01)
        self.step_size = _float(contract.get("quanto_multiplier"), 0.01)
        self.min_qty = max(self.step_size, _float(contract.get("order_size_min"), 1) * self.step_size)
        self.mark = mark
        self.index_price = _float(ticker.get("index_price"), mark)
        self.funding_rate = _float(ticker.get("funding_rate"))
        cfg = self.config
        step = _round_to(mark * cfg.spacing_bp / 1e4, self.tick_size)
        if step < self.tick_size:
            raise ValueError(
                f"网格间距 {cfg.spacing_bp:g}bp 小于最小价格变动 {self.tick_size:g}"
            )
        unit = _floor_to(cfg.capital * cfg.leverage / max(1, cfg.levels) / mark, self.step_size)
        if unit < self.min_qty:
            unit = self.min_qty
        self.account = PaperAccount(
            cash=float(cfg.capital),
            anchor=mark,
            step=step,
            unit=unit,
            funding_next=int(contract.get("funding_next_apply") or 0) or None,
            funding_interval=int(contract.get("funding_interval") or 28_800),
        )
        self.account.peak_equity = cfg.capital
        self.equity = float(cfg.capital)
        self.started_at = _iso(time.time())
        self.last_error = None
        self.last_tick_at = _iso(time.time())
        self._last_snapshot = 0.0
        with self._connect() as conn:
            conn.execute("DELETE FROM paper_fills")
            conn.execute("DELETE FROM paper_equity")
            conn.execute("DELETE FROM paper_funding")
        self._save()

    # -- persistence -----------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _save(self) -> None:
        account = self.account
        payload = (
            self.status,
            json.dumps(asdict(self.config), sort_keys=True),
            account.cash,
            account.position,
            account.avg_entry,
            account.peak_equity,
            account.realized,
            account.fees,
            account.funding,
            account.anchor,
            account.step,
            account.unit,
            account.funding_next,
            account.funding_interval,
            self.started_at,
            _iso(time.time()),
            self.last_error,
            self.mark,
            float(getattr(self, "equity", account.cash)),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO paper_account (id, status, config, cash, position, avg_entry, peak_equity,"
                " realized, fees, funding, anchor, step, unit, funding_next, funding_interval,"
                " started_at, updated_at, last_error, mark, equity) VALUES"
                " (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET status=excluded.status, config=excluded.config,"
                " cash=excluded.cash, position=excluded.position, avg_entry=excluded.avg_entry,"
                " peak_equity=excluded.peak_equity, realized=excluded.realized, fees=excluded.fees,"
                " funding=excluded.funding, anchor=excluded.anchor, step=excluded.step, unit=excluded.unit,"
                " funding_next=excluded.funding_next, funding_interval=excluded.funding_interval,"
                " started_at=excluded.started_at, updated_at=excluded.updated_at,"
                " last_error=excluded.last_error, mark=excluded.mark, equity=excluded.equity",
                payload,
            )

    def _load(self) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
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
        self.account = PaperAccount(
            cash=row["cash"],
            position=row["position"],
            avg_entry=row["avg_entry"],
            peak_equity=row["peak_equity"],
            realized=row["realized"],
            fees=row["fees"],
            funding=row["funding"],
            anchor=row["anchor"],
            step=row["step"],
            unit=row["unit"],
            funding_next=row["funding_next"],
            funding_interval=row["funding_interval"],
        )
        self.mark = row["mark"]
        self.equity = row["equity"]
        self.started_at = row["started_at"]
        self.last_error = row["last_error"]
        self.last_tick_at = row["updated_at"]

    # -- read models -----------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            account = self.account
            equity = float(getattr(self, "equity", account.cash))
            unrealized = account.position * (self.mark - account.avg_entry) if account.position else 0.0
            drawdown = 0.0
            if account.peak_equity > 0:
                drawdown = (account.peak_equity - equity) / account.peak_equity * 100
            buy, sell = self._grid()
            with self._connect() as conn:
                fills = [dict(r) for r in conn.execute("SELECT * FROM paper_fills ORDER BY id DESC LIMIT 50")]
                funding = [dict(r) for r in conn.execute("SELECT * FROM paper_funding ORDER BY id DESC LIMIT 20")]
                equity_rows = [
                    [r["ts"], r["equity"]]
                    for r in conn.execute("SELECT ts, equity FROM paper_equity ORDER BY id DESC LIMIT 600")
                ]
            equity_rows.reverse()
            return {
                "enabled": self.config.enabled,
                "status": self.status,
                "symbol": self.config.symbol,
                "source": "gate",
                "mark_price": self.mark,
                "index_price": self.index_price,
                "change_24h_pct": self.change_24h_pct,
                "funding_rate": self.funding_rate,
                "next_funding_time": _iso(account.funding_next),
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
                    "position": account.position,
                    "avg_entry": account.avg_entry,
                    "leverage": self.config.leverage,
                    "margin_used": abs(account.position) * self.mark / max(1.0, self.config.leverage),
                    "peak_equity": account.peak_equity,
                    "drawdown_pct": drawdown,
                    "return_pct": (equity / self.config.capital - 1) * 100 if self.config.capital else 0.0,
                },
                "grid": {
                    "anchor": account.anchor,
                    "step": account.step,
                    "unit": account.unit,
                    "level": int(round(-account.position / account.unit)) if account.unit else 0,
                    "buy_price": buy,
                    "sell_price": sell,
                    "max_position": account.unit * self.config.levels,
                },
                "fills": fills,
                "funding": funding,
                "equity": equity_rows,
            }
