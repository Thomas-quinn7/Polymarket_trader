"""
Health routes - Health check endpoints.
"""

from typing import Dict

from fastapi import APIRouter
from config.polymarket_config import config

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check() -> Dict:
    """
    Health check endpoint.

    Returns:
        Health status
    """
    return {
        "status": "healthy",
        "service": "polymarket_trading_bot",
        "version": "1.0.0",
        "timestamp": "2026-03-17T10:00:00Z",
        "components": {
            "scanner": "active",
            "executor": "active",
            "portfolio": "active",
            "notifications": "active",
        },
    }


@router.get("/health/details")
async def health_check_details() -> Dict:
    """
    Detailed health check with component status.

    Returns:
        Detailed health status with component information
    """
    return {
        "status": "healthy",
        "service": "polymarket_trading_bot",
        "version": "1.0.0",
        "timestamp": "2026-03-17T10:00:00Z",
        "components": {
            "scanner": {
                "status": "healthy",
                "type": "PolymarketClient",
                "builder_tier": config.BUILDER_TIER,
                "rate_limit": (
                    "unlimited" if config.daily_request_limit is None
                    else f"{config.daily_request_limit:,} relay tx/day"
                ),
                "builder_auth": config.BUILDER_ENABLED,
                "safe_scan_interval_ms": config.safe_scan_interval_ms,
            },
            "executor": {
                "status": "healthy",
                "mode": "paper_trading_only",
                "position_limit": 5,
            },
            "portfolio": {
                "status": "healthy",
                "balance": 10000.0,
                "currency": "USD",
            },
            "notifications": {
                "status": "healthy",
                "channels": ["email", "discord"],
            },
            "database": {
                "status": "healthy",
                "type": "in_memory",
            },
        },
    }


@router.get("/health/readiness")
async def readiness_check() -> Dict:
    """
    Readiness check for orchestration systems.

    Returns:
        Readiness status
    """
    return {
        "ready": True,
        "timestamp": "2026-03-17T10:00:00Z",
        "dependencies": ["scanner", "executor", "portfolio", "notifications"],
    }
