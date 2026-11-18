"""Generic Binance REST gateway (spot / USDⓈ-M / COIN-M / options / wallet).

Read paths may target any official endpoint for the selected product.  Write
paths are restricted to trading controls only (orders, cancels, leverage,
position mode); withdrawals, transfers, sub-account and API-key management are
never accepted here.  Funds movement lives in ``scripts/binance_cli.py`` only.

The gateway never logs the secret or signature.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

PRODUCTS: dict[str, str] = {
    "spot": "https://api.binance.com",
    "usdm": "https://fapi.binance.com",
    "coinm": "https://dapi.binance.com",
    "options": "https://eapi.binance.com",
    "wallet": "https://api.binance.com",
}

# Write paths are explicit.  No /sapi/v1/capital/withdraw, /sapi/v1/asset/transfer,
# /sapi/v1/sub-account, /sapi/v1/account/apiRestrictions here by design.
WRITE_PREFIXES: dict[str, tuple[str, ...]] = {
    "spot": ("/api/v3/order", "/api/v3/openOrders", "/api/v3/allOrders"),
    "usdm": (
        "/fapi/v1/order",
        "/fapi/v1/allOpenOrders",
        "/fapi/v1/leverage",
        "/fapi/v1/positionSide/dual",
        "/fapi/v1/multiAssetsMargin",
    ),
    "coinm": (
        "/dapi/v1/order",
        "/dapi/v1/allOpenOrders",
        "/dapi/v1/leverage",
        "/dapi/v1/positionSide/dual",
    ),
    "options": (
        "/eapi/v1/order",
        "/eapi/v1/batchOrders",
        "/eapi/v1/allOpenOrders",
        "/eapi/v1/positionSide/dual",
    ),
    "wallet": (),
}

BLOCKED_PREFIXES = (
    "/sapi/v1/capital/withdraw",
    "/sapi/v1/asset/transfer",
    "/sapi/v1/sub-account",
    "/sapi/v1/account/apiRestrictions",
    "/sapi/v1/account/apiTradingStatus",
)


class BinanceGatewayError(Exception):
    def __init__(self, msg: str, *, status: int = 400, code: int | str | None = None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.status = status
        self.code = code


@dataclass(slots=True)
class BinanceGateway:
    api_key: str = ""
    api_secret: str = ""
    trading_enabled: bool = False
    kill_switch_file: str = "/etc/binance/KILL"
    timeout_s: float = 15.0
    allow_funds: bool = False  # local CLI only; never enabled by HTTP gateway

    @classmethod
    def from_env(cls) -> "BinanceGateway":
        return cls(
            api_key=os.environ.get("BINANCE_API_KEY", "").strip(),
            api_secret=os.environ.get("BINANCE_API_SECRET", "").strip(),
            trading_enabled=os.environ.get("BINANCE_TRADING", "").strip().lower()
            in {"1", "true", "yes", "on"},
            kill_switch_file=os.environ.get("BINANCE_KILL_SWITCH_FILE", "/etc/binance/KILL"),
            allow_funds=False,
        )

    def _check_write(self, product: str, path: str, confirm: bool) -> None:
        if product not in PRODUCTS:
            raise BinanceGatewayError(f"unknown product: {product}")
        if any(path.startswith(prefix) for prefix in BLOCKED_PREFIXES):
            raise BinanceGatewayError("fund-moving endpoints are CLI-only", status=403)
        if not self.trading_enabled and not self.allow_funds:
            raise BinanceGatewayError("trading locked: set BINANCE_TRADING=1", status=403)
        if not confirm:
            raise BinanceGatewayError("write confirmation missing: pass confirm=true", status=403)
        prefixes = WRITE_PREFIXES.get(product, ())
        if self.allow_funds and product == "wallet":
            return
        if not any(path.startswith(prefix) for prefix in prefixes):
            raise BinanceGatewayError(f"write path not allowed: {path}", status=403)
        try:
            if os.path.exists(self.kill_switch_file):
                raise BinanceGatewayError(f"kill switch active: {self.kill_switch_file}", status=403)
        except OSError:
            pass

    def request(
        self,
        product: str,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        product = product.strip().lower()
        method = method.strip().upper()
        if product not in PRODUCTS:
            raise BinanceGatewayError(f"unknown product: {product}")
        if not path.startswith("/"):
            raise BinanceGatewayError("path must start with /")
        if method not in {"GET", "POST", "PUT", "DELETE"}:
            raise BinanceGatewayError(f"method not allowed: {method}")
        if any(path.startswith(prefix) for prefix in BLOCKED_PREFIXES) and not (
            self.allow_funds and product == "wallet"
        ):
            raise BinanceGatewayError("fund-moving endpoints are CLI-only", status=403)
        if method != "GET":
            self._check_write(product, path, confirm)
        if signed and (not self.api_key or not self.api_secret):
            raise BinanceGatewayError("API credentials not configured", status=503)

        payload: dict[str, Any] = {str(k): v for k, v in (params or {}).items() if v is not None}
        headers = {"Accept": "application/json"}
        if signed:
            payload["timestamp"] = int(time.time() * 1000)
            payload.setdefault("recvWindow", 5000)
            query = urlencode(payload, doseq=True)
            signature = hmac.new(
                self.api_secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()
            query = f"{query}&signature={signature}"
            headers["X-MBX-APIKEY"] = self.api_key
            url = PRODUCTS[product] + path + "?" + query
            request_kwargs: dict[str, Any] = {}
        else:
            url = PRODUCTS[product] + path
            request_kwargs = (
                {"params": payload} if method == "GET" else {"data": payload}
            )
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout_s, connect=5.0)) as client:
                response = client.request(method, url, headers=headers, **request_kwargs)
        except httpx.HTTPError as exc:
            raise BinanceGatewayError(f"Binance request failed: {exc}", status=502) from exc
        try:
            data = response.json()
        except ValueError:
            data = response.text
        if response.status_code >= 400:
            code = data.get("code") if isinstance(data, dict) else None
            msg = data.get("msg") if isinstance(data, dict) else str(data)
            raise BinanceGatewayError(str(msg), status=response.status_code, code=code)
        return {
            "ok": True,
            "product": product,
            "method": method,
            "path": path,
            "status": response.status_code,
            "data": data,
        }
