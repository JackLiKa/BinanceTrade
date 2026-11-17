"""Best-effort live market snapshot from Binance USDⓈ-M futures.

Research never depends on this call: when the exchange or the network is
unreachable the caller falls back to the last bar in the local dataset and the
UI labels the source explicitly.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

FAPI = "https://fapi.binance.com"
CACHE_SECONDS = 3.0


class LiveMarket:
    def __init__(
        self, *, enabled: bool = True, proxy: str = "", failure_ttl: float = 60.0
    ) -> None:
        self.enabled = enabled
        self.proxy = proxy or None
        self.failure_ttl = failure_ttl
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0
        self._failure: dict[str, Any] | None = None
        self._failure_at = 0.0
        self._lock = asyncio.Lock()

    async def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=FAPI,
                proxy=self.proxy,
                timeout=httpx.Timeout(3.0, connect=1.5),
                headers={"User-Agent": "gridtrade/0.1 research-dashboard"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _offline(self, symbol: str, error: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "mark_price": None,
            "index_price": None,
            "last_price": None,
            "change_24h_pct": None,
            "high_24h": None,
            "low_24h": None,
            "volume_24h": None,
            "quote_volume_24h": None,
            "last_funding_rate": None,
            "next_funding_time": None,
            "source": "offline",
            "updated_at": round(time.time(), 3),
            "error": error,
        }

    async def snapshot(self, symbol: str) -> dict[str, Any]:
        if not self.enabled:
            return self._offline(symbol, "live market disabled")
        async with self._lock:
            now = time.monotonic()
            if self._cache is not None and now - self._cache_at < CACHE_SECONDS:
                return self._cache
            if self._failure is not None and now - self._failure_at < self.failure_ttl:
                return self._failure
            try:
                snapshot = await self._fetch(symbol)
            except Exception as exc:  # exchange unreachable: fail fast and cache it
                snapshot = self._offline(symbol, str(exc)[:200])
                self._failure = snapshot
                self._failure_at = now
                return snapshot
            if snapshot.get("source") == "binance":
                self._cache = snapshot
                self._cache_at = now
            return snapshot

    async def _fetch(self, symbol: str) -> dict[str, Any]:
        now = time.time()
        try:
            client = await self.client()
            premium, ticker = await asyncio.gather(
                client.get("/fapi/v1/premiumIndex", params={"symbol": symbol}),
                client.get("/fapi/v1/ticker/24hr", params={"symbol": symbol}),
            )
            premium.raise_for_status()
            ticker.raise_for_status()
            p = premium.json()
            t = ticker.json()
            next_funding = p.get("nextFundingTime")
            return {
                "symbol": symbol,
                "mark_price": _float(p.get("markPrice")),
                "index_price": _float(p.get("indexPrice")),
                "last_price": _float(t.get("lastPrice")),
                "change_24h_pct": _float(t.get("priceChangePercent")),
                "high_24h": _float(t.get("highPrice")),
                "low_24h": _float(t.get("lowPrice")),
                "volume_24h": _float(t.get("volume")),
                "quote_volume_24h": _float(t.get("quoteVolume")),
                "last_funding_rate": _float(p.get("lastFundingRate")),
                "next_funding_time": _iso_ms(next_funding),
                "exchange_time": _iso_ms(p.get("time")),
                "source": "binance",
                "updated_at": round(now, 3),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - network is optional for research
            return {
                "symbol": symbol,
                "source": "offline",
                "updated_at": round(now, 3),
                "error": f"{type(exc).__name__}: {exc}"[:200],
            }


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_ms(value: Any) -> str | None:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
