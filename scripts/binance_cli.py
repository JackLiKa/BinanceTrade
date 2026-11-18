#!/usr/bin/env python3
"""Local-only Binance CLI for fund movement and raw API calls.

This is intentionally NOT exposed by the panel or adapter.  Run it on the Tokyo
node (or the machine holding BINANCE_API_KEY/SECRET) so withdrawals/transfers
never travel through the web gateway.

Examples:
    python scripts/binance_cli.py read --product usdm --path /fapi/v1/time
    python scripts/binance_cli.py write --product usdm --path /fapi/v1/order \
        --params '{"symbol":"BTCUSDT","side":"BUY","type":"MARKET","quantity":"0.001"}' --confirm
    python scripts/binance_cli.py withdraw --coin USDT --address 0x... --amount 10 --network ETH
    python scripts/binance_cli.py transfer --type MAIN_UMFUTURE --asset USDT --amount 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gridtrade.api.binance_gateway import BinanceGateway, BinanceGatewayError  # noqa: E402


def _gateway(*, allow_funds: bool = False) -> BinanceGateway:
    gw = BinanceGateway.from_env()
    gw.allow_funds = allow_funds
    if not gw.api_key or not gw.api_secret:
        raise SystemExit("BINANCE_API_KEY/BINANCE_API_SECRET not set")
    return gw


def _print(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _require_confirm(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise SystemExit("refusing: pass --confirm")
    answer = input("Type YES to confirm real fund movement: ").strip()
    if answer != "YES":
        raise SystemExit("cancelled")


def main() -> None:
    ap = argparse.ArgumentParser(description="Local-only Binance CLI")
    sub = ap.add_subparsers(dest="command", required=True)

    read = sub.add_parser("read")
    read.add_argument("--product", default="usdm")
    read.add_argument("--path", required=True)
    read.add_argument("--params", default="{}")
    read.add_argument("--signed", action="store_true")

    write = sub.add_parser("write")
    write.add_argument("--product", default="usdm")
    write.add_argument("--path", required=True)
    write.add_argument("--params", default="{}")
    write.add_argument("--confirm", action="store_true")

    withdraw = sub.add_parser("withdraw")
    withdraw.add_argument("--coin", required=True)
    withdraw.add_argument("--address", required=True)
    withdraw.add_argument("--amount", required=True)
    withdraw.add_argument("--network", default=None)
    withdraw.add_argument("--confirm", action="store_true")

    transfer = sub.add_parser("transfer")
    transfer.add_argument("--type", required=True)
    transfer.add_argument("--asset", required=True)
    transfer.add_argument("--amount", required=True)
    transfer.add_argument("--confirm", action="store_true")

    args = ap.parse_args()
    try:
        if args.command == "read":
            gw = _gateway()
            _print(gw.request(args.product, "GET", args.path, json.loads(args.params), signed=args.signed))
        elif args.command == "write":
            gw = _gateway()
            _print(gw.request(args.product, "POST", args.path, json.loads(args.params), signed=True, confirm=args.confirm))
        elif args.command == "withdraw":
            _require_confirm(args)
            gw = _gateway(allow_funds=True)
            params = {"coin": args.coin, "address": args.address, "amount": args.amount}
            if args.network:
                params["network"] = args.network
            _print(gw.request("wallet", "POST", "/sapi/v1/capital/withdraw/apply", params, signed=True, confirm=True))
        elif args.command == "transfer":
            _require_confirm(args)
            gw = _gateway(allow_funds=True)
            params = {"type": args.type, "asset": args.asset, "amount": args.amount}
            _print(gw.request("wallet", "POST", "/sapi/v1/asset/transfer", params, signed=True, confirm=True))
    except BinanceGatewayError as exc:
        raise SystemExit(f"Binance error: {exc.msg} (code={exc.code}, status={exc.status})") from exc


if __name__ == "__main__":
    main()
