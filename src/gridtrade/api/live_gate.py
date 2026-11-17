"""Gate USDT futures live account integration.

Read-only analysis is available as soon as API credentials are configured.
Order placement is implemented but hard-locked behind ``trading_enabled``; every
order path checks the lock, the configured notional/position/order limits and the
panel kill switch before it talks to the exchange.

Credentials live in the repo-root ``.env`` (0600, gitignored). The API only ever
returns a masked hint, never the secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import LiveConfig

GATE_BASE = "https://api.gateio.ws/api/v4"
SETTLE = "usdt"


class LiveError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class LiveDisabled(LiveError):
    def __init__(self, message: str = "实盘未启用或未配置 API Key") -> None:
        super().__init__(message, 409)


class LiveLocked(LiveError):
    def __init__(self, message: str = "实盘下单已锁定（GRIDTRADE_LIVE_TRADING=0）") -> None:
        super().__init__(message, 403)


class LiveRejected(LiveError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 422)


class LiveUpstream(LiveError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message, status_code)


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 4:
        return "…"
    return "…" + key[-4:]


def write_env_file(path: Path, updates: dict[str, str | None]) -> None:
    """Update KEY=VALUE lines in-place, keeping comments and unrelated keys."""
    path = Path(path)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key not in updates:
            output.append(line)
            continue
        seen.add(key)
        value = updates[key]
        if value is not None:
            output.append(f"{key}={value}")
    for key, value in updates.items():
        if key not in seen and value is not None:
            output.append(f"{key}={value}")
    text = "\n".join(output).rstrip("\n") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


class GatePrivateClient:
    """Minimal Gate API v4 futures client using the official APIv4 signature."""

    def __init__(self, key: str, secret: str, base: str = GATE_BASE, timeout: float = 8.0) -> None:
        self.key = key
        self.secret = secret
        self.base = base
        self._client = httpx.Client(
            base_url=base,
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers={"User-Agent": "gridtrade/0.1 live"},
        )

    def close(self) -> None:
        self._client.close()

    def _sign(self, method: str, path: str, query: str, body: str, timestamp: str) -> dict[str, str]:
        payload = hashlib.sha512(body.encode("utf-8")).hexdigest()
        message = f"{method}\n{path}\n{query}\n{payload}\n{timestamp}"
        signature = hmac.new(
            self.secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha512
        ).hexdigest()
        return {"KEY": self.key, "Timestamp": timestamp, "SIGN": signature}

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> Any:
        query = urlencode(sorted((key, value) for key, value in (params or {}).items()))
        payload = json.dumps(body) if body is not None else ""
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if auth:
            timestamp = str(time.time())
            headers.update(self._sign(method, path, query, payload, timestamp))
        url = path + (f"?{query}" if query else "")
        try:
            response = self._client.request(
                method, url, content=payload.encode("utf-8") if payload else None, headers=headers
            )
        except httpx.HTTPError as exc:
            raise LiveUpstream(f"Gate 网络错误: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:300]
            try:
                data = response.json()
                detail = str(data.get("message") or data.get("label") or detail)
            except ValueError:
                pass
            if response.status_code in {401, 403}:
                raise LiveUpstream(f"Gate 鉴权失败（检查 Key/Secret 与权限）: {detail}", 401)
            raise LiveUpstream(f"Gate 返回 {response.status_code}: {detail}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # -- private reads ---------------------------------------------------

    def account(self) -> dict[str, Any]:
        return self.request("GET", f"/futures/{SETTLE}/accounts")

    def positions(self) -> list[dict[str, Any]]:
        return self.request("GET", f"/futures/{SETTLE}/positions")

    def open_orders(self) -> list[dict[str, Any]]:
        return self.request("GET", f"/futures/{SETTLE}/orders", params={"status": "open"})

    def my_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.request("GET", f"/futures/{SETTLE}/my_trades", params={"limit": limit})

    def account_book(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.request("GET", f"/futures/{SETTLE}/account_book", params={"limit": limit})

    def fee(self) -> list[dict[str, Any]]:
        return self.request("GET", f"/futures/{SETTLE}/fee")

    def contracts(self) -> list[dict[str, Any]]:
        return self.request("GET", f"/futures/{SETTLE}/contracts", auth=False)

    def ticker(self, contract: str) -> dict[str, Any]:
        rows = self.request(
            "GET", f"/futures/{SETTLE}/tickers", params={"contract": contract}, auth=False
        )
        if not rows:
            raise LiveRejected(f"{contract} 没有行情")
        return rows[0]

    # -- private writes (gated by LiveService) ---------------------------

    def create_order(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"/futures/{SETTLE}/orders", body=body)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self.request("DELETE", f"/futures/{SETTLE}/orders/{order_id}")

    def set_leverage(self, contract: str, leverage: int) -> dict[str, Any]:
        return self.request(
            "POST", f"/futures/{SETTLE}/positions/{contract}/leverage", params={"leverage": leverage}
        )


class LiveService:
    def __init__(
        self,
        config: LiveConfig,
        *,
        env_path: Path | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self.config = config
        self.env_path = env_path
        self._client_factory = client_factory or GatePrivateClient
        self._client: Any | None = None
        self._cache: dict[str, Any] | None = None
        self._cache_at = 0.0
        self._contracts: dict[str, dict[str, Any]] = {}
        self._contracts_at = 0.0

    # -- config ----------------------------------------------------------

    def update_config(self, config: LiveConfig) -> None:
        self.config = config
        self._close_client()
        self._cache = None
        self._contracts_at = 0.0

    def masked_config(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "enabled": cfg.enabled,
            "trading_enabled": cfg.trading_enabled,
            "exchange": cfg.exchange,
            "configured": cfg.configured,
            "api_key_hint": mask_key(cfg.api_key),
            "has_secret": bool(cfg.api_secret),
            "subaccount": cfg.subaccount,
            "max_notional": cfg.max_notional,
            "max_order_notional": cfg.max_order_notional,
            "max_position_notional": cfg.max_position_notional,
            "max_open_orders": cfg.max_open_orders,
            "poll_seconds": cfg.poll_seconds,
        }

    def _client_or_raise(self) -> Any:
        if not self.config.configured:
            raise LiveDisabled()
        if self._client is None:
            self._client = self._client_factory(self.config.api_key, self.config.api_secret)
        return self._client

    def _close_client(self) -> None:
        client = self._client
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass
        self._client = None

    # -- analysis --------------------------------------------------------

    def test_connection(self) -> dict[str, Any]:
        client = self._client_or_raise()
        account = client.account()
        return {
            "ok": True,
            "exchange": self.config.exchange,
            "currency": account.get("currency"),
            "total": _opt_float(account.get("total")),
            "available": _opt_float(account.get("available")),
            "user": account.get("user"),
        }

    def contracts(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        if self._contracts and now - self._contracts_at < 120:
            return self._contracts
        client = self._client_or_raise()
        rows = client.contracts()
        self._contracts = {str(row.get("name", "")).upper(): row for row in rows}
        self._contracts_at = now
        return self._contracts

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache is not None and now - self._cache_at < 10:
            return self._cache
        if not self.config.enabled:
            result = {
                "configured": self.config.configured,
                "enabled": False,
                "trading_enabled": self.config.trading_enabled,
                "exchange": self.config.exchange,
                "config": self.masked_config(),
                "error": None,
                "account": None,
                "positions": [],
                "orders": [],
                "trades": [],
                "ledger": [],
                "fees": [],
                "analysis": None,
                "synced_at": None,
            }
            self._cache, self._cache_at = result, now
            return result
        try:
            client = self._client_or_raise()
            account = client.account()
            positions = client.positions()
            orders = client.open_orders()
            trades = client.my_trades(limit=50)
            ledger = client.account_book(limit=100)
            fees = client.fee()
            contracts = self.contracts()
            result = self._build_snapshot(account, positions, orders, trades, ledger, fees, contracts)
            result["error"] = None
        except LiveError as exc:
            result = {
                "configured": self.config.configured,
                "enabled": self.config.enabled,
                "trading_enabled": self.config.trading_enabled,
                "exchange": self.config.exchange,
                "config": self.masked_config(),
                "error": str(exc),
                "account": None,
                "positions": [],
                "orders": [],
                "trades": [],
                "ledger": [],
                "fees": [],
                "analysis": None,
                "synced_at": None,
            }
        except Exception as exc:  # pragma: no cover - defensive
            result = {
                "configured": self.config.configured,
                "enabled": self.config.enabled,
                "trading_enabled": self.config.trading_enabled,
                "exchange": self.config.exchange,
                "config": self.masked_config(),
                "error": f"实盘同步失败: {exc}",
                "account": None,
                "positions": [],
                "orders": [],
                "trades": [],
                "ledger": [],
                "fees": [],
                "analysis": None,
                "synced_at": None,
            }
        self._cache, self._cache_at = result, now
        return result

    def _build_snapshot(
        self,
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        orders: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        ledger: list[dict[str, Any]],
        fees: list[dict[str, Any]],
        contracts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        total = _opt_float(account.get("total")) or 0.0
        available = _opt_float(account.get("available")) or 0.0
        unrealized = _opt_float(account.get("unrealised_pnl")) or 0.0
        maintenance = _opt_float(account.get("maintenance_margin")) or 0.0
        position_margin = _opt_float(account.get("position_margin")) or 0.0
        order_margin = _opt_float(account.get("order_margin")) or 0.0

        normalized_positions: list[dict[str, Any]] = []
        gross = 0.0
        net = 0.0
        for row in positions:
            contract = str(row.get("contract", "")).upper()
            size = _opt_float(row.get("size")) or 0.0
            if abs(size) < 1e-12:
                continue
            mark = _opt_float(row.get("mark_price")) or 0.0
            mult = _opt_float((contracts.get(contract) or {}).get("quanto_multiplier")) or 0.0
            notional = abs(size) * mark * mult
            gross += notional
            net += size * mark * mult
            normalized_positions.append(
                {
                    "contract": contract,
                    "size": size,
                    "entry_price": _opt_float(row.get("entry_price")),
                    "mark_price": mark,
                    "liq_price": _opt_float(row.get("liq_price")),
                    "leverage": _opt_float(row.get("leverage")),
                    "margin": _opt_float(row.get("margin")),
                    "unrealized": _opt_float(row.get("unrealised_pnl")),
                    "realized": _opt_float(row.get("realised_pnl")),
                    "notional": notional,
                    "quanto_multiplier": mult,
                }
            )

        orders_notional = 0.0
        for row in orders:
            price = _opt_float(row.get("price")) or 0.0
            left = abs(_opt_float(row.get("left")) or 0.0)
            contracts_map = contracts.get(str(row.get("contract", "")).upper()) or {}
            mark = _opt_float(row.get("mark_price")) or price
            mult = _opt_float(contracts_map.get("quanto_multiplier")) or 0.0
            orders_notional += left * (mark or price) * mult

        realized = sum(
            _opt_float(item.get("change")) or 0.0
            for item in ledger
            if str(item.get("type")) == "pnl"
        )
        fees_paid = -sum(
            _opt_float(item.get("change")) or 0.0
            for item in ledger
            if str(item.get("type")) == "fee"
        )
        funding_paid = -sum(
            _opt_float(item.get("change")) or 0.0
            for item in ledger
            if str(item.get("type")) == "fund"
        )
        margin_ratio = maintenance / total if total > 0 else None
        cfg = self.config
        warnings: list[str] = []
        if gross > cfg.max_notional:
            warnings.append(f"总名义 {gross:.2f} 超过上限 {cfg.max_notional:.2f}")
        if len(orders) > cfg.max_open_orders:
            warnings.append(f"挂单数 {len(orders)} 超过上限 {cfg.max_open_orders}")
        for position in normalized_positions:
            if position["notional"] > cfg.max_position_notional:
                warnings.append(
                    f"{position['contract']} 名义 {position['notional']:.2f} 超过单标的上限 "
                    f"{cfg.max_position_notional:.2f}"
                )
        if margin_ratio is not None and margin_ratio > 0.7:
            warnings.append(f"维持保证金率 {margin_ratio:.1%} 偏高")

        analysis = {
            "equity": total,
            "available": available,
            "unrealized": unrealized,
            "realized": realized,
            "fees_paid": fees_paid,
            "funding_paid": funding_paid,
            "gross_notional": gross,
            "net_notional": net,
            "position_margin": position_margin,
            "order_margin": order_margin,
            "maintenance_margin": maintenance,
            "margin_ratio": margin_ratio,
            "open_orders": len(orders),
            "open_orders_notional": orders_notional,
            "trade_count": len(trades),
            "limits": {
                "max_notional": cfg.max_notional,
                "max_order_notional": cfg.max_order_notional,
                "max_position_notional": cfg.max_position_notional,
                "max_open_orders": cfg.max_open_orders,
            },
            "warnings": warnings,
        }
        return {
            "configured": self.config.configured,
            "enabled": self.config.enabled,
            "trading_enabled": self.config.trading_enabled,
            "exchange": self.config.exchange,
            "config": self.masked_config(),
            "account": {
                "currency": account.get("currency"),
                "total": total,
                "available": available,
                "unrealized": unrealized,
                "position_margin": position_margin,
                "order_margin": order_margin,
                "maintenance_margin": maintenance,
                "in_dual_mode": bool(account.get("in_dual_mode")),
            },
            "positions": normalized_positions,
            "orders": orders,
            "trades": trades,
            "ledger": ledger,
            "fees": fees,
            "analysis": analysis,
            "synced_at": time.time(),
            "error": None,
        }

    # -- order placement (hard-locked by default) ------------------------

    def _ensure_trading(self) -> Any:
        if not self.config.enabled:
            raise LiveDisabled("实盘未启用")
        if not self.config.trading_enabled:
            raise LiveLocked()
        return self._client_or_raise()

    def _limits_and_mark(self, contract: str) -> tuple[dict[str, Any], float]:
        contracts = self.contracts()
        meta = contracts.get(contract.upper())
        if meta is None:
            raise LiveRejected(f"未知合约 {contract}")
        client = self._client_or_raise()
        ticker = client.ticker(contract.upper())
        mark = _opt_float(ticker.get("mark_price")) or 0.0
        if mark <= 0:
            raise LiveRejected(f"{contract} 暂无标记价，无法评估名义")
        return meta, mark

    def place_order(
        self,
        contract: str,
        size: int,
        *,
        price: str | None = None,
        tif: str = "gtc",
        reduce_only: bool = False,
        text: str = "gridtrade-live",
    ) -> dict[str, Any]:
        client = self._ensure_trading()
        contract = contract.upper()
        if size == 0:
            raise LiveRejected("下单数量不能为 0")
        meta, mark = self._limits_and_mark(contract)
        mult = _opt_float(meta.get("quanto_multiplier")) or 0.0
        notional = abs(size) * mark * mult
        cfg = self.config
        if notional > cfg.max_order_notional:
            raise LiveRejected(
                f"单笔名义 {notional:.2f} 超过上限 {cfg.max_order_notional:.2f}"
            )
        account = client.account()
        total = _opt_float(account.get("total")) or 0.0
        positions = client.positions()
        orders = client.open_orders()
        if len(orders) >= cfg.max_open_orders:
            raise LiveRejected(f"挂单数已达上限 {cfg.max_open_orders}")
        current = 0.0
        gross = 0.0
        for row in positions:
            row_size = _opt_float(row.get("size")) or 0.0
            row_mark = _opt_float(row.get("mark_price")) or 0.0
            row_mult = _opt_float((self.contracts().get(str(row.get("contract", "")).upper()) or {}).get("quanto_multiplier")) or 0.0
            gross += abs(row_size) * row_mark * row_mult
            if str(row.get("contract", "")).upper() == contract:
                current = row_size
        projected = abs(current + size) * mark * mult
        if not reduce_only and projected > cfg.max_position_notional:
            raise LiveRejected(
                f"{contract} 预计名义 {projected:.2f} 超过单标的上限 {cfg.max_position_notional:.2f}"
            )
        if not reduce_only and gross + notional > cfg.max_notional:
            raise LiveRejected(f"组合名义将超过上限 {cfg.max_notional:.2f}")
        if total > 0 and gross + notional > total * 20:
            raise LiveRejected("组合名义超过权益的 20 倍，拒绝下单")
        body: dict[str, Any] = {
            "contract": contract,
            "size": size,
            "price": price if price is not None else "0",
            "tif": tif,
            "reduce_only": reduce_only,
            "text": text,
        }
        return client.create_order(body)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        client = self._ensure_trading()
        return client.cancel_order(order_id)

    def close_position(self, contract: str) -> dict[str, Any]:
        client = self._ensure_trading()
        contract = contract.upper()
        for row in client.positions():
            if str(row.get("contract", "")).upper() == contract:
                size = _opt_int(row.get("size")) or 0
                if size == 0:
                    raise LiveRejected(f"{contract} 没有持仓")
                return client.create_order(
                    {
                        "contract": contract,
                        "size": -size,
                        "price": "0",
                        "tif": "ioc",
                        "reduce_only": True,
                        "text": "gridtrade-close",
                    }
                )
        raise LiveRejected(f"{contract} 没有持仓")

    def set_leverage(self, contract: str, leverage: int) -> dict[str, Any]:
        client = self._ensure_trading()
        if leverage < 1 or leverage > 100:
            raise LiveRejected("杠杆需在 1-100 之间")
        return client.set_leverage(contract.upper(), leverage)
