"""Runtime configuration for the HTTP API.

Everything is environment-driven and local by default. Values are read from the
process environment first, then from a repo-root ``.env`` file (gitignored).
The API writes a random access token to ``var/token`` on first boot instead of
shipping a default credential; the login screen accepts that token.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _as_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _as_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def default_env_path() -> Path:
    """Locate the deployment ``.env``.

    When the package is installed non-editable, ``REPO_ROOT`` points inside
    site-packages; the working directory (systemd ``WorkingDirectory``) is the
    deployment root, so prefer it when it looks like a checkout. An explicit
    ``GRIDTRADE_ENV_FILE`` always wins.
    """
    explicit = os.environ.get("GRIDTRADE_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit)
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").is_file() or (cwd / "src" / "gridtrade").is_dir():
        return cwd / ".env"
    return REPO_ROOT / ".env"


def load_env_file(path: Path | None = None) -> Path | None:
    """Load KEY=VALUE pairs from ``.env`` without overriding the environment.

    Real environment variables win so systemd overrides and one-off commands
    still behave as expected. Returns the file that was read, if any.
    """
    target = path or default_env_path()
    if not target.is_file():
        return None
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)
    return target


def _token(var_dir: Path) -> str:
    env = os.environ.get("GRIDTRADE_TOKEN", "").strip()
    if env:
        return env
    var_dir.mkdir(parents=True, exist_ok=True)
    path = var_dir / "token"
    if path.exists():
        value = path.read_text().strip()
        if value:
            return value
    value = secrets.token_urlsafe(24)
    path.write_text(value + "\n")
    path.chmod(0o600)
    return value


def _symbols() -> list[str]:
    raw = os.environ.get("GRIDTRADE_PAPER_SYMBOLS") or os.environ.get(
        "GRIDTRADE_PAPER_SYMBOL", "SKHY_USDT,SPCX_USDT,GOOGL_USDT,AMGN_USDT"
    )
    seen: list[str] = []
    for item in raw.split(","):
        name = item.strip().upper()
        if name and name not in seen:
            seen.append(name)
    return seen or ["SKHY_USDT", "SPCX_USDT", "GOOGL_USDT", "AMGN_USDT"]


@dataclass(slots=True)
class PaperConfig:
    """Live paper-trading grid driven by a public futures market feed."""

    enabled: bool = False
    autostart: bool = False
    source: str = "gate"
    symbols: list[str] = field(
        default_factory=lambda: ["SKHY_USDT", "SPCX_USDT", "GOOGL_USDT", "AMGN_USDT"]
    )
    capital: float = 10_000.0
    leverage: float = 2.0
    spacing_bp: float = 60.0
    levels: int = 20
    stop_dd_pct: float = 10.0
    maker_fee_bp: float = 2.0
    taker_fee_bp: float = 5.0
    slippage_bp: float = 0.2
    use_exchange_fees: bool = True
    poll_seconds: float = 3.0

    @classmethod
    def from_env(cls) -> PaperConfig:
        return cls(
            enabled=_env_bool("GRIDTRADE_PAPER_ENABLED", True),
            autostart=_env_bool("GRIDTRADE_PAPER_AUTOSTART", True),
            source=os.environ.get("GRIDTRADE_PAPER_SOURCE", "gate").strip().lower(),
            symbols=_symbols(),
            capital=_as_float("GRIDTRADE_PAPER_CAPITAL", 10_000.0),
            leverage=_as_float("GRIDTRADE_PAPER_LEVERAGE", 2.0),
            spacing_bp=_as_float("GRIDTRADE_PAPER_SPACING_BP", 60.0),
            levels=_as_int("GRIDTRADE_PAPER_LEVELS", 20),
            stop_dd_pct=_as_float("GRIDTRADE_PAPER_STOP_DD_PCT", 10.0),
            maker_fee_bp=_as_float("GRIDTRADE_PAPER_MAKER_FEE_BP", 2.0),
            taker_fee_bp=_as_float("GRIDTRADE_PAPER_TAKER_FEE_BP", 5.0),
            slippage_bp=max(0.0, _as_float("GRIDTRADE_PAPER_SLIPPAGE_BP", 0.2)),
            use_exchange_fees=_env_bool("GRIDTRADE_PAPER_USE_EXCHANGE_FEES", True),
            poll_seconds=max(1.0, _as_float("GRIDTRADE_PAPER_POLL_SECONDS", 3.0)),
        )


@dataclass(slots=True)
class LiveConfig:
    """Gate USDT futures live account. Trading stays locked unless explicitly enabled."""

    enabled: bool = False
    trading_enabled: bool = False
    exchange: str = "gate"
    api_key: str = ""
    api_secret: str = ""
    subaccount: str = ""
    max_notional: float = 5_000.0
    max_order_notional: float = 1_000.0
    max_position_notional: float = 3_000.0
    max_open_orders: int = 20
    poll_seconds: float = 15.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    @classmethod
    def from_env(cls) -> LiveConfig:
        return cls(
            enabled=_env_bool("GRIDTRADE_LIVE_ENABLED", False),
            trading_enabled=_env_bool("GRIDTRADE_LIVE_TRADING", False),
            exchange=os.environ.get("GRIDTRADE_LIVE_EXCHANGE", "gate").strip().lower(),
            api_key=os.environ.get("GATE_API_KEY", "").strip(),
            api_secret=os.environ.get("GATE_API_SECRET", "").strip(),
            subaccount=os.environ.get("GRIDTRADE_LIVE_SUBACCOUNT", "").strip(),
            max_notional=_as_float("GRIDTRADE_LIVE_MAX_NOTIONAL", 5_000.0),
            max_order_notional=_as_float("GRIDTRADE_LIVE_MAX_ORDER_NOTIONAL", 1_000.0),
            max_position_notional=_as_float("GRIDTRADE_LIVE_MAX_POSITION_NOTIONAL", 3_000.0),
            max_open_orders=_as_int("GRIDTRADE_LIVE_MAX_OPEN_ORDERS", 20),
            poll_seconds=max(3.0, _as_float("GRIDTRADE_LIVE_POLL_SECONDS", 15.0)),
        )


@dataclass(slots=True)
class Settings:
    data_dir: Path = REPO_ROOT / "research" / "data"
    var_dir: Path = REPO_ROOT / "var"
    web_dir: Path = REPO_ROOT / "web" / "dist"
    symbol: str = "GOOGLUSDT"
    host: str = "127.0.0.1"
    port: int = 8000
    auto_run: bool = True
    secure_cookie: bool = False
    market_live: bool = True
    proxy: str = ""
    binance_node_url: str = ""
    token: str = ""
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    paper: PaperConfig = field(default_factory=PaperConfig)
    live: LiveConfig = field(default_factory=LiveConfig)
    env_path: Path = field(default_factory=default_env_path)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.var_dir = Path(self.var_dir)
        self.web_dir = Path(self.web_dir)
        self.env_path = Path(self.env_path)
        self.var_dir.mkdir(parents=True, exist_ok=True)
        if not self.token:
            self.token = _token(self.var_dir)

    @classmethod
    def from_env(cls) -> Settings:
        load_env_file()
        origins = os.environ.get(
            "GRIDTRADE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        )
        return cls(
            data_dir=Path(os.environ.get("GRIDTRADE_DATA", REPO_ROOT / "research" / "data")),
            var_dir=Path(os.environ.get("GRIDTRADE_VAR", REPO_ROOT / "var")),
            web_dir=Path(os.environ.get("GRIDTRADE_WEB", REPO_ROOT / "web" / "dist")),
            symbol=os.environ.get("GRIDTRADE_SYMBOL", "GOOGLUSDT"),
            host=os.environ.get("GRIDTRADE_HOST", "127.0.0.1"),
            port=_as_int("GRIDTRADE_PORT", 8000),
            auto_run=_env_bool("GRIDTRADE_AUTORUN", True),
            secure_cookie=_env_bool("GRIDTRADE_SECURE_COOKIE", False),
            market_live=_env_bool("GRIDTRADE_MARKET_LIVE", True),
            proxy=os.environ.get("GRIDTRADE_PROXY", "").strip(),
            binance_node_url=os.environ.get("GRIDTRADE_BINANCE_NODE_URL", "").strip(),
            token=os.environ.get("GRIDTRADE_TOKEN", "").strip(),
            cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
            paper=PaperConfig.from_env(),
            live=LiveConfig.from_env(),
            env_path=default_env_path(),
        )
