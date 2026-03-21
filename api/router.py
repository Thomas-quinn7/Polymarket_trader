"""
API Router - Main FastAPI application setup.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pkg.config import get_settings
from pkg.logger import get_logger

from api.routes import bot_routes, portfolio_routes, health_routes


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    settings = get_settings()

    # Create FastAPI app
    app = FastAPI(
        title="Polymarket Trading Bot API",
        description="RESTful API for monitoring and controlling the trading bot",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "polymarket_trading_bot",
            "version": "1.0.0",
        }

    # Register routes
    app.include_router(health_routes.router, tags=["health"])
    app.include_router(bot_routes.router, tags=["bot"])
    app.include_router(portfolio_routes.router, tags=["portfolio"])

    logger = get_logger(__name__)
    logger.info("api_created", routes=[
        "/health",
        "/api/bot",
        "/api/portfolio",
    ])

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.router:app",
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        reload=True,
    )
