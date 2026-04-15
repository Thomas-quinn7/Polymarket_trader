"""
Dashboard API Module
REST API for monitoring and controlling the trading bot
"""

import os
import statistics as _stats
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
# Uses a regex to match any localhost port so that port auto-increment and
# hot-reload changes are reflected without a restart.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
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
        session_trades = 0
        if bot is not None and getattr(bot, "session_store", None) is not None:
            try:
                session_trades = len(bot.session_store.get_all_trades(limit=9999))
            except Exception:
                pass
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "bot_registered": bot is not None,
            "bot_running": bot.running if bot is not None else False,
            "session_trades_in_db": session_trades,
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
    """Get recent trades — current-session order history merged with historical session trades."""
    try:
        bot = _get_bot_instance()
        if bot is None:
            return []

        results: list = []

        # Current session: individual BUY/SELL orders from executor (in-memory)
        orders = bot.executor.get_order_history(limit=limit)
        current_position_ids: set = set()
        for o in orders:
            current_position_ids.add(o.get("position_id", ""))
            results.append(TradeResponse(
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
                    else str(o["executed_at"])
                ),
                status=o["status"],
                gross_pnl=o.get("gross_pnl"),
                pnl=o.get("pnl"),
            ))

        # Historical: completed round-trip trades from session store (survives restarts)
        # Skip any position already in the current executor history to avoid duplicates.
        if getattr(bot, "session_store", None) is not None:
            session_trades = bot.session_store.get_all_trades(limit=limit)
            for t in session_trades:
                if t.get("position_id") in current_position_ids:
                    continue
                results.append(TradeResponse(
                    order_id=t["trade_id"],
                    position_id=t["position_id"],
                    action="SETTLED",
                    market_id=t["market_id"],
                    market_slug=t.get("market_slug") or "",
                    token_id=t.get("winning_token_id") or "",
                    quantity=float(t.get("shares") or 0),
                    price=float(t.get("entry_price") or 0),
                    total=float(t.get("allocated_capital") or 0),
                    fee=float((t.get("entry_fee") or 0) + (t.get("exit_fee") or 0)),
                    slippage_pct=0.0,
                    executed_at=t.get("exit_time") or t.get("entry_time") or "",
                    status=t.get("outcome") or "SETTLED",
                    gross_pnl=t.get("gross_pnl"),
                    pnl=t.get("net_pnl"),
                ))

        # Sort newest first and cap at requested limit
        results.sort(key=lambda x: x.executed_at or "", reverse=True)
        return results[:limit]

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


@app.get("/api/analytics", dependencies=[_auth])
async def get_analytics():
    """
    Deep strategy evaluation metrics computed across all persisted session trades.

    Metrics returned
    ----------------
    risk          — VaR (95%), CVaR (95%), VaR (99% when ≥100 trades), per-trade
                    Sharpe and Sortino ratios, maximum drawdown.
    costs         — Total / entry / exit fees, fee-drag %, avg fee per trade,
                    break-even price and minimum edge needed to cover taker fee.
    edge_realization — Average expected edge at entry vs average realised net-edge,
                    plus a scatter array for the chart.
    slippage      — Distribution across 5 buckets (current-session order history).
    hold_times    — Distribution across 5 time buckets, min/avg/max seconds.
    distributions — Pre-bucketed PnL and entry-edge histograms for bar charts.
    """
    try:
        return _compute_analytics()
    except Exception as e:
        logger.error("Error computing analytics: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Analytics computation failed")


def _compute_analytics():
    """Compute analytics — extracted so get_analytics() can wrap it in try/except."""
    bot = _get_bot_instance()

    # ── Trades from session store (all historical sessions) ───────────
    trades: list = []
    if bot is not None and getattr(bot, "session_store", None) is not None:
        trades = bot.session_store.get_all_trades(limit=1000)

    # ── Slippage from in-memory order history (deque, last 500 orders) ─
    # Note: slippage is not stored in session_trades — this is the current
    # and recent session only.  See CODE_REVIEW #S-slip for the full fix.
    slip_values: list = []
    if bot is not None and hasattr(bot, "executor"):
        for o in bot.executor.get_order_history(limit=500):
            if o.get("action") == "BUY" and o.get("slippage_pct") is not None:
                slip_values.append(float(o["slippage_pct"]))

    n = len(trades)

    # ── Per-trade return series (net PnL as % of allocated capital) ────
    returns: list = []
    for t in trades:
        cap = t.get("allocated_capital") or 0.0
        pnl = t.get("net_pnl")
        if cap > 0 and pnl is not None:
            returns.append(pnl / cap * 100.0)

    net_pnls_raw = [t["net_pnl"] for t in trades if t.get("net_pnl") is not None]
    net_pnls_sorted = sorted(net_pnls_raw)

    # ── Risk metrics ──────────────────────────────────────────────────
    var_95 = var_99 = cvar_95 = sharpe = sortino = None

    if len(net_pnls_sorted) >= 4:
        idx_95 = max(0, int(len(net_pnls_sorted) * 0.05) - 1)
        var_95 = round(net_pnls_sorted[idx_95], 4)
        tail_95 = net_pnls_sorted[: max(1, int(len(net_pnls_sorted) * 0.05))]
        cvar_95 = round(sum(tail_95) / len(tail_95), 4)

    if len(net_pnls_sorted) >= 100:
        idx_99 = max(0, int(len(net_pnls_sorted) * 0.01) - 1)
        var_99 = round(net_pnls_sorted[idx_99], 4)

    if len(returns) >= 2:
        mean_r = _stats.mean(returns)
        stdev_r = _stats.stdev(returns)
        if stdev_r > 0:
            sharpe = round(mean_r / stdev_r, 3)
        downside = [r for r in returns if r < 0]
        if len(downside) >= 2:
            ds_std = _stats.stdev(downside)
            if ds_std > 0:
                sortino = round(mean_r / ds_std, 3)

    max_dd = None
    if bot is not None and hasattr(bot, "pnl_tracker"):
        max_dd = round(bot.pnl_tracker.max_drawdown, 2)

    # ── Cost metrics ──────────────────────────────────────────────────
    entry_fees = sum(t.get("entry_fee") or 0.0 for t in trades)
    exit_fees = sum(t.get("exit_fee") or 0.0 for t in trades)
    total_fees = entry_fees + exit_fees
    total_gross = sum(t.get("gross_pnl") or 0.0 for t in trades)
    total_net = sum(t.get("net_pnl") or 0.0 for t in trades)
    fee_drag = round(total_fees / total_gross * 100.0, 2) if total_gross > 0 else None
    avg_fee = round(total_fees / n, 4) if n > 0 else 0.0
    taker_fee = config.TAKER_FEE_PERCENT
    break_even_price = round(1.0 / (1.0 + taker_fee / 100.0), 6)

    # ── Edge realization ─────────────────────────────────────────────
    edge_scatter: list = []
    for t in trades:
        cap = t.get("allocated_capital") or 0.0
        exp_edge = t.get("edge_pct")
        pnl = t.get("net_pnl")
        if cap > 0 and exp_edge is not None and pnl is not None:
            edge_scatter.append({
                "expected": round(float(exp_edge), 4),
                "realized": round(pnl / cap * 100.0, 4),
                "outcome": t.get("outcome") or "",
            })
    # Limit scatter payload to most recent 300 trades
    edge_scatter = edge_scatter[-300:]

    avg_exp = round(sum(p["expected"] for p in edge_scatter) / len(edge_scatter), 4) if edge_scatter else None
    avg_real = round(sum(p["realized"] for p in edge_scatter) / len(edge_scatter), 4) if edge_scatter else None
    avg_leak = (
        round(avg_exp - avg_real, 4)
        if avg_exp is not None and avg_real is not None
        else None
    )

    # ── Slippage distribution ─────────────────────────────────────────
    slip_buckets = ["< -1%", "-1% to 0%", "0% to 0.5%", "0.5% to 1%", "> 1%"]
    slip_counts = [0, 0, 0, 0, 0]
    for s in slip_values:
        if s < -1.0:
            slip_counts[0] += 1
        elif s < 0.0:
            slip_counts[1] += 1
        elif s <= 0.5:
            slip_counts[2] += 1
        elif s <= 1.0:
            slip_counts[3] += 1
        else:
            slip_counts[4] += 1
    pct_adverse = (
        round(sum(1 for s in slip_values if s > 0) / len(slip_values) * 100.0, 1)
        if slip_values else 0.0
    )

    # ── Hold time distribution ────────────────────────────────────────
    hold_times = [
        t.get("hold_seconds") for t in trades if t.get("hold_seconds") is not None
    ]
    hold_buckets = ["< 1 min", "1–5 min", "5–30 min", "30 min–1 h", "> 1 h"]
    hold_counts = [0, 0, 0, 0, 0]
    for h in hold_times:
        if h < 60:
            hold_counts[0] += 1
        elif h < 300:
            hold_counts[1] += 1
        elif h < 1800:
            hold_counts[2] += 1
        elif h < 3600:
            hold_counts[3] += 1
        else:
            hold_counts[4] += 1

    # ── PnL histogram ────────────────────────────────────────────────
    def _histogram(values: list, n_bins: int, fmt_fn) -> tuple:
        """Return (bucket_labels, counts) for a list of floats."""
        if len(values) < 2:
            return [], []
        lo, hi = min(values), max(values)
        span = hi - lo
        if span < 1e-9:
            return [fmt_fn((lo + hi) / 2)], [len(values)]
        bins = min(n_bins, max(4, len(values) // 3))
        step = span / bins
        labels, counts = [], []
        for i in range(bins):
            b_lo = lo + i * step
            b_hi = lo + (i + 1) * step
            if i < bins - 1:
                c = sum(1 for v in values if b_lo <= v < b_hi)
            else:
                c = sum(1 for v in values if b_lo <= v <= b_hi)
            labels.append(fmt_fn((b_lo + b_hi) / 2))
            counts.append(c)
        return labels, counts

    pnl_buckets, pnl_counts = _histogram(
        net_pnls_raw, 12, lambda v: f"${v:.2f}"
    )
    edge_vals = [t.get("edge_pct") for t in trades if t.get("edge_pct") is not None]
    edge_hist_buckets, edge_hist_counts = _histogram(
        edge_vals, 10, lambda v: f"{v:.2f}%"
    )

    return {
        "sample_size": n,
        "insufficient_data": n < 5,
        "risk": {
            "var_95": var_95,
            "var_99": var_99,
            "cvar_95": cvar_95,
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown_pct": max_dd,
        },
        "costs": {
            "total_fees": round(total_fees, 4),
            "entry_fees": round(entry_fees, 4),
            "exit_fees": round(exit_fees, 4),
            "total_gross_pnl": round(total_gross, 4),
            "total_net_pnl": round(total_net, 4),
            "fee_drag_pct": fee_drag,
            "avg_fee_per_trade": avg_fee,
            "break_even_price": break_even_price,
            "break_even_edge_pct": round(taker_fee, 2),
            "taker_fee_pct": round(taker_fee, 2),
        },
        "edge_realization": {
            "avg_expected_edge": avg_exp,
            "avg_realized_edge": avg_real,
            "avg_leakage": avg_leak,
            "scatter": edge_scatter,
        },
        "slippage": {
            "count": len(slip_values),
            "note": "Current-session order history only",
            "avg_pct": round(sum(slip_values) / len(slip_values), 4) if slip_values else None,
            "max_adverse_pct": round(
                max((s for s in slip_values if s > 0), default=0.0), 4
            ),
            "pct_adverse_trades": pct_adverse,
            "buckets": slip_buckets,
            "counts": slip_counts,
        },
        "hold_times": {
            "count": len(hold_times),
            "avg_seconds": round(sum(hold_times) / len(hold_times), 1) if hold_times else None,
            "min_seconds": round(min(hold_times), 1) if hold_times else None,
            "max_seconds": round(max(hold_times), 1) if hold_times else None,
            "buckets": hold_buckets,
            "counts": hold_counts,
        },
        "distributions": {
            "pnl_buckets": pnl_buckets,
            "pnl_counts": pnl_counts,
            "edge_buckets": edge_hist_buckets,
            "edge_counts": edge_hist_counts,
            "edge_breakeven_pct": round(taker_fee, 2),
        },
    }


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


# ── Session Endpoints ─────────────────────────────────────────────────


@app.get("/api/sessions", dependencies=[_auth])
async def get_sessions(
    strategy: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    List past strategy sessions, newest first.
    Pass ?strategy=settlement_arbitrage to filter to one strategy.
    """
    bot = _get_bot_instance()
    if bot is None or bot.session_store is None:
        return []
    return bot.session_store.get_sessions(strategy=strategy, limit=limit)


@app.get("/api/sessions/{session_id}", dependencies=[_auth])
async def get_session(session_id: str):
    """Return full session data including every settled trade and the Ollama review."""
    bot = _get_bot_instance()
    if bot is None or bot.session_store is None:
        raise HTTPException(status_code=503, detail="Session store unavailable")
    data = bot.session_store.get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@app.post("/api/sessions/{session_id}/review", dependencies=[_auth])
async def regenerate_review(session_id: str):
    """
    Re-run the Ollama review for a past session.
    Useful for re-generating with a different model or after a model upgrade.
    """
    bot = _get_bot_instance()
    if bot is None or bot.session_store is None:
        raise HTTPException(status_code=503, detail="Session store unavailable")
    if bot.session_reviewer is None:
        raise HTTPException(status_code=503, detail="Ollama not enabled (set OLLAMA_ENABLED=true)")
    session_data = bot.session_store.get_session(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")

    # Reshape the flat DB row into the format generate_review expects
    stats_keys = {
        "total_trades",
        "winning_trades",
        "losing_trades",
        "break_even_trades",
        "win_rate",
        "total_gross_pnl",
        "total_net_pnl",
        "total_fees",
        "avg_hold_seconds",
        "avg_edge_pct",
        "avg_entry_price",
        "best_trade_pnl",
        "worst_trade_pnl",
        "profit_factor",
    }
    review_payload = {
        "session": {
            "session_id": session_data.get("session_id"),
            "strategy": session_data.get("strategy_name"),
            "start_time": session_data.get("start_time"),
            "end_time": session_data.get("end_time"),
            "trading_mode": session_data.get("trading_mode"),
            "starting_balance": session_data.get("starting_balance"),
            "ending_balance": session_data.get("ending_balance"),
        },
        "stats": {k: session_data.get(k) for k in stats_keys},
        "trades": session_data.get("trades", []),
    }

    review = bot.session_reviewer.generate_review(review_payload)
    if review is None:
        raise HTTPException(status_code=502, detail="Ollama generation failed")

    bot.session_store.save_review(session_id, review, config.OLLAMA_MODEL)
    return {"session_id": session_id, "review": review}


def start_dashboard(port: int = 8080, host: str = config.DASHBOARD_HOST):
    """Start the dashboard server"""
    logger.info(f"Starting dashboard server on {host}:{port}")

    uvicorn.run(
        "dashboard.api:app",
        host=host,
        port=port,
        log_level="info",
    )
