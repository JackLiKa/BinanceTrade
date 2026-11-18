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
        self,
        *,
        enabled: bool = True,
        proxy: str = "",
        failure_ttl: float = 60.0,
        node_url: str = "",
    ) -> None:
        self.enabled = enabled
        self.proxy = proxy or None
        self.failure_ttl = failure_ttl
        # Tokyo execution node (WireGuard tunnel) can reach Binance even when this
        # host cannot; when set it is the preferred market-data source.
        self.node_url = (node_url or "").rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._node_client: httpx.AsyncClient | None = None
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0
        self._failure: dict[str, Any] | None = None
        self._failure_at = 0.0
        self._candle_cache: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    @property
    def node_enabled(self) -> bool:
        return bool(self.node_url)

    async def node_client(self) -> httpx.AsyncClient:
        if self._node_client is None or self._node_client.is_closed:
            self._node_client = httpx.AsyncClient(
                base_url=self.node_url,
                timeout=httpx.Timeout(8.0, connect=2.0),
                headers={"User-Agent": "gridtrade/0.1 research-dashboard"},
            )
        return self._node_client

    async def node_candles(
        self, symbol: str, interval: str, limit: int
    ) -> dict[str, Any] | None:
        """K-lines from the tunnel node (real-time, ~55ms away). Cached for 2s."""
        if not self.node_url:
            return None
        key = (symbol, interval, int(limit))
        now = time.monotonic()
        cached = self._candle_cache.get(key)
        if cached is not None and now - cached[0] < 2.0:
            return cached[1]
        try:
            client = await self.node_client()
            response = await client.get(
                "/market/candles",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:  # noqa: BLE001 - node optional
            return None
        if not isinstance(payload, dict) or not payload.get("candles"):
            return None
        payload["source"] = "node"
        payload["fetched_at"] = round(time.time(), 3)
        self._candle_cache[key] = (now, payload)
        return payload

    async def node_funding(self, symbol: str, limit: int = 300) -> dict[str, Any] | None:
        if not self.node_url:
            return None
        try:
            client = await self.node_client()
            response = await client.get(
                "/market/funding", params={"symbol": symbol, "limit": limit}
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:  # noqa: BLE001 - node optional
            return None
        if not isinstance(payload, dict) or not payload.get("funding"):
            return None
        payload["source"] = "node"
        return payload

    async def node_insurance_balance(self, symbol: str | None = None) -> dict[str, Any] | None:
        if not self.node_url:
            return None
        try:
            client = await self.node_client()
            response = await client.get(
                "/market/insurance-balance", params={"symbol": symbol} if symbol else None
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:  # noqa: BLE001 - node optional
            return None
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        assets = payload.get("assets") or []
        usdt = next(
            (item for item in assets if str(item.get("asset", "")).upper() == "USDT"),
            None,
        )
        try:
            balance = float(usdt.get("marginBalance", 0)) if usdt else 0.0
        except (TypeError, ValueError):
            balance = 0.0
        return {
            "balance_usdt": balance,
            "assets": assets,
            "symbols_count": payload.get("symbols_count"),
            "source": "node",
            "updated_at": round(time.time(), 3),
        }

    async def node_adl_risk(self, symbol: str) -> dict[str, Any] | None:
        if not self.node_url:
            return None
        try:
            client = await self.node_client()
            response = await client.get("/market/adl-risk", params={"symbol": symbol})
            response.raise_for_status()
            payload = response.json()
        except Exception:  # noqa: BLE001 - node optional
            return None
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        data = payload.get("data") or {}
        return {
            "symbol": symbol,
            "adl_risk": str(data.get("adlRisk") or "").lower() or None,
            "update_time": data.get("updateTime"),
            "source": "node",
        }

    async def node_snapshot(self, symbol: str) -> dict[str, Any] | None:
        if not self.node_url:
            return None
        try:
            client = await self.node_client()
            response = await client.get("/market/snapshot", params={"symbol": symbol})
            response.raise_for_status()
            payload = response.json()
        except Exception:  # noqa: BLE001 - node optional
            return None
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        return {
            "symbol": symbol,
            "mark_price": payload.get("mark_price"),
            "index_price": payload.get("index_price"),
            "last_price": payload.get("last_price"),
            "change_24h_pct": payload.get("change_24h_pct"),
            "high_24h": payload.get("high_24h"),
            "low_24h": payload.get("low_24h"),
            "volume_24h": payload.get("volume_24h"),
            "quote_volume_24h": payload.get("quote_volume_24h"),
            "last_funding_rate": payload.get("last_funding_rate"),
            "next_funding_time": _iso_ms(payload.get("next_funding_time")),
            "exchange_time": _iso_ms(payload.get("exchange_time")),
            "source": "node",
            "updated_at": round(time.time(), 3),
            "error": None,
        }

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
            node = await self.node_snapshot(symbol)
            if node is not None:
                return node
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
            if snapshot.get("source") == "offline" and self.node_enabled:
                node = await self.node_snapshot(symbol)
                if node is not None:
                    snapshot = node
            if snapshot.get("source") in {"binance", "node"}:
                self._cache = snapshot
                self._cache_at = now
                return snapshot
            self._failure = snapshot
            self._failure_at = now
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
