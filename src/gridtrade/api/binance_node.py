"""Read-only HTTP client for the tunnel-only Binance execution adapter.

The adapter runs on the Tokyo node and binds **only** the WireGuard address
(``10.66.0.2:8100`` by default), so the panel reaches it through the tunnel.
This module is intentionally thin: no signing, no credentials — the adapter owns
the API key and the trading lock. The panel can only read.

Set ``GRIDTRADE_BINANCE_NODE_URL`` (e.g. ``http://10.66.0.2:8100``) to enable;
when empty the routes answer 503 and the page shows "未配置".
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_NODE_URL = "http://10.66.0.2:8100"
DEFAULT_TIMEOUT_S = 8.0


class BinanceNodeError(Exception):
    """Node unreachable, timed out, or answered with an error payload."""

    def __init__(self, msg: str, *, status: int = 0, code: int | str | None = None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.status = status
        self.code = code


class BinanceNodeClient:
    """Small JSON client for ``/healthz``, ``/account``, ``/positions``, ``/open_orders``."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        http: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.Client(
            base_url=self.base_url, timeout=timeout_s, headers={"Accept": "application/json"}
        )

    # -- plumbing --------------------------------------------------------
    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> BinanceNodeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._http.get(path, params=params or None)
        except httpx.HTTPError as exc:
            raise BinanceNodeError(f"节点不可达: {exc}") from exc
        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400:
            msg = "节点返回错误"
            code = None
            if isinstance(payload, dict):
                msg = str(payload.get("msg") or payload.get("error") or msg)
                code = payload.get("code")
            raise BinanceNodeError(msg, status=response.status_code, code=code)
        if not isinstance(payload, dict):
            raise BinanceNodeError("节点返回了非 JSON 响应", status=response.status_code)
        return payload

    # -- reads -----------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return self._get("/healthz")

    def account(self) -> dict[str, Any]:
        return self._get("/account")

    def positions(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol.upper()} if symbol else None
        return self._get("/positions", params)

    def open_orders(self, symbol: str | None = None) -> dict[str, Any]:
        params = {"symbol": symbol.upper()} if symbol else None
        return self._get("/open_orders", params)

    def fills(self, symbol: str | None = None, limit: int = 20) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._get("/fills", params)

    def all_orders(self, symbol: str | None = None, limit: int = 20) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._get("/orders", params)
