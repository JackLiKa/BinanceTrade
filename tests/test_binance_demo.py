"""Offline tests for the Binance USDⓈ-M demo adapter.

Every test drives :class:`httpx.MockTransport`; nothing here opens a socket, reads
the real ``/etc`` or needs a real API key. The signing expectation is recomputed
independently with :mod:`hmac`/:mod:`hashlib`, so no magic signature values.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx
import pytest

from gridtrade.api import binance_demo
from gridtrade.api.binance_demo import (
    DEMO_BASE_URL,
    MAX_PRICE_DEVIATION,
    BinanceDemoClient,
    BinanceDemoConfig,
    BinanceError,
    BinanceLocked,
)

API_KEY = "TESTAPIKEY1234567890"
API_SECRET = "test-secret-value"
FIXED_CLOCK = 1_700_000_000.0
FIXED_MS = 1_700_000_000_000
BOOK_TICKER = {"symbol": "BTCUSDT", "bidPrice": "49900", "askPrice": "50100"}

Handler = Callable[[httpx.Request], httpx.Response]
Responder = dict[str, Any] | list[dict[str, Any]] | httpx.Response


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_config(**overrides: Any) -> BinanceDemoConfig:
    values: dict[str, Any] = {
        "base_url": DEMO_BASE_URL,
        "api_key": API_KEY,
        "api_secret": API_SECRET,
        "trading_enabled": True,
        "recv_window": 5000,
        "timeout_s": 5.0,
        "max_order_notional": 500.0,
        "max_position_notional": 3000.0,
        "max_open_orders": 10,
        "kill_switch_file": "",
        "position_mode": "oneway",
    }
    values.update(overrides)
    return BinanceDemoConfig(**values)


def make_client(
    handler: Handler,
    *,
    clock_value: float = FIXED_CLOCK,
    **config_overrides: Any,
) -> BinanceDemoClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url=DEMO_BASE_URL)
    return BinanceDemoClient(
        make_config(**config_overrides), http=http, clock=lambda: clock_value
    )


def handler_for(
    routes: dict[tuple[str, str], Responder],
    seen: list[httpx.Request] | None = None,
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        responder = routes.get((request.method, request.url.path))
        if responder is None:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        if isinstance(responder, httpx.Response):
            return responder
        if callable(responder):
            return responder(request)
        return httpx.Response(200, json=responder)

    return handler


def no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected network request: {request.method} {request.url}")


def pairs(raw: bytes | str) -> list[tuple[str, str]]:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return parse_qsl(text, keep_blank_values=True)


def expected_signature(raw_pairs: list[tuple[str, str]]) -> str:
    """Independently recompute the HMAC over the sent params (signature excluded)."""
    payload = urlencode([(key, value) for key, value in raw_pairs if key != "signature"])
    return hmac.new(
        API_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def value_of(raw_pairs: list[tuple[str, str]], key: str) -> str:
    return dict(raw_pairs)[key]


# ---------------------------------------------------------------------------
# signing / clock
# ---------------------------------------------------------------------------


def test_sign_matches_independent_hmac_and_is_order_sensitive() -> None:
    client = BinanceDemoClient(make_config(), clock=lambda: FIXED_CLOCK)
    try:
        params: dict[str, Any] = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.01",
            "price": "50000",
            "timestamp": "1700000000000",
            "recvWindow": "5000",
        }
        payload = urlencode([(key, str(value)) for key, value in params.items()])
        assert payload == (
            "symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=0.01&price=50000"
            "&timestamp=1700000000000&recvWindow=5000"
        )
        expected = hmac.new(
            API_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        assert client._sign(params) == expected
        # Order matters: signing is over the exact sent payload, not a sorted dict.
        reordered = dict(reversed(list(params.items())))
        assert client._sign(reordered) != expected
    finally:
        client.close()


def test_signed_get_injects_timestamp_recvwindow_and_signature_last() -> None:
    seen: list[httpx.Request] = []
    handler = handler_for(
        {("GET", "/fapi/v2/account"): {"totalWalletBalance": "1000"}}, seen
    )
    client = make_client(handler)
    assert client.account() == {"totalWalletBalance": "1000"}

    assert len(seen) == 1
    request = seen[0]
    assert request.headers["X-MBX-APIKEY"] == API_KEY
    query = pairs(request.url.query)
    assert query[-1][0] == "signature"
    assert value_of(query, "timestamp") == str(FIXED_MS)
    assert value_of(query, "recvWindow") == "5000"
    assert value_of(query, "signature") == expected_signature(query)
    assert [key for key, _ in query].count("signature") == 1


def test_sync_time_records_millisecond_offset() -> None:
    server_ms = FIXED_MS + 1234
    handler = handler_for({("GET", "/fapi/v1/time"): {"serverTime": server_ms}})
    client = make_client(handler)
    try:
        assert client.server_time_offset_ms == 0
        assert client.sync_time() == 1234
        assert client.server_time_offset_ms == 1234
        assert client._timestamp() == FIXED_MS + 1234
    finally:
        client.close()


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def test_configured_requires_both_key_and_secret() -> None:
    assert BinanceDemoConfig().configured is False
    assert BinanceDemoConfig(api_key="key").configured is False
    assert BinanceDemoConfig(api_secret="secret").configured is False
    assert BinanceDemoConfig(api_key="key", api_secret="secret").configured is True


def test_config_from_env_reads_all_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    names = (
        "BINANCE_BASE_URL",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "BINANCE_TRADING",
        "BINANCE_RECV_WINDOW",
        "BINANCE_TIMEOUT_S",
        "BINANCE_MAX_ORDER_NOTIONAL",
        "BINANCE_MAX_POSITION_NOTIONAL",
        "BINANCE_MAX_OPEN_ORDERS",
        "BINANCE_KILL_SWITCH_FILE",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    default = BinanceDemoConfig.from_env()
    assert default.base_url == DEMO_BASE_URL
    assert default.api_key == ""
    assert default.api_secret == ""
    assert default.trading_enabled is False
    assert default.recv_window == 5000
    assert default.timeout_s == pytest.approx(10.0)
    assert default.max_order_notional == pytest.approx(500.0)
    assert default.max_position_notional == pytest.approx(3000.0)
    assert default.max_open_orders == 10
    assert default.kill_switch_file == "/etc/binance/KILL"
    assert default.configured is False

    monkeypatch.setenv("BINANCE_BASE_URL", "https://example.test/")
    monkeypatch.setenv("BINANCE_API_KEY", " key ")
    monkeypatch.setenv("BINANCE_API_SECRET", " secret ")
    monkeypatch.setenv("BINANCE_TRADING", "off")
    monkeypatch.setenv("BINANCE_RECV_WINDOW", "3000")
    monkeypatch.setenv("BINANCE_TIMEOUT_S", "2.5")
    monkeypatch.setenv("BINANCE_MAX_ORDER_NOTIONAL", "42.5")
    monkeypatch.setenv("BINANCE_MAX_POSITION_NOTIONAL", "100")
    monkeypatch.setenv("BINANCE_MAX_OPEN_ORDERS", "3")
    monkeypatch.setenv("BINANCE_KILL_SWITCH_FILE", "/tmp/KILL")

    cfg = BinanceDemoConfig.from_env()
    assert cfg.base_url == "https://example.test"
    assert cfg.api_key == "key"
    assert cfg.api_secret == "secret"
    assert cfg.trading_enabled is False
    assert cfg.recv_window == 3000
    assert cfg.timeout_s == pytest.approx(2.5)
    assert cfg.max_order_notional == pytest.approx(42.5)
    assert cfg.max_position_notional == pytest.approx(100)
    assert cfg.max_open_orders == 3
    assert cfg.kill_switch_file == "/tmp/KILL"
    assert cfg.configured is True

    monkeypatch.setenv("BINANCE_TRADING", "1")
    assert BinanceDemoConfig.from_env().trading_enabled is True


# ---------------------------------------------------------------------------
# write gates
# ---------------------------------------------------------------------------


def test_place_order_is_locked_without_trading_flag() -> None:
    client = make_client(no_network, trading_enabled=False, kill_switch_file="")
    with pytest.raises(BinanceLocked) as info:
        client.place_order("BTCUSDT", "BUY", 0.001, price=50000.0, confirm=True)
    assert info.value.code == -1
    assert "trading locked" in str(info.value)
    with pytest.raises(BinanceLocked):
        client.cancel_order("BTCUSDT", 1)


def test_kill_switch_file_blocks_writes(tmp_path: Any) -> None:
    kill = tmp_path / "KILL"
    kill.write_text("halt", encoding="utf-8")
    client = make_client(
        no_network, trading_enabled=True, kill_switch_file=str(kill)
    )
    with pytest.raises(BinanceError) as info:
        client.place_order("BTCUSDT", "BUY", 0.001, price=50000.0, confirm=True)
    assert not isinstance(info.value, BinanceLocked)
    assert "kill switch" in str(info.value)


def test_place_order_requires_second_confirmation() -> None:
    client = make_client(no_network, trading_enabled=True, kill_switch_file="")
    with pytest.raises(BinanceError) as info:
        client.place_order("BTCUSDT", "BUY", 0.001, price=50000.0)
    assert "confirm" in str(info.value).lower()


# ---------------------------------------------------------------------------
# risk controls
# ---------------------------------------------------------------------------


def test_order_notional_limit_rejects_before_hitting_network() -> None:
    client = make_client(no_network, max_order_notional=10.0, kill_switch_file="")
    # 0.001 × 50000 = 50 > 10
    with pytest.raises(BinanceError) as info:
        client.place_order("BTCUSDT", "BUY", 0.001, price=50000.0, confirm=True)
    assert "notional" in str(info.value)


def test_limit_price_deviation_over_five_percent_is_rejected() -> None:
    assert binance_demo.MAX_PRICE_DEVIATION == pytest.approx(0.05)
    seen: list[httpx.Request] = []
    handler = handler_for(
        {("GET", "/fapi/v1/ticker/bookTicker"): BOOK_TICKER}, seen
    )
    client = make_client(handler)
    with pytest.raises(BinanceError) as info:
        # book mid = 50000, 60000 is 20% away.
        client.place_order("BTCUSDT", "BUY", 0.001, price=60000.0, confirm=True)
    assert "deviat" in str(info.value)
    assert all(request.url.path != "/fapi/v1/order" for request in seen)


def test_price_deviation_limit_can_be_monkeypatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(binance_demo, "MAX_PRICE_DEVIATION", 0.5)
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/ticker/bookTicker"): BOOK_TICKER,
        ("GET", "/fapi/v1/openOrders"): [],
        ("POST", "/fapi/v1/order"): {"orderId": 99, "status": "NEW"},
    }
    client = make_client(handler_for(routes))
    result = client.place_order("BTCUSDT", "BUY", 0.001, price=60000.0, confirm=True)
    assert result["orderId"] == 99


def test_open_order_limit_is_enforced() -> None:
    seen: list[httpx.Request] = []
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/ticker/bookTicker"): BOOK_TICKER,
        ("GET", "/fapi/v1/openOrders"): [{"orderId": 1}, {"orderId": 2}],
    }
    client = make_client(handler_for(routes, seen), max_open_orders=2)
    with pytest.raises(BinanceError) as info:
        client.place_order("BTCUSDT", "BUY", 0.001, price=50000.0, confirm=True)
    assert "open orders" in str(info.value)
    assert not any(request.method == "POST" for request in seen)


# ---------------------------------------------------------------------------
# successful writes
# ---------------------------------------------------------------------------


def test_place_order_signs_form_body_and_returns_order() -> None:
    seen: list[httpx.Request] = []
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/ticker/bookTicker"): BOOK_TICKER,
        ("GET", "/fapi/v1/openOrders"): [],
        ("POST", "/fapi/v1/order"): {
            "orderId": 42,
            "symbol": "BTCUSDT",
            "status": "NEW",
        },
    }
    client = make_client(handler_for(routes, seen))
    result = client.place_order(
        "BTCUSDT",
        "BUY",
        0.001,
        price=50000.0,
        order_type="LIMIT",
        time_in_force="GTC",
        reduce_only=True,
        client_order_id="grid-1",
        confirm=True,
    )
    assert result["orderId"] == 42
    assert result["status"] == "NEW"

    posts = [request for request in seen if request.method == "POST"]
    assert len(posts) == 1
    request = posts[0]
    assert request.url.path == "/fapi/v1/order"
    assert request.headers["X-MBX-APIKEY"] == API_KEY
    assert request.headers["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )
    body = pairs(request.content)
    assert body[-1][0] == "signature"
    assert value_of(body, "symbol") == "BTCUSDT"
    assert value_of(body, "side") == "BUY"
    assert value_of(body, "type") == "LIMIT"
    assert float(value_of(body, "quantity")) == pytest.approx(0.001)
    assert float(value_of(body, "price")) == pytest.approx(50000.0)
    assert value_of(body, "timeInForce") == "GTC"
    assert value_of(body, "reduceOnly") == "true"
    assert value_of(body, "newClientOrderId") == "grid-1"
    assert value_of(body, "timestamp") == str(FIXED_MS)
    assert value_of(body, "recvWindow") == "5000"
    assert value_of(body, "signature") == expected_signature(body)
    assert [key for key, _ in body].count("signature") == 1

    # The public bookTicker probe is not signed and carries no signature.
    book = next(
        request
        for request in seen
        if request.url.path == "/fapi/v1/ticker/bookTicker"
    )
    assert "signature" not in dict(pairs(book.url.query))


def test_hedge_mode_sends_position_side_and_omits_reduce_only() -> None:
    seen: list[httpx.Request] = []
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/ticker/bookTicker"): BOOK_TICKER,
        ("GET", "/fapi/v1/openOrders"): [],
        ("POST", "/fapi/v1/order"): {"orderId": 100, "status": "NEW"},
    }
    client = make_client(handler_for(routes, seen), position_mode="hedge")

    client.place_order("BTCUSDT", "BUY", 0.001, price=50000.0, confirm=True)
    body = pairs(seen[-1].content)
    assert value_of(body, "positionSide") == "LONG"
    assert "reduceOnly" not in dict(body)
    assert value_of(body, "signature") == expected_signature(body)

    client.place_order(
        "BTCUSDT", "SELL", 0.001, price=50000.0, reduce_only=True, confirm=True
    )
    body = pairs(seen[-1].content)
    assert value_of(body, "positionSide") == "LONG"  # closing a long

    client.place_order(
        "BTCUSDT", "BUY", 0.001, price=50000.0, reduce_only=True, confirm=True
    )
    body = pairs(seen[-1].content)
    assert value_of(body, "positionSide") == "SHORT"  # closing a short


def test_explicit_position_side_forces_hedge_parameters() -> None:
    seen: list[httpx.Request] = []
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/ticker/bookTicker"): BOOK_TICKER,
        ("GET", "/fapi/v1/openOrders"): [],
        ("POST", "/fapi/v1/order"): {"orderId": 101, "status": "NEW"},
    }
    client = make_client(handler_for(routes, seen), position_mode="oneway")
    client.place_order(
        "BTCUSDT", "SELL", 0.001, price=50000.0, confirm=True, position_side="short"
    )
    body = pairs(seen[-1].content)
    assert value_of(body, "positionSide") == "SHORT"
    assert "reduceOnly" not in dict(body)


def test_auto_mode_detects_hedge_once() -> None:
    seen: list[httpx.Request] = []
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/ticker/bookTicker"): BOOK_TICKER,
        ("GET", "/fapi/v1/openOrders"): [],
        ("GET", "/fapi/v1/positionSide/dual"): {"dualSidePosition": True},
        ("POST", "/fapi/v1/order"): {"orderId": 102, "status": "NEW"},
    }
    client = make_client(handler_for(routes, seen), position_mode="auto")

    assert client.dual_side_position() is True
    assert client.dual_side_position() is True  # cached
    client.place_order("BTCUSDT", "BUY", 0.001, price=50000.0, confirm=True)
    body = pairs(seen[-1].content)
    assert value_of(body, "positionSide") == "LONG"
    dual_calls = [
        request for request in seen if request.url.path == "/fapi/v1/positionSide/dual"
    ]
    assert len(dual_calls) == 1


def test_auto_mode_falls_back_to_oneway_when_detection_fails() -> None:
    seen: list[httpx.Request] = []
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/ticker/bookTicker"): BOOK_TICKER,
        ("GET", "/fapi/v1/openOrders"): [],
        ("GET", "/fapi/v1/positionSide/dual"): httpx.Response(
            404, json={"code": -1102, "msg": "not supported"}
        ),
        ("POST", "/fapi/v1/order"): {"orderId": 103, "status": "NEW"},
    }
    client = make_client(handler_for(routes, seen), position_mode="auto")
    client.place_order("BTCUSDT", "BUY", 0.001, price=50000.0, confirm=True)
    body = pairs(seen[-1].content)
    assert "positionSide" not in dict(body)
    assert value_of(body, "reduceOnly") == "false"


def test_cancel_and_leverage_are_gated_and_signed() -> None:
    seen: list[httpx.Request] = []
    routes: dict[tuple[str, str], Responder] = {
        ("DELETE", "/fapi/v1/order"): {"orderId": 7, "status": "CANCELED"},
        ("DELETE", "/fapi/v1/allOpenOrders"): {"code": 200, "msg": "done"},
        ("POST", "/fapi/v1/leverage"): {"symbol": "BTCUSDT", "leverage": 10},
    }
    client = make_client(handler_for(routes, seen))
    assert client.cancel_order("btcusdt", 7)["status"] == "CANCELED"
    assert client.cancel_all("BTCUSDT")["code"] == 200
    assert client.set_leverage("btcusdt", 10)["leverage"] == 10

    assert len(seen) == 3
    for request in seen:
        body = pairs(request.content)
        assert body[-1][0] == "signature"
        assert value_of(body, "signature") == expected_signature(body)
        assert request.headers["X-MBX-APIKEY"] == API_KEY
    assert value_of(pairs(seen[0].content), "orderId") == "7"
    assert value_of(pairs(seen[2].content), "leverage") == "10"

    locked = make_client(no_network, trading_enabled=False, kill_switch_file="")
    with pytest.raises(BinanceLocked):
        locked.cancel_all("BTCUSDT")


# ---------------------------------------------------------------------------
# HTTP errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (400, -2015, "Invalid API-key, IP, or permissions for action."),
        (429, -1003, "Too many requests; current limit is 2400 request weight per minute."),
        (418, -1003, "Way too many requests; IP banned until 1700000060000."),
    ],
)
def test_http_errors_carry_code_and_status(
    status: int, code: int, message: str
) -> None:
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v2/account"): httpx.Response(
            status, json={"code": code, "msg": message}
        )
    }
    client = make_client(handler_for(routes))
    with pytest.raises(BinanceError) as info:
        client.account()
    assert info.value.code == code
    assert info.value.http_status == status
    assert info.value.msg == message
    assert message in str(info.value)


def test_503_unknown_execution_status_is_not_retried() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            503,
            json={
                "code": -1,
                "msg": "Unknown error, please check your request or try again later.",
            },
        )

    client = make_client(handler)
    with pytest.raises(BinanceError) as info:
        client.account()
    assert info.value.http_status == 503
    assert "Unknown error" in info.value.msg
    assert len(calls) == 1  # no blind retry: the order state is unknown


# ---------------------------------------------------------------------------
# reads / status
# ---------------------------------------------------------------------------


def test_exchange_info_filters_symbol_locally_and_flattens_filters() -> None:
    """Binance ignores the ``symbol`` query param, so the client must filter locally."""
    seen: list[httpx.Request] = []
    payload = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "100"},
                ],
            },
            {
                "symbol": "DOGEUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.000010"},
                    {"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            },
        ]
    }
    client = make_client(handler_for({("GET", "/fapi/v1/exchangeInfo"): payload}, seen))

    filtered = client.exchange_info("dogeusdt")
    assert [row["symbol"] for row in filtered["symbols"]] == ["DOGEUSDT"]
    assert client.exchange_info()["symbols"][0]["symbol"] == "BTCUSDT"
    assert client.symbol_filters("DOGEUSDT") == {
        "step": 1.0,
        "min_qty": 1.0,
        "tick": 0.00001,
        "min_notional": 5.0,
    }
    with pytest.raises(BinanceError) as excinfo:
        client.exchange_info("NOPEUSDT")
    assert excinfo.value.code == -1121
    for request in seen:
        assert request.url.path == "/fapi/v1/exchangeInfo"
        assert "symbol=" not in request.url.query.decode()


def test_read_methods_parse_responses() -> None:
    seen: list[httpx.Request] = []
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/time"): {"serverTime": FIXED_MS},
        ("GET", "/fapi/v1/exchangeInfo"): {"symbols": [{"symbol": "BTCUSDT"}]},
        ("GET", "/fapi/v2/account"): {
            "totalWalletBalance": "1000",
            "availableBalance": "800",
        },
        ("GET", "/fapi/v2/positionRisk"): [
            {"symbol": "BTCUSDT", "positionAmt": "0.5"},
            {"symbol": "ETHUSDT", "positionAmt": "0"},
        ],
        ("GET", "/fapi/v1/openOrders"): [{"orderId": 11, "symbol": "BTCUSDT"}],
        ("GET", "/fapi/v1/order"): {"orderId": 11, "status": "NEW"},
        ("GET", "/fapi/v1/income"): [
            {"incomeType": "FUNDING_FEE", "income": "-0.1"}
        ],
        ("GET", "/fapi/v1/userTrades"): [{"id": 1, "price": "50000"}],
    }
    client = make_client(handler_for(routes, seen))

    assert client.time()["serverTime"] == FIXED_MS
    assert client.exchange_info("BTCUSDT")["symbols"][0]["symbol"] == "BTCUSDT"
    assert client.account()["totalWalletBalance"] == "1000"
    assert len(client.positions()) == 2
    assert [row["symbol"] for row in client.positions_nonzero()] == ["BTCUSDT"]
    assert client.open_orders()[0]["orderId"] == 11
    assert client.query_order("BTCUSDT", 11)["status"] == "NEW"
    income = client.income(symbol="BTCUSDT", income_type="FUNDING_FEE", limit=10)
    assert income[0]["incomeType"] == "FUNDING_FEE"
    fills = client.fills(symbol="BTCUSDT", limit=10)
    assert fills[0]["id"] == 1

    unsigned_paths = {"/fapi/v1/time", "/fapi/v1/exchangeInfo"}
    for request in seen:
        query = pairs(request.url.query)
        if request.url.path in unsigned_paths:
            assert "signature" not in dict(query)
            assert "timestamp" not in dict(query)
        else:
            assert value_of(query, "signature") == expected_signature(query)


def test_health_is_offline_safe_and_probes_time() -> None:
    routes: dict[tuple[str, str], Responder] = {
        ("GET", "/fapi/v1/time"): {"serverTime": FIXED_MS + 500}
    }
    client = make_client(handler_for(routes))
    info = client.health()
    assert info["reachable"] is True
    assert info["configured"] is True
    assert info["trading_enabled"] is True
    assert info["base_url"] == DEMO_BASE_URL
    assert info["kill_switch"] is False
    assert info["server_offset_ms"] == 0
    assert info["server_time"] == {"serverTime": FIXED_MS + 500}

    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to demo")

    offline = make_client(failing).health()
    assert offline["reachable"] is False
    assert offline["configured"] is True
    assert "error" in offline


def test_masked_never_exposes_secret() -> None:
    client = BinanceDemoClient(make_config(), clock=lambda: FIXED_CLOCK)
    try:
        masked = client.masked()
        assert set(masked) == {"api_key_hint", "has_secret"}
        assert masked["api_key_hint"] == f"{API_KEY[:4]}…{API_KEY[-4:]}"
        assert masked["has_secret"] is True
        dumped = json.dumps(masked, ensure_ascii=False)
        assert API_SECRET not in dumped
        assert API_KEY not in dumped
        assert "api_secret" not in dumped
        assert "signature" not in dumped
        assert API_SECRET not in repr(make_config())
    finally:
        client.close()

    empty = BinanceDemoClient(
        make_config(api_key="", api_secret=""), clock=lambda: FIXED_CLOCK
    )
    try:
        assert empty.masked() == {"api_key_hint": "", "has_secret": False}
    finally:
        empty.close()
