"""
Market data provider with speed-ordered source fallback.

Strategies declare a MarketCriteria that specifies which markets they want
and how prices should be resolved.  MarketProvider handles all of the data
pipeline work — fetching, conversion, pre-filtering, and price resolution —
so strategies receive a clean List[PolymarketMarket] and implement only
their domain logic.

Source priority (fastest → slowest):
  GAMMA_EMBEDDED  — price embedded in the Gamma API response, zero extra calls
  CLOB_REST       — CLOB SDK get_price(), one HTTP call per market
  ORDER_BOOK_MID  — full order-book midpoint, highest precision, most expensive

Flow per scan cycle
-------------------
1. Fetch raw market dicts from Gamma API (cached with TTL)
2. Convert each dict to PolymarketMarket ONCE (not once-per-strategy)
3. Apply MarketCriteria pre-filters (volume, binary, time bounds)
4. Resolve prices for the filtered set using the source preference list
5. Return List[PolymarketMarket] with resolved_price set on every entry
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from config.polymarket_config import config
from data.market_scanner import scan_categories
from data.market_schema import PolymarketMarket
from utils.logger import logger


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------

class MarketDataSource(str, Enum):
    """
    Price data sources, ordered from fastest to slowest.

    GAMMA_EMBEDDED   Zero extra API calls; price comes directly from the
                     Gamma /events response (outcomePrices field).  Available
                     for most markets.  Should be first in any preference list.

    CLOB_REST        One CLOB SDK get_price() call per market that lacks an
                     embedded price.  ~50–200 ms per call over the network.

    ORDER_BOOK_MID   Full order-book fetch.  Most expensive but gives a true
                     mid-market price, useful when precision matters more than
                     speed.
    """

    GAMMA_EMBEDDED = "gamma_embedded"
    CLOB_REST = "clob_rest"
    ORDER_BOOK_MID = "order_book_mid"


# ---------------------------------------------------------------------------
# Criteria declaration
# ---------------------------------------------------------------------------

@dataclass
class MarketCriteria:
    """
    Declares what a strategy needs from the market universe.

    Gates declared here are applied by MarketProvider *before*
    scan_for_opportunities() is called.  Strategies therefore only see markets
    that already satisfy these constraints and do not need to repeat them.

    Attributes
    ----------
    categories
        Which Polymarket categories to pull from the Gamma API.
        Default: all four standard categories.
    min_volume_usd
        Skip markets whose volume is below this threshold (0 = no gate).
    require_binary
        When True (default), skip markets that do not have exactly two token
        IDs (i.e. non-binary / multi-outcome markets).
    max_time_to_close_s
        Skip markets whose close time is further away than this (seconds).
        None = no upper bound.
    min_time_to_close_s
        Skip markets that have already passed their close time by more than
        this many seconds.  Default 0 (allow up to the close second).
    price_source_preference
        Ordered list of price sources to try.  The first source that can
        produce a non-zero price is used; subsequent sources are skipped.
        Default: GAMMA_EMBEDDED → CLOB_REST (fastest; no extra calls unless
        Gamma did not include an embedded price).
    """

    categories: List[str] = field(
        default_factory=lambda: ["crypto", "fed", "regulatory", "other"]
    )
    min_volume_usd: float = 0.0
    require_binary: bool = True
    max_time_to_close_s: Optional[float] = None
    min_time_to_close_s: float = 0.0
    price_source_preference: List[MarketDataSource] = field(
        default_factory=lambda: [
            MarketDataSource.GAMMA_EMBEDDED,
            MarketDataSource.CLOB_REST,
        ]
    )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class MarketProvider:
    """
    Single point of market data access for the trading loop.

    Usage
    -----
    provider = MarketProvider(polymarket_client)
    criteria = strategy.get_market_criteria()
    markets  = provider.get_markets(criteria)   # List[PolymarketMarket]
    """

    # Cache TTL (seconds) per trading mode
    _CACHE_TTL: dict = {
        "simulation": 5,
        "paper": 60,
        "live": 60,
    }

    def __init__(self, client) -> None:
        self._client = client
        self._raw_cache: list = []
        self._raw_cache_mono: float = 0.0          # time.monotonic() at last refresh
        self._last_categories: Optional[List[str]] = None

    # ── public API ──────────────────────────────────────────────────────────

    def get_markets(self, criteria: MarketCriteria) -> List[PolymarketMarket]:
        """
        Return markets matching *criteria* with prices already resolved.

        The raw market list is cached per TTL.  Conversion, filtering, and
        price resolution all happen here so strategies receive clean typed
        objects and implement only their domain logic.
        """
        raw = self._get_raw(criteria.categories)
        markets = self._convert_and_filter(raw, criteria)
        self._resolve_prices(markets, criteria.price_source_preference)
        return markets

    def invalidate_cache(self) -> None:
        """Force the next get_markets() call to re-fetch from the API."""
        self._raw_cache = []
        self._raw_cache_mono = 0.0
        self._last_categories = None

    # ── raw-market cache ────────────────────────────────────────────────────

    def _get_raw(self, categories: List[str]) -> list:
        ttl = self._CACHE_TTL.get(config.TRADING_MODE, 60)
        now = time.monotonic()
        stale = (now - self._raw_cache_mono) > ttl
        categories_changed = categories != self._last_categories

        if categories_changed or not self._raw_cache or stale:
            logger.debug(
                f"[MarketProvider] Refreshing raw market cache "
                f"(categories={categories}, ttl={ttl}s, "
                f"stale={stale}, cats_changed={categories_changed})"
            )
            self._raw_cache = scan_categories(self._client, categories)
            self._raw_cache_mono = now
            self._last_categories = list(categories)

        return self._raw_cache

    # ── conversion + pre-filtering ──────────────────────────────────────────

    def _convert_and_filter(
        self, raw_markets: list, criteria: MarketCriteria
    ) -> List[PolymarketMarket]:
        """
        Convert raw dicts to PolymarketMarket objects and apply criteria gates.

        Each raw dict is converted exactly ONCE here — strategies no longer call
        PolymarketMarket.from_api() inside scan_for_opportunities().  Gates are
        applied in cheapest-first order (no API calls required):

          1. Binary check  (len(token_ids) == 2)
          2. Volume check  (market.volume >= min_volume_usd)
          3. Time-to-close bounds
        """
        out: List[PolymarketMarket] = []
        skipped_parse = skipped_binary = skipped_volume = skipped_time = skipped_category = 0

        for raw in raw_markets:
            market = PolymarketMarket.from_api(raw)
            if market is None:
                skipped_parse += 1
                continue

            # 0. Category gate (cheapest after parse — no I/O).
            # The Gamma API tag_id filter covers "crypto" and "fed" at the
            # fetch level, but "regulatory" and "other" have no tag_id mapping
            # so scan_categories returns the entire market universe for those
            # categories.  Without this gate, every fetched market passes
            # through to the strategy regardless of criteria.categories.
            if criteria.categories and market.category not in criteria.categories:
                skipped_category += 1
                continue

            # 1. Binary gate (cheapest — just a len() check)
            if criteria.require_binary and len(market.token_ids) != 2:
                skipped_binary += 1
                continue

            # 2. Volume gate
            if criteria.min_volume_usd > 0 and not market.has_sufficient_liquidity(
                criteria.min_volume_usd
            ):
                skipped_volume += 1
                continue

            # 3. Time-to-close gates (only if at least one bound is set)
            if criteria.max_time_to_close_s is not None or criteria.min_time_to_close_s > 0:
                ttc = market.seconds_to_close()
                if ttc is None:
                    # Unknown close time — skip when an upper bound is required
                    if criteria.max_time_to_close_s is not None:
                        skipped_time += 1
                        continue
                else:
                    if ttc < criteria.min_time_to_close_s:
                        skipped_time += 1
                        continue
                    if (
                        criteria.max_time_to_close_s is not None
                        and ttc > criteria.max_time_to_close_s
                    ):
                        skipped_time += 1
                        continue

            out.append(market)

        if skipped_parse or skipped_category or skipped_binary or skipped_volume or skipped_time:
            logger.debug(
                f"[MarketProvider] Pre-filter: {len(raw_markets)} raw → {len(out)} kept "
                f"(parse={skipped_parse}, category={skipped_category}, binary={skipped_binary}, "
                f"volume={skipped_volume}, time={skipped_time} skipped)"
            )

        return out

    # ── price resolution ────────────────────────────────────────────────────

    def _resolve_prices(
        self,
        markets: List[PolymarketMarket],
        sources: List[MarketDataSource],
    ) -> None:
        """
        Set resolved_price on every market in-place.

        Sources are tried in order; the first that yields a finite, positive
        price wins.  Markets that cannot be priced from any source get
        resolved_price = 0.0.

        Batching strategy
        -----------------
        GAMMA_EMBEDDED  — resolved inline (no I/O)
        CLOB_REST       — collected and resolved after the inline pass,
                          keeping the call pattern identical to what strategies
                          previously did (one call per market that needs it)
        ORDER_BOOK_MID  — same batch approach
        """
        needs_clob: List[PolymarketMarket] = []
        needs_ob: List[PolymarketMarket] = []

        for market in markets:
            market.resolved_price = 0.0  # sentinel; overwritten below

            for source in sources:
                if source == MarketDataSource.GAMMA_EMBEDDED:
                    if market.outcome_prices:
                        p = market.outcome_prices[0]
                        if math.isfinite(p) and p > 0:
                            market.resolved_price = p
                            break
                    # Embedded price absent or zero — try next source

                elif source == MarketDataSource.CLOB_REST:
                    # Defer to the post-loop batch; break so we don't also
                    # add this market to needs_ob.
                    needs_clob.append(market)
                    break

                elif source == MarketDataSource.ORDER_BOOK_MID:
                    needs_ob.append(market)
                    break

        # CLOB batch (one get_price() per market that needs it)
        clob_resolved = 0
        for market in needs_clob:
            try:
                p = self._client.get_price(market.token_ids[0])
                if p and math.isfinite(p) and p > 0:
                    market.resolved_price = float(p)
                    clob_resolved += 1
            except Exception as exc:
                logger.debug(
                    f"[MarketProvider] CLOB price fetch failed for {market.slug}: {exc}"
                )

        # Order-book batch (one get_order_book() per market that needs it)
        ob_resolved = 0
        for market in needs_ob:
            try:
                book = self._client.get_order_book(market.token_ids[0])
                mid = book.get("mid_price", 0.0)
                if mid and math.isfinite(float(mid)) and float(mid) > 0:
                    market.resolved_price = float(mid)
                    ob_resolved += 1
            except Exception as exc:
                logger.debug(
                    f"[MarketProvider] Order-book fetch failed for {market.slug}: {exc}"
                )

        if needs_clob:
            logger.debug(
                f"[MarketProvider] CLOB price resolution: "
                f"{clob_resolved}/{len(needs_clob)} resolved"
            )
        if needs_ob:
            logger.debug(
                f"[MarketProvider] Order-book price resolution: "
                f"{ob_resolved}/{len(needs_ob)} resolved"
            )
