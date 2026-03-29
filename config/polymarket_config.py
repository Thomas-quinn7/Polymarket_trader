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

    # Builder Configuration
    # BUILDER_TIER controls which rate limit applies:
    #   unverified — 100 relay transactions/day  (default, no approval needed)
    #   verified   — 3,000 relay transactions/day (manual approval via builder@polymarket.com)
    #   partner    — unlimited                    (enterprise / strategic partner)
    # BUILDER_ENABLED must also be True for the SDK to attach builder auth headers to orders.
    BUILDER_ENABLED = os.getenv("BUILDER_ENABLED", "False").lower() == "true"
    BUILDER_TIER = os.getenv("BUILDER_TIER", "unverified").lower()  # unverified | verified | partner
    BUILDER_API_KEY = os.getenv("BUILDER_API_KEY")
    BUILDER_SECRET = os.getenv("BUILDER_SECRET")
    BUILDER_PASSPHRASE = os.getenv("BUILDER_PASSPHRASE")

    # Per-tier daily relay transaction limits (used for logging and safe-interval calculation)
    _TIER_DAILY_LIMITS = {
        "unverified": 100,
        "verified":   3_000,
        "partner":    None,   # None = unlimited
    }

    @property
    def daily_request_limit(self):
        """Return the daily relay transaction limit for the configured builder tier."""
        return self._TIER_DAILY_LIMITS.get(self.BUILDER_TIER, 100)

    @property
    def safe_scan_interval_ms(self) -> int:
        """
        Return the minimum safe scan interval in ms for the current builder tier.
        Each full scan consumes ~4 API calls (one per market category).
        Unverified: 100/day ÷ 4 = 25 scans → 86400000ms / 25 = 3,456,000ms (~57 min)
        Verified:   3000/day ÷ 4 = 750 scans → 86400000ms / 750 = 115,200ms (~2 min)
        Partner:    unlimited → 30,000ms (30s) as a sensible default
        """
        limit = self.daily_request_limit
        if limit is None:
            return 30_000
        scans_per_day = limit // 4
        return int(86_400_000 / scans_per_day) if scans_per_day > 0 else 86_400_000

    @property
    def builder_tier_label(self) -> str:
        """Human-readable label for the current builder tier and rate limit."""
        limit = self.daily_request_limit
        limit_str = "unlimited" if limit is None else f"{limit:,}/day"
        enabled = "enabled" if self.BUILDER_ENABLED else "disabled"
        return f"{self.BUILDER_TIER} ({limit_str}, builder auth {enabled})"

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

    # Trading Mode
    # "paper"      - real Polymarket API prices, simulated order execution (no real money)
    # "simulation" - fully offline, synthetic market data, no API calls
    TRADING_MODE = os.getenv("TRADING_MODE", "paper").lower()
    PAPER_TRADING_ONLY = os.getenv("PAPER_TRADING_ONLY", "True").lower() == "true"

    # Strategy Selection
    # Name of the strategy to load from strategies/registry.py.
    # Set STRATEGY=<name> in .env to switch strategies without code changes.
    STRATEGY = os.getenv("STRATEGY", "settlement_arbitrage")

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
    MIN_PRICE_THRESHOLD = float(os.getenv("MIN_PRICE_THRESHOLD", "0.95"))
    MAX_PRICE_THRESHOLD = float(os.getenv("MAX_PRICE_THRESHOLD", "1.00"))
    MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
    CAPITAL_SPLIT_PERCENT = float(os.getenv("CAPITAL_SPLIT_PERCENT", "0.20"))

    # Fee Configuration
    # Polymarket charges ~2% taker fee on CLOB. Edge must exceed this to be profitable.
    TAKER_FEE_PERCENT = float(os.getenv("TAKER_FEE_PERCENT", "2.0"))

    # Stop-loss: close a position early if its price drops this many percent below entry.
    # Set to 0.0 to disable stop-losses entirely.
    STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "0.0"))

    # Minimum confidence threshold (0.0–1.0).
    # Opportunities scored below this value are discarded before execution.
    # Confidence is calculated from price proximity, time-to-close, and edge size.
    MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.5"))

    # Liquidity Filter
    # Markets with volume below this threshold are excluded (too illiquid to trade)
    MIN_VOLUME_USD = float(os.getenv("MIN_VOLUME_USD", "1000.0"))

    # Scanning Configuration
    # WARNING: Each scan makes ~4 API calls (one per market category).
    # Safe minimums per builder tier (use safe_scan_interval_ms property for the computed value):
    #   unverified — 100 relay tx/day  →  25 scans/day  → ~3,456,000 ms (~57 min)
    #   verified   — 3,000 relay tx/day → 750 scans/day → ~115,200 ms  (~2 min)
    #   partner    — unlimited          →  no hard limit → 30,000 ms   (30s default)
    # Override via SCAN_INTERVAL_MS in .env. Defaults to 30s (safe for verified/partner).
    SCAN_INTERVAL_MS = int(os.getenv("SCAN_INTERVAL_MS", "30000"))

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

    # SQLite — trades, positions, PnL history
    DB_ENABLED = os.getenv("DB_ENABLED", "True").lower() == "true"
    DB_PATH = os.getenv("DB_PATH", "./storage/trading.db")

    # ScyllaDB — order book snapshot storage
    SCYLLA_ENABLED = os.getenv("SCYLLA_ENABLED", "False").lower() == "true"
    SCYLLA_HOST = os.getenv("SCYLLA_HOST", "127.0.0.1")
    SCYLLA_PORT = int(os.getenv("SCYLLA_PORT", "9042"))
    SCYLLA_KEYSPACE = os.getenv("SCYLLA_KEYSPACE", "polymarket")


    def reload(self):
        """Re-read .env and update all live-configurable fields in-place."""
        from dotenv import dotenv_values
        env = dotenv_values()
        self.TRADING_MODE                = env.get("TRADING_MODE", "paper").lower()
        self.PAPER_TRADING_ONLY          = env.get("PAPER_TRADING_ONLY", "True").lower() == "true"
        self.FAKE_CURRENCY_BALANCE       = float(env.get("FAKE_CURRENCY_BALANCE", "10000.00"))
        self.EXECUTE_BEFORE_CLOSE_SECONDS= int(env.get("EXECUTE_BEFORE_CLOSE_SECONDS", "2"))
        self.SCAN_INTERVAL_MS            = int(env.get("SCAN_INTERVAL_MS", "500"))
        self.MAX_POSITIONS               = int(env.get("MAX_POSITIONS", "5"))
        self.CAPITAL_SPLIT_PERCENT       = float(env.get("CAPITAL_SPLIT_PERCENT", "0.20"))
        self.MIN_PRICE_THRESHOLD         = float(env.get("MIN_PRICE_THRESHOLD", "0.95"))
        self.MAX_PRICE_THRESHOLD         = float(env.get("MAX_PRICE_THRESHOLD", "1.00"))
        self.STOP_LOSS_PERCENT           = float(env.get("STOP_LOSS_PERCENT", "0.0"))
        self.MIN_CONFIDENCE              = float(env.get("MIN_CONFIDENCE", "0.5"))
        self.BUILDER_ENABLED             = env.get("BUILDER_ENABLED", "False").lower() == "true"
        self.BUILDER_TIER                = env.get("BUILDER_TIER", "unverified").lower()
        self.ENABLE_EMAIL_ALERTS         = env.get("ENABLE_EMAIL_ALERTS", "True").lower() == "true"
        self.ENABLE_DISCORD_ALERTS       = env.get("ENABLE_DISCORD_ALERTS", "True").lower() == "true"
        self.DISCORD_WEBHOOK_URL         = env.get("DISCORD_WEBHOOK_URL", "")
        self.ALERT_EMAIL_FROM            = env.get("ALERT_EMAIL_FROM", "noreply@example.com")
        self.ALERT_EMAIL_TO              = env.get("ALERT_EMAIL_TO", "")
        self.SMTP_SERVER                 = env.get("SMTP_SERVER", "smtp.gmail.com")
        self.SMTP_PORT                   = int(env.get("SMTP_PORT", "587"))
        self.SMTP_USERNAME               = env.get("SMTP_USERNAME", "")
        self.LOG_LEVEL                   = env.get("LOG_LEVEL", "INFO")


# Global config instance
config = PolymarketConfig()
