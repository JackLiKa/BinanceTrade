"""Every external endpoint used by the app must be an official, documented one.

The allowlist below mirrors ``docs/memory/11-外部接口清单.md``.
Adding a new exchange call without registering it here (and in that document)
fails the suite, so "use the official API" stays enforced instead of aspirational.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# path -> official documentation reference
BINANCE_FAPI = {
    # public market data (panel + dataset fetch)
    "/fapi/v1/premiumIndex": "Binance USDⓈ-M Futures · Mark Price",
    "/fapi/v1/ticker/24hr": "Binance USDⓈ-M Futures · 24hr Ticker Price Change Statistics",
    "/fapi/v1/ticker/bookTicker": "Binance USDⓈ-M Futures · Symbol Order Book Ticker",
    "/fapi/v1/klines": "Binance USDⓈ-M Futures · Kline Candlestick Data",
    "/fapi/v1/markPriceKlines": "Binance USDⓈ-M Futures · Mark Price Kline Candlestick Data",
    "/fapi/v1/fundingRate": "Binance USDⓈ-M Futures · Get Funding Rate History",
    "/fapi/v1/exchangeInfo": "Binance USDⓈ-M Futures · Exchange Information",
    "/fapi/v1/fundingInfo": "Binance USDⓈ-M Futures · Get Funding Rate Info",
    "/fapi/v1/tradingSchedule": "Binance USDⓈ-M Futures · Trading Schedule",
    "/fapi/v1/time": "Binance USDⓈ-M Futures · Check Server Time",
    # signed account/read-only (execution adapter, demo + live)
    "/fapi/v2/account": "Binance USDⓈ-M Futures · Account Information V2",
    "/fapi/v2/positionRisk": "Binance USDⓈ-M Futures · Position Information V2",
    "/fapi/v1/openOrders": "Binance USDⓈ-M Futures · Current All Open Orders",
    "/fapi/v1/allOrders": "Binance USDⓈ-M Futures · All Orders",
    "/fapi/v1/income": "Binance USDⓈ-M Futures · Get Income History",
    "/fapi/v1/userTrades": "Binance USDⓈ-M Futures · Account Trade List",
    "/fapi/v1/positionSide/dual": "Binance USDⓈ-M Futures · Get Current Position Mode",
    "/fapi/v1/commissionRate": "Binance USDⓈ-M Futures · User Commission Rate",
    # signed trading (locked behind BINANCE_TRADING + kill switch + confirm)
    "/fapi/v1/order": "Binance USDⓈ-M Futures · New/Query/Cancel Order",
    "/fapi/v1/allOpenOrders": "Binance USDⓈ-M Futures · Cancel All Open Orders",
    "/fapi/v1/leverage": "Binance USDⓈ-M Futures · Change Initial Leverage",
    "/fapi/v1/leverageBracket": "Binance USDⓈ-M Futures · Notional and Leverage Brackets",
}

GATE_FUTURES = {
    "/futures/{settle}/contracts/{contract}": "Gate API v4 · Futures · Get a single contract",
    "/futures/{settle}/contracts": "Gate API v4 · Futures · Get contracts",
    "/futures/{settle}/tickers": "Gate API v4 · Futures · Get tickers",
    "/futures/{settle}/funding_rate": "Gate API v4 · Futures · Get funding rate history",
    # private account endpoints used by the live integration
    "/futures/{settle}/accounts": "Gate API v4 · Futures · Get futures account",
    "/futures/{settle}/positions": "Gate API v4 · Futures · Get user position list",
    "/futures/{settle}/positions/{contract}/leverage": "Gate API v4 · Futures · Update position leverage",
    "/futures/{settle}/orders": "Gate API v4 · Futures · Query/place/cancel orders",
    "/futures/{settle}/orders/{order_id}": "Gate API v4 · Futures · Cancel an order",
    "/futures/{settle}/my_trades": "Gate API v4 · Futures · Query personal trading records",
    "/futures/{settle}/account_book": "Gate API v4 · Futures · Query account change history",
    "/futures/{settle}/fee": "Gate API v4 · Futures · Query trading fee rates",
}

# ``10.66.0.2`` is not an exchange: it is the internal WireGuard address of the
# Tokyo execution node that the panel proxies to (never a public endpoint).
ALLOWED_HOSTS = {
    "fapi.binance.com",
    "demo-fapi.binance.com",  # official demo/testnet base for the futures API
    "api.gateio.ws",
    "10.66.0.2",
}

SOURCE_FILES = [
    ROOT / "src/gridtrade/api/live.py",
    ROOT / "src/gridtrade/api/live_gate.py",
    ROOT / "src/gridtrade/api/paper.py",
    ROOT / "src/gridtrade/api/binance_demo.py",
    ROOT / "src/gridtrade/api/binance_node.py",
    ROOT / "src/gridtrade/api/adapter_server.py",
    ROOT / "research/fetch.py",
]


def _normalize(path: str) -> str:
    path = re.sub(r"\{[^}]+\}", "{x}", path)
    path = re.sub(r"^/futures/[^/]+/", "/futures/{settle}/", path)
    path = path.replace("/positions/{x}/leverage", "/positions/{contract}/leverage")
    path = path.replace("/contracts/{x}", "/contracts/{contract}")
    path = path.replace("/orders/{x}", "/orders/{order_id}")
    return path


def _paths(text: str) -> set[str]:
    return {
        _normalize(match.group(1))
        for match in re.finditer(r'"(/fapi/[^"]+|/futures/[^"]+)"', text)
    }


def test_every_external_endpoint_is_documented() -> None:
    documented = set(BINANCE_FAPI) | set(GATE_FUTURES)
    seen: set[str] = set()
    for file in SOURCE_FILES:
        text = file.read_text(encoding="utf-8")
        seen |= _paths(text)
    assert seen, "expected at least one external endpoint in the source"
    undocumented = seen - documented
    assert not undocumented, f"undocumented external endpoints: {sorted(undocumented)}"


def test_only_known_exchange_hosts_are_used() -> None:
    hosts: set[str] = set()
    for file in SOURCE_FILES:
        text = file.read_text(encoding="utf-8")
        hosts |= set(re.findall(r'https?://([A-Za-z0-9.-]+)', text))
    unexpected = hosts - ALLOWED_HOSTS
    assert not unexpected, f"unexpected external hosts: {sorted(unexpected)}"
