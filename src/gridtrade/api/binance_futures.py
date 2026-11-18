"""Binance USDⓈ-M futures production adapter (read-only + locked writes).

The Tokyo execution node talks to the official Binance USDⓈ-M futures REST
endpoint ``https://fapi.binance.com``.  Testnet is not used at runtime; tests
inject an ``httpx.MockTransport`` and never send orders to the exchange.

Read-only methods work as soon as an API key/secret pair is configured. Every
write path is hard-locked twice: ``BINANCE_TRADING`` must be truthy *and* the
caller has to pass ``confirm=True``. A panel kill-switch file
(``BINANCE_KILL_SWITCH_FILE``) is checked on every write; while it exists no order,
cancel or leverage change leaves the process.

Signing
-------
Binance signs ``totalParams`` - the query string for ``GET`` (or the form body for
``POST``/``PUT``/``DELETE``) built in the exact order the parameters are sent -
with HMAC-SHA256 using the API secret as key. ``timestamp`` (milliseconds) is
mandatory, ``recvWindow`` is optional (default 5000 ms, recommended ``<= 5000``),
and ``signature`` must be the **last** parameter. The API key travels in the
``X-MBX-APIKEY`` request header.

Common production-environment rejections
----------------------------------
``-1021``
    "Timestamp for this request is outside of the recvWindow." The local clock is
    behind/ahead of Binance. Call :meth:`BinanceFuturesClient.sync_time` (or use NTP)
    and keep ``recvWindow`` small; do not blindly increase it.
``-2015``
    "Invalid API-key, IP, or permissions for action." Wrong key, key not enabled
    for futures trading, missing IP whitelist on the API key, or missing trade
    permission.
``-1003``
    Too many requests (HTTP ``429``). Back off exponentially. HTTP ``418`` means
    the IP is temporarily banned for ignoring ``429``; stop sending requests.
``503`` with ``"Unknown error, please check your request or try again later."``
    The order may already have executed: the state is **unknown**, so it must not
    be retried as a plain failure. Reconcile with ``query_order``/``open_orders``
    first (this adapter performs no automatic retries).

Credentials come from the environment only and the adapter exposes a masked hint,
never the secret. Logs deliberately never contain the secret or a raw signature.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from ..strategy.costs import CostModel

logger = logging.getLogger(__name__)

LIVE_BASE_URL = "https://fapi.binance.com"
DEFAULT_KILL_SWITCH_FILE = "/etc/binance/KILL"
DEFAULT_RECV_WINDOW = 5000
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_MAX_ORDER_NOTIONAL = 500.0
DEFAULT_MAX_POSITION_NOTIONAL = 3000.0
DEFAULT_MAX_OPEN_ORDERS = 10

#: A limit price further than this fraction from the book mid is rejected.
MAX_PRICE_DEVIATION = 0.05

__all__ = [
    "BinanceFuturesClient",
    "BinanceFuturesConfig",
    "BinanceError",
    "BinanceLocked",
    "LIVE_BASE_URL",
    "MAX_PRICE_DEVIATION",
]


# ---------------------------------------------------------------------------
# environment helpers (same semantics as gridtrade.api.config)
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


POSITION_MODES = ("auto", "oneway", "hedge")


def _position_mode_env() -> str:
    """``BINANCE_POSITION_MODE``: ``auto`` (detect), ``oneway`` or ``hedge``.

    Hedge mode requires ``positionSide=LONG/SHORT`` on every order and forbids
    ``reduceOnly``; one-way mode is the opposite. ``auto`` asks
    ``GET /fapi/v1/positionSide/dual`` once per client.
    """
    raw = _env_str("BINANCE_POSITION_MODE", "auto").lower()
    return raw if raw in POSITION_MODES else "auto"


# ---------------------------------------------------------------------------
# value helpers
# ---------------------------------------------------------------------------


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _num_str(value: float) -> str:
    """Render a quantity/price without scientific notation or trailing zeros."""
    if not math.isfinite(value):
        return str(value)
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text or "0"


def _mask_key(key: str) -> str:
    """Return a first-4 / last-4 hint; short keys are hidden completely."""
    if not key:
        return ""
    if len(key) < 8:
        return "…"
    return f"{key[:4]}…{key[-4:]}"


# ---------------------------------------------------------------------------
# order/fill semantics: open-long / open-short / close-long / close-short
# ---------------------------------------------------------------------------

ACTIONS = ("OPEN_LONG", "OPEN_SHORT", "CLOSE_LONG", "CLOSE_SHORT")
ACTION_LABELS = {
    "OPEN_LONG": "开多",
    "OPEN_SHORT": "开空",
    "CLOSE_LONG": "平多",
    "CLOSE_SHORT": "平空",
}


def classify_action(
    side: str,
    position_side: str | None = None,
    reduce_only: bool = False,
) -> str:
    """Map ``(side, positionSide, reduceOnly)`` to a grid-friendly action.

    Hedge mode (``positionSide=LONG|SHORT``) is unambiguous:
    ``BUY+LONG`` opens a long, ``SELL+LONG`` closes it, ``SELL+SHORT`` opens a
    short and ``BUY+SHORT`` closes it. One-way mode has no ``positionSide``, so
    ``reduceOnly`` decides between open and close.
    """
    side_u = (side or "").strip().upper()
    ps_u = (position_side or "").strip().upper()
    if ps_u == "LONG":
        return "OPEN_LONG" if side_u == "BUY" else "CLOSE_LONG"
    if ps_u == "SHORT":
        return "OPEN_SHORT" if side_u == "SELL" else "CLOSE_SHORT"
    if reduce_only:
        return "CLOSE_LONG" if side_u == "SELL" else "CLOSE_SHORT"
    return "OPEN_LONG" if side_u == "BUY" else "OPEN_SHORT"


def order_view(order: dict[str, Any]) -> dict[str, Any]:
    """Enrich one ``/fapi/v1/order(s)`` row with action + notional."""
    side = str(order.get("side") or "")
    position_side = order.get("positionSide")
    reduce_only = bool(order.get("reduceOnly"))
    price = _opt_float(order.get("price")) or _opt_float(order.get("avgPrice")) or 0.0
    qty = _opt_float(order.get("origQty")) or 0.0
    executed = _opt_float(order.get("executedQty")) or 0.0
    action = classify_action(side, position_side, reduce_only)
    return {
        "orderId": order.get("orderId"),
        "clientOrderId": order.get("clientOrderId"),
        "symbol": order.get("symbol"),
        "side": side,
        "positionSide": position_side,
        "action": action,
        "actionLabel": ACTION_LABELS[action],
        "type": order.get("type"),
        "status": order.get("status"),
        "price": order.get("price"),
        "avgPrice": order.get("avgPrice"),
        "origQty": order.get("origQty"),
        "executedQty": order.get("executedQty"),
        "notional": round(price * (executed or qty), 8),
        "cumQuote": order.get("cumQuote"),
        "time": order.get("time"),
        "updateTime": order.get("updateTime"),
        "reduceOnly": reduce_only,
    }


def fill_view(fill: dict[str, Any]) -> dict[str, Any]:
    """Enrich one ``/fapi/v1/userTrades`` row: action, notional, fee (bp)."""
    side = str(fill.get("side") or "")
    position_side = fill.get("positionSide")
    reduce_only = bool(fill.get("reduceOnly")) or fill.get("realizedPnl") not in (None, "", "0")
    price = _opt_float(fill.get("price")) or 0.0
    qty = _opt_float(fill.get("qty")) or 0.0
    commission = _opt_float(fill.get("commission")) or 0.0
    notional = price * qty
    action = classify_action(side, position_side, reduce_only and not position_side)
    fee_bp = (commission / notional * 10_000.0) if notional else 0.0
    return {
        "id": fill.get("id"),
        "orderId": fill.get("orderId"),
        "symbol": fill.get("symbol"),
        "side": side,
        "positionSide": position_side,
        "action": action,
        "actionLabel": ACTION_LABELS[action],
        "price": fill.get("price"),
        "qty": fill.get("qty"),
        "quoteQty": fill.get("quoteQty"),
        "notional": round(notional, 8),
        "commission": fill.get("commission"),
        "commissionAsset": fill.get("commissionAsset"),
        "feeBp": round(fee_bp, 4),
        "realizedPnl": fill.get("realizedPnl"),
        "maker": fill.get("maker"),
        "time": fill.get("time"),
    }


# ---------------------------------------------------------------------------
# config / errors
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BinanceFuturesConfig:
    """Environment-driven configuration for the Binance production adapter.

    Instantiate directly in tests/callers (defaults are the live endpoint and
    trading locked), or use :meth:`from_env` for deployment.
    """

    base_url: str = LIVE_BASE_URL
    api_key: str = ""
    #: Hidden from ``repr`` so a stray log line cannot leak the signing secret.
    api_secret: str = field(default="", repr=False)
    trading_enabled: bool = False
    recv_window: int = DEFAULT_RECV_WINDOW
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_order_notional: float = DEFAULT_MAX_ORDER_NOTIONAL
    max_position_notional: float = DEFAULT_MAX_POSITION_NOTIONAL
    max_open_orders: int = DEFAULT_MAX_OPEN_ORDERS
    kill_switch_file: str = DEFAULT_KILL_SWITCH_FILE
    position_mode: str = "auto"  # auto | oneway | hedge
    maker_fee_bp: float = 2.0
    taker_fee_bp: float = 5.0
    slippage_bp: float = 0.2

    @property
    def configured(self) -> bool:
        """True when both API key and secret are present."""
        return bool(self.api_key and self.api_secret)

    @classmethod
    def from_env(cls) -> BinanceFuturesConfig:
        return cls(
            base_url=_env_str("BINANCE_BASE_URL", LIVE_BASE_URL).rstrip("/") or LIVE_BASE_URL,
            api_key=os.environ.get("BINANCE_API_KEY", "").strip(),
            api_secret=os.environ.get("BINANCE_API_SECRET", "").strip(),
            trading_enabled=_env_bool("BINANCE_TRADING", False),
            recv_window=_env_int("BINANCE_RECV_WINDOW", DEFAULT_RECV_WINDOW),
            timeout_s=_env_float("BINANCE_TIMEOUT_S", DEFAULT_TIMEOUT_S),
            max_order_notional=_env_float(
                "BINANCE_MAX_ORDER_NOTIONAL", DEFAULT_MAX_ORDER_NOTIONAL
            ),
            max_position_notional=_env_float(
                "BINANCE_MAX_POSITION_NOTIONAL", DEFAULT_MAX_POSITION_NOTIONAL
            ),
            max_open_orders=_env_int("BINANCE_MAX_OPEN_ORDERS", DEFAULT_MAX_OPEN_ORDERS),
            kill_switch_file=_env_str("BINANCE_KILL_SWITCH_FILE", DEFAULT_KILL_SWITCH_FILE),
            position_mode=_position_mode_env(),
            maker_fee_bp=_env_float("BINANCE_MAKER_FEE_BP", 2.0),
            taker_fee_bp=_env_float("BINANCE_TAKER_FEE_BP", 5.0),
            slippage_bp=_env_float("BINANCE_SLIPPAGE_BP", 0.2),
        )


class BinanceError(Exception):
    """A Binance rejection, transport failure or local risk-control rejection.

    ``code`` mirrors the Binance JSON error code (``-1`` when the exchange did not
    supply one, or for purely local rejections); ``http_status`` is the HTTP status
    (``0`` for local/transport failures and for the trading lock).
    """

    def __init__(self, msg: str, *, code: int = -1, http_status: int = 0) -> None:
        super().__init__(msg)
        self.msg = msg
        self.code = int(code)
        self.http_status = int(http_status)


class BinanceLocked(BinanceError):
    """Raised when a write is attempted while ``trading_enabled`` is false."""

    def __init__(self, msg: str = "trading locked: set BINANCE_TRADING=1 to enable orders") -> None:
        super().__init__(msg, code=-1, http_status=403)


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


class BinanceFuturesClient:
    """Small, explicitly-gated client for the Binance USDⓈ-M production API.

    The underlying :class:`httpx.Client` is created once and reused for keep-alive
    connections. Pass ``http`` to inject a client (tests use
    :class:`httpx.MockTransport`); the adapter will not close an injected client.
    """

    def __init__(
        self,
        cfg: BinanceFuturesConfig,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg
        self._clock = clock
        self.server_time_offset_ms: int = 0
        self._dual_side: bool | None = None
        self._owns_http = http is None
        if http is None:
            headers = {"X-MBX-APIKEY": cfg.api_key} if cfg.api_key else {}
            self._http = httpx.Client(
                base_url=cfg.base_url.rstrip("/"),
                timeout=cfg.timeout_s,
                headers=headers,
            )
        else:
            self._http = http
            if cfg.api_key:
                self._http.headers["X-MBX-APIKEY"] = cfg.api_key
        logger.debug("Binance live client created: base_url=%s", cfg.base_url)

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        """Close the HTTP connection pool. Injected clients stay owned by caller."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> BinanceFuturesClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- time / signing --------------------------------------------------

    def _timestamp(self) -> int:
        return int(self._clock() * 1000) + self.server_time_offset_ms

    def sync_time(self) -> int:
        """Fetch ``GET /fapi/v1/time`` and store the server/local millisecond offset.

        Returns the offset in milliseconds (server minus local). Call this after a
        ``-1021`` rejection or on a fresh node whose clock may drift.
        """
        local_ms = int(self._clock() * 1000)
        data = self.time()
        server_ms = _opt_int(data.get("serverTime"))
        if server_ms is None:
            raise BinanceError("Binance time endpoint returned no serverTime")
        self.server_time_offset_ms = server_ms - local_ms
        logger.info("Binance live clock synced: offset=%+d ms", self.server_time_offset_ms)
        return self.server_time_offset_ms

    def _sign(self, params: dict[str, Any]) -> str:
        """HMAC-SHA256 hex over the URL-encoded ``totalParams`` in insertion order."""
        payload = urlencode([(key, str(value)) for key, value in params.items()])
        return hmac.new(
            self.cfg.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    # -- transport -------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        """Send one REST request and return decoded JSON.

        ``GET`` sends parameters in the query string; ``POST``/``PUT``/``DELETE``
        send them as a form body. Signed requests receive ``timestamp`` and
        ``recvWindow`` automatically, then ``signature`` as the final parameter.
        HTTP failures raise :class:`BinanceError` carrying the exchange ``code``,
        ``msg`` and the original ``http_status`` (including ``418``/``429``).
        ``503`` is deliberately *not* retried: the execution state is unknown.
        """
        method = method.upper()
        payload: dict[str, Any] = {
            key: value for key, value in (params or {}).items() if value is not None
        }
        if signed:
            payload["timestamp"] = str(self._timestamp())
            payload["recvWindow"] = str(self.cfg.recv_window)
            payload["signature"] = self._sign(payload)
        headers = {"X-MBX-APIKEY": self.cfg.api_key} if self.cfg.api_key else None
        try:
            if method == "GET":
                response = self._http.request(
                    method, path, params=payload or None, headers=headers
                )
            else:
                response = self._http.request(
                    method, path, data=payload or None, headers=headers
                )
        except httpx.HTTPError as exc:
            logger.warning("Binance live request failed: %s %s (%s)", method, path, exc)
            raise BinanceError(f"Binance network error: {exc}", code=-1) from exc

        status = response.status_code
        if status < 200 or status >= 300:
            code = -1
            body: Any = None
            try:
                body = response.json()
            except ValueError:
                body = None
            message = f"HTTP {status} for {path}"
            if isinstance(body, dict):
                raw_code = body.get("code", -1)
                try:
                    code = int(raw_code)
                except (TypeError, ValueError):
                    code = -1
                detail = body.get("msg") or body.get("message")
                if detail is not None:
                    message = str(detail)
            elif response.text:
                message = response.text[:300]
            if status in {418, 429}:
                logger.warning(
                    "Binance live rate limited/banned: HTTP %s code=%s", status, code
                )
            elif status == 503:
                logger.error(
                    "Binance live HTTP 503, execution status unknown - do not retry blindly: %s",
                    message,
                )
            else:
                logger.warning("Binance live HTTP %s code=%s: %s", status, code, message)
            raise BinanceError(message, code=code, http_status=status)

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise BinanceError(
                f"Binance returned invalid JSON for {path}", http_status=status
            ) from exc

    # -- public reads ----------------------------------------------------

    def time(self) -> dict[str, Any]:
        """``GET /fapi/v1/time`` (public): server time in milliseconds."""
        return _as_dict(self._request("GET", "/fapi/v1/time"))

    def exchange_info(self, symbol: str | None = None) -> dict[str, Any]:
        """``GET /fapi/v1/exchangeInfo`` (public): symbol filters and metadata.

        Binance currently **ignores the ``symbol`` query parameter** on this
        endpoint and always returns the full symbol list, so the filter is applied
        locally here. The returned dict keeps the API shape (``symbols`` list).
        """
        data = _as_dict(self._request("GET", "/fapi/v1/exchangeInfo", None))
        if not symbol:
            return data
        wanted = symbol.strip().upper()
        rows = data.get("symbols")
        if isinstance(rows, list):
            data = {**data, "symbols": [r for r in rows if isinstance(r, dict) and r.get("symbol") == wanted]}
            if not data["symbols"]:
                raise BinanceError(f"symbol {wanted} not found in exchangeInfo", code=-1121)
        return data

    def symbol_filters(self, symbol: str) -> dict[str, float]:
        """Flatten the useful numeric filters for ``symbol``.

        Returns ``step`` (LOT_SIZE stepSize), ``min_qty``, ``tick``
        (PRICE_FILTER tickSize) and ``min_notional`` (MIN_NOTIONAL notional).
        """
        rows = self.exchange_info(symbol).get("symbols") or []
        if not rows:
            raise BinanceError(f"symbol {symbol} not found", code=-1121)
        filters = {f.get("filterType"): f for f in rows[0].get("filters", [])}
        lot = filters.get("LOT_SIZE") or {}
        price_filter = filters.get("PRICE_FILTER") or {}
        notional = filters.get("MIN_NOTIONAL") or {}
        return {
            "step": _opt_float(lot.get("stepSize")) or 0.0,
            "min_qty": _opt_float(lot.get("minQty")) or 0.0,
            "tick": _opt_float(price_filter.get("tickSize")) or 0.0,
            "min_notional": _opt_float(notional.get("notional")) or 0.0,
        }

    # -- signed reads ----------------------------------------------------

    def account(self) -> dict[str, Any]:
        """``GET /fapi/v2/account``: wallet balances and margin summary."""
        return _as_dict(self._request("GET", "/fapi/v2/account", signed=True))

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """``GET /fapi/v2/positionRisk``: all positions (zero-size included)."""
        params = {"symbol": symbol.strip().upper()} if symbol else None
        return _as_list(self._request("GET", "/fapi/v2/positionRisk", params, signed=True))

    def positions_nonzero(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Positions whose ``positionAmt`` is not zero."""
        return [
            row
            for row in self.positions(symbol)
            if abs(_opt_float(row.get("positionAmt")) or 0.0) > 0.0
        ]

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """``GET /fapi/v1/openOrders``: currently working orders."""
        params = {"symbol": symbol.strip().upper()} if symbol else None
        return _as_list(self._request("GET", "/fapi/v1/openOrders", params, signed=True))

    def query_order(self, symbol: str, order_id: int | str) -> dict[str, Any]:
        """``GET /fapi/v1/order``: single order by exchange order id."""
        params = {"symbol": symbol.strip().upper(), "orderId": order_id}
        return _as_dict(self._request("GET", "/fapi/v1/order", params, signed=True))

    def all_orders(self, symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """``GET /fapi/v1/allOrders``: order history (newest last)."""
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol.strip().upper()
        return _as_list(self._request("GET", "/fapi/v1/allOrders", params, signed=True))

    def income(
        self,
        symbol: str | None = None,
        income_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """``GET /fapi/v1/income``: funding fees, commissions, realised PnL."""
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.strip().upper()
        if income_type:
            params["incomeType"] = income_type
        params["limit"] = limit
        return _as_list(self._request("GET", "/fapi/v1/income", params, signed=True))

    def fills(self, symbol: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        """``GET /fapi/v1/userTrades``: recent account fills."""
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol.strip().upper()
        return _as_list(self._request("GET", "/fapi/v1/userTrades", params, signed=True))

    def commission_rate(self, symbol: str) -> dict[str, Any]:
        """``GET /fapi/v1/commissionRate``: this account's real maker/taker fee."""
        params = {"symbol": symbol.strip().upper()}
        return _as_dict(
            self._request("GET", "/fapi/v1/commissionRate", params, signed=True)
        )

    def premium_index(self, symbol: str) -> dict[str, Any]:
        """``GET /fapi/v1/premiumIndex``: mark price + current funding rate (public)."""
        params = {"symbol": symbol.strip().upper()}
        return _as_dict(self._request("GET", "/fapi/v1/premiumIndex", params))

    def dual_side_position(self) -> bool:
        """``GET /fapi/v1/positionSide/dual``: hedge (dual-side) mode flag.

        Hedge mode accounts must send ``positionSide=LONG|SHORT`` on every order
        and must **not** send ``reduceOnly``; sending ``BOTH`` or omitting the
        field is rejected with ``-4061 Order's position side does not match
        user's setting``. Cached per client instance.
        """
        if self._dual_side is None:
            data = _as_dict(
                self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
            )
            self._dual_side = bool(data.get("dualSidePosition"))
        return self._dual_side

    # -- write gates -----------------------------------------------------

    def _kill_switch_active(self) -> bool:
        raw = self.cfg.kill_switch_file.strip()
        if not raw:
            return False
        try:
            return Path(raw).exists()
        except OSError:  # pragma: no cover - defensive
            return False

    def _ensure_trading(self, *, confirm: bool = True) -> None:
        """Enforce the trading lock, the kill switch and the second confirmation.

        ``cancel_order``/``cancel_all``/``set_leverage`` use the default
        ``confirm=True``: only ``place_order`` exposes the flag to its caller.
        """
        if not self.cfg.trading_enabled:
            raise BinanceLocked()
        if self._kill_switch_active():
            raise BinanceError(
                f"kill switch engaged: {self.cfg.kill_switch_file} exists",
                code=-1,
                http_status=403,
            )
        if not confirm:
            raise BinanceError(
                "order confirmation missing: pass confirm=True to submit a write",
                code=-1,
                http_status=403,
            )

    def _book_mid(self, symbol: str) -> float:
        data = _as_dict(
            self._request(
                "GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol}
            )
        )
        bid = _opt_float(data.get("bidPrice"))
        ask = _opt_float(data.get("askPrice"))
        if bid is not None and ask is not None and bid > 0.0 and ask > 0.0:
            return (bid + ask) / 2.0
        if bid is not None and bid > 0.0:
            return bid
        if ask is not None and ask > 0.0:
            return ask
        raise BinanceError(f"{symbol} has no usable bookTicker bid/ask", code=-1)

    # -- writes ----------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        *,
        order_type: str = "LIMIT",
        price: float | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        client_order_id: str | None = None,
        confirm: bool = False,
        position_side: str | None = None,
    ) -> dict[str, Any]:
        """Place one live order after every lock and risk control passes.

        Rejections: trading disabled (:class:`BinanceLocked`), kill switch present,
        ``confirm`` not true, non-positive qty, LIMIT without a positive price,
        notional above ``max_order_notional``, limit price more than
        :data:`MAX_PRICE_DEVIATION` away from the book mid, or the number of open
        orders already at ``max_open_orders``.

        Hedge-mode accounts (``BINANCE_POSITION_MODE=hedge`` or detected ``auto``)
        need ``positionSide``: it is derived from ``side``/``reduce_only`` when not
        given (BUY opens LONG, SELL opens SHORT; reduce-only is the opposite) and
        ``reduceOnly`` is omitted, because Binance rejects it in hedge mode.
        One-way accounts must not send ``positionSide`` at all.
        """
        self._ensure_trading(confirm=confirm)
        cfg = self.cfg
        symbol_u = symbol.strip().upper()
        side_u = side.strip().upper()
        type_u = order_type.strip().upper()
        try:
            qty_value = float(qty)
            price_value = float(price) if price is not None else None
        except (TypeError, ValueError) as exc:
            raise BinanceError("qty/price must be numeric", code=-1) from exc
        if not math.isfinite(qty_value) or qty_value <= 0.0:
            raise BinanceError(f"qty must be positive, got {qty!r}", code=-1)
        if side_u not in {"BUY", "SELL"}:
            raise BinanceError(f"side must be BUY or SELL, got {side!r}", code=-1)
        if type_u not in {"LIMIT", "MARKET"}:
            raise BinanceError(
                f"unsupported order_type {order_type!r} (production adapter: LIMIT/MARKET)",
                code=-1,
            )

        limit_price: float | None = None
        if type_u == "LIMIT":
            if price_value is None or not math.isfinite(price_value) or price_value <= 0.0:
                raise BinanceError("LIMIT order requires a positive price", code=-1)
            limit_price = price_value
            limit_notional = qty_value * limit_price
            if limit_notional > cfg.max_order_notional:
                raise BinanceError(
                    f"order notional {limit_notional:.2f} exceeds limit "
                    f"{cfg.max_order_notional:.2f}",
                    code=-1,
                )

        mark = self._book_mid(symbol_u)
        if limit_price is not None:
            deviation = abs(limit_price - mark) / mark
            if deviation > MAX_PRICE_DEVIATION:
                raise BinanceError(
                    f"limit price {limit_price} deviates {deviation:.2%} from book mid "
                    f"{mark:.8g} (max {MAX_PRICE_DEVIATION:.0%})",
                    code=-1,
                )
        else:
            market_notional = qty_value * mark
            if market_notional > cfg.max_order_notional:
                raise BinanceError(
                    f"market notional {market_notional:.2f} exceeds limit "
                    f"{cfg.max_order_notional:.2f}",
                    code=-1,
                )

        if len(self.open_orders()) >= cfg.max_open_orders:
            raise BinanceError(
                f"open orders already at limit {cfg.max_open_orders}", code=-1
            )

        params: dict[str, Any] = {
            "symbol": symbol_u,
            "side": side_u,
            "type": type_u,
            "quantity": _num_str(qty_value),
        }
        if limit_price is not None:
            params["price"] = _num_str(limit_price)
            params["timeInForce"] = time_in_force.strip().upper()

        mode = (cfg.position_mode or "auto").strip().lower()
        requested_side = position_side.strip().upper() if position_side else None
        if requested_side is not None:
            if requested_side not in {"LONG", "SHORT"}:
                raise BinanceError(
                    f"position_side must be LONG or SHORT, got {position_side!r}", code=-1
                )
            mode = "hedge"
        if mode == "auto":
            try:
                mode = "hedge" if self.dual_side_position() else "oneway"
            except BinanceError as exc:
                logger.warning(
                    "cannot detect position mode (%s); assuming one-way", exc
                )
                mode = "oneway"
        if mode == "hedge":
            if requested_side is None:
                if side_u == "BUY":
                    requested_side = "SHORT" if reduce_only else "LONG"
                else:
                    requested_side = "LONG" if reduce_only else "SHORT"
            params["positionSide"] = requested_side
        else:
            params["reduceOnly"] = "true" if reduce_only else "false"
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        result = _as_dict(self._request("POST", "/fapi/v1/order", params, signed=True))
        logger.info(
            "Binance live order submitted: %s %s %s qty=%s price=%s id=%s",
            symbol_u,
            side_u,
            type_u,
            params["quantity"],
            params.get("price", "MARKET"),
            result.get("orderId"),
        )
        return result

    def cancel_order(self, symbol: str, order_id: int | str) -> dict[str, Any]:
        """``DELETE /fapi/v1/order``: cancel one order (still gated)."""
        self._ensure_trading()
        params = {"symbol": symbol.strip().upper(), "orderId": order_id}
        return _as_dict(self._request("DELETE", "/fapi/v1/order", params, signed=True))

    def cancel_all(self, symbol: str) -> dict[str, Any]:
        """``DELETE /fapi/v1/allOpenOrders``: cancel every order on a symbol."""
        self._ensure_trading()
        params = {"symbol": symbol.strip().upper()}
        return _as_dict(
            self._request("DELETE", "/fapi/v1/allOpenOrders", params, signed=True)
        )

    def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        """``POST /fapi/v1/leverage``: set initial leverage (1-125)."""
        self._ensure_trading()
        try:
            value = int(leverage)
        except (TypeError, ValueError) as exc:
            raise BinanceError(f"leverage must be an integer, got {leverage!r}", code=-1) from exc
        if value < 1 or value > 125:
            raise BinanceError(f"leverage must be between 1 and 125, got {value}", code=-1)
        params = {"symbol": symbol.strip().upper(), "leverage": value}
        return _as_dict(self._request("POST", "/fapi/v1/leverage", params, signed=True))

    # -- status ----------------------------------------------------------

    def cost_report(
        self, spacing_bp: float | None = None, symbol: str | None = None
    ) -> dict[str, Any]:
        """Expected round-trip cost for this account's fee assumptions.

        Real fees always come from the exchange fills (``commission``); this is
        the *planning* estimate used to sanity-check a grid spacing before it is
        deployed. ``spacing_bp`` fills in ``net_edge_bp`` / ``is_profitable``.
        With ``symbol`` the account's **actual** maker/taker rates
        (``/fapi/v1/commissionRate``) and the live funding rate
        (``/fapi/v1/premiumIndex``) replace the configured assumptions.
        """
        model = CostModel(
            maker_fee_bp=self.cfg.maker_fee_bp,
            taker_fee_bp=self.cfg.taker_fee_bp,
            slippage_bp=self.cfg.slippage_bp,
        )
        out: dict[str, Any] = dict(model.describe())
        out["assumed"] = {
            "maker_fee_bp": self.cfg.maker_fee_bp,
            "taker_fee_bp": self.cfg.taker_fee_bp,
            "slippage_bp": self.cfg.slippage_bp,
        }
        if symbol:
            try:
                rates = self.commission_rate(symbol)
                premium = self.premium_index(symbol)
                maker_bp = _opt_float(rates.get("makerCommissionRate"))
                taker_bp = _opt_float(rates.get("takerCommissionRate"))
                funding = _opt_float(premium.get("lastFundingRate"))
                real_model = CostModel(
                    maker_fee_bp=(maker_bp * 1e4) if maker_bp is not None else self.cfg.maker_fee_bp,
                    taker_fee_bp=(taker_bp * 1e4) if taker_bp is not None else self.cfg.taker_fee_bp,
                    slippage_bp=self.cfg.slippage_bp,
                    funding_rate_8h=funding if funding is not None else 0.0,
                    funding_interval_h=8.0,
                )
                out["actual"] = {
                    "symbol": symbol.strip().upper(),
                    "maker_fee_bp": maker_bp * 1e4 if maker_bp is not None else None,
                    "taker_fee_bp": taker_bp * 1e4 if taker_bp is not None else None,
                    "funding_rate_8h": funding,
                    "funding_bp_per_8h": (funding * 1e4) if funding is not None else None,
                    "round_trip_maker_bp": real_model.round_trip_bp(entry_taker=False, exit_taker=False),
                    "round_trip_taker_bp": real_model.round_trip_bp(entry_taker=True, exit_taker=True),
                    "round_trip_taker_8h_bp": real_model.round_trip_bp(
                        entry_taker=True, exit_taker=True, hold_hours=8.0
                    ),
                    "breakeven_spacing_bp": real_model.breakeven_spacing_bp(
                        entry_taker=False, exit_taker=False
                    ),
                }
                if maker_bp is not None and taker_bp is not None:
                    model = real_model
            except Exception as exc:  # noqa: BLE001 - real fees are best-effort
                out["actual_error"] = str(exc)[:160]
        if spacing_bp is not None:
            out["spacing_bp"] = spacing_bp
            out["round_trip_bp"] = model.round_trip_bp(entry_taker=False, exit_taker=False)
            out["net_edge_bp"] = model.net_edge_bp(
                spacing_bp, entry_taker=False, exit_taker=False
            )
            out["is_profitable"] = model.is_profitable(
                spacing_bp, entry_taker=False, exit_taker=False
            )
        return out

    def health(self) -> dict[str, Any]:
        """Offline-safe summary plus one ``GET /fapi/v1/time`` reachability probe."""
        info: dict[str, Any] = {
            "configured": self.cfg.configured,
            "trading_enabled": self.cfg.trading_enabled,
            "base_url": self.cfg.base_url,
            "kill_switch": self._kill_switch_active(),
            "server_offset_ms": self.server_time_offset_ms,
            "position_mode": self.cfg.position_mode,
            "dual_side_position": self._dual_side,
            "cost": self.cost_report(),
            "reachable": False,
        }
        try:
            info["server_time"] = self.time()
            info["reachable"] = True
        except Exception as exc:  # noqa: BLE001 - health must never raise
            logger.warning("Binance live health probe failed: %s", exc)
            info["error"] = f"Binance live unreachable: {exc}"
        return info

    def masked(self) -> dict[str, Any]:
        """Configuration hint safe to expose through an API: never the secret."""
        return {
            "api_key_hint": _mask_key(self.cfg.api_key),
            "has_secret": bool(self.cfg.api_secret),
        }
