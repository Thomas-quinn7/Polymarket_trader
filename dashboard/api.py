"""
Dashboard API Module
REST API for monitoring and controlling the trading bot
"""

import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

from utils.logger import logger
from utils.pnl_tracker import PnLTracker, TradeRecord, PnLSummary
from portfolio.position_tracker import Position
from portfolio.fake_currency_tracker import FakeCurrencyTracker
from execution.order_executor import OrderExecutor
from config.polymarket_config import config


# Global bot instance (will be set by main.py)
bot_instance = None


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
from fastapi.staticfiles import StaticFiles
import os

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    status: str
    opened_at: Optional[str]
    settled_at: Optional[str]
    settlement_price: Optional[float]
    realized_pnl: Optional[float]


class TradeResponse(BaseModel):
    """Trade response"""

    order_id: str
    position_id: str
    action: str
    market_id: str
    market_slug: str
    quantity: float
    price: float
    total: float
    executed_at: str
    status: str
    pnl: Optional[float]


class PnLResponse(BaseModel):
    """PnL response"""

    total_trades: int
    wins: int
    losses: int
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

    execute_before_close_seconds: int
    max_positions: int
    capital_split_percent: float
    min_price_threshold: float
    max_price_threshold: float
    scan_interval_ms: int
    fake_currency_balance: float


# Helper function to get bot instance
def get_bot():
    """Get the global bot instance"""
    if bot_instance is None:
        raise HTTPException(
            status_code=503, detail="Trading bot not initialized or not running. Please start the trading bot first."
        )
    return bot_instance


def is_bot_available():
    """Check if bot instance is available"""
    return bot_instance is not None


# Dashboard Routes
@app.get("/", response_class=HTMLResponse)
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
@app.get("/api/status", response_model=BotStatusResponse)
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
            mode="paper",
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
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def get_health():
    """Get system health"""
    try:
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "bot_running": bot_instance.running if bot_instance else False,
        }
    except Exception as e:
        logger.error(f"Error getting health: {e}")
        return {"status": "unhealthy", "error": str(e)}


# Portfolio Endpoints
@app.get("/api/portfolio")
async def get_portfolio():
    """Get portfolio summary"""
    try:
        bot = get_bot()

        return {
            "balance": bot.currency_tracker.get_balance(),
            "deployed": bot.currency_tracker.get_deployed(),
            "available": bot.currency_tracker.get_available(),
            "starting_balance": bot.currency_tracker.starting_balance,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting portfolio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pnl", response_model=PnLResponse)
async def get_pnl():
    """Get PnL summary"""
    try:
        bot = get_bot()
        summary = bot.pnl_tracker.get_summary()

        return PnLResponse(
            total_trades=summary.total_trades,
            wins=summary.wins,
            losses=summary.losses,
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
        logger.error(f"Error getting PnL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Position Endpoints
@app.get("/api/positions", response_model=List[PositionResponse])
async def get_positions(status: Optional[str] = None):
    """Get positions (open, settled, or all)"""
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
                status=p.status,
                opened_at=p.opened_at.isoformat() if p.opened_at else None,
                settled_at=p.settled_at.isoformat() if p.settled_at else None,
                settlement_price=p.settlement_price,
                realized_pnl=p.realized_pnl,
            )
            for p in positions
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Trade Endpoints
@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(limit: int = 50):
    """Get recent trades"""
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
                executed_at=o["executed_at"].isoformat() if isinstance(o["executed_at"], datetime) else o["executed_at"],
                status=o["status"],
                pnl=o.get("pnl"),
            )
            for o in orders
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Configuration Endpoints
@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """Get configuration"""
    return ConfigResponse(
        execute_before_close_seconds=config.EXECUTE_BEFORE_CLOSE_SECONDS,
        max_positions=config.MAX_POSITIONS,
        capital_split_percent=config.CAPITAL_SPLIT_PERCENT,
        min_price_threshold=config.MIN_PRICE_THRESHOLD,
        max_price_threshold=config.MAX_PRICE_THRESHOLD,
        scan_interval_ms=config.SCAN_INTERVAL_MS,
        fake_currency_balance=config.FAKE_CURRENCY_BALANCE,
    )


def start_dashboard(port: int = 8080, host: str = "0.0.0.0"):
    """Start the dashboard server"""
    logger.info(f"Starting dashboard server on {host}:{port}")

    uvicorn.run(
        "dashboard.api:app",
        host=host,
        port=port,
        log_level="info",
    )
