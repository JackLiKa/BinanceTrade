"""Offline tests for the tunnel-node market-data feed (K-lines/funding/snapshot)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from gridtrade.api.live import LiveMarket


def node_market(handler) -> LiveMarket:
    market = LiveMarket(enabled=False, node_url="http://10.66.0.2:8100")
    client = httpx.AsyncClient(
        base_url="http://10.66.0.2:8100",
        transport=httpx.MockTransport(handler),
    )
    market._node_client = client  # inject the mock transport
    return market


def run(coro):
    return asyncio.run(coro)


def test_node_candles_returns_real_time_bars_and_caches() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/market/candles":
            assert request.url.params["symbol"] == "GOOGLUSDT"
            assert request.url.params["interval"] == "1m"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "symbol": "GOOGLUSDT",
                    "interval": "1m",
                    "count": 2,
                    "candles": [[1700000000, 1.0, 2.0, 0.5, 1.5, 10.0], [1700000060, 1.5, 2.5, 1.0, 2.0, 12.0]],
                },
            )
        raise AssertionError(request.url.path)

    market = node_market(handler)
    first = run(market.node_candles("GOOGLUSDT", "1m", 2))
    second = run(market.node_candles("GOOGLUSDT", "1m", 2))
    assert first is not None and second is not None
    assert first["source"] == "node"
    assert first["count"] == 2
    assert first["candles"][-1][0] == 1700000060
    assert len(calls) == 1  # 2s cache


def test_node_candles_failure_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    market = node_market(handler)
    assert run(market.node_candles("GOOGLUSDT", "1m", 5)) is None


def test_node_snapshot_maps_fields_and_iso_time() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/market/snapshot"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "symbol": "GOOGLUSDT",
                "mark_price": 282.5,
                "index_price": 282.4,
                "last_price": 282.6,
                "change_24h_pct": 0.86,
                "last_funding_rate": 0.0001,
                "next_funding_time": 1794940800000,
                "exchange_time": 1794937000000,
            },
        )

    market = node_market(handler)
    snapshot = run(market.node_snapshot("GOOGLUSDT"))
    assert snapshot is not None
    assert snapshot["source"] == "node"
    assert snapshot["mark_price"] == pytest.approx(282.5)
    assert snapshot["next_funding_time"].endswith("Z")


def test_node_funding_returns_points() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/market/funding"
        return httpx.Response(
            200,
            json={"ok": True, "count": 1, "funding": [[1700000000, 0.0001, 282.0]]},
        )

    market = node_market(handler)
    payload = run(market.node_funding("GOOGLUSDT", 10))
    assert payload is not None
    assert payload["funding"][0][1] == pytest.approx(0.0001)


def test_node_disabled_returns_none() -> None:
    market = LiveMarket(enabled=False, node_url="")
    assert market.node_enabled is False
    assert run(market.node_candles("GOOGLUSDT", "1m", 5)) is None
    assert run(market.node_snapshot("GOOGLUSDT")) is None


def test_snapshot_falls_back_to_node_when_live_disabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True, "mark_price": 1.0, "index_price": 1.0, "last_price": 1.0},
        )

    market = node_market(handler)
    snapshot = run(market.snapshot("GOOGLUSDT"))
    assert snapshot["source"] == "node"
    assert snapshot["mark_price"] == pytest.approx(1.0)
