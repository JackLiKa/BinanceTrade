"""Position/order reconciliation and alerting for the execution node.

The adapter owns the only credential, so it is also the only place that can
compare "what we think we submitted" (a local ledger) with "what the exchange
says is open/held" (authoritative). The reconciler runs on a timer in the
adapter process and emits structured alerts; critical ones can auto-engage the
kill switch so a human sees it before the next order.

Design notes
------------
* **Ledger**: every order the adapter submits is appended to a JSON file
  (``ADAPTER_LEDGER``, default ``/opt/gridtrade/state/ledger.json``). Explicit
  cancels mark entries closed. This is deliberately a *log*, not a source of
  truth — the exchange wins; differences are alerts, not silent corrections.
* **Alerts** are JSONL (``ADAPTER_ALERT_LOG``) plus a bounded in-memory ring so
  ``GET /alerts`` and ``/healthz`` can show recent ones.
* No new dependencies: only stdlib + the existing client.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger("gridtrade.reconcile")

DEFAULT_LEDGER = "/opt/gridtrade/state/ledger.json"
DEFAULT_ALERT_LOG = "/opt/gridtrade/state/alerts.jsonl"
LEVELS = ("info", "warn", "critical")


class ExchangeView(Protocol):
    """The subset of the Binance client the reconciler needs."""

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]: ...
    def positions_nonzero(self, symbol: str | None = None) -> list[dict[str, Any]]: ...


@dataclass(slots=True)
class Alert:
    ts: float
    level: str
    kind: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Ledger:
    """Append-only JSON ledger of orders submitted/cancelled by the adapter."""

    def __init__(self, path: str = DEFAULT_LEDGER) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        if self.path is not None:
            self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._entries = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            logger.warning("ledger unreadable, starting empty: %s", self.path)

    def _flush(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._entries, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        except OSError:
            logger.exception("cannot persist ledger to %s", self.path)

    def record_order(self, order: dict[str, Any]) -> None:
        oid = order.get("orderId")
        if oid is None:
            return
        with self._lock:
            self._entries[str(oid)] = {
                "orderId": oid,
                "clientOrderId": order.get("clientOrderId"),
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "positionSide": order.get("positionSide"),
                "type": order.get("type"),
                "price": order.get("price"),
                "origQty": order.get("origQty"),
                "status": order.get("status") or "NEW",
                "submittedAt": int(time.time() * 1000),
            }
            self._flush()

    def mark_closed(self, order_id: Any, status: str = "CANCELED") -> None:
        with self._lock:
            entry = self._entries.get(str(order_id))
            if entry is not None:
                entry["status"] = status
                self._flush()

    def open_entries(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                key: dict(value)
                for key, value in self._entries.items()
                if str(value.get("status", "")).upper() in {"NEW", "PARTIALLY_FILLED"}
            }

    def all_entries(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: dict(value) for key, value in self._entries.items()}


class Reconciler:
    """Compare the exchange's open orders/positions against local expectations."""

    def __init__(
        self,
        client_factory: Callable[[], ExchangeView],
        *,
        ledger: Ledger | None = None,
        alert_log: str = DEFAULT_ALERT_LOG,
        auto_kill_file: str = "",
        reconcile_symbol: str | None = None,
        max_open_orders: int = 20,
        max_order_notional: float = 1000.0,
        max_position_notional: float = 3000.0,
        ring_size: int = 50,
    ) -> None:
        self._client_factory = client_factory
        self.ledger = ledger or Ledger()
        self.alert_log = Path(alert_log) if alert_log else None
        self.auto_kill_file = auto_kill_file.strip()
        self.symbol = reconcile_symbol
        self.max_open_orders = max_open_orders
        self.max_order_notional = max_order_notional
        self.max_position_notional = max_position_notional
        self._ring: list[Alert] = []
        self._ring_size = ring_size
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_run_at: float | None = None
        self.last_error: str | None = None

    # -- alert plumbing --------------------------------------------------
    def alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return [alert.as_dict() for alert in self._ring[-limit:]][::-1]

    def _emit(self, level: str, kind: str, message: str, details: dict[str, Any] | None = None) -> None:
        alert = Alert(ts=time.time(), level=level, kind=kind, message=message, details=details or {})
        logger.warning("ALERT[%s] %s: %s", level, kind, message)
        with self._lock:
            self._ring.append(alert)
            if len(self._ring) > self._ring_size:
                del self._ring[: len(self._ring) - self._ring_size]
        if self.alert_log is not None:
            try:
                self.alert_log.parent.mkdir(parents=True, exist_ok=True)
                with self.alert_log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(alert.as_dict(), ensure_ascii=False) + "\n")
            except OSError:
                logger.exception("cannot append alert log %s", self.alert_log)
        if level == "critical" and self.auto_kill_file:
            try:
                Path(self.auto_kill_file).parent.mkdir(parents=True, exist_ok=True)
                Path(self.auto_kill_file).touch()
                logger.error("auto-triggered kill switch: %s", self.auto_kill_file)
            except OSError:
                logger.exception("cannot touch kill switch %s", self.auto_kill_file)

    # -- checks ----------------------------------------------------------
    def run_once(self) -> list[Alert]:
        """Fetch the exchange view and emit alerts for every invariant broken."""
        self.last_run_at = time.time()
        self.last_error = None
        try:
            with self._client_factory() as client:  # type: ignore[attr-defined]
                orders = client.open_orders(self.symbol)
                positions = client.positions_nonzero(self.symbol)
        except Exception as exc:  # noqa: BLE001 - reconciliation must never raise
            self.last_error = str(exc)[:200]
            with self._lock:
                before = len(self._ring)
            self._emit("warn", "unreachable", f"交易所不可达: {self.last_error}")
            with self._lock:
                return list(self._ring[before:])

        found: list[Alert] = []
        before = len(self._ring)

        if len(orders) > self.max_open_orders:
            self._emit(
                "critical",
                "too_many_orders",
                f"挂单数 {len(orders)} 超过上限 {self.max_open_orders}",
                {"count": len(orders)},
            )

        exchange_ids = {str(o.get("orderId")) for o in orders}
        ledger_open = self.ledger.open_entries()
        unexpected = exchange_ids - set(ledger_open)
        if unexpected:
            self._emit(
                "critical",
                "unexpected_order",
                f"交易所存在本地账本未记录的挂单: {sorted(unexpected)[:5]}",
                {"orderIds": sorted(unexpected)[:10]},
            )
        vanished = set(ledger_open) - exchange_ids
        for order_id in sorted(vanished):
            self.ledger.mark_closed(order_id, "VANISHED")
        if vanished:
            self._emit(
                "warn",
                "order_vanished",
                f"本地账本挂单在交易所已消失（可能成交/撤单）: {sorted(vanished)[:5]}",
                {"orderIds": sorted(vanished)[:10]},
            )

        for order in orders:
            notional = _order_notional(order)
            if notional > self.max_order_notional:
                self._emit(
                    "critical",
                    "order_notional",
                    f"挂单名义 {notional:.2f} 超过上限 {self.max_order_notional:.2f}",
                    {"orderId": order.get("orderId"), "symbol": order.get("symbol")},
                )

        total_position = 0.0
        for row in positions:
            amount = _float(row.get("positionAmt"))
            mark = _float(row.get("markPrice"))
            notional = abs(amount) * mark
            total_position += notional
            if notional > self.max_position_notional:
                self._emit(
                    "critical",
                    "position_notional",
                    f"{row.get('symbol')} 持仓名义 {notional:.2f} 超过上限 {self.max_position_notional:.2f}",
                    {"symbol": row.get("symbol"), "notional": round(notional, 4)},
                )
            liq = _float(row.get("liquidationPrice"))
            if liq > 0 and mark > 0:
                distance = abs(mark - liq) / mark
                if distance < 0.05:
                    self._emit(
                        "critical",
                        "liquidation_risk",
                        f"{row.get('symbol')} 强平价距离仅 {distance:.2%}",
                        {"symbol": row.get("symbol"), "liquidationPrice": liq, "markPrice": mark},
                    )

        with self._lock:
            new_alerts = self._ring[before:]
        return new_alerts

    # -- background loop -------------------------------------------------
    def start(self, interval_s: float = 15.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.run_once()
                except Exception:  # noqa: BLE001 - keep the thread alive
                    logger.exception("reconcile loop error")
                self._stop.wait(max(3.0, interval_s))

        self._thread = threading.Thread(target=loop, name="gridtrade-reconcile", daemon=True)
        self._thread.start()
        logger.info("reconciler started, interval=%.1fs", interval_s)

    def stop(self) -> None:
        self._stop.set()


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _order_notional(order: dict[str, Any]) -> float:
    price = _float(order.get("price")) or _float(order.get("avgPrice")) or _float(order.get("stopPrice"))
    qty = _float(order.get("origQty")) or _float(order.get("executedQty"))
    return price * qty


def build_from_env() -> Reconciler:
    """Construct the reconciler from adapter environment variables."""
    from .binance_demo import BinanceDemoClient, BinanceDemoConfig

    cfg = BinanceDemoConfig.from_env()
    return Reconciler(
        lambda: BinanceDemoClient(cfg),
        ledger=Ledger(os.environ.get("ADAPTER_LEDGER", DEFAULT_LEDGER)),
        alert_log=os.environ.get("ADAPTER_ALERT_LOG", DEFAULT_ALERT_LOG),
        auto_kill_file=os.environ.get("ADAPTER_AUTO_KILL_FILE", "")
        if os.environ.get("ADAPTER_AUTO_KILL", "0").lower() not in {"0", "false", "no", "off"}
        else "",
        reconcile_symbol=os.environ.get("ADAPTER_RECONCILE_SYMBOL") or None,
        max_open_orders=cfg.max_open_orders,
        max_order_notional=cfg.max_order_notional,
        max_position_notional=cfg.max_position_notional,
    )
