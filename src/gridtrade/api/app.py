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
from dataclasses import asdict
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
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..research.runner import ResearchParams
from ..strategy.grid import GridParams
from .config import Settings
from .jobs import JobQueue
from .live import LiveMarket
from .service import INTERVALS, ResearchService
from .store import Store

VERSION = "0.1.0"
COOKIE_NAME = "gt_token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30
MODES = {
    "research": {"enabled": True, "label": "研究", "detail": "本地 Parquet 回放"},
    "paper": {
        "enabled": False,
        "label": "模拟",
        "detail": "等待流式模拟适配器；回放仍然可用",
    },
    "live": {"enabled": False, "locked": True, "label": "实盘", "detail": "未提供实盘适配器"},
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


class KillSwitchRequest(BaseModel):
    engaged: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.var_dir / "gridtrade.db")
    live = LiveMarket()
    service = ResearchService(settings.data_dir, live)
    jobs = JobQueue(store, workers=2)
    started_at = time.time()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_run:
            recovered = store.fail_interrupted("服务重启导致任务中断")
            if recovered:
                log.warning("recovered %s stale run(s) from previous process", recovered)
        jobs.start()
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

    def require_token(request: Request) -> None:
        if not hmac.compare_digest(supplied_token(request), settings.token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing access token",
                headers={"WWW-Authenticate": "Bearer"},
            )

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

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": VERSION,
            "uptime_s": round(time.time() - started_at, 1),
            "symbols": visible_symbols(),
        }

    @app.post("/api/auth/login", tags=["auth"])
    async def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        if not hmac.compare_digest(payload.token.strip(), settings.token):
            store.audit("auth.failed", "invalid token")
            raise HTTPException(status_code=401, detail="invalid access token")
        response.set_cookie(
            COOKIE_NAME,
            settings.token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookie,
            path="/",
        )
        store.audit("auth.login", "cookie issued")
        return {
            "ok": True,
            "token_hint": "…" + settings.token[-4:],
            "expires_in": COOKIE_MAX_AGE,
        }

    @app.post("/api/auth/logout", tags=["auth"], dependencies=guarded)
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(COOKIE_NAME, path="/")
        store.audit("auth.logout", "cookie cleared")
        return {"ok": True}

    @app.get("/api/session", tags=["system"], dependencies=guarded)
    async def session() -> dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
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
            return await asyncio.to_thread(
                service.candles,
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
        return await asyncio.to_thread(service.funding, resolved, limit=limit)

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
        if not hmac.compare_digest(supplied, settings.token):
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
