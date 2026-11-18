"""Generic Binance gateway safety tests (no network calls)."""

import pytest

from gridtrade.api.binance_gateway import BinanceGateway, BinanceGatewayError


def gateway(**kwargs) -> BinanceGateway:
    values = {"api_key": "key", "api_secret": "secret", "trading_enabled": True}
    values.update(kwargs)
    return BinanceGateway(**values)


def test_fund_movement_is_blocked_on_http_gateway() -> None:
    with pytest.raises(BinanceGatewayError, match="CLI-only"):
        gateway().request(
            "wallet",
            "POST",
            "/sapi/v1/capital/withdraw/apply",
            {"coin": "USDT", "amount": "1"},
            signed=True,
            confirm=True,
        )


def test_write_requires_trading_and_confirmation() -> None:
    with pytest.raises(BinanceGatewayError, match="trading locked"):
        gateway(trading_enabled=False).request(
            "usdm", "POST", "/fapi/v1/leverage", {"symbol": "BTCUSDT", "leverage": 2}, signed=True, confirm=True
        )
    with pytest.raises(BinanceGatewayError, match="confirmation missing"):
        gateway().request(
            "usdm", "POST", "/fapi/v1/leverage", {"symbol": "BTCUSDT", "leverage": 2}, signed=True, confirm=False
        )
    with pytest.raises(BinanceGatewayError, match="write path not allowed"):
        gateway().request("usdm", "POST", "/fapi/v1/account", {}, signed=True, confirm=True)
