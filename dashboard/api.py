"""
Dashboard API Module
REST API for monitoring and controlling the trading bot
"""

import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from config.polymarket_config import config
from utils.logger import logger

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOTENV_PATH = os.path.join(_PROJECT_ROOT, ".env")

# Fields that only take effect after a full process restart
_RESTART_REQUIRED = {"fake_currency_balance"}

# Bot instance — written by main.py via set_bot_instance() before the
# dashboard thread starts, then read from dashboard endpoint handlers.
# _bot_lock protects the reference itself; individual tracker reads are
# safe under CPython's GIL for simple attribute/float access.
_bot_lock = threading.Lock()
_bot_instance = None


def set_bot_instance(bot) -> None:
    """Register the TradingBot with the dashboard. Called once by main.py."""
    global _bot_instance
    with _bot_lock:
        _bot_instance = bot


def _get_bot_instance():
    """Return the current bot instance (thread-safe read)."""
    with _bot_lock:
        return _bot_instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager"""
    logger.info("Dashboard API starting...")
    yield
    logger.info("Dashboard API shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Polymarket Arbitrage Bot Dashboard",
    description="Monitoring and control API for Polymarket Arbitrage Bot",
    version="1.0.0",
    lifespan=lifespan,
)

# Add static files mount
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Add CORS middleware — restrict to localhost origins so the dashboard is not
# reachable from arbitrary third-party websites even if the port is exposed.
# allow_credentials is omitted: the dashboard uses no cookies or auth headers.
_ALLOWED_ORIGINS = [
    f"http://localhost:{config.DASHBOARD_PORT}",
    f"http://127.0.0.1:{config.DASHBOARD_PORT}",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ── Authentication ──────────────────────────────────────────────────────────
async def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """
    Enforce API-key authentication when DASHBOARD_API_KEY is configured.

    Pass the key in the ``X-API-Key`` request header.  If DASHBOARD_API_KEY
    is empty (the default), authentication is disabled so existing setups
    continue to work without any changes.

    /api/health is intentionally excluded — it is a monitoring-only endpoint
    that returns no sensitive data and must remain reachable without credentials.
    """
    configured_key = config.DASHBOARD_API_KEY
    if not configured_key:
        return  # auth disabled
    if x_api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# Shared dependency applied to every endpoint that should be protected.
_auth = Depends(verify_api_key)


# Request/Response Models
class BotStatusResponse(BaseModel):
    """Bot status response"""

    running: bool
    mode: str
    open_positions: int
    max_positions: int
    balance: float
    deployed: float
    total_pnl: float
    win_rate: float
    uptime: str
    last_update: str


class PositionResponse(BaseModel):
    """Position response"""

    position_id: str
    market_id: str
    market_slug: str
    question: str
    shares: float
    entry_price: float
    allocated_capital: float
    expected_profit: float
    edge_percent: float
    entry_fee: float
    status: str
    opened_at: Optional[str]
    settled_at: Optional[str]
    settlement_price: Optional[float]
    exit_fee: float
    gross_pnl: Optional[float]
    realized_pnl: Optional[float]


class TradeResponse(BaseModel):
    """Trade response"""

    order_id: str
    position_id: str
    action: str
    market_id: str
    market_slug: str
    token_id: str
    quantity: float
    price: float
    total: float
    fee: float
    slippage_pct: float
    executed_at: str
    status: str
    gross_pnl: Optional[float]
    pnl: Optional[float]


class PnLResponse(BaseModel):
    """PnL response"""

    total_trades: int
    wins: int
    losses: int
    gross_pnl: float
    total_fees_paid: float
    total_pnl: float
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    max_drawdown: float
    current_drawdown: float
    peak_balance: float
    initial_balance: float


class ConfigResponse(BaseModel):
    """Configuration response"""

    max_positions: int
    capital_split_percent: float
    scan_interval_ms: int
    fake_currency_balance: float


# Attributes that must be present for a bot instance to be considered fully
# initialised.  Guards against partially-constructed objects being exposed
# via the API if set_bot_instance() is ever called too early.
_REQUIRED_BOT_ATTRS = (
    "running",
    "pnl_tracker",
    "position_tracker",
    "currency_tracker",
    "strategy",
)


def get_bot():
    """
    Return the current TradingBot instance or raise HTTP 503.

    Raises 503 if:
    - set_bot_instance() has not yet been called (None reference), or
    - the stored instance is missing required attributes (partially initialised).
    """
    bot = _get_bot_instance()
    if bot is None:
        raise HTTPException(
            status_code=503,
            detail="Trading bot not initialized. Please start the trading bot first.",
        )
    missing = [attr for attr in _REQUIRED_BOT_ATTRS if not hasattr(bot, attr)]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Trading bot is not fully initialized (missing: {', '.join(missing)}).",
        )
    return bot


def is_bot_available():
    """Return True only when a fully-initialised bot instance is registered."""
    bot = _get_bot_instance()
    if bot is None:
        return False
    return all(hasattr(bot, attr) for attr in _REQUIRED_BOT_ATTRS)


# Dashboard Routes
@app.get("/", response_class=HTMLResponse, dependencies=[_auth])
async def get_dashboard():
    """Serve the dashboard HTML page"""
    try:
        # Get working directory path
        import os

        dashboard_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Dashboard not found</h1><p>Static files not available</p>")


# Status Endpoints
@app.get("/api/status", response_model=BotStatusResponse, dependencies=[_auth])
async def get_status():
    """Get bot status"""
    try:
        bot = get_bot()

        # Calculate uptime
        uptime = "Unknown"
        if hasattr(bot, "start_time"):
            uptime_seconds = (datetime.now() - bot.start_time).total_seconds()
            uptime = f"{uptime_seconds:.0f}s"

        pnl_summary = bot.pnl_tracker.get_summary()

        return BotStatusResponse(
            running=bot.running,
            mode=config.TRADING_MODE,
            open_positions=bot.position_tracker.get_position_count(),
            max_positions=config.MAX_POSITIONS,
            balance=bot.currency_tracker.get_balance(),
            deployed=bot.currency_tracker.get_deployed(),
            total_pnl=pnl_summary.total_pnl,
            win_rate=pnl_summary.win_rate,
            uptime=uptime,
            last_update=datetime.now().isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/health")
async def get_health():
    """Get system health"""
    try:
        bot = _get_bot_instance()
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "bot_running": bot.running if bot is not None else False,
        }
    except Exception as e:
        logger.error(f"Error getting health: {e}")
        return {"status": "unhealthy", "error": str(e)}


# Portfolio Endpoints
@app.get("/api/portfolio", dependencies=[_auth])
async def get_portfolio():
    """Get portfolio summary"""
    try:
        bot = get_bot()

        balance = bot.currency_tracker.get_balance()
        deployed = bot.currency_tracker.get_deployed()
        return {
            "balance": balance,
            "deployed": deployed,
            "available": bot.currency_tracker.get_balance(),
            "starting_balance": bot.currency_tracker.starting_balance,
            # total_value = cash-in-hand + deployed capital (at cost basis).
            # Used to compute unrealised gain so an open position doesn't
            # show as a loss simply because cash left the balance.
            "total_value": balance + deployed,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting portfolio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/pnl", response_model=PnLResponse, dependencies=[_auth])
async def get_pnl():
    """Get PnL summary"""
    try:
        bot = get_bot()
        summary = bot.pnl_tracker.get_summary()

        return PnLResponse(
            total_trades=summary.total_trades,
            wins=summary.wins,
            losses=summary.losses,
            gross_pnl=summary.gross_pnl,
            total_fees_paid=summary.total_fees_paid,
            total_pnl=summary.total_pnl,
            win_rate=summary.win_rate,
            average_win=summary.average_win,
            average_loss=summary.average_loss,
            profit_factor=summary.profit_factor,
            max_drawdown=summary.max_drawdown,
            current_drawdown=summary.current_drawdown,
            peak_balance=summary.peak_balance,
            initial_balance=summary.initial_balance,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting PnL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# Position Endpoints
@app.get("/api/positions", response_model=List[PositionResponse], dependencies=[_auth])
async def get_positions(status: Optional[Literal["open", "settled"]] = None):
    """Get positions — pass ?status=open or ?status=settled to filter."""
    try:
        bot = get_bot()

        if status == "open":
            positions = bot.position_tracker.get_open_positions()
        elif status == "settled":
            positions = bot.position_tracker.get_settled_positions()
        else:
            positions = bot.position_tracker.get_all_positions()

        return [
            PositionResponse(
                position_id=p.position_id,
                market_id=p.market_id,
                market_slug=p.market_slug,
                question=p.question,
                shares=p.shares,
                entry_price=p.entry_price,
                allocated_capital=p.allocated_capital,
                expected_profit=p.expected_profit,
                edge_percent=p.edge_percent,
                entry_fee=p.entry_fee,
                status=p.status,
                opened_at=p.opened_at.isoformat() if p.opened_at else None,
                settled_at=p.settled_at.isoformat() if p.settled_at else None,
                settlement_price=p.settlement_price,
                exit_fee=p.exit_fee,
                gross_pnl=p.gross_pnl,
                realized_pnl=p.realized_pnl,
            )
            for p in positions
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting positions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# Trade Endpoints
@app.get("/api/trades", response_model=List[TradeResponse], dependencies=[_auth])
async def get_trades(limit: int = Query(default=50, ge=1, le=500)):
    """Get recent trades (max 500 — the order history buffer size)."""
    try:
        bot = get_bot()
        orders = bot.executor.get_order_history(limit=limit)

        return [
            TradeResponse(
                order_id=o["order_id"],
                position_id=o["position_id"],
                action=o["action"],
                market_id=o["market_id"],
                market_slug=o["market_slug"],
                token_id=o["token_id"],
                quantity=o["quantity"],
                price=o["price"],
                total=o["total"],
                fee=o.get("fee", 0.0),
                slippage_pct=o.get("slippage_pct", 0.0),
                executed_at=(
                    o["executed_at"].isoformat()
                    if isinstance(o["executed_at"], datetime)
                    else o["executed_at"]
                ),
                status=o["status"],
                gross_pnl=o.get("gross_pnl"),
                pnl=o.get("pnl"),
            )
            for o in orders
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trades: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# Execution Stats Endpoint
@app.get("/api/execution/stats", dependencies=[_auth])
async def get_execution_stats():
    """Execution quality metrics: fill rate, fees paid, slippage."""
    try:
        bot = get_bot()
        stats = bot.executor.get_execution_stats()
        pnl_summary = bot.pnl_tracker.get_summary()
        return {
            **stats,
            "taker_fee_percent": config.TAKER_FEE_PERCENT,
            "slippage_tolerance_percent": config.SLIPPAGE_TOLERANCE_PERCENT,
            "gross_pnl": pnl_summary.gross_pnl,
            "net_pnl": pnl_summary.total_pnl,
            "fee_drag_pct": (
                (pnl_summary.total_fees_paid / abs(pnl_summary.gross_pnl) * 100)
                if pnl_summary.gross_pnl != 0
                else 0.0
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# Configuration Endpoints
@app.get("/api/config", response_model=ConfigResponse, dependencies=[_auth])
async def get_config():
    """Get configuration"""
    return ConfigResponse(
        max_positions=config.MAX_POSITIONS,
        capital_split_percent=config.CAPITAL_SPLIT_PERCENT,
        scan_interval_ms=config.SCAN_INTERVAL_MS,
        fake_currency_balance=config.FAKE_CURRENCY_BALANCE,
    )


# ── Settings Models ────────────────────────────────────────────────────
class SettingsResponse(BaseModel):
    """
    All user-editable settings returned by GET /api/settings.

    Credential fields (webhook URLs, email passwords, private keys) are
    NEVER included here.  Where a credential is relevant to the UI,
    a boolean ``*_configured`` flag is returned instead so the frontend
    can show "configured / not configured" without exposing the secret.
    """

    trading_mode: str
    fake_currency_balance: float
    scan_interval_ms: int
    max_positions: int
    capital_split_percent: float
    min_confidence: float
    min_volume_usd: float
    enable_email_alerts: bool
    enable_discord_alerts: bool
    # Webhook URL is a bearer token — never echoed back.
    # Frontend uses this flag to show "Discord webhook configured ✓".
    discord_webhook_configured: bool
    alert_email_from: str
    alert_email_to: str
    smtp_server: str
    smtp_port: int
    # Username is non-secret; password is NOT returned.
    smtp_username: str
    log_level: str


class SettingsUpdate(BaseModel):
    """Partial update — any subset of fields"""

    trading_mode: Optional[str] = None
    fake_currency_balance: Optional[float] = None
    scan_interval_ms: Optional[int] = None
    max_positions: Optional[int] = None
    capital_split_percent: Optional[float] = None
    min_confidence: Optional[float] = None
    min_volume_usd: Optional[float] = None
    enable_email_alerts: Optional[bool] = None
    enable_discord_alerts: Optional[bool] = None
    discord_webhook_url: Optional[str] = None
    alert_email_from: Optional[str] = None
    alert_email_to: Optional[str] = None
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    log_level: Optional[str] = None


# Map Pydantic field → (.env key, serialiser)
_ENV_MAP: Dict[str, tuple] = {
    # trading_mode is a runtime toggle — updated in memory only, not written to .env
    "fake_currency_balance": ("FAKE_CURRENCY_BALANCE", str),
    "scan_interval_ms": ("SCAN_INTERVAL_MS", str),
    "max_positions": ("MAX_POSITIONS", str),
    "capital_split_percent": ("CAPITAL_SPLIT_PERCENT", str),
    "min_confidence": ("MIN_CONFIDENCE", str),
    "min_volume_usd": ("MIN_VOLUME_USD", str),
    "enable_email_alerts": ("ENABLE_EMAIL_ALERTS", lambda v: "true" if v else "false"),
    "enable_discord_alerts": ("ENABLE_DISCORD_ALERTS", lambda v: "true" if v else "false"),
    "discord_webhook_url": ("DISCORD_WEBHOOK_URL", str),
    "alert_email_from": ("ALERT_EMAIL_FROM", str),
    "alert_email_to": ("ALERT_EMAIL_TO", str),
    "smtp_server": ("SMTP_SERVER", str),
    "smtp_port": ("SMTP_PORT", str),
    "smtp_username": ("SMTP_USERNAME", str),
    "log_level": ("LOG_LEVEL", str),
}


@app.get("/api/settings", response_model=SettingsResponse, dependencies=[_auth])
async def get_settings():
    """
    Get all editable settings.

    Credential fields are never returned in plaintext — the Discord webhook
    URL is replaced with a boolean flag indicating whether it is configured.
    To update the webhook URL, POST to this endpoint with the new value.
    """
    return SettingsResponse(
        trading_mode=config.TRADING_MODE,
        fake_currency_balance=config.FAKE_CURRENCY_BALANCE,
        scan_interval_ms=config.SCAN_INTERVAL_MS,
        max_positions=config.MAX_POSITIONS,
        capital_split_percent=config.CAPITAL_SPLIT_PERCENT,
        min_confidence=config.MIN_CONFIDENCE,
        min_volume_usd=config.MIN_VOLUME_USD,
        enable_email_alerts=config.ENABLE_EMAIL_ALERTS,
        enable_discord_alerts=config.ENABLE_DISCORD_ALERTS,
        discord_webhook_configured=bool(config.DISCORD_WEBHOOK_URL),
        alert_email_from=config.ALERT_EMAIL_FROM,
        alert_email_to=config.ALERT_EMAIL_TO,
        smtp_server=config.SMTP_SERVER,
        smtp_port=config.SMTP_PORT,
        smtp_username=config.SMTP_USERNAME,
        log_level=config.LOG_LEVEL,
    )


def _write_env_key(dotenv_path: str, key: str, value: str) -> None:
    """
    Update a single key in a .env file with a direct in-place write.

    python-dotenv's set_key() writes to a tmp file then renames it, which
    fails on Docker bind mounts on Windows ("Device or resource busy").
    Writing directly to the file avoids that rename entirely.

    Security: strip CR, LF, and NUL from the value before writing.  A value
    containing a newline would split into two lines in the .env file, allowing
    a caller to inject arbitrary keys (e.g. "smtp.host\nPAPER_TRADING_ONLY=false")
    that would take effect on the next config.reload() call.
    """
    value = value.replace("\r", "").replace("\n", "").replace("\x00", "")

    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    found = False
    new_lines = []
    for line in lines:
        if line.lstrip().startswith(f"{key}=") or line.lstrip().startswith(f"{key} ="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    with open(dotenv_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


@app.post("/api/settings", dependencies=[_auth])
async def update_settings(update: SettingsUpdate):
    """Write changed values to .env and hot-reload config"""
    changed = []
    needs_restart = []
    payload = update.model_dump(exclude_none=True)

    # trading_mode is a runtime-only toggle — update config in memory, no file write.
    # PAPER_TRADING_ONLY is kept in sync so the executor's live-order gate matches
    # what the UI shows. Live mode is only reachable via the --live CLI flag (which
    # requires explicit confirmation), never through this endpoint.
    new_trading_mode: Optional[str] = None
    if "trading_mode" in payload:
        mode = payload.pop("trading_mode").lower()
        if mode not in ("paper", "simulation"):
            raise HTTPException(
                status_code=422, detail="trading_mode must be 'paper' or 'simulation'"
            )
        new_trading_mode = mode
        changed.append("trading_mode")

    for field, value in payload.items():
        env_key, serialiser = _ENV_MAP.get(field, (None, None))
        if env_key is None:
            continue
        try:
            _write_env_key(_DOTENV_PATH, env_key, serialiser(value))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Could not write to .env ({_DOTENV_PATH}): {e}",
            )
        changed.append(field)
        if field in _RESTART_REQUIRED:
            needs_restart.append(field)

    # Reload .env-backed fields first so they don't clobber the in-memory
    # trading_mode we're about to apply.
    if any(f != "trading_mode" for f in changed):
        config.reload()

    # Apply trading_mode AFTER reload so reload cannot overwrite it.
    if new_trading_mode is not None:
        config.TRADING_MODE = new_trading_mode
        config.PAPER_TRADING_ONLY = True  # paper and simulation are both non-live

    return {
        "updated": changed,
        "restart_required": needs_restart,
    }


# ── Bot Control Endpoints ──────────────────────────────────────────────
@app.post("/api/bot/start", dependencies=[_auth])
async def bot_start():
    """Start the trading loop (reinitialises client for current mode)."""
    bot = get_bot()
    if bot.running:
        raise HTTPException(status_code=409, detail="Trading loop already running")
    success = bot.start_trading_loop()
    return {"success": success, "running": bot.running, "mode": config.TRADING_MODE}


@app.post("/api/bot/stop", dependencies=[_auth])
async def bot_stop():
    """Signal the trading loop to stop after its current iteration."""
    bot = get_bot()
    if not bot.running:
        raise HTTPException(status_code=409, detail="Trading loop is not running")
    success = bot.stop_trading_loop()
    return {"success": success, "running": bot.running}


def start_dashboard(port: int = 8080, host: str = config.DASHBOARD_HOST):
    """Start the dashboard server"""
    logger.info(f"Starting dashboard server on {host}:{port}")

    uvicorn.run(
        "dashboard.api:app",
        host=host,
        port=port,
        log_level="info",
    )
