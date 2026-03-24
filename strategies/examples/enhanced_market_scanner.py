"""
Enhanced Market Scanner
Advanced market filtering and scanning capabilities
"""

import json
import os
from typing import List, Optional, Set, Dict
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
import re

from config.polymarket_config import config
from data.polymarket_client import PolymarketClient
from data.polymarket_models import ArbitrageOpportunity
from data.market_schema import PolymarketMarket
from utils.logger import logger

_SEEN_MARKETS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", ".seen_markets.json")


@dataclass
class MarketFilter:
    """Market filter configuration"""
    
    enabled: bool = True
    keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_volume: Optional[float] = None
    max_volume: Optional[float] = None
    min_edge: Optional[float] = None
    max_edge: Optional[float] = None
    min_time_to_close: Optional[int] = None
    max_time_to_close: Optional[int] = None


@dataclass
class MarketScannerConfig:
    """Enhanced market scanner configuration"""
    
    # Category filters
    crypto_enabled: bool = True
    fed_enabled: bool = True
    regulatory_enabled: bool = True
    other_enabled: bool = True
    
    # Priority filters (1=highest, 5=lowest)
    crypto_priority: int = 1
    fed_priority: int = 2
    regulatory_priority: int = 3
    other_priority: int = 4
    
    # Keyword filters
    crypto_keywords: List[str] = field(default_factory=list)
    fed_keywords: List[str] = field(default_factory=list)
    regulatory_keywords: List[str] = field(default_factory=list)
    other_keywords: List[str] = field(default_factory=list)
    
    # Exclusion filters
    exclude_keywords: List[str] = field(default_factory=list)
    exclude_slugs: List[str] = field(default_factory=list)
    
    # Price filters
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    price_range_enabled: bool = False
    
    # Edge filters
    min_edge: Optional[float] = None
    max_edge: Optional[float] = None
    edge_range_enabled: bool = False
    
    # Time filters
    min_time_to_close: Optional[int] = None
    max_time_to_close: Optional[int] = None
    time_range_enabled: bool = False
    
    # Scanning behavior
    scan_interval_ms: int = 500
    max_markets_to_track: Optional[int] = None
    track_new_markets_only: bool = False
    ignore_seen_markets: bool = False


class EnhancedMarketScanner:
    """
    Enhanced market scanner with advanced filtering capabilities
    """
    
    def __init__(self, client: PolymarketClient):
        self.client = client
        self.config = self._load_config()
        self.seen_markets: Set[str] = set()
        self.market_cache: Dict[str, dict] = {}
        self.last_scan_time: Optional[datetime] = None
        
        # Load persistent state
        self._load_seen_markets()
        
    def _load_config(self) -> MarketScannerConfig:
        """Load scanner configuration from config and .env"""
        
        # Category filters
        crypto_enabled = config.ENABLE_CRYPTO_MARKETS
        fed_enabled = config.ENABLE_FED_MARKETS
        regulatory_enabled = config.ENABLE_REGULATORY_MARKETS
        other_enabled = config.ENABLE_OTHER_MARKETS
        
        # Priority from config
        crypto_priority = config.PRIORITY_CRYPTO
        fed_priority = config.PRIORITY_FED
        regulatory_priority = config.PRIORITY_REGULATORY
        other_priority = config.PRIORITY_OTHER
        
        # Keywords (from .env)
        crypto_keywords = self._parse_list(os.getenv("CRYPTO_KEYWORDS", ""))
        fed_keywords = self._parse_list(os.getenv("FED_KEYWORDS", ""))
        regulatory_keywords = self._parse_list(os.getenv("REGULATORY_KEYWORDS", ""))
        other_keywords = self._parse_list(os.getenv("OTHER_KEYWORDS", ""))
        
        # Exclusions (from .env)
        exclude_keywords = self._parse_list(os.getenv("EXCLUDE_KEYWORDS", ""))
        exclude_slugs = self._parse_list(os.getenv("EXCLUDE_SLUGS", ""))
        
        # Price range (from .env)
        min_price = self._parse_float(os.getenv("MIN_PRICE"))
        max_price = self._parse_float(os.getenv("MAX_PRICE"))
        
        # Edge range (from .env)
        min_edge = self._parse_float(os.getenv("MIN_EDGE"))
        max_edge = self._parse_float(os.getenv("MAX_EDGE"))
        
        # Time to close range (from .env)
        min_time_to_close = self._parse_int(os.getenv("MIN_TIME_TO_CLOSE"))
        max_time_to_close = self._parse_int(os.getenv("MAX_TIME_TO_CLOSE"))
        
        # Scanning behavior
        scan_interval_ms = self._parse_int(os.getenv("SCAN_INTERVAL_MS", str(config.SCAN_INTERVAL_MS))) or 500
        max_markets_to_track = self._parse_int(os.getenv("MAX_MARKETS_TO_TRACK"))
        track_new_markets_only = os.getenv("TRACK_NEW_MARKETS_ONLY", "false").lower() == "true"
        ignore_seen_markets = os.getenv("IGNORE_SEEN_MARKETS", "false").lower() == "true"
        
        return MarketScannerConfig(
            crypto_enabled=crypto_enabled,
            fed_enabled=fed_enabled,
            regulatory_enabled=regulatory_enabled,
            other_enabled=other_enabled,
            crypto_priority=crypto_priority,
            fed_priority=fed_priority,
            regulatory_priority=regulatory_priority,
            other_priority=other_priority,
            crypto_keywords=crypto_keywords,
            fed_keywords=fed_keywords,
            regulatory_keywords=regulatory_keywords,
            other_keywords=other_keywords,
            exclude_keywords=exclude_keywords,
            exclude_slugs=exclude_slugs,
            min_price=min_price,
            max_price=max_price,
            min_edge=min_edge,
            max_edge=max_edge,
            min_time_to_close=min_time_to_close,
            max_time_to_close=max_time_to_close,
            scan_interval_ms=scan_interval_ms,
            max_markets_to_track=max_markets_to_track,
            track_new_markets_only=track_new_markets_only,
            ignore_seen_markets=ignore_seen_markets,
        )
    
    def _parse_list(self, value: str) -> List[str]:
        """Parse comma-separated list from string"""
        if not value:
            return []
        items = [item.strip() for item in value.split(",")]
        return [item for item in items if item]
    
    def _parse_float(self, value: Optional[str]) -> Optional[float]:
        """Parse float from string"""
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            logger.warning(f"Invalid float config value: '{value}' — ignoring")
            return None

    def _parse_int(self, value: Optional[str]) -> Optional[int]:
        """Parse integer from string"""
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            logger.warning(f"Invalid int config value: '{value}' — ignoring")
            return None
    
    def _load_seen_markets(self):
        """Load seen market IDs from JSON file for persistence across restarts."""
        try:
            path = os.path.abspath(_SEEN_MARKETS_FILE)
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                self.seen_markets = set(data) if isinstance(data, list) else set()
                logger.debug(f"Loaded {len(self.seen_markets)} seen markets from {path}")
            else:
                self.seen_markets = set()
        except Exception as e:
            logger.warning(f"Could not load seen markets file: {e} — starting fresh")
            self.seen_markets = set()

    def _save_seen_markets(self):
        """Persist seen market IDs to JSON file."""
        try:
            path = os.path.abspath(_SEEN_MARKETS_FILE)
            with open(path, "w") as f:
                json.dump(list(self.seen_markets), f)
        except Exception as e:
            logger.warning(f"Could not save seen markets file: {e}")
    
    def matches_filters(self, market: PolymarketMarket, category: str) -> bool:
        """
        Check if a PolymarketMarket matches all configured filters.
        """

        # Liquidity filter
        if not market.has_sufficient_liquidity(config.MIN_VOLUME_USD):
            return False

        # Check if market is seen
        if self.config.ignore_seen_markets:
            if market.market_id in self.seen_markets:
                return False

        # Keyword filters
        keywords = self._get_category_keywords(category)
        if keywords:
            title_lower = market.question.lower()
            slug_lower = market.slug.lower()

            if not any(kw.lower() in title_lower or kw.lower() in slug_lower for kw in keywords):
                return False

        if self.config.exclude_keywords:
            title_lower = market.question.lower()
            slug_lower = market.slug.lower()
            if any(kw.lower() in title_lower or kw.lower() in slug_lower for kw in self.config.exclude_keywords):
                return False

        if self.config.exclude_slugs and market.slug in self.config.exclude_slugs:
            return False

        # Price filters (requires live price fetch — skip if not configured)
        if self.config.min_price is not None or self.config.max_price is not None:
            price = self._get_market_price(market)
            if price is not None:
                if self.config.min_price is not None and price < self.config.min_price:
                    return False
                if self.config.max_price is not None and price > self.config.max_price:
                    return False

        # Time to close filters
        if self.config.min_time_to_close is not None or self.config.max_time_to_close is not None:
            ttc = market.seconds_to_close()
            if ttc is not None:
                if self.config.min_time_to_close is not None and ttc < self.config.min_time_to_close:
                    return False
                if self.config.max_time_to_close is not None and ttc > self.config.max_time_to_close:
                    return False

        return True
    
    def _get_category_keywords(self, category: str) -> Optional[List[str]]:
        """Get keywords for a specific category"""
        if category == "crypto":
            return self.config.crypto_keywords
        elif category == "fed":
            return self.config.fed_keywords
        elif category == "regulation":
            return self.config.regulatory_keywords
        elif category == "other":
            return self.config.other_keywords
        return None
    
    def _get_market_price(self, market: PolymarketMarket) -> Optional[float]:
        """Get the current YES price for a market"""
        try:
            if not market.token_ids:
                return None
            return self.client.get_price(market.token_ids[0]) or None
        except Exception:
            return None
    
    def get_category_priority(self, category: str) -> int:
        """Get priority for a category (1=highest, 5=lowest)"""
        if category == "crypto":
            return self.config.crypto_priority
        elif category == "fed":
            return self.config.fed_priority
        elif category == "regulation":
            return self.config.regulatory_priority
        elif category == "other":
            return self.config.other_priority
        return 3  # Default medium priority
    
    def scan_markets_by_category(self, category: str) -> List[dict]:
        """
        Scan markets by category with advanced filtering
        
        Note: Uses get_all_markets() which is available in PolymarketClient
        Note: get_all_markets() does not accept limit parameter
        Do not pass limit parameter as it's not supported by the API
        """
        
        # Check if category is enabled
        if category == "crypto" and not self.config.crypto_enabled:
            logger.debug(f"Crypto markets disabled, skipping")
            return []
        elif category == "fed" and not self.config.fed_enabled:
            logger.debug(f"Fed markets disabled, skipping")
            return []
        elif category == "regulation" and not self.config.regulatory_enabled:
            logger.debug(f"Regulatory markets disabled, skipping")
            return []
        elif category == "other" and not self.config.other_enabled:
            logger.debug(f"Other markets disabled, skipping")
            return []
        
        # Get markets from API
        try:
            raw_markets = self.client.get_all_markets(category=category)
        except Exception as e:
            logger.error(f"Failed to get markets for category {category}: {e}")
            return []

        if not raw_markets:
            logger.debug(f"No markets found for category {category}")
            return []

        # Parse and filter
        filtered_markets = []
        skipped_parse = 0
        for raw in raw_markets:
            market = PolymarketMarket.from_api(raw)
            if market is None:
                skipped_parse += 1
                continue
            if self.matches_filters(market, category):
                filtered_markets.append(market)
                if not self.config.track_new_markets_only:
                    self.seen_markets.add(market.market_id)

        if skipped_parse:
            logger.warning(f"Skipped {skipped_parse} markets with missing required fields for category {category}")

        logger.info(f"Scanned {len(filtered_markets)}/{len(raw_markets)} markets for category {category}")

        return filtered_markets
    
    def scan_all_markets(self) -> List[dict]:
        """
        Scan all enabled market categories
        """
        
        categories = []
        
        # Build category list with priorities
        category_map = {
            "crypto": (self.config.crypto_enabled, self.config.crypto_priority),
            "fed": (self.config.fed_enabled, self.config.fed_priority),
            "regulation": (self.config.regulatory_enabled, self.config.regulatory_priority),
            "other": (self.config.other_enabled, self.config.other_priority),
        }
        
        # Sort categories by priority
        sorted_categories = sorted(
            [(cat, info) for cat, info in category_map.items() if info[0]],
            key=lambda x: x[1][1]  # Sort by priority (1=highest)
        )
        
        all_markets = []
        for category, (enabled, priority) in sorted_categories:
            if enabled:
                logger.debug(f"Scanning {category} markets (priority: {priority})")
                markets = self.scan_markets_by_category(category)
                all_markets.extend(markets)
        
        logger.info(f"Total markets scanned: {len(all_markets)}")
        self.last_scan_time = datetime.now()
        
        # Save seen markets
        self._save_seen_markets()
        
        return all_markets
    
    def get_scan_summary(self) -> dict:
        """Get summary of last scan"""
        return {
            "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "seen_markets_count": len(self.seen_markets),
            "config": {
                "crypto_enabled": self.config.crypto_enabled,
                "fed_enabled": self.config.fed_enabled,
                "regulatory_enabled": self.config.regulatory_enabled,
                "other_enabled": self.config.other_enabled,
                "keywords_enabled": bool(self.config.crypto_keywords or self.config.fed_keywords or 
                                       self.config.regulatory_keywords or self.config.other_keywords),
                "exclude_enabled": bool(self.config.exclude_keywords or self.config.exclude_slugs),
            }
        }
    
    def reset_seen_markets(self):
        """Reset the seen markets tracking"""
        self.seen_markets.clear()
        logger.info("Reset seen markets tracking")
