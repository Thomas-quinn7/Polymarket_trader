"""
Polymarket Configuration
Configuration settings for Polymarket Arbitrage Bot
"""

import os
from dotenv import load_dotenv

load_dotenv()


class PolymarketConfig:
    """Polymarket configuration settings"""

    # API Configuration
    POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
    POLYMARKET_FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS")
    CLOB_API_URL = "https://clob.polymarket.com"
    GAMMA_API_URL = "https://gamma-api.polymarket.com"
    CHAIN_ID = 137  # Polygon chain ID

    # Relayer API Configuration
    # Relayer keys provide unlimited relay transactions for a single wallet without tier approval.
    # Generate at: https://polymarket.com/settings?tab=api-keys
    # Docs: https://docs.polymarket.com/trading/gasless
    # When RELAYER_ENABLED=True, Relayer auth headers are injected alongside L2 CLOB headers.
    # Relayer mode takes priority over Builder mode if both are configured.
    RELAYER_ENABLED = os.getenv("RELAYER_ENABLED", "False").lower() == "true"
    RELAYER_API_KEY = os.getenv("RELAYER_API_KEY")
    RELAYER_API_KEY_ADDRESS = os.getenv("RELAYER_API_KEY_ADDRESS")

    # Builder Configuration
    # BUILDER_TIER controls which rate limit applies:
    #   unverified — 100 relay transactions/day  (default, no approval needed)
    #   verified   — 3,000 relay transactions/day (manual approval via builder@polymarket.com)
    #   partner    — unlimited                    (enterprise / strategic partner)
    # BUILDER_ENABLED must also be True for the SDK to attach builder auth headers to orders.
    BUILDER_ENABLED = os.getenv("BUILDER_ENABLED", "False").lower() == "true"
    BUILDER_TIER = os.getenv(
        "BUILDER_TIER", "unverified"
    ).lower()  # unverified | verified | partner
    BUILDER_API_KEY = os.getenv("BUILDER_API_KEY")
    BUILDER_SECRET = os.getenv("BUILDER_SECRET")
    BUILDER_PASSPHRASE = os.getenv("BUILDER_PASSPHRASE")

    # Per-tier daily relay transaction limits (used for logging and safe-interval calculation)
    _TIER_DAILY_LIMITS = {
        "unverified": 100,
        "verified": 3_000,
        "partner": None,  # None = unlimited
    }

    @property
    def daily_request_limit(self):
        """Return the daily relay transaction limit. None = unlimited (relayer or partner tier)."""
        if self.RELAYER_ENABLED:
            return None  # Relayer keys have no daily transaction limit
        return PolymarketConfig._TIER_DAILY_LIMITS.get(self.BUILDER_TIER, 100)

    @property
    def safe_scan_interval_ms(self) -> int:
        """
        Return the minimum safe scan interval in ms for the current auth mode.

        The divisor of 4 assumes one Gamma API call per enabled market category
        (crypto, fed, regulatory, other).  If fewer categories are enabled, or
        if multi-page pagination triggers additional calls, the actual call rate
        will differ.  Treat this value as a conservative lower bound and tune
        SCAN_INTERVAL_MS manually if needed.

        Relayer / Partner: unlimited → 30,000ms (30s) as a sensible default
        Verified:   3000/day ÷ 4 = 750 scans → 86400000ms / 750 = 115,200ms (~2 min)
        Unverified: 100/day ÷ 4 = 25 scans → 86400000ms / 25 = 3,456,000ms (~57 min)
        """
        limit = self.daily_request_limit
        if limit is None:
            return 30_000
        scans_per_day = limit // 4
        return int(86_400_000 / scans_per_day) if scans_per_day > 0 else 86_400_000

    @property
    def builder_tier_label(self) -> str:
        """Human-readable label for the current auth mode and rate limit."""
        if self.RELAYER_ENABLED:
            return "relayer (unlimited, relayer auth enabled)"
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
    STRATEGY = os.getenv("STRATEGY", "example_strategy")

    FAKE_CURRENCY_BALANCE = float(os.getenv("FAKE_CURRENCY_BALANCE", "10000.00"))

    # Dashboard Configuration
    DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "True").lower() == "true"
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
    # Bind to localhost by default so the dashboard is not exposed to the
    # local network.  Set DASHBOARD_HOST=0.0.0.0 in .env only when you
    # intentionally want remote access (e.g., behind a reverse proxy with auth).
    DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    # Optional API key for dashboard authentication.
    # When set, all endpoints (except /api/health) require the header
    # "X-API-Key: <value>".  Leave empty to disable auth (localhost-only default).
    DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")

    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_TO_FILE = os.getenv("LOG_TO_FILE", "True").lower() == "true"

    # ── Strategy execution ─────────────────────────────────────────────
    MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))
    CAPITAL_SPLIT_PERCENT = float(os.getenv("CAPITAL_SPLIT_PERCENT", "0.20"))

    # Fractional Kelly multiplier (0.0–1.0).
    # Full Kelly (1.0) maximises long-run growth but produces extreme volatility.
    # 0.25 (quarter Kelly) is a common conservative starting point.
    # Kelly sizing is applied in OrderExecutor and capped at CAPITAL_SPLIT_PERCENT.
    KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))

    # Maximum open positions allowed within a single market category (crypto, fed, etc.).
    # Prevents over-concentration in correlated markets.  Set to 0 to disable.
    MAX_POSITIONS_PER_CATEGORY = int(os.getenv("MAX_POSITIONS_PER_CATEGORY", "2"))

    # Stop-loss: close a position when price drops this % below entry (0 = disabled).
    STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "0.0"))

    # Minimum confidence threshold (0.0–1.0); strategy-computed, discards low-quality signals.
    MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.5"))

    # Liquidity filter: skip markets below this USD volume threshold.
    MIN_VOLUME_USD = float(os.getenv("MIN_VOLUME_USD", "1000.0"))

    # Market categories to scan (comma-separated). Strategies may override this.
    SCAN_CATEGORIES = [
        c.strip()
        for c in os.getenv("SCAN_CATEGORIES", "crypto,fed,regulatory,other").split(",")
        if c.strip()
    ]

    # Scanning Configuration
    # WARNING: Each scan makes ~4 API calls (one per market category).
    # Safe minimums per builder tier (use safe_scan_interval_ms property for the computed value):
    #   unverified — 100 relay tx/day  →  25 scans/day  → ~3,456,000 ms (~57 min)
    #   verified   — 3,000 relay tx/day → 750 scans/day → ~115,200 ms  (~2 min)
    #   partner    — unlimited          →  no hard limit → 30,000 ms   (30s default)
    # Override via SCAN_INTERVAL_MS in .env. Defaults to 30s (safe for verified/partner).
    SCAN_INTERVAL_MS = int(os.getenv("SCAN_INTERVAL_MS", "30000"))

    # Market Categories
    ENABLE_CRYPTO_MARKETS = os.getenv("ENABLE_CRYPTO_MARKETS", "True").lower() == "true"
    ENABLE_FED_MARKETS = os.getenv("ENABLE_FED_MARKETS", "True").lower() == "true"
    ENABLE_REGULATORY_MARKETS = os.getenv("ENABLE_REGULATORY_MARKETS", "True").lower() == "true"
    ENABLE_OTHER_MARKETS = os.getenv("ENABLE_OTHER_MARKETS", "True").lower() == "true"

    # Market Priority (1=highest, 5=lowest)
    PRIORITY_CRYPTO = int(os.getenv("PRIORITY_CRYPTO", "1"))
    PRIORITY_FED = int(os.getenv("PRIORITY_FED", "2"))
    PRIORITY_REGULATORY = int(os.getenv("PRIORITY_REGULATORY", "3"))
    PRIORITY_OTHER = int(os.getenv("PRIORITY_OTHER", "4"))

    # Execution Settings
    # ORDER_TYPE is intentionally absent: Polymarket's CLOB requires FOK (Fill-or-Kill)
    # for all market orders at the protocol level. The SDK hardcodes OrderType.FOK and
    # the exchange rejects any other type — it is not a user-configurable value.
    SLIPPAGE_TOLERANCE_PERCENT = float(os.getenv("SLIPPAGE_TOLERANCE_PERCENT", "5.0"))
    TAKER_FEE_PERCENT = float(os.getenv("TAKER_FEE_PERCENT", "2.0"))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY_MS = int(os.getenv("RETRY_DELAY_MS", "100"))

    # Power management (Windows only)
    # PREVENT_SLEEP=true  — blocks Windows idle sleep while the bot runs.
    # To also keep running when the lid is closed you must separately set
    # Windows Settings → Power → "When I close the lid" → "Do nothing".
    PREVENT_SLEEP = os.getenv("PREVENT_SLEEP", "False").lower() == "true"

    # SQLite — trades, positions, PnL history
    DB_ENABLED = os.getenv("DB_ENABLED", "True").lower() == "true"
    DB_PATH = os.getenv("DB_PATH", "./storage/trading.db")

    # ScyllaDB — order book snapshot storage
    SCYLLA_ENABLED = os.getenv("SCYLLA_ENABLED", "False").lower() == "true"
    SCYLLA_HOST = os.getenv("SCYLLA_HOST", "127.0.0.1")
    SCYLLA_PORT = int(os.getenv("SCYLLA_PORT", "9042"))
    SCYLLA_KEYSPACE = os.getenv("SCYLLA_KEYSPACE", "polymarket")

    # Session storage — per-strategy JSON exports for charting and algo processing
    SESSIONS_DIR = os.getenv("SESSIONS_DIR", "./logs/sessions")

    # Ollama — local LLM used to generate end-of-session strategy reviews
    OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "False").lower() == "true"
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    def __repr__(self) -> str:
        """
        Safe representation that masks all credential fields.

        Prevents private keys and API secrets from appearing in log output,
        exception tracebacks, or debug dumps.
        """
        return (
            f"PolymarketConfig("
            f"TRADING_MODE={self.TRADING_MODE!r}, "
            f"STRATEGY={self.STRATEGY!r}, "
            f"PAPER_TRADING_ONLY={self.PAPER_TRADING_ONLY}, "
            f"MAX_POSITIONS={self.MAX_POSITIONS}, "
            f"MIN_VOLUME_USD={self.MIN_VOLUME_USD}, "
            f"SCAN_INTERVAL_MS={self.SCAN_INTERVAL_MS}, "
            f"<credentials masked>)"
        )

    def reload(self):
        """Re-read .env and update all live-configurable fields in-place.

        RESTART REQUIRED for the following fields — they are consumed only during
        __init__ of PolymarketClient (or AlertManager / TradeDatabase) and cannot
        be hot-applied to an already-running instance:

          * POLYMARKET_PRIVATE_KEY          — used to sign orders at client init
          * RELAYER_ENABLED / RELAYER_API_KEY / RELAYER_API_KEY_ADDRESS
          * BUILDER_ENABLED / BUILDER_TIER / BUILDER_API_KEY / BUILDER_SECRET / BUILDER_PASSPHRASE
          * SCYLLA_ENABLED / SCYLLA_HOST / SCYLLA_PORT / SCYLLA_KEYSPACE
          * DB_ENABLED / DB_PATH

        All other fields below are live-reloadable via the /api/reload endpoint.
        """
        from dotenv import dotenv_values

        env = dotenv_values()

        # Trading mode
        self.TRADING_MODE = env.get("TRADING_MODE", "paper").lower()
        self.PAPER_TRADING_ONLY = env.get("PAPER_TRADING_ONLY", "True").lower() == "true"
        self.STRATEGY = env.get("STRATEGY", "example_strategy")
        self.FAKE_CURRENCY_BALANCE = float(env.get("FAKE_CURRENCY_BALANCE", "10000.00"))

        # Strategy execution
        self.MAX_POSITIONS = int(env.get("MAX_POSITIONS", "5"))
        self.MAX_POSITIONS_PER_CATEGORY = int(env.get("MAX_POSITIONS_PER_CATEGORY", "2"))
        self.CAPITAL_SPLIT_PERCENT = float(env.get("CAPITAL_SPLIT_PERCENT", "0.20"))
        self.KELLY_FRACTION = float(env.get("KELLY_FRACTION", "0.25"))
        self.STOP_LOSS_PERCENT = float(env.get("STOP_LOSS_PERCENT", "0.0"))
        self.SLIPPAGE_TOLERANCE_PERCENT = float(env.get("SLIPPAGE_TOLERANCE_PERCENT", "5.0"))
        self.TAKER_FEE_PERCENT = float(env.get("TAKER_FEE_PERCENT", "2.0"))
        self.MIN_CONFIDENCE = float(env.get("MIN_CONFIDENCE", "0.5"))
        self.MIN_VOLUME_USD = float(env.get("MIN_VOLUME_USD", "1000.0"))

        # Scanning
        self.SCAN_INTERVAL_MS = int(env.get("SCAN_INTERVAL_MS", "30000"))
        self.SCAN_CATEGORIES = [
            c.strip()
            for c in env.get("SCAN_CATEGORIES", "crypto,fed,regulatory,other").split(",")
            if c.strip()
        ]

        # Market category filters
        self.ENABLE_CRYPTO_MARKETS = env.get("ENABLE_CRYPTO_MARKETS", "True").lower() == "true"
        self.ENABLE_FED_MARKETS = env.get("ENABLE_FED_MARKETS", "True").lower() == "true"
        self.ENABLE_REGULATORY_MARKETS = (
            env.get("ENABLE_REGULATORY_MARKETS", "True").lower() == "true"
        )
        self.ENABLE_OTHER_MARKETS = env.get("ENABLE_OTHER_MARKETS", "True").lower() == "true"
        self.PRIORITY_CRYPTO = int(env.get("PRIORITY_CRYPTO", "1"))
        self.PRIORITY_FED = int(env.get("PRIORITY_FED", "2"))
        self.PRIORITY_REGULATORY = int(env.get("PRIORITY_REGULATORY", "3"))
        self.PRIORITY_OTHER = int(env.get("PRIORITY_OTHER", "4"))

        # Execution
        self.SLIPPAGE_TOLERANCE_PERCENT = float(env.get("SLIPPAGE_TOLERANCE_PERCENT", "5.0"))
        self.TAKER_FEE_PERCENT = float(env.get("TAKER_FEE_PERCENT", "2.0"))
        self.MAX_RETRIES = int(env.get("MAX_RETRIES", "3"))
        self.RETRY_DELAY_MS = int(env.get("RETRY_DELAY_MS", "100"))

        # Relayer
        self.RELAYER_ENABLED = env.get("RELAYER_ENABLED", "False").lower() == "true"
        self.RELAYER_API_KEY = env.get("RELAYER_API_KEY")
        self.RELAYER_API_KEY_ADDRESS = env.get("RELAYER_API_KEY_ADDRESS")

        # Builder
        self.BUILDER_ENABLED = env.get("BUILDER_ENABLED", "False").lower() == "true"
        self.BUILDER_TIER = env.get("BUILDER_TIER", "unverified").lower()
        self.BUILDER_API_KEY = env.get("BUILDER_API_KEY")
        self.BUILDER_SECRET = env.get("BUILDER_SECRET")
        self.BUILDER_PASSPHRASE = env.get("BUILDER_PASSPHRASE")

        # Alerts
        self.ENABLE_EMAIL_ALERTS = env.get("ENABLE_EMAIL_ALERTS", "True").lower() == "true"
        self.ENABLE_DISCORD_ALERTS = env.get("ENABLE_DISCORD_ALERTS", "True").lower() == "true"
        self.DISCORD_WEBHOOK_URL = env.get("DISCORD_WEBHOOK_URL", "")
        self.DISCORD_MENTION_USER = env.get("DISCORD_MENTION_USER", "")
        self.ALERT_EMAIL_FROM = env.get("ALERT_EMAIL_FROM", "noreply@example.com")
        self.ALERT_EMAIL_TO = env.get("ALERT_EMAIL_TO", "")
        self.SMTP_SERVER = env.get("SMTP_SERVER", "smtp.gmail.com")
        self.SMTP_PORT = int(env.get("SMTP_PORT", "587"))
        self.SMTP_USERNAME = env.get("SMTP_USERNAME", "")
        self.SMTP_PASSWORD = env.get("SMTP_PASSWORD", "")

        # Dashboard
        self.DASHBOARD_ENABLED = env.get("DASHBOARD_ENABLED", "True").lower() == "true"
        self.DASHBOARD_PORT = int(env.get("DASHBOARD_PORT", "8080"))
        self.DASHBOARD_HOST = env.get("DASHBOARD_HOST", "127.0.0.1")
        self.DASHBOARD_API_KEY = env.get("DASHBOARD_API_KEY", "")

        # Logging
        self.LOG_LEVEL = env.get("LOG_LEVEL", "INFO")
        self.LOG_TO_FILE = env.get("LOG_TO_FILE", "True").lower() == "true"

        # Power management
        self.PREVENT_SLEEP = env.get("PREVENT_SLEEP", "False").lower() == "true"

        # Database
        self.DB_ENABLED = env.get("DB_ENABLED", "True").lower() == "true"
        self.DB_PATH = env.get("DB_PATH", "./storage/trading.db")
        self.SCYLLA_ENABLED = env.get("SCYLLA_ENABLED", "False").lower() == "true"
        self.SCYLLA_HOST = env.get("SCYLLA_HOST", "127.0.0.1")
        self.SCYLLA_PORT = int(env.get("SCYLLA_PORT", "9042"))
        self.SCYLLA_KEYSPACE = env.get("SCYLLA_KEYSPACE", "polymarket")
        self.SESSIONS_DIR = env.get("SESSIONS_DIR", "./logs/sessions")
        self.OLLAMA_ENABLED = env.get("OLLAMA_ENABLED", "False").lower() == "true"
        self.OLLAMA_HOST = env.get("OLLAMA_HOST", "http://localhost:11434")
        self.OLLAMA_MODEL = env.get("OLLAMA_MODEL", "llama3.2:3b")


# Global config instance
config = PolymarketConfig()
