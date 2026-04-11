"""
Enhanced Market Scanner
Advanced market filtering and scanning capabilities
"""

import json
import os
from typing import List, Optional, Set, Dict
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from config.polymarket_config import config
from data.polymarket_client import PolymarketClient
from data.polymarket_models import ArbitrageOpportunity
from data.market_schema import PolymarketMarket
from strategies.config_loader import load_strategy_config
from utils.logger import logger

# Resolved relative to the project data/ directory regardless of where this
# file lives — previously broke when the file moved between directories.
_SEEN_MARKETS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", ".seen_markets.json"
)


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
    Enhanced market scanner with advanced filtering capabilities.

    Configuration lives in strategies/enhanced_market_scanner/config.yaml.
    All values can be overridden via environment variables (see config.yaml
    for the full list of supported keys).
    """

    def __init__(self, client: PolymarketClient):
        self.client = client
        self.config = self._load_config()
        self.seen_markets: Set[str] = set()
        self.market_cache: Dict[str, dict] = {}
        self.last_scan_time: Optional[datetime] = None

        # Pre-compute lowercased keyword tuples and O(1) exclusion sets so that
        # matches_filters() — called once per market per scan — does no repeated
        # .lower() calls or O(n) list membership tests at scan time.
        self._crypto_kws: tuple = tuple(kw.lower() for kw in self.config.crypto_keywords)
        self._fed_kws: tuple = tuple(kw.lower() for kw in self.config.fed_keywords)
        self._regulatory_kws: tuple = tuple(kw.lower() for kw in self.config.regulatory_keywords)
        self._other_kws: tuple = tuple(kw.lower() for kw in self.config.other_keywords)
        self._exclude_kws: tuple = tuple(kw.lower() for kw in self.config.exclude_keywords)
        self._exclude_slugs_set: frozenset = frozenset(self.config.exclude_slugs)

        # Load persistent state
        self._load_seen_markets()

    def _load_config(self) -> MarketScannerConfig:
        """
        Load scanner configuration.

        Priority (highest → lowest):
          1. Environment variables  — for runtime overrides of scalar values
          2. YAML file              — strategies/enhanced_market_scanner/config.yaml
          3. Global config / hardcoded defaults
        """
        yaml_cfg = load_strategy_config("enhanced_market_scanner")
        cats = yaml_cfg.get("categories", {})

        def _cat(name: str, key: str, default):
            return cats.get(name, {}).get(key, default)

        # ── Category enabled flags ────────────────────────────────────────
        crypto_enabled = getattr(config, "ENABLE_CRYPTO_MARKETS", _cat("crypto", "enabled", True))
        fed_enabled = getattr(config, "ENABLE_FED_MARKETS", _cat("fed", "enabled", True))
        regulatory_enabled = getattr(
            config, "ENABLE_REGULATORY_MARKETS", _cat("regulatory", "enabled", True)
        )
        other_enabled = getattr(config, "ENABLE_OTHER_MARKETS", _cat("other", "enabled", True))

        # ── Category priorities ────────────────────────────────────────────
        crypto_priority = getattr(config, "PRIORITY_CRYPTO", _cat("crypto", "priority", 1))
        fed_priority = getattr(config, "PRIORITY_FED", _cat("fed", "priority", 2))
        regulatory_priority = getattr(
            config, "PRIORITY_REGULATORY", _cat("regulatory", "priority", 3)
        )
        other_priority = getattr(config, "PRIORITY_OTHER", _cat("other", "priority", 4))

        # ── Keywords (YAML list; env-var CRYPTO_KEYWORDS=a,b overrides) ──
        crypto_keywords = self._parse_list(os.getenv("CRYPTO_KEYWORDS", "")) or _cat(
            "crypto", "keywords", []
        )
        fed_keywords = self._parse_list(os.getenv("FED_KEYWORDS", "")) or _cat(
            "fed", "keywords", []
        )
        regulatory_keywords = self._parse_list(os.getenv("REGULATORY_KEYWORDS", "")) or _cat(
            "regulatory", "keywords", []
        )
        other_keywords = self._parse_list(os.getenv("OTHER_KEYWORDS", "")) or _cat(
            "other", "keywords", []
        )

        # ── Exclusions ────────────────────────────────────────────────────
        exclude_keywords = self._parse_list(os.getenv("EXCLUDE_KEYWORDS", "")) or yaml_cfg.get(
            "exclude_keywords", []
        )
        exclude_slugs = self._parse_list(os.getenv("EXCLUDE_SLUGS", "")) or yaml_cfg.get(
            "exclude_slugs", []
        )

        # ── Scalar filters (env var > YAML > None) ────────────────────────
        def _scalar(env_key: str, yaml_key: str, parse_fn):
            env_val = os.getenv(env_key)
            if env_val:
                return parse_fn(env_val)
            return yaml_cfg.get(yaml_key)

        min_price = _scalar("MIN_PRICE", "min_price", self._parse_float)
        max_price = _scalar("MAX_PRICE", "max_price", self._parse_float)
        min_edge = _scalar("MIN_EDGE", "min_edge", self._parse_float)
        max_edge = _scalar("MAX_EDGE", "max_edge", self._parse_float)
        min_time_to_close = _scalar("MIN_TIME_TO_CLOSE", "min_time_to_close", self._parse_int)
        max_time_to_close = _scalar("MAX_TIME_TO_CLOSE", "max_time_to_close", self._parse_int)
        max_markets_to_track = _scalar(
            "MAX_MARKETS_TO_TRACK", "max_markets_to_track", self._parse_int
        )

        # ── Boolean behaviour flags ───────────────────────────────────────
        track_new_markets_only = (
            os.getenv("TRACK_NEW_MARKETS_ONLY", "").lower() in ("true", "1", "yes")
        ) or bool(yaml_cfg.get("track_new_markets_only", False))

        ignore_seen_markets = (
            os.getenv("IGNORE_SEEN_MARKETS", "").lower() in ("true", "1", "yes")
        ) or bool(yaml_cfg.get("ignore_seen_markets", False))

        scan_interval_ms = (
            self._parse_int(os.getenv("SCAN_INTERVAL_MS", str(config.SCAN_INTERVAL_MS))) or 500
        )

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
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    def _parse_float(self, value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            logger.warning(f"Invalid float config value: '{value}' — ignoring")
            return None

    def _parse_int(self, value: Optional[str]) -> Optional[int]:
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

    # Maximum number of market IDs to keep in the seen_markets set.
    # Entries beyond this cap are pruned before each disk write to prevent
    # unbounded memory growth and an ever-growing JSON file.
    _SEEN_MARKETS_MAX = 10_000

    def _save_seen_markets(self):
        """Persist seen market IDs to JSON file."""
        # Trim the in-memory set when it exceeds the size cap so memory and the
        # JSON file don't grow unboundedly across long-running sessions.
        if len(self.seen_markets) > self._SEEN_MARKETS_MAX:
            overflow = len(self.seen_markets) - self._SEEN_MARKETS_MAX
            trimmed = set(list(self.seen_markets)[overflow:])
            self.seen_markets = trimmed
            logger.debug(
                f"Trimmed seen_markets from {len(self.seen_markets) + overflow} "
                f"to {len(self.seen_markets)} entries (cap={self._SEEN_MARKETS_MAX})"
            )
        try:
            path = os.path.abspath(_SEEN_MARKETS_FILE)
            with open(path, "w") as f:
                json.dump(list(self.seen_markets), f)
        except Exception as e:
            logger.warning(f"Could not save seen markets file: {e}")

    def matches_filters(self, market: PolymarketMarket, category: str) -> bool:
        """Check if a PolymarketMarket matches all configured filters.

        Uses pre-lowercased keyword tuples and frozenset slug exclusions (built
        at __init__ time) so no repeated .lower() or O(n) list scans at runtime.
        """
        if not market.has_sufficient_liquidity(config.MIN_VOLUME_USD):
            return False

        if self.config.ignore_seen_markets and market.market_id in self.seen_markets:
            return False

        # Lowercase market text once — reused by both include and exclude checks.
        title_lower = market.question.lower()
        slug_lower = market.slug.lower()

        kws = self._get_category_keywords_lower(category)
        if kws and not any(kw in title_lower or kw in slug_lower for kw in kws):
            return False

        if self._exclude_kws and any(
            kw in title_lower or kw in slug_lower for kw in self._exclude_kws
        ):
            return False

        # O(1) frozenset lookup replaces O(n) list scan
        if self._exclude_slugs_set and market.slug in self._exclude_slugs_set:
            return False

        if self.config.min_price is not None or self.config.max_price is not None:
            price = self._get_market_price(market)
            if price is not None:
                if self.config.min_price is not None and price < self.config.min_price:
                    return False
                if self.config.max_price is not None and price > self.config.max_price:
                    return False

        if self.config.min_time_to_close is not None or self.config.max_time_to_close is not None:
            ttc = market.seconds_to_close()
            if ttc is not None:
                if (
                    self.config.min_time_to_close is not None
                    and ttc < self.config.min_time_to_close
                ):
                    return False
                if (
                    self.config.max_time_to_close is not None
                    and ttc > self.config.max_time_to_close
                ):
                    return False

        return True

    def _get_category_keywords_lower(self, category: str) -> tuple:
        """Return the pre-lowercased keyword tuple for a category."""
        if category == "crypto":
            return self._crypto_kws
        elif category == "fed":
            return self._fed_kws
        elif category == "regulatory":
            return self._regulatory_kws
        elif category == "other":
            return self._other_kws
        return ()

    def _get_category_keywords(self, category: str) -> Optional[List[str]]:
        """Return the original (non-lowercased) keyword list for a category."""
        if category == "crypto":
            return self.config.crypto_keywords
        elif category == "fed":
            return self.config.fed_keywords
        elif category == "regulatory":
            return self.config.regulatory_keywords
        elif category == "other":
            return self.config.other_keywords
        return None

    def _get_market_price(self, market: PolymarketMarket) -> Optional[float]:
        try:
            if not market.token_ids:
                return None
            return self.client.get_price(market.token_ids[0]) or None
        except Exception:
            return None

    def get_category_priority(self, category: str) -> int:
        if category == "crypto":
            return self.config.crypto_priority
        elif category == "fed":
            return self.config.fed_priority
        elif category == "regulatory":
            return self.config.regulatory_priority
        elif category == "other":
            return self.config.other_priority
        return 3

    def scan_markets_by_category(self, category: str) -> List[dict]:
        """Scan markets by category with advanced filtering."""
        if category == "crypto" and not self.config.crypto_enabled:
            return []
        elif category == "fed" and not self.config.fed_enabled:
            return []
        elif category == "regulatory" and not self.config.regulatory_enabled:
            return []
        elif category == "other" and not self.config.other_enabled:
            return []

        try:
            raw_markets = self.client.get_all_markets(category=category)
        except Exception as e:
            logger.error(f"Failed to get markets for category {category}: {e}")
            return []

        if not raw_markets:
            return []

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
            logger.warning(
                f"Skipped {skipped_parse} markets with missing required fields for category {category}"
            )

        logger.info(
            f"Scanned {len(filtered_markets)}/{len(raw_markets)} markets for category {category}"
        )
        return filtered_markets

    def scan_all_markets(self) -> List[dict]:
        """Scan all enabled market categories."""
        category_map = {
            "crypto": (self.config.crypto_enabled, self.config.crypto_priority),
            "fed": (self.config.fed_enabled, self.config.fed_priority),
            "regulatory": (self.config.regulatory_enabled, self.config.regulatory_priority),
            "other": (self.config.other_enabled, self.config.other_priority),
        }
        sorted_categories = sorted(
            [(cat, info) for cat, info in category_map.items() if info[0]],
            key=lambda x: x[1][1],
        )

        all_markets = []
        for category, (enabled, priority) in sorted_categories:
            if enabled:
                logger.debug(f"Scanning {category} markets (priority: {priority})")
                all_markets.extend(self.scan_markets_by_category(category))

        logger.info(f"Total markets scanned: {len(all_markets)}")
        self.last_scan_time = datetime.now()
        self._save_seen_markets()
        return all_markets

    def get_scan_summary(self) -> dict:
        return {
            "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "seen_markets_count": len(self.seen_markets),
            "config": {
                "crypto_enabled": self.config.crypto_enabled,
                "fed_enabled": self.config.fed_enabled,
                "regulatory_enabled": self.config.regulatory_enabled,
                "other_enabled": self.config.other_enabled,
                "keywords_enabled": bool(
                    self.config.crypto_keywords
                    or self.config.fed_keywords
                    or self.config.regulatory_keywords
                    or self.config.other_keywords
                ),
                "exclude_enabled": bool(self.config.exclude_keywords or self.config.exclude_slugs),
            },
        }

    def reset_seen_markets(self):
        self.seen_markets.clear()
        logger.info("Reset seen markets tracking")
