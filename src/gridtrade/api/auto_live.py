"""Guarded automatic grid executor for the Tokyo Binance node.

The panel never holds Binance secrets.  Every order goes through the node's
``/gateway`` write path, which itself enforces BINANCE_TRADING, KILL and
confirmation.  This service adds a *second* manual arm switch, per-order/size
caps, max inventory, daily-loss stop and an audit log.

It is intentionally simple: at most one bid and one ask, refreshed after fills.
Starting it requires ``arm()``; a process restart is always disarmed.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from .binance_node import BinanceNodeClient, BinanceNodeError


@dataclass(slots=True)
class AutoLiveConfig:
    symbol: str = "AMGNUSDT"
    capital: float = 10.0
    levels: int = 4
    leverage: float = 1.0
    spacing_bp: float = 100.0
    stop_dd_pct: float = 10.0
    max_order_notional: float = 6.0
    max_position_notional: float = 10.0
    daily_loss_limit_pct: float = 5.0
    poll_seconds: float = 5.0


@dataclass
class AutoLiveState:
    armed: bool = False
    status: str = "disarmed"
    symbol: str = ""
    last_error: str | None = None
    started_at: str | None = None
    anchor: float = 0.0
    unit: float = 0.0
    step: float = 0.0
    level: int = 0
    position: float = 0.0
    start_equity: float = 0.0
    orders: list[dict[str, Any]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


class AutoLive:
    def __init__(self, node: BinanceNodeClient) -> None:
        self.node = node
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.config = AutoLiveConfig()
        self.state = AutoLiveState()
        self._seen: set[str] = set()
        self._last_poll = 0.0

    # -- control ---------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "armed": self.state.armed,
                "status": self.state.status,
                "symbol": self.state.symbol,
                "last_error": self.state.last_error,
                "started_at": self.state.started_at,
                "anchor": round(self.state.anchor, 6),
                "unit": self.state.unit,
                "step": round(self.state.step, 6),
                "level": self.state.level,
                "position": self.state.position,
                "start_equity": self.state.start_equity,
                "orders": list(self.state.orders),
                "log": self.state.log[-40:],
                "config": asdict(self.config),
                "poll_seconds": self.config.poll_seconds,
            }

    def _append(self, text: str) -> None:
        self.state.log.append(time.strftime("%H:%M:%S ") + text)

    def arm(self, config: AutoLiveConfig) -> dict[str, Any]:
        with self._lock:
            if self.state.armed:
                raise ValueError("auto live already armed")
            health = self.node.health()
            if not health.get("configured") or not health.get("trading_enabled"):
                raise ValueError("node is not configured/trading_enabled")
            if health.get("kill_switch"):
                raise ValueError("node KILL switch is active")
            snapshot = self.node.snapshot(config.symbol)
            if not snapshot.get("ok") or not snapshot.get("mark_price"):
                raise ValueError("no mark price")
            contract = self.node.contract(config.symbol)
            step_size = float(contract.get("quanto_multiplier") or 0.01)
            account = self.node.account().get("account") or {}
            available = float(account.get("availableBalance") or 0)
            capital = min(float(config.capital), max(1.0, available * 0.8))
            mark = float(snapshot["mark_price"])
            levels = max(2, int(config.levels))
            unit = 0.0
            while levels >= 2:
                level_notional = capital * config.leverage / levels
                candidate = math.floor(level_notional / mark / step_size) * step_size
                candidate = round(candidate, 8)
                if (
                    candidate > 0
                    and candidate * mark >= 5.0
                    and candidate * mark <= config.max_order_notional + 1e-9
                    and levels * candidate * mark <= config.max_position_notional + 1e-9
                ):
                    unit = candidate
                    break
                levels -= 1
            if unit <= 0:
                raise ValueError(
                    "当前余额/上限放不下最小 5U 网格；提高资金或放宽 max_order/max_position"
                )
            config = replace(config, levels=levels)
            # cancel orders left by a previous auto session
            self._cancel_all_orders(config.symbol)
            self.config = AutoLiveConfig(**{**config.__dict__, "capital": capital})
            self.state = AutoLiveState(
                armed=True,
                status="running",
                symbol=config.symbol.upper(),
                started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                anchor=mark,
                unit=unit,
                step=mark * config.spacing_bp / 10_000.0,
                start_equity=float(account.get("totalWalletBalance") or available),
            )
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="auto-live", daemon=True)
            self._thread.start()
            self._append(f"ARMED {config.symbol} unit={unit} anchor={mark}")
            return self.snapshot()

    def disarm(self) -> dict[str, Any]:
        with self._lock:
            self._stop.set()
            self.state.armed = False
            self.state.status = "disarmed"
            try:
                self._cancel_all_orders(self.state.symbol or self.config.symbol)
            except BinanceNodeError as exc:
                self.state.last_error = exc.msg
            self._append("DISARMED")
            return self.snapshot()

    # -- thread ----------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - keep last error visible
                with self._lock:
                    self.state.last_error = str(exc)[:300]
                    self._append("ERROR " + str(exc)[:160])
            if self._stop.wait(self.config.poll_seconds):
                return

    def _tick(self) -> None:
        with self._lock:
            if not self.state.armed:
                return
            config = self.config
            symbol = self.state.symbol
        snap = self.node.snapshot(symbol)
        mark = float(snap.get("mark_price") or 0)
        if mark <= 0:
            raise RuntimeError("no mark price")
        account = self.node.account().get("account") or {}
        equity = float(account.get("totalWalletBalance") or 0)
        positions = (self.node.positions(symbol).get("positions") or [])
        position = 0.0
        for row in positions:
            if str(row.get("symbol")) == symbol:
                position = float(row.get("positionAmt") or 0)
        open_orders = self.node.open_orders(symbol).get("orders") or []
        with self._lock:
            self.state.position = position
            self.state.orders = open_orders
            self.state.level = int(round(-position / self.state.unit)) if self.state.unit else 0
            loss_limit_pct = min(config.stop_dd_pct, config.daily_loss_limit_pct)
            if self.state.start_equity > 0 and equity < self.state.start_equity * (1 - loss_limit_pct / 100):
                self.state.last_error = f"daily loss stop equity={equity:.2f}"
                self._stop.set()
                self.state.status = "halted"
                self._cancel_all_orders(symbol)
                return
            desired: list[tuple[str, float]] = []
            level = self.state.level
            if level < config.levels:
                desired.append(("BUY", self.state.anchor + (level - 1) * self.state.step))
            if level > -config.levels:
                desired.append(("SELL", self.state.anchor + (level + 1) * self.state.step))
            for side, price in desired:
                if price <= 0:
                    continue
                existing = [
                    order
                    for order in open_orders
                    if str(order.get("clientOrderId", "")).startswith("gtal")
                    and order.get("side") == side
                ]
                if existing:
                    continue
                self._place(side, price, config)
                break
            # cancel stale auto orders that no longer match the adjacent levels
            keep = {(side, round(price, 8)) for side, price in desired}
            for order in open_orders:
                cid = str(order.get("clientOrderId", ""))
                if not cid.startswith("gtal"):
                    continue
                side = str(order.get("side"))
                price = round(float(order.get("price") or 0), 8)
                if (side, price) not in keep:
                    try:
                        self.node.gateway({
                            "product": "usdm", "method": "DELETE",
                            "path": "/fapi/v1/order", "params": {
                                "symbol": symbol, "orderId": order.get("orderId")
                            }, "signed": True, "confirm": True,
                        })
                    except BinanceNodeError:
                        pass

    def _cancel_all_orders(self, symbol: str) -> None:
        if not symbol:
            return
        orders = self.node.open_orders(symbol).get("orders") or []
        for order in orders:
            if not str(order.get("clientOrderId", "")).startswith("gtal"):
                continue
            try:
                self.node.gateway({
                    "product": "usdm", "method": "DELETE", "path": "/fapi/v1/order",
                    "params": {"symbol": symbol, "orderId": order.get("orderId")},
                    "signed": True, "confirm": True,
                })
            except BinanceNodeError:
                pass

    def _place(self, side: str, price: float, config: AutoLiveConfig) -> None:
        tick = 0.01
        price = round(round(price / tick) * tick, 8)
        qty = self.state.unit
        params = {
            "symbol": self.state.symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTX",
            "quantity": f"{qty:.8f}".rstrip("0").rstrip("."),
            "price": f"{price:.8f}".rstrip("0").rstrip("."),
            "newClientOrderId": f"gtal{int(time.time()*1000)}{side[0]}"[:36],
        }
        result = self.node.gateway({
            "product": "usdm", "method": "POST", "path": "/fapi/v1/order",
            "params": params, "signed": True, "confirm": True,
        })
        self._append(f"{side} {qty} @ {price} -> {result.get('data', {}).get('orderId')}")
