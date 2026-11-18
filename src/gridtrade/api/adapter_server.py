"""Internal HTTP surface for the Tokyo execution node.

Runs on the WireGuard tunnel address only (default ``10.66.0.2:8100``) so nothing
is reachable from the public internet. Deliberately dependency-light: stdlib
``http.server`` + the :mod:`gridtrade.api.binance_demo` client.

Routes
------
``GET  /healthz``      adapter state (no secret), plus public ``time`` reachability
``GET  /market/ping``  public demo/live ``time`` + ``premiumIndex`` sample
``GET  /account``      signed read (requires configured key)
``GET  /positions``    signed read, non-zero positions only
``GET  /open_orders``  signed read
``POST /order``        write path, triple-locked (trading flag + kill switch + confirm)

The service never logs the secret, the signature, or full request bodies.
"""

from __future__ import annotations

import json
import logging
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from gridtrade.api.binance_demo import (
    ACTION_LABELS,
    BinanceDemoClient,
    BinanceDemoConfig,
    BinanceError,
    BinanceLocked,
    fill_view,
    order_view,
)
from gridtrade.api.binance_reconcile import Reconciler, build_from_env

logger = logging.getLogger("gridtrade.adapter")

_reconciler: Reconciler | None = None


def _client() -> BinanceDemoClient:
    cfg = BinanceDemoConfig.from_env()
    return BinanceDemoClient(cfg)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _recon() -> Reconciler | None:
    return _reconciler


class Handler(BaseHTTPRequestHandler):
    server_version = "gridtrade-adapter/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401 - stdlib hook
        logger.info("%s - %s", self.address_string(), fmt % args)

    # -- helpers ---------------------------------------------------------
    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, exc: BinanceError) -> None:
        status = HTTPStatus.BAD_REQUEST
        if isinstance(exc, BinanceLocked):
            status = HTTPStatus.FORBIDDEN
        elif exc.http_status == 401:
            status = HTTPStatus.UNAUTHORIZED
        elif exc.http_status in (418, 429):
            status = HTTPStatus.TOO_MANY_REQUESTS
        elif exc.http_status and 400 <= exc.http_status < 600:
            status = HTTPStatus(exc.http_status)
        self._send(int(status), {"ok": False, "code": exc.code, "msg": exc.msg})

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        symbol = (query.get("symbol") or [None])[0]
        try:
            with _client() as client:
                if route == "/healthz":
                    recon = _recon()
                    payload = {"ok": True, **client.health()}
                    if recon is not None:
                        payload["reconcile"] = {
                            "last_run_at": recon.last_run_at,
                            "last_error": recon.last_error,
                            "auto_kill": bool(recon.auto_kill_file),
                            "alerts": recon.alerts(3),
                        }
                    self._send(HTTPStatus.OK, payload)
                    return
                if route == "/cost":
                    sym = (symbol or "DOGEUSDT").upper()
                    self._send(
                        HTTPStatus.OK,
                        {"ok": True, "symbol": sym, **client.cost_report(symbol=sym)},
                    )
                    return
                if route == "/alerts":
                    recon = _recon()
                    if recon is None:
                        self._send(HTTPStatus.OK, {"ok": True, "alerts": []})
                        return
                    self._send(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "alerts": recon.alerts(50),
                            "last_run_at": recon.last_run_at,
                            "last_error": recon.last_error,
                        },
                    )
                    return
                if route == "/ledger":
                    recon = _recon()
                    if recon is None:
                        self._send(HTTPStatus.OK, {"ok": True, "open": [], "total": 0})
                        return
                    opened = recon.ledger.open_entries()
                    self._send(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "open": list(opened.values()),
                            "total": len(recon.ledger.all_entries()),
                        },
                    )
                    return
                if route == "/market/candles":
                    sym = (symbol or "BTCUSDT").upper()
                    interval = str((query.get("interval") or ["1m"])[0])
                    limit = max(1, min(1500, int((query.get("limit") or ["500"])[0])))
                    raw = client._request(  # public market data
                        "GET",
                        "/fapi/v1/klines",
                        {"symbol": sym, "interval": interval, "limit": limit},
                    )
                    points = [
                        [
                            int(row[0]) // 1000 if row[0] > 1e11 else int(row[0]),
                            float(row[1]),
                            float(row[2]),
                            float(row[3]),
                            float(row[4]),
                            float(row[5]),
                        ]
                        for row in (raw or [])
                        if isinstance(row, (list, tuple)) and len(row) >= 6
                    ]
                    self._send(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "symbol": sym,
                            "interval": interval,
                            "count": len(points),
                            "from": points[0][0] if points else None,
                            "to": points[-1][0] if points else None,
                            "candles": points,
                            "source": "node",
                        },
                    )
                    return
                if route == "/market/leverage-bracket":
                    sym = (symbol or "BTCUSDT").upper()
                    payload = client._request(
                        "GET", "/fapi/v1/leverageBracket", {"symbol": sym}, signed=True
                    )
                    rows = payload if isinstance(payload, list) else payload.get("symbols", [])
                    item = rows[0] if rows else {}
                    brackets = item.get("brackets") or []
                    normalized = [
                        {
                            "bracket": int(b.get("bracket") or index + 1),
                            "initial_leverage": int(b.get("initialLeverage") or 0),
                            "notional_floor": float(b.get("notionalFloor") or 0.0),
                            "notional_cap": float(b.get("notionalCap") or 0.0),
                            "mmr": float(b.get("maintMarginRatio") or 0.0),
                            "cum": float(b.get("cum") or 0.0),
                        }
                        for index, b in enumerate(brackets)
                    ]
                    self._send(
                        HTTPStatus.OK,
                        {"ok": True, "symbol": sym, "brackets": normalized},
                    )
                    return
                if route == "/market/contract":
                    sym = (symbol or "BTCUSDT").upper()
                    filt = client.symbol_filters(sym)
                    premium = client.premium_index(sym)
                    maker_bp = float(os.environ.get("BINANCE_MAKER_FEE_BP", "2") or 2)
                    taker_bp = float(os.environ.get("BINANCE_TAKER_FEE_BP", "5") or 5)
                    next_ms = int(premium.get("nextFundingTime") or 0)
                    self._send(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "symbol": sym,
                            "order_price_round": filt["tick"] or 0.01,
                            "quanto_multiplier": filt["step"] or 0.01,
                            "order_size_min": filt["min_qty"] or filt["step"] or 0.01,
                            "maker_fee_rate": maker_bp / 10_000.0,
                            "taker_fee_rate": taker_bp / 10_000.0,
                            "funding_next_apply": next_ms // 1000 if next_ms else 0,
                            "funding_interval": 28_800,
                            "liquidation_fee": float(
                        (client.exchange_info(sym).get("symbols") or [{}])[0].get(
                            "liquidationFee", 0.0
                        )
                        or 0.0
                    ),
                    "exchange": "binance",
                        },
                    )
                    return
                if route == "/market/tickers":
                    raw_symbols = (query.get("symbols") or [""])[0]
                    wanted = [item.strip().upper() for item in raw_symbols.split(",") if item.strip()]
                    if not wanted:
                        wanted = [(symbol or "BTCUSDT").upper()]
                    rows = []
                    for sym in wanted:
                        premium = client.premium_index(sym)
                        ticker = client._request("GET", "/fapi/v1/ticker/24hr", {"symbol": sym}) or {}
                        rows.append(
                            {
                                "contract": sym,
                                "mark_price": float(premium.get("markPrice") or 0.0),
                                "index_price": float(premium.get("indexPrice") or 0.0),
                                "change_percentage": float(ticker.get("priceChangePercent") or 0.0),
                                "funding_rate": float(premium.get("lastFundingRate") or 0.0),
                                "next_funding_time": int(premium.get("nextFundingTime") or 0),
                            }
                        )
                    self._send(HTTPStatus.OK, {"ok": True, "tickers": rows})
                    return
                if route == "/market/funding":
                    sym = (symbol or "BTCUSDT").upper()
                    limit = max(1, min(1000, int((query.get("limit") or ["300"])[0])))
                    raw = client._request(  # public market data
                        "GET",
                        "/fapi/v1/fundingRate",
                        {"symbol": sym, "limit": limit},
                    )
                    points = [
                        [
                            int(row.get("fundingTime", 0)) // 1000,
                            float(row.get("fundingRate") or 0.0),
                            float(row["markPrice"]) if row.get("markPrice") not in (None, "") else None,
                        ]
                        for row in (raw or [])
                        if isinstance(row, dict)
                    ]
                    self._send(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "symbol": sym,
                            "count": len(points),
                            "funding": points,
                            "source": "node",
                        },
                    )
                    return
                if route == "/market/snapshot":
                    sym = (symbol or "BTCUSDT").upper()
                    now_ms = int(time.time() * 1000)
                    premium = client._request(
                        "GET", "/fapi/v1/premiumIndex", {"symbol": sym}
                    )
                    ticker = client._request(
                        "GET", "/fapi/v1/ticker/24hr", {"symbol": sym}
                    )
                    self._send(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "symbol": sym,
                            "mark_price": _num(premium.get("markPrice")),
                            "index_price": _num(premium.get("indexPrice")),
                            "last_price": _num(ticker.get("lastPrice")),
                            "change_24h_pct": _num(ticker.get("priceChangePercent")),
                            "high_24h": _num(ticker.get("highPrice")),
                            "low_24h": _num(ticker.get("lowPrice")),
                            "volume_24h": _num(ticker.get("volume")),
                            "quote_volume_24h": _num(ticker.get("quoteVolume")),
                            "last_funding_rate": _num(premium.get("lastFundingRate")),
                            "next_funding_time": premium.get("nextFundingTime"),
                            "exchange_time": premium.get("time"),
                            "fetched_at": now_ms,
                            "source": "node",
                        },
                    )
                    return
                if route == "/market/ping":
                    out: dict[str, Any] = {"ok": True, "base_url": client.cfg.base_url}
                    try:
                        out["time"] = client.time()
                        out["server_offset_ms"] = client.sync_time()
                        data = client._request(  # public market data
                            "GET", "/fapi/v1/premiumIndex", {"symbol": symbol or "BTCUSDT"}
                        )
                        keep = ("symbol", "markPrice", "indexPrice", "lastFundingRate", "nextFundingTime")
                        out["premium_index"] = {k: data.get(k) for k in keep if isinstance(data, dict)}
                    except BinanceError as exc:
                        out["reachable"] = False
                        out["error"] = {"code": exc.code, "msg": exc.msg}
                        self._send(HTTPStatus.BAD_GATEWAY, out)
                        return
                    out["reachable"] = True
                    self._send(HTTPStatus.OK, out)
                    return
                if route == "/account":
                    self._send(HTTPStatus.OK, {"ok": True, "account": client.account()})
                    return
                if route == "/positions":
                    self._send(HTTPStatus.OK, {"ok": True, "positions": client.positions_nonzero(symbol)})
                    return
                if route == "/open_orders":
                    rows = [order_view(row) for row in client.open_orders(symbol)]
                    self._send(HTTPStatus.OK, {"ok": True, "orders": rows})
                    return
                if route == "/orders":
                    limit = int((query.get("limit") or ["50"])[0])
                    rows = [order_view(row) for row in client.all_orders(symbol, limit=limit)]
                    rows.sort(key=lambda row: row.get("time") or 0, reverse=True)
                    self._send(
                        HTTPStatus.OK,
                        {"ok": True, "orders": rows, "actions": ACTION_LABELS},
                    )
                    return
                if route == "/fills":
                    limit = int((query.get("limit") or ["50"])[0])
                    rows = [fill_view(row) for row in client.fills(symbol, limit=limit)]
                    rows.sort(key=lambda row: row.get("time") or 0, reverse=True)
                    self._send(
                        HTTPStatus.OK,
                        {"ok": True, "fills": rows, "actions": ACTION_LABELS},
                    )
                    return
                self._send(HTTPStatus.NOT_FOUND, {"ok": False, "msg": "unknown route"})
        except BinanceError as exc:
            self._err(exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("unhandled error")
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "msg": str(exc)})

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "msg": "invalid json"})
            return

        if route == "/cancel":
            symbol = str(payload.get("symbol", ""))
            order_id = payload.get("orderId")
            ok = bool(payload.get("confirm", False))
            try:
                with _client() as client:
                    if not ok:
                        raise BinanceError("cancel confirmation missing: pass confirm=true", code=-1)
                    result = client.cancel_order(symbol, order_id)
                recon = _recon()
                if recon is not None:
                    recon.ledger.mark_closed(order_id, str(result.get("status") or "CANCELED"))
                self._send(HTTPStatus.OK, {"ok": True, "order": result})
            except BinanceError as exc:
                self._err(exc)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("unhandled error")
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "msg": str(exc)})
            return

        if route == "/cancel_all":
            symbol = str(payload.get("symbol", ""))
            ok = bool(payload.get("confirm", False))
            try:
                with _client() as client:
                    if not ok:
                        raise BinanceError("cancel confirmation missing: pass confirm=true", code=-1)
                    result = client.cancel_all(symbol)
                recon = _recon()
                if recon is not None:
                    for key in list(recon.ledger.open_entries()):
                        recon.ledger.mark_closed(key, "CANCELED")
                self._send(HTTPStatus.OK, {"ok": True, "result": result})
            except BinanceError as exc:
                self._err(exc)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("unhandled error")
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "msg": str(exc)})
            return

        if route != "/order":
            self._send(HTTPStatus.NOT_FOUND, {"ok": False, "msg": "unknown route"})
            return
        try:
            with _client() as client:
                order = client.place_order(
                    symbol=str(payload.get("symbol", "")),
                    side=str(payload.get("side", "")),
                    qty=float(payload.get("qty", 0) or 0),
                    order_type=str(payload.get("type", "LIMIT")),
                    price=payload.get("price"),
                    time_in_force=str(payload.get("tif", "GTC")),
                    reduce_only=bool(payload.get("reduce_only", False)),
                    confirm=bool(payload.get("confirm", False)),
                    position_side=payload.get("positionSide"),
                )
                recon = _recon()
                if recon is not None:
                    recon.ledger.record_order(order)
                self._send(HTTPStatus.OK, {"ok": True, "order": order})
        except BinanceError as exc:
            self._err(exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("unhandled error")
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "msg": str(exc)})


def main() -> None:
    global _reconciler
    logging.basicConfig(
        level=os.environ.get("ADAPTER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        _reconciler = build_from_env()
        interval = float(os.environ.get("ADAPTER_RECONCILE_SECONDS", "15") or 15)
        _reconciler.start(interval_s=interval)
    except Exception:  # noqa: BLE001 - never block the HTTP surface
        logger.exception("reconciler failed to start; continuing without it")
        _reconciler = None
    bind = os.environ.get("ADAPTER_BIND", "10.66.0.2")
    port = int(os.environ.get("ADAPTER_PORT", "8100"))
    httpd = ThreadingHTTPServer((bind, port), Handler)
    logger.info("adapter listening on http://%s:%s", bind, port)
    try:
        httpd.serve_forever()
    finally:
        if _reconciler is not None:
            _reconciler.stop()


if __name__ == "__main__":
    main()
