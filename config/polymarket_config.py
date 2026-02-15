"""
Polymarket Configuration
Configuration settings for Polymarket Arbitrage Bot
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class PolymarketConfig:
    """Polymarket configuration settings"""

    # API Configuration
    POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
    POLYMARKET_FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS")
    CLOB_API_URL = "https://clob.polymarket.com"
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    CHAIN_ID = 137  # Polygon chain ID

    # Builder Configuration (for verified status and 3000 req/day)
    BUILDER_ENABLED = os.getenv("BUILDER_ENABLED", "False").lower() == "true"
    BUILDER_API_KEY = os.getenv("BUILDER_API_KEY")
    BUILDER_SECRET = os.getenv("BUILDER_SECRET")
    BUILDER_PASSPHRASE = os.getenv("BUILDER_PASSPHRASE")

    # Alert Configuration
    ENABLE_EMAIL_ALERTS = os.getenv("ENABLE_EMAIL_ALERTS", "True").lower() == "true"
    ENABLE_DISCORD_ALERTS = os.getenv("ENABLE_DISCORD_ALERTS", "True").lower() == "true"

    # Email Configuration (for alerts)
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "noreply@example.com")
    ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

    # Discord Configuration (for alerts)
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
    DISCORD_MENTION_USER = os.getenv("DISCORD_MENTION_USER", "")

    # Paper Trading
    PAPER_TRADING_ENABLED = os.getenv("PAPER_TRADING_ENABLED", "True").lower() == "true"
    PAPER_TRADING_ONLY = os.getenv("PAPER_TRADING_ONLY", "True").lower() == "true"
    FAKE_CURRENCY_BALANCE = float(os.getenv("FAKE_CURRENCY_BALANCE", "10000.00"))

    # Dashboard Configuration
    DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "True").lower() == "true"
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
    DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")

    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_TO_FILE = os.getenv("LOG_TO_FILE", "True").lower() == "true"

    # Arbitrage Strategy Configuration
    EXECUTE_BEFORE_CLOSE_SECONDS = int(os.getenv("EXECUTE_BEFORE_CLOSE_SECONDS", "2"))
    MIN_PRICE_THRESHOLD = 0.985  # 98.5 cents
    MAX_PRICE_THRESHOLD = 1.00  # 100 cents
    MAX_POSITIONS = 5
    CAPITAL_SPLIT_PERCENT = 0.2  # 20%

    # Scanning Configuration
    SCAN_INTERVAL_MS = 500

    # Market Categories (all enabled)
    ENABLE_CRYPTO_MARKETS = True
    ENABLE_FED_MARKETS = True
    ENABLE_REGULATORY_MARKETS = True
    ENABLE_OTHER_MARKETS = True

    # Market Priority (1=highest, 5=lowest)
    PRIORITY_CRYPTO = 1
    PRIORITY_FED = 2
    PRIORITY_REGULATORY = 3
    PRIORITY_OTHER = 4

    # Execution Settings
    ORDER_TYPE = "FOK"  # Fill or Kill
    SLIPPAGE_TOLERANCE_PERCENT = 5.0  # 5% max slippage
    MAX_RETRIES = 3
    RETRY_DELAY_MS = 100


# Global config instance
config = PolymarketConfig()
