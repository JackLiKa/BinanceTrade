"""FastAPI application: research jobs, market data and the built SPA.

Security model is deliberately small: one access token, kept in ``var/token``
(or ``GRIDTRADE_TOKEN``), sent as a Bearer header, an ``X-API-Token`` header,
or the httpOnly ``gt_token`` cookie set by the login endpoint. The WebSocket
additionally accepts ``?token=`` because browsers cannot set headers on it.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..research.runner import ResearchParams
from ..strategy.grid import GridParams
from .config import LiveConfig, Settings
from .binance_node import BinanceNodeClient, BinanceNodeError
from .jobs import JobQueue
from .live import LiveMarket
from .admin import ADMIN_COOKIE, SESSION_TTL, AdminError, AdminService, AdminAuth
from .google_auth import GoogleAuthError, GoogleAuthStore, GoogleDeviceFlow
from .live_gate import LiveError, LiveService, write_env_file
from .paper import PaperEngine
from .service import INTERVALS, ResearchService
from .store import Store

VERSION = "0.1.0"
COOKIE_NAME = "gt_token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30
MODES = {
    "research": {"enabled": True, "label": "研究", "detail": "本地 Parquet 回放"},
    "paper": {
        "enabled": True,
        "label": "模拟盘",
        "detail": "Gate 永续实时行情，网格纸面成交（含手续费与资金费）",
    },
    "live": {
        "enabled": True,
        "locked": False,
        "label": "实盘",
        "detail": "Gate 实盘只读分析；下单受 .env 总开关与风控上限锁定",
    },
}

log = logging.getLogger("gridtrade.api")


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    capital: float = Field(10_000.0, gt=0, le=10_000_000)
    spacing_bp: float = Field(120.0, gt=0, le=10_000)
    levels: int = Field(30, ge=1, le=500)
    leverage: float = Field(0.5, gt=0, le=10)
    reanchor_bars: int | None = Field(None, ge=1, le=100_000)
    stop_dd: float | None = Field(0.10, ge=0, le=1)
    maker_fee: float = Field(0.0002, ge=0, le=0.01)
    taker_fee: float = Field(0.0005, ge=0, le=0.01)
    slip_bp: float = Field(0.2, ge=0, le=100)
    intrabar: bool = False

    @model_validator(mode="after")
    def _range(self) -> ResearchRequest:
        if self.start and self.end and self.start >= self.end:
            raise ValueError("start must be before end")
        return self

    def to_params(self) -> ResearchParams:
        return ResearchParams(
            capital=self.capital,
            spacing_bp=self.spacing_bp,
            levels=self.levels,
            leverage=self.leverage,
            reanchor_bars=self.reanchor_bars,
            stop_dd=self.stop_dd,
            maker_fee=self.maker_fee,
            taker_fee=self.taker_fee,
            slip_bp=self.slip_bp,
            intrabar=self.intrabar,
        )

    def stored(self) -> dict[str, Any]:
        return {
            **asdict(self.to_params()),
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
        }


class WalkforwardRequest(ResearchRequest):
    min_days: int = Field(5, ge=1, le=31)


class SweepAxes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spacings: list[float] = Field(default_factory=lambda: [60.0, 90.0, 120.0])
    levels: list[int] = Field(default_factory=lambda: [10, 20, 30])
    leverages: list[float] = Field(default_factory=lambda: [0.5, 1.0])

    @field_validator("spacings")
    @classmethod
    def _spacings(cls, values: list[float]) -> list[float]:
        cleaned = sorted({round(value, 4) for value in values if value > 0})
        if not cleaned or len(cleaned) > 12:
            raise ValueError("spacings must contain 1-12 positive values")
        return cleaned

    @field_validator("levels")
    @classmethod
    def _levels(cls, values: list[int]) -> list[int]:
        cleaned = sorted({value for value in values if value > 0})
        if not cleaned or len(cleaned) > 12 or max(cleaned) > 500:
            raise ValueError("levels must contain 1-12 values between 1 and 500")
        return cleaned

    @field_validator("leverages")
    @classmethod
    def _leverages(cls, values: list[float]) -> list[float]:
        cleaned = sorted({round(value, 4) for value in values if value > 0})
        if not cleaned or len(cleaned) > 8 or max(cleaned) > 10:
            raise ValueError("leverages must contain 1-8 values up to 10x")
        return cleaned


class SweepRequest(ResearchRequest):
    axes: SweepAxes = Field(default_factory=SweepAxes)

    @model_validator(mode="after")
    def _size(self) -> SweepRequest:
        combos = len(self.axes.spacings) * len(self.axes.levels) * len(self.axes.leverages)
        if combos > 48:
            raise ValueError(f"sweep has {combos} combinations; maximum is 48")
        return self


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class GooglePollRequest(BaseModel):
    flow_id: str = Field(min_length=8, max_length=128)


class AdminGoogleConfig(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    enabled: bool | None = None
    clear_secret: bool = False


class AdminGoogleUser(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field("", max_length=120)
    is_admin: bool = False


class AdminGoogleRole(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    is_admin: bool


class KillSwitchRequest(BaseModel):
    engaged: bool


class PaperConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] | None = Field(None, min_length=1, max_length=8)
    capital: float | None = Field(None, gt=0, le=10_000_000)
    leverage: float | None = Field(None, gt=0, le=20)
    spacing_bp: float | None = Field(None, gt=0, le=5_000)
    levels: int | None = Field(None, ge=1, le=500)
    stop_dd_pct: float | None = Field(None, ge=0, le=100)
    maker_fee_bp: float | None = Field(None, ge=0, le=200)
    taker_fee_bp: float | None = Field(None, ge=0, le=500)
    poll_seconds: float | None = Field(None, ge=1, le=60)


class PaperStartRequest(BaseModel):
    reset: bool = False
    config: PaperConfigRequest | None = None


class LiveConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str | None = Field(None, max_length=128)
    api_secret: str | None = Field(None, max_length=128)
    enabled: bool | None = None
    trading_enabled: bool | None = None
    confirm_trading: bool = False
    subaccount: str | None = Field(None, max_length=64)
    max_notional: float | None = Field(None, gt=0, le=10_000_000)
    max_order_notional: float | None = Field(None, gt=0, le=10_000_000)
    max_position_notional: float | None = Field(None, gt=0, le=10_000_000)
    max_open_orders: int | None = Field(None, ge=1, le=500)
    clear_credentials: bool = False


class LiveOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str = Field(min_length=3, max_length=32)
    size: int = Field(..., description="contracts; positive = long/buy, negative = short/sell")
    price: str | None = None
    tif: str = Field("gtc", pattern="^(gtc|ioc|poc|fok)$")
    reduce_only: bool = False


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminLiveRequest(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    enabled: bool | None = None
    trading_enabled: bool | None = None
    confirm_trading: bool = False
    clear_credentials: bool = False
    max_notional: float | None = Field(None, gt=0)
    max_order_notional: float | None = Field(None, gt=0)
    max_position_notional: float | None = Field(None, gt=0)
    max_open_orders: int | None = Field(None, ge=1, le=500)


class AdminPaperRequest(BaseModel):
    symbols: list[str] | None = None
    capital: float | None = Field(None, gt=0)
    leverage: float | None = Field(None, gt=0)
    spacing_bp: float | None = Field(None, gt=0)
    levels: int | None = Field(None, ge=1, le=500)
    stop_dd_pct: float | None = Field(None, ge=0, le=100)
    maker_fee_bp: float | None = Field(None, ge=0, le=200)
    taker_fee_bp: float | None = Field(None, ge=0, le=500)
    poll_seconds: float | None = Field(None, ge=1, le=600)


class AdminActionRequest(BaseModel):
    action: str = Field(pattern="^(start|stop|reset)$")


class AdminPasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=5, max_length=128)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.var_dir / "gridtrade.db")
    live = LiveMarket(
        enabled=settings.market_live,
        proxy=settings.proxy,
        node_url=settings.binance_node_url,
    )
    service = ResearchService(settings.data_dir, live)
    jobs = JobQueue(store, workers=2)
    paper = PaperEngine(settings.paper, settings.var_dir)
    live_service = LiveService(settings.live, env_path=settings.env_path)
    admin_service = AdminService(settings, store, live_service, paper)
    google_store = GoogleAuthStore(settings.var_dir / "auth.db")
    google_flow = GoogleDeviceFlow(
        google_store,
        relay_url=settings.google_relay_url,
        relay_token=settings.google_relay_token,
    )
    started_at = time.time()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_run:
            recovered = store.fail_interrupted("服务重启导致任务中断")
            if recovered:
                log.warning("recovered %s stale run(s) from previous process", recovered)
        jobs.start()
        paper.autostart()
        symbols = service.symbols()
        log.info(
            "gridtrade api up: data=%s symbols=%s web=%s",
            settings.data_dir,
            ",".join(symbols) or "none",
            settings.web_dir if settings.web_dir.exists() else "not built",
        )
        store.audit("server.start", f"symbols={','.join(symbols)} version={VERSION}")
        try:
            yield
        finally:
            jobs.stop()
            paper.close()
            getattr(live_service, "close", lambda: None)()
            await live.close()

    app = FastAPI(
        title="Gridtrade Research API",
        version=VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.store = store
    app.state.service = service
    app.state.jobs = jobs
    app.state.paper = paper
    app.state.live_service = live_service

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/") and not request.url.path.endswith("/artifact"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    def supplied_token(request: Request) -> str:
        header = request.headers.get("authorization", "")
        if header[:7].lower() == "bearer ":
            return header[7:].strip()
        api_token = request.headers.get("x-api-token", "").strip()
        if api_token:
            return api_token
        return request.cookies.get(COOKIE_NAME, "")

    def actor_for(token: str) -> str | None:
        if token and hmac.compare_digest(token, settings.token):
            return "token"
        email = google_store.session_email(token)
        return email

    def require_token(request: Request) -> None:
        actor = actor_for(supplied_token(request))
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing access token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.actor = actor

    def visible_symbols() -> list[str]:
        return service.symbols()

    def resolve_symbol(name: str | None) -> str:
        symbols = visible_symbols()
        if not symbols:
            raise HTTPException(status_code=503, detail="no research datasets found")
        candidate = (name or settings.symbol or symbols[0]).upper()
        if candidate not in symbols:
            raise HTTPException(
                status_code=404,
                detail=f"unknown symbol {candidate}; available: {', '.join(symbols)}",
            )
        return candidate

    guarded = [Depends(require_token)]

    def admin_token(request: Request) -> str:
        return request.cookies.get(ADMIN_COOKIE, "")

    def require_admin(request: Request) -> None:
        if not admin_service.auth.check(admin_token(request)):
            raise HTTPException(status_code=401, detail="管理员未登录或会话已过期")

    admin_guarded = [Depends(require_admin)]

    def admin_http(exc: AdminError) -> HTTPException:
        return HTTPException(status_code=exc.status_code, detail=str(exc))

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": VERSION,
            "uptime_s": round(time.time() - started_at, 1),
            "symbols": visible_symbols(),
        }

    def set_panel_cookie(response: Response, value: str) -> None:
        response.set_cookie(
            COOKIE_NAME,
            value,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookie,
            path="/",
        )

    @app.get("/api/auth/providers", tags=["auth"])
    async def auth_providers() -> dict[str, Any]:
        config = google_store.config()
        return {
            "google": {
                "enabled": config.enabled,
                "configured": config.configured,
                "device_flow": True,
                "users": len(google_store.list_users()),
                "admin_users": len([user for user in google_store.list_users() if user.get("is_admin")]),
            }
        }

    @app.post("/api/auth/google/start", tags=["auth"])
    async def google_start() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(google_flow.start)
        except GoogleAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    @app.post("/api/auth/google/poll", tags=["auth"])
    async def google_poll(payload: GooglePollRequest, response: Response) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(google_flow.poll, payload.flow_id)
        except GoogleAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        token = result.pop("session_token", "")
        if result.get("status") == "ok" and token:
            set_panel_cookie(response, token)
            store.audit("auth.google_login", str(result.get("email") or ""), actor="google")
        return result

    @app.post("/api/auth/login", tags=["auth"])
    async def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        if not hmac.compare_digest(payload.token.strip(), settings.token):
            store.audit("auth.failed", "invalid token")
            raise HTTPException(status_code=401, detail="invalid access token")
        set_panel_cookie(response, settings.token)
        store.audit("auth.login", "cookie issued")
        return {
            "ok": True,
            "token_hint": "…" + settings.token[-4:],
            "expires_in": COOKIE_MAX_AGE,
        }

    @app.post("/api/auth/logout", tags=["auth"], dependencies=guarded)
    async def logout(request: Request, response: Response) -> dict[str, bool]:
        token = supplied_token(request)
        if not hmac.compare_digest(token, settings.token):
            google_store.revoke_session(token)
        response.delete_cookie(COOKIE_NAME, path="/")
        store.audit("auth.logout", "cookie cleared")
        return {"ok": True}

    @app.get("/api/session", tags=["system"], dependencies=guarded)
    async def session(request: Request) -> dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "actor": getattr(request.state, "actor", ""),
            "symbol": resolve_symbol(None),
            "symbols": visible_symbols(),
            "modes": MODES,
            "kill_switch": store.get_bool("kill_switch", False),
        }

    # -- market & dataset -------------------------------------------------

    @app.get("/api/dataset/symbols", dependencies=guarded)
    async def dataset_symbols() -> dict[str, Any]:
        return {"symbols": visible_symbols(), "default": resolve_symbol(None)}

    @app.get("/api/dataset/quality", dependencies=guarded)
    async def dataset_quality(symbol: str | None = None) -> dict[str, Any]:
        resolved = resolve_symbol(symbol)
        return await asyncio.to_thread(service.dataset_quality, resolved)

    @app.get("/api/market/snapshot", dependencies=guarded)
    async def market_snapshot(symbol: str | None = None) -> dict[str, Any]:
        resolved = resolve_symbol(symbol)
        return await service.market_snapshot(resolved)

    @app.get("/api/market/candles", dependencies=guarded)
    async def market_candles(
        symbol: str | None = None,
        interval: str = Query("1h"),
        limit: int = Query(400, ge=20, le=3_000),
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        resolved = resolve_symbol(symbol)
        if interval not in INTERVALS:
            raise HTTPException(
                status_code=400, detail=f"interval must be one of {', '.join(INTERVALS)}"
            )
        try:
            return await service.market_candles(
                resolved,
                interval=interval,
                limit=limit,
                start=start,
                end=end,
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/market/funding", dependencies=guarded)
    async def market_funding(
        symbol: str | None = None, limit: int = Query(300, ge=10, le=2_000)
    ) -> dict[str, Any]:
        resolved = resolve_symbol(symbol)
        return await service.market_funding(resolved, limit=limit)

    @app.get("/api/overview", dependencies=guarded)
    async def overview(symbol: str | None = None) -> dict[str, Any]:
        resolved = resolve_symbol(symbol)
        snapshot, quality = await asyncio.gather(
            service.market_snapshot(resolved),
            asyncio.to_thread(service.dataset_quality, resolved),
        )
        walkforward_run = await asyncio.to_thread(store.latest_succeeded, "walkforward")
        walkforward_payload = None
        if walkforward_run is not None:
            artifact = await asyncio.to_thread(store.load_artifact, walkforward_run["id"])
            walkforward_payload = {
                "run": walkforward_run,
                "rows": (artifact or {}).get("rows", []),
                "cumulative": (artifact or {}).get("cumulative", []),
                "summary": (artifact or {}).get("summary", walkforward_run.get("summary")),
            }
        latest_replay = await asyncio.to_thread(store.latest_succeeded, "replay")
        replay_summary = None
        if latest_replay is not None:
            replay_summary = {
                "run": latest_replay,
                "summary": latest_replay.get("summary"),
            }
        return {
            "symbol": resolved,
            "market": snapshot,
            "dataset": quality,
            "runs": await asyncio.to_thread(store.list_runs, limit=8),
            "walkforward": walkforward_payload,
            "replay": replay_summary,
            "kill_switch": store.get_bool("kill_switch", False),
            "modes": MODES,
        }

    # -- research runs ----------------------------------------------------

    def submit(kind: str, symbol_name: str, params: dict[str, Any], fn) -> dict[str, Any]:
        run_id = store.create_run(kind, symbol_name, params)
        store.audit(f"run.{kind}.queued", f"{run_id} {symbol_name}")
        jobs.submit(run_id, fn)
        return {"run": store.get_run(run_id)}

    @app.post("/api/runs/replay", status_code=202, dependencies=guarded)
    async def create_replay(payload: ResearchRequest) -> dict[str, Any]:
        symbol_name = resolve_symbol(payload.symbol)
        params = payload.to_params()
        start = payload.start.isoformat() if payload.start else None
        end = payload.end.isoformat() if payload.end else None
        return submit(
            "replay",
            symbol_name,
            payload.stored(),
            service.replay_job(symbol_name, params, start, end),
        )

    @app.post("/api/runs/walkforward", status_code=202, dependencies=guarded)
    async def create_walkforward(payload: WalkforwardRequest) -> dict[str, Any]:
        symbol_name = resolve_symbol(payload.symbol)
        params = payload.to_params()
        start = payload.start.isoformat() if payload.start else None
        end = payload.end.isoformat() if payload.end else None
        stored = {**payload.stored(), "min_days": payload.min_days}
        return submit(
            "walkforward",
            symbol_name,
            stored,
            service.walkforward_job(symbol_name, params, payload.min_days, start, end),
        )

    @app.post("/api/runs/sweep", status_code=202, dependencies=guarded)
    async def create_sweep(payload: SweepRequest) -> dict[str, Any]:
        symbol_name = resolve_symbol(payload.symbol)
        params = payload.to_params()
        axes = payload.axes.model_dump()
        start = payload.start.isoformat() if payload.start else None
        end = payload.end.isoformat() if payload.end else None
        stored = {**payload.stored(), "axes": axes}
        return submit(
            "sweep",
            symbol_name,
            stored,
            service.sweep_job(symbol_name, params, axes, start, end),
        )

    @app.get("/api/runs", dependencies=guarded)
    async def list_runs(
        kind: Literal["replay", "walkforward", "sweep"] | None = None,
        limit: int = Query(30, ge=1, le=200),
    ) -> dict[str, Any]:
        runs = await asyncio.to_thread(store.list_runs, limit=limit, kind=kind)
        return {"runs": runs}

    @app.get("/api/runs/{run_id}", dependencies=guarded)
    async def get_run(run_id: str) -> dict[str, Any]:
        run = await asyncio.to_thread(store.get_run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run": run}

    @app.get("/api/runs/{run_id}/artifact", dependencies=guarded)
    async def get_artifact(run_id: str) -> JSONResponse:
        run = await asyncio.to_thread(store.get_run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run["status"] != "succeeded":
            raise HTTPException(status_code=409, detail=f"run is {run['status']}")
        artifact = await asyncio.to_thread(store.load_artifact, run_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact missing")
        return JSONResponse(
            artifact,
            headers={"Cache-Control": "private, max-age=86400", "X-Run-Id": run_id},
        )

    @app.post("/api/runs/{run_id}/cancel", dependencies=guarded)
    async def cancel_run(run_id: str) -> dict[str, Any]:
        canceled = await asyncio.to_thread(store.request_cancel, run_id)
        if canceled:
            store.audit("run.cancel", run_id)
        run = await asyncio.to_thread(store.get_run, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"canceled": canceled, "run": run}

    # -- risk, settings, audit -------------------------------------------

    # -- standalone admin console -----------------------------------------

    @app.post("/api/admin/google/start", tags=["admin"])
    async def admin_google_start() -> dict[str, Any]:
        try:
            return await asyncio.to_thread(google_flow.start)
        except GoogleAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    @app.post("/api/admin/google/poll", tags=["admin"])
    async def admin_google_poll(payload: GooglePollRequest, response: Response) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(google_flow.poll, payload.flow_id)
        except GoogleAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        panel_token = result.pop("session_token", "")
        if result.get("status") != "ok":
            return result
        email = str(result.get("email") or "")
        if panel_token:
            google_store.revoke_session(panel_token)
        if not google_store.is_admin(email):
            return {"status": "not_allowed", "email": email, "error": "该 Google 账号未被授予后台权限"}
        admin_token = admin_service.auth.grant(email)
        response.set_cookie(
            ADMIN_COOKIE,
            admin_token,
            max_age=SESSION_TTL,
            httponly=True,
            samesite="strict",
            secure=settings.secure_cookie,
            path="/",
        )
        store.audit("admin.google_login", email, actor="admin")
        return {"status": "ok", "email": email, "name": result.get("name", "")}

    @app.post("/api/admin/login", tags=["admin"])
    async def admin_login(payload: AdminLoginRequest, request: Request, response: Response) -> dict[str, Any]:
        client = request.client.host if request.client else ""
        try:
            session = admin_service.auth.login(payload.username, payload.password, client=client)
        except AdminError as exc:
            store.audit("admin.login_failed", payload.username[:32], actor="admin")
            raise admin_http(exc) from exc
        response.set_cookie(
            ADMIN_COOKIE,
            session,
            max_age=SESSION_TTL,
            httponly=True,
            samesite="strict",
            secure=settings.secure_cookie,
            path="/",
        )
        store.audit("admin.login", payload.username[:32], actor="admin")
        return {"ok": True, "default_password": admin_service.auth.default_password()}

    @app.post("/api/admin/logout", dependencies=admin_guarded)
    async def admin_logout(request: Request, response: Response) -> dict[str, Any]:
        admin_service.auth.logout(admin_token(request))
        response.delete_cookie(ADMIN_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/admin/me", dependencies=admin_guarded)
    async def admin_me() -> dict[str, Any]:
        return {
            "username": admin_service.auth.username(),
            "default_password": admin_service.auth.default_password(),
        }

    @app.get("/api/admin/overview", dependencies=admin_guarded)
    async def admin_overview() -> dict[str, Any]:
        return await asyncio.to_thread(admin_service.overview)

    @app.get("/api/admin/audit", dependencies=admin_guarded)
    async def admin_audit(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        return {"entries": await asyncio.to_thread(store.list_audit, limit=limit)}

    @app.post("/api/admin/live", dependencies=admin_guarded)
    async def admin_live(payload: AdminLiveRequest) -> dict[str, Any]:
        try:
            config = await asyncio.to_thread(
                admin_service.save_live, payload.model_dump(exclude_none=True)
            )
        except AdminError as exc:
            raise admin_http(exc) from exc
        return {"config": config}

    @app.post("/api/admin/paper", dependencies=admin_guarded)
    async def admin_paper(payload: AdminPaperRequest) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                admin_service.save_paper, payload.model_dump(exclude_none=True)
            )
        except AdminError as exc:
            raise admin_http(exc) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"模拟盘配置失败: {exc}") from exc
        return result

    @app.post("/api/admin/paper/action", dependencies=admin_guarded)
    async def admin_paper_action(payload: AdminActionRequest) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(admin_service.paper_action, payload.action)
        except AdminError as exc:
            raise admin_http(exc) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"模拟盘操作失败: {exc}") from exc

    @app.post("/api/admin/token/rotate", dependencies=admin_guarded)
    async def admin_rotate_token() -> dict[str, Any]:
        return await asyncio.to_thread(admin_service.rotate_token)

    @app.post("/api/admin/password", dependencies=admin_guarded)
    async def admin_password(payload: AdminPasswordRequest, request: Request) -> dict[str, Any]:
        try:
            await asyncio.to_thread(
                admin_service.change_password,
                admin_token(request),
                payload.current_password,
                payload.new_password,
            )
        except AdminError as exc:
            raise admin_http(exc) from exc
        return {"ok": True}

    @app.get("/admin", include_in_schema=False)
    async def admin_page() -> FileResponse:
        page = settings.web_dir / "admin" / "index.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="admin console not built")
        return FileResponse(page, headers={"Cache-Control": "no-store"})

    # -- live trading (Gate private account; orders locked by default) ----

    def live_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LiveError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.get("/api/live", dependencies=guarded)
    async def live_state(refresh: bool = False) -> dict[str, Any]:
        return await asyncio.to_thread(live_service.snapshot, force=refresh)

    @app.post("/api/live/sync", dependencies=guarded)
    async def live_sync() -> dict[str, Any]:
        return await asyncio.to_thread(live_service.snapshot, force=True)

    @app.get("/api/live/config", dependencies=guarded)
    async def live_config() -> dict[str, Any]:
        return {"config": live_service.masked_config()}

    @app.post("/api/live/config", dependencies=guarded)
    async def live_save_config(payload: LiveConfigRequest) -> dict[str, Any]:
        cfg: LiveConfig = settings.live
        updates: dict[str, str | None] = {}
        if payload.clear_credentials:
            cfg = replace(cfg, api_key="", api_secret="")
            updates["GATE_API_KEY"] = None
            updates["GATE_API_SECRET"] = None
        if payload.api_key is not None:
            key = payload.api_key.strip()
            cfg = replace(cfg, api_key=key)
            updates["GATE_API_KEY"] = key or None
        if payload.api_secret is not None:
            secret = payload.api_secret.strip()
            cfg = replace(cfg, api_secret=secret)
            updates["GATE_API_SECRET"] = secret or None
        if payload.subaccount is not None:
            cfg = replace(cfg, subaccount=payload.subaccount.strip())
            updates["GRIDTRADE_LIVE_SUBACCOUNT"] = cfg.subaccount or None
        if payload.max_notional is not None:
            cfg = replace(cfg, max_notional=payload.max_notional)
            updates["GRIDTRADE_LIVE_MAX_NOTIONAL"] = str(payload.max_notional)
        if payload.max_order_notional is not None:
            cfg = replace(cfg, max_order_notional=payload.max_order_notional)
            updates["GRIDTRADE_LIVE_MAX_ORDER_NOTIONAL"] = str(payload.max_order_notional)
        if payload.max_position_notional is not None:
            cfg = replace(cfg, max_position_notional=payload.max_position_notional)
            updates["GRIDTRADE_LIVE_MAX_POSITION_NOTIONAL"] = str(payload.max_position_notional)
        if payload.max_open_orders is not None:
            cfg = replace(cfg, max_open_orders=payload.max_open_orders)
            updates["GRIDTRADE_LIVE_MAX_OPEN_ORDERS"] = str(payload.max_open_orders)
        if payload.enabled is not None:
            cfg = replace(cfg, enabled=payload.enabled)
            updates["GRIDTRADE_LIVE_ENABLED"] = "1" if payload.enabled else "0"
        if payload.trading_enabled is not None:
            if payload.trading_enabled and not payload.confirm_trading:
                raise HTTPException(
                    status_code=400,
                    detail="开启实盘下单需要 confirm_trading=true",
                )
            if payload.trading_enabled and not cfg.configured:
                raise HTTPException(status_code=400, detail="先保存 API Key/Secret 再开启下单")
            cfg = replace(cfg, trading_enabled=payload.trading_enabled)
            updates["GRIDTRADE_LIVE_TRADING"] = "1" if payload.trading_enabled else "0"
        if updates:
            await asyncio.to_thread(write_env_file, settings.env_path, updates)
        settings.live = cfg
        live_service.update_config(cfg)
        store.audit(
            "live.config",
            "credentials_updated" if ("GATE_API_KEY" in updates or "GATE_API_SECRET" in updates) else "updated",
        )
        return {"config": live_service.masked_config()}

    @app.post("/api/live/test", dependencies=guarded)
    async def live_test() -> dict[str, Any]:
        result = await asyncio.to_thread(live_call, live_service.test_connection)
        store.audit("live.test", "ok")
        return result

    @app.post("/api/live/orders", dependencies=guarded)
    async def live_submit_order(payload: LiveOrderRequest) -> dict[str, Any]:
        if store.get_bool("kill_switch", False):
            raise HTTPException(status_code=409, detail="紧急停止已触发，拒绝实盘下单")
        order = await asyncio.to_thread(
            live_call,
            live_service.place_order,
            payload.contract,
            payload.size,
            price=payload.price,
            tif=payload.tif,
            reduce_only=payload.reduce_only,
        )
        store.audit(
            "live.order",
            f"{payload.contract} size={payload.size} price={payload.price or 'market'}",
        )
        return {"order": order}

    @app.delete("/api/live/orders/{order_id}", dependencies=guarded)
    async def live_cancel_order(order_id: str) -> dict[str, Any]:
        order = await asyncio.to_thread(live_call, live_service.cancel_order, order_id)
        store.audit("live.cancel", order_id)
        return {"order": order}

    @app.post("/api/live/positions/{contract}/close", dependencies=guarded)
    async def live_close_position(contract: str) -> dict[str, Any]:
        if store.get_bool("kill_switch", False):
            raise HTTPException(status_code=409, detail="紧急停止已触发，拒绝实盘下单")
        order = await asyncio.to_thread(live_call, live_service.close_position, contract)
        store.audit("live.close", contract.upper())
        return {"order": order}

    # -- live paper trading ------------------------------------------------

    @app.get("/api/paper", dependencies=guarded)
    async def paper_state() -> dict[str, Any]:
        return await asyncio.to_thread(paper.snapshot)

    @app.get("/api/paper/runs", dependencies=guarded)
    async def paper_runs(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
        "已归档的模拟盘运行摘要（reset / 止损时写入），用于复盘。"
        return {"runs": await asyncio.to_thread(paper.runs, limit)}

    @app.post("/api/paper/start", dependencies=guarded)
    async def paper_start(payload: PaperStartRequest) -> dict[str, Any]:
        overrides = payload.config.model_dump(exclude_none=True) if payload.config else None
        try:
            state = await asyncio.to_thread(
                paper.start, reset=payload.reset, overrides=overrides
            )
        except Exception as exc:  # market feed unreachable or invalid sizing
            raise HTTPException(status_code=503, detail=f"模拟盘启动失败: {exc}") from exc
        store.audit("paper.start", f"reset={payload.reset}")
        return state

    @app.post("/api/paper/stop", dependencies=guarded)
    async def paper_stop() -> dict[str, Any]:
        state = await asyncio.to_thread(paper.stop)
        store.audit("paper.stop", "stopped")
        return state

    @app.post("/api/paper/reset", dependencies=guarded)
    async def paper_reset(payload: PaperConfigRequest | None = None) -> dict[str, Any]:
        overrides = payload.model_dump(exclude_none=True) if payload else None
        try:
            state = await asyncio.to_thread(paper.reset, overrides)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"模拟盘重置失败: {exc}") from exc
        store.audit("paper.reset", "account reset")
        return state

    # -- binance execution node (tunnel-only, read-only from the panel) ----

    node_client = (
        BinanceNodeClient(settings.binance_node_url) if settings.binance_node_url else None
    )

    def node_or_503() -> BinanceNodeClient:
        if node_client is None:
            raise HTTPException(
                status_code=503,
                detail="未配置 Binance 执行节点（GRIDTRADE_BINANCE_NODE_URL）",
            )
        return node_client

    def node_fetch(fn: Any) -> Any:
        try:
            return fn()
        except BinanceNodeError as exc:
            raise HTTPException(status_code=502, detail=f"执行节点错误: {exc.msg}") from exc

    @app.get("/api/binance/health", dependencies=guarded)
    async def binance_health() -> dict[str, Any]:
        client = node_or_503()
        payload = await asyncio.to_thread(node_fetch, client.health)
        return {"ok": True, "node_url": client.base_url, "health": payload}

    @app.get("/api/binance/state", dependencies=guarded)
    async def binance_state(symbol: str | None = None) -> dict[str, Any]:
        client = node_or_503()

        def collect() -> dict[str, Any]:
            out: dict[str, Any] = {"node_url": client.base_url, "errors": {}}
            for key, fn in (
                ("health", client.health),
                ("account", client.account),
                ("positions", lambda: client.positions(symbol)),
                ("orders", lambda: client.open_orders(symbol)),
                ("fills", lambda: client.fills(symbol, limit=20)),
                ("history", lambda: client.all_orders(symbol, limit=20)),
                ("alerts", client.alerts),
            ):
                try:
                    out[key] = fn()
                except BinanceNodeError as exc:  # keep partial data
                    out["errors"][key] = exc.msg
            return out

        return await asyncio.to_thread(collect)

    @app.get("/api/risk", dependencies=guarded)
    async def risk(
        symbol: str | None = None,
        capital: float = Query(10_000, gt=0, le=10_000_000),
        spacing_bp: float = Query(120, gt=0),
        levels: int = Query(30, ge=1, le=500),
        leverage: float = Query(0.5, gt=0, le=10),
    ) -> dict[str, Any]:
        resolved = resolve_symbol(symbol)
        grid = GridParams(spacing_bp=spacing_bp, levels=levels, leverage=leverage)
        profile = await asyncio.to_thread(service.risk_profile, capital, resolved, grid)
        latest = await asyncio.to_thread(store.latest_succeeded, "replay")
        rejections: list[dict[str, Any]] = []
        if latest is not None:
            artifact = await asyncio.to_thread(store.load_artifact, latest["id"])
            rejections = ((artifact or {}).get("orders") or {}).get("rejection_reasons", [])
        return {
            "symbol": resolved,
            "capital": capital,
            "grid": asdict(grid),
            "stop_dd": 0.10,
            "kill_switch": store.get_bool("kill_switch", False),
            "rejections": rejections,
            "latest_run": latest,
            **profile,
        }

    @app.post("/api/settings/kill-switch", dependencies=guarded)
    async def set_kill_switch(payload: KillSwitchRequest) -> dict[str, Any]:
        store.set_setting("kill_switch", "1" if payload.engaged else "0")
        store.audit(
            "risk.kill_switch", "engaged" if payload.engaged else "released", actor="panel"
        )
        return {"kill_switch": payload.engaged}

    @app.get("/api/settings", dependencies=guarded)
    async def settings_view() -> dict[str, Any]:
        return {
            "version": VERSION,
            "auth": {
                "mode": "bearer",
                "token_hint": "…" + settings.token[-4:],
                "cookie": COOKIE_NAME,
            },
            "paths": {
                "data": str(settings.data_dir),
                "var": str(settings.var_dir),
                "web": str(settings.web_dir),
                "web_built": (settings.web_dir / "index.html").is_file(),
            },
            "server": {
                "host": settings.host,
                "port": settings.port,
                "cors_origins": settings.cors_origins,
                "uptime_s": round(time.time() - started_at, 1),
            },
            "symbol": resolve_symbol(None),
            "symbols": visible_symbols(),
            "intervals": list(INTERVALS),
            "modes": MODES,
            "kill_switch": store.get_bool("kill_switch", False),
        }

    @app.get("/api/admin/google", dependencies=admin_guarded)
    async def admin_google() -> dict[str, Any]:
        config = google_store.config()
        return {
            "enabled": config.enabled,
            "configured": config.configured,
            "client_id": config.client_id,
            "secret_hint": ("…" + config.client_secret[-4:]) if config.client_secret else "",
            "users": await asyncio.to_thread(google_store.list_users),
            "device_flow": True,
        }

    @app.post("/api/admin/google/config", dependencies=admin_guarded)
    async def admin_google_config(payload: AdminGoogleConfig) -> dict[str, Any]:
        config = await asyncio.to_thread(
            google_store.set_config,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            enabled=payload.enabled,
            clear_secret=payload.clear_secret,
        )
        store.audit("admin.google_config", "updated", actor="admin")
        return {
            "enabled": config.enabled,
            "configured": config.configured,
            "client_id": config.client_id,
            "secret_hint": ("…" + config.client_secret[-4:]) if config.client_secret else "",
        }

    @app.post("/api/admin/google/users", dependencies=admin_guarded)
    async def admin_google_add_user(payload: AdminGoogleUser) -> dict[str, Any]:
        try:
            user = await asyncio.to_thread(
                google_store.add_user,
                payload.email,
                payload.name,
                "admin",
                payload.is_admin,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.audit("admin.google_user_add", user["email"], actor="admin")
        return {"user": user}

    @app.patch("/api/admin/google/users", dependencies=admin_guarded)
    async def admin_google_set_role(payload: AdminGoogleRole) -> dict[str, Any]:
        ok = await asyncio.to_thread(google_store.set_admin, payload.email, payload.is_admin)
        if not ok:
            raise HTTPException(status_code=404, detail="账号不存在")
        store.audit(
            "admin.google_user_role",
            f"{payload.email.lower()}={'admin' if payload.is_admin else 'panel'}",
            actor="admin",
        )
        return {"ok": True, "email": payload.email.lower(), "is_admin": payload.is_admin}

    @app.delete("/api/admin/google/users", dependencies=admin_guarded)
    async def admin_google_remove_user(email: str = Query(..., min_length=3, max_length=254)) -> dict[str, Any]:
        removed = await asyncio.to_thread(google_store.remove_user, email)
        store.audit("admin.google_user_remove", email.lower(), actor="admin")
        return {"removed": removed}

    @app.get("/api/audit", dependencies=guarded)
    async def audit_log(limit: int = Query(60, ge=1, le=500)) -> dict[str, Any]:
        return {"entries": await asyncio.to_thread(store.list_audit, limit=limit)}

    # -- websocket --------------------------------------------------------

    @app.websocket("/ws")
    async def market_stream(
        websocket: WebSocket,
        token: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
    ) -> None:
        supplied = token or websocket.cookies.get(COOKIE_NAME, "")
        if actor_for(supplied) is None:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        available = service.symbols()
        chosen = (symbol or settings.symbol).upper()
        if chosen not in available:
            chosen = available[0] if available else settings.symbol
        try:
            while True:
                snapshot = await service.market_snapshot(chosen)
                await websocket.send_json(
                    {
                        "type": "market",
                        "symbol": chosen,
                        "data": snapshot,
                        "sent_at": datetime.now(timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z"),
                    }
                )
                await asyncio.sleep(3)
        except (WebSocketDisconnect, RuntimeError):
            return

    # -- SPA --------------------------------------------------------------

    web_root = settings.web_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        if path:
            target = (web_root / path).resolve()
            if target.is_file() and web_root in target.parents:
                cache = (
                    "public, max-age=31536000, immutable"
                    if path.startswith("assets/")
                    else "no-cache"
                )
                return FileResponse(target, headers={"Cache-Control": cache})
        index = web_root / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {"detail": "web UI not built. Run: cd web && pnpm install && pnpm build"},
            status_code=503,
        )

    return app


app = create_app()
