"""Tests for the read-only Binance execution-node client (no network)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from gridtrade.api.binance_node import (
    DEFAULT_NODE_URL,
    BinanceNodeClient,
    BinanceNodeError,
)


def make_client(handler, timeout_s: float = 5.0) -> BinanceNodeClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url=DEFAULT_NODE_URL)
    return BinanceNodeClient(DEFAULT_NODE_URL, timeout_s=timeout_s, http=http)


def test_default_node_url_points_at_the_tunnel_address() -> None:
    assert DEFAULT_NODE_URL == "http://10.66.0.2:8100"


def test_health_and_reads_parse_json() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/healthz":
            return httpx.Response(200, json={"ok": True, "configured": True})
        if path == "/account":
            return httpx.Response(200, json={"ok": True, "account": {"totalWalletBalance": "1"}})
        if path == "/positions":
            return httpx.Response(200, json={"ok": True, "positions": []})
        if path == "/open_orders":
            return httpx.Response(200, json={"ok": True, "orders": []})
        raise AssertionError(f"unexpected path {path}")

    client = make_client(handler)
    assert client.health()["configured"] is True
    assert client.account()["account"]["totalWalletBalance"] == "1"
    assert client.positions("dogeusdt") == {"ok": True, "positions": []}
    assert client.open_orders() == {"ok": True, "orders": []}

    position_request = next(r for r in seen if r.url.path == "/positions")
    assert "symbol=DOGEUSDT" in str(position_request.url)


def test_http_error_is_wrapped_with_status_and_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"ok": False, "code": -1, "msg": "trading locked"})

    client = make_client(handler)
    with pytest.raises(BinanceNodeError) as info:
        client.account()
    assert info.value.status == 403
    assert info.value.code == -1
    assert "trading locked" in info.value.msg


def test_non_json_body_is_rejected() -> None:
    client = make_client(lambda request: httpx.Response(200, text="<html>nginx</html>"))
    with pytest.raises(BinanceNodeError) as info:
        client.health()
    assert "非 JSON" in info.value.msg


def test_transport_failure_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("tunnel down", request=request)

    client = make_client(handler)
    with pytest.raises(BinanceNodeError) as info:
        client.health()
    assert "不可达" in info.value.msg


def test_client_does_not_own_injected_http() -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                        base_url=DEFAULT_NODE_URL)
    client = BinanceNodeClient(DEFAULT_NODE_URL, http=http)
    client.close()
    assert not http.is_closed  # external client stays open
    http.close()


def test_context_manager_closes_owned_client() -> None:
    client = BinanceNodeClient("http://127.0.0.1:9", timeout_s=0.01)
    with client as entered:
        assert entered is client
    assert client._http.is_closed
