"""
Configuration module using Pydantic Settings.
Single source of truth for all application configuration.
"""

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Polymarket API Configuration
    polymarket_private_key: str = Field(default="", description="Polymarket private key")
    polymarket_funder_address: str = Field(default="", description="Polymarket funder address")

    # Builder Configuration
    builder_enabled: bool = Field(default=False, description="Enable builder verification")
    builder_api_key: str = Field(default="", description="Builder API key")
    builder_secret: str = Field(default="", description="Builder secret")
    builder_passphrase: str = Field(default="", description="Builder passphrase")

    # Strategy Configuration
    min_price_threshold: float = Field(default=0.985, description="Minimum price threshold")
    max_price_threshold: float = Field(default=1.00, description="Maximum price threshold")
    max_positions: int = Field(default=5, description="Maximum concurrent positions")
    capital_split_percent: float = Field(default=0.2, description="Capital split per position")
    scan_interval_ms: int = Field(default=500, description="Scanning interval in milliseconds")
    # Email Notifications
    enable_email_alerts: bool = Field(default=True, description="Enable email alerts")
    smtp_server: str = Field(default="smtp.gmail.com", description="SMTP server")
    smtp_port: int = Field(default=587, description="SMTP port")
    smtp_username: str = Field(default="", description="SMTP username")
    smtp_password: str = Field(default="", description="SMTP password")
    alert_email_from: str = Field(default="", description="Alert from email address")
    alert_email_to: str = Field(default="", description="Alert to email address")

    # Discord Notifications
    enable_discord_alerts: bool = Field(default=True, description="Enable Discord alerts")
    discord_webhook_url: str = Field(default="", description="Discord webhook URL")
    discord_mention_user_id: str = Field(default="", description="Discord user ID to mention")

    # Dashboard Configuration
    dashboard_enabled: bool = Field(default=True, description="Enable dashboard")
    dashboard_port: int = Field(default=8080, description="Dashboard port")
    dashboard_host: str = Field(default="0.0.0.0", description="Dashboard host")

    # Paper Trading Settings
    paper_trading_enabled: bool = Field(default=True, description="Enable paper trading")
    paper_trading_only: bool = Field(default=True, description="Only paper trading (no real money)")
    fake_currency_balance: float = Field(
        default=10000.0, description="Fake currency starting balance"
    )

    # Logging Configuration
    log_level: str = Field(default="INFO", description="Logging level")
    log_to_file: bool = Field(default=True, description="Log to file")

    # Market Categories
    enable_crypto_markets: bool = Field(default=True, description="Enable crypto markets")
    enable_fed_markets: bool = Field(default=True, description="Enable federal reserve markets")
    enable_regulatory_markets: bool = Field(default=True, description="Enable regulatory markets")
    enable_other_markets: bool = Field(default=True, description="Enable other markets")

    # Category Priority
    priority_crypto: int = Field(default=1, description="Crypto market priority (1=highest)")
    priority_fed: int = Field(default=2, description="Fed market priority")
    priority_regulatory: int = Field(default=3, description="Regulatory market priority")
    priority_other: int = Field(default=4, description="Other market priority")

    # Keyword Filters (comma-separated strings)
    crypto_keywords: str = Field(
        default="bitcoin,ethereum,crypto,defi,web3", description="Crypto market keywords"
    )
    fed_keywords: str = Field(
        default="federal,reserve,fed,interest rate,inflation,economy",
        description="Fed market keywords",
    )
    regulatory_keywords: str = Field(
        default="sec,regulation,compliance,government,fed chair,powell",
        description="Regulatory keywords",
    )
    other_keywords: str = Field(
        default="politics,election,sports,entertainment,celebrity",
        description="Other market keywords",
    )

    # Exclude Filters
    exclude_keywords: str = Field(
        default="trump,biden,presidential,prediction,speculative,gambling,uncertain",
        description="Exclude keywords",
    )
    exclude_slugs: str = Field(default="", description="Exclude market slugs (comma-separated)")

    # Edge Filters
    min_edge: float = Field(default=0.5, description="Minimum arbitrage edge percentage")
    max_edge: float = Field(default=5.0, description="Maximum arbitrage edge percentage")

    # Scanning Behavior
    max_markets_to_track: int = Field(default=1000, description="Maximum markets to track")
    track_new_markets_only: bool = Field(default=False, description="Track only new markets")
    ignore_seen_markets: bool = Field(default=False, description="Ignore previously seen markets")

    # Execution Settings
    order_type: str = Field(default="FOK", description="Order type (FOK, IOC)")
    slippage_tolerance_percent: float = Field(
        default=5.0, description="Maximum slippage tolerance %"
    )
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    retry_delay_ms: int = Field(default=100, description="Retry delay in milliseconds")

    # Additional Settings
    targeted_scanning_enabled: bool = Field(default=False, description="Enable targeted scanning")
    targeted_market_scan_interval_minutes: int = Field(
        default=15, description="Targeted scan interval (minutes)"
    )
    targeted_market_keywords: str = Field(default="", description="Targeted market keywords")
    sleep_on_no_opportunities: bool = Field(default=True, description="Sleep when no opportunities")
    sleep_duration_minutes: int = Field(
        default=10, description="Sleep duration when no opportunities"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("discord_mention_user_id")
    @classmethod
    def validate_discord_user_id(cls, v: str) -> str:
        """Validate Discord user ID is numeric."""
        if v and not v.isdigit():
            raise ValueError("Discord user ID must be numeric")
        return v

    @property
    def crypto_keywords_list(self) -> List[str]:
        """Get crypto keywords as list."""
        return [kw.strip() for kw in self.crypto_keywords.split(",") if kw.strip()]

    @property
    def fed_keywords_list(self) -> List[str]:
        """Get fed keywords as list."""
        return [kw.strip() for kw in self.fed_keywords.split(",") if kw.strip()]

    @property
    def regulatory_keywords_list(self) -> List[str]:
        """Get regulatory keywords as list."""
        return [kw.strip() for kw in self.regulatory_keywords.split(",") if kw.strip()]

    @property
    def other_keywords_list(self) -> List[str]:
        """Get other keywords as list."""
        return [kw.strip() for kw in self.other_keywords.split(",") if kw.strip()]

    @property
    def exclude_keywords_list(self) -> List[str]:
        """Get exclude keywords as list."""
        return [kw.strip() for kw in self.exclude_keywords.split(",") if kw.strip()]

    @property
    def exclude_slugs_list(self) -> List[str]:
        """Get exclude slugs as list."""
        return [slug.strip() for slug in self.exclude_slugs.split(",") if slug.strip()]

    @property
    def all_categories(self) -> List[str]:
        """Get all enabled category keywords."""
        categories = []
        if self.enable_crypto_markets:
            categories.extend(self.crypto_keywords_list)
        if self.enable_fed_markets:
            categories.extend(self.fed_keywords_list)
        if self.enable_regulatory_markets:
            categories.extend(self.regulatory_keywords_list)
        if self.enable_other_markets:
            categories.extend(self.other_keywords_list)
        return categories


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Call this once at application startup.
    """
    return Settings()
