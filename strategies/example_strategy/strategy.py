"""
Example Strategy — Configuration & Structure Reference
======================================================

Copy this folder to strategies/<your_strategy_name>/ to start a new strategy.

REQUIRED STEPS after copying
-----------------------------
1. Rename the class (ExampleStrategy → YourStrategyName).
2. Edit config.yaml with your parameters.
3. Implement scan_for_opportunities() with your own signal logic.
4. Implement get_best_opportunities() to rank/filter candidates.
5. Optionally override should_exit() and get_exit_price().
6. Done — the registry auto-discovers it with no further changes.

HOW CONFIGURATION WORKS
------------------------
All tunable parameters live in config.yaml (same folder as this file).

On __init__ the strategy calls load_strategy_config("<folder_name>"), which:
  1. Reads config.yaml from this folder.
  2. Applies any matching environment-variable overrides (uppercase key name).
  3. Returns a plain dict merged on top of _DEFAULTS.

_DEFAULTS below acts as the last-resort fallback; it means the strategy
still runs if config.yaml is missing or a key is absent.

Pattern used throughout:
    cfg = {**_DEFAULTS, **load_strategy_config("example_strategy")}
    self._some_param = cfg["some_param"]       # always present
    self._other      = cfg.get("other", None)  # optional / new key
"""

from datetime import datetime, timedelta, timezone
from typing import List

from config.polymarket_config import config
from data.polymarket_client import PolymarketClient
from data.polymarket_models import TradeOpportunity, TradeStatus
from data.market_schema import PolymarketMarket
from data.market_provider import MarketCriteria
from strategies.base import BaseStrategy
from strategies.config_loader import load_strategy_config
from utils.logger import logger

# ---------------------------------------------------------------------------
# Hard-coded fallback defaults
# ---------------------------------------------------------------------------
# These values are used when:
#   a) config.yaml does not exist, or
#   b) a key is present in _DEFAULTS but absent from config.yaml.
#
# Keeping sensible defaults here means the strategy always starts without
# error even in a bare environment.  Tune everything in config.yaml instead.

_DEFAULTS = dict(
    # Market scope
    scan_categories=["crypto", "fed", "regulatory", "other"],
    # Price window
    min_price=0.985,
    max_price=1.00,
    # Timing
    execute_before_close_seconds=60,
    hold_seconds=0,
    # Edge filter
    edge_filter_mode="net_edge",  # "net_edge" | "slippage_adjusted"
    expected_slippage_buffer_pct=1.0,
    # Confidence gate
    strategy_min_confidence=0.0,
    # Position sizing
    strategy_max_positions=5,
)

# Valid options for edge_filter_mode — validated at init time
_EDGE_FILTER_MODES = {"net_edge", "slippage_adjusted"}


class ExampleStrategy(BaseStrategy):
    """
    A fully-configured example strategy that demonstrates every framework
    pattern.  It targets markets near $1.00 (settlement arb territory) but
    exposes all parameters through config.yaml so it can be easily adapted.

    This is intentionally verbose — real strategies can be much leaner.
    """

    def __init__(self, client: PolymarketClient):
        self.client = client

        # ------------------------------------------------------------------
        # STEP 1 — Load config
        # ------------------------------------------------------------------
        # Merge _DEFAULTS with config.yaml values (YAML wins, then env vars).
        # cfg is a plain dict; pull out each value with a typed assignment.
        cfg = {**_DEFAULTS, **load_strategy_config("example_strategy")}

        # Market scope — YAML list, not env-var overridable (see config_loader.py)
        self._scan_categories: List[str] = list(cfg["scan_categories"])

        # Price window — env-var overridable via MIN_PRICE / MAX_PRICE
        self._min_price: float = float(cfg["min_price"])
        self._max_price: float = float(cfg["max_price"])

        # Timing — env-var overridable via EXECUTE_BEFORE_CLOSE_SECONDS / HOLD_SECONDS
        self._execute_before_close_seconds: int = int(cfg["execute_before_close_seconds"])
        self._hold_seconds: int = int(cfg["hold_seconds"])

        # Edge filter — env-var overridable via EDGE_FILTER_MODE
        self._edge_filter_mode: str = cfg["edge_filter_mode"]
        if self._edge_filter_mode not in _EDGE_FILTER_MODES:
            logger.warning(
                f"[ExampleStrategy] unknown edge_filter_mode {self._edge_filter_mode!r}; "
                f"falling back to 'net_edge'"
            )
            self._edge_filter_mode = "net_edge"

        # Slippage buffer — env-var overridable via EXPECTED_SLIPPAGE_BUFFER_PCT
        self._slippage_buffer: float = float(cfg["expected_slippage_buffer_pct"])

        # Confidence gate — env-var overridable via STRATEGY_MIN_CONFIDENCE
        self._min_confidence: float = float(cfg["strategy_min_confidence"])

        # Position cap — env-var overridable via STRATEGY_MAX_POSITIONS
        self._max_positions: int = (
            int(cfg["strategy_max_positions"]) if cfg["strategy_max_positions"] is not None else 5
        )

        # Store raw cfg for any custom keys added to config.yaml
        self._cfg = cfg

        logger.info(
            f"ExampleStrategy initialised\n"
            f"  Price window : [{self._min_price}, {self._max_price}]\n"
            f"  Categories   : {self._scan_categories}\n"
            f"  Edge mode    : {self._edge_filter_mode}"
            + (
                f" (buffer={self._slippage_buffer}%)"
                if self._edge_filter_mode == "slippage_adjusted"
                else ""
            )
            + f"\n  Max positions: {self._max_positions}"
        )

    # ------------------------------------------------------------------
    # STEP 2 — Declare which markets and price source this strategy needs
    # ------------------------------------------------------------------
    # MarketProvider uses this to pre-filter the universe and resolve prices
    # before scan_for_opportunities() is called.

    def get_market_criteria(self) -> MarketCriteria:
        return MarketCriteria(
            categories=self._scan_categories,
            min_volume_usd=config.MIN_VOLUME_USD,
            require_binary=True,
        )

    # ------------------------------------------------------------------
    # STEP 3 — Scan pre-filtered markets for entry signals
    # ------------------------------------------------------------------
    # markets: List[PolymarketMarket] — already filtered and priced by
    # MarketProvider.  Read market.resolved_price; no from_api() needed.

    def scan_for_opportunities(self, markets: List[PolymarketMarket]) -> List[TradeOpportunity]:
        taker_fee = config.TAKER_FEE_PERCENT
        opportunities = []

        for market in markets:
            try:
                token_yes = market.token_ids[0]
                token_no = market.token_ids[1]

                # resolved_price is set by MarketProvider — no extra API call.
                yes_price = market.resolved_price or 0.0
                if not yes_price:
                    continue

                # ── SIGNAL: price window ──────────────────────────────
                if not (self._min_price <= yes_price <= self._max_price):
                    continue

                # ── SIGNAL: edge filter ───────────────────────────────
                gross_edge = (1.0 - yes_price) * 100
                net_edge = gross_edge - taker_fee

                if not self._passes_edge_filter(net_edge, market.slug, gross_edge):
                    continue

                # ── SIGNAL: timing gate ───────────────────────────────
                time_to_close = market.seconds_to_close() or 0.0
                if time_to_close > self._execute_before_close_seconds:
                    logger.debug(
                        f"[Example] Skipping {market.slug}: closes in {time_to_close:.0f}s "
                        f"(gate={self._execute_before_close_seconds}s)"
                    )
                    continue

                # ── SIGNAL: confidence score ──────────────────────────
                confidence = self._calculate_confidence(yes_price, time_to_close, net_edge)
                min_conf = max(self._min_confidence, config.MIN_CONFIDENCE)
                if confidence < min_conf:
                    logger.debug(
                        f"[Example] Skipping {market.slug}: confidence {confidence:.2f} "
                        f"< {min_conf:.2f}"
                    )
                    continue

                # ── Build the opportunity ─────────────────────────────
                # expires_at drives should_exit(); set it to either the
                # hold period or the real market close time.
                if self._hold_seconds > 0:
                    expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._hold_seconds)
                else:
                    expires_at = market.end_time  # hold until market settles

                opp = TradeOpportunity(
                    market_id=market.market_id,
                    market_slug=market.slug,
                    question=market.question,
                    category=market.category,
                    token_id_yes=token_yes,
                    token_id_no=token_no,
                    winning_token_id=token_yes,
                    current_price=yes_price,
                    edge_percent=net_edge,
                    confidence=confidence,
                    detected_at=datetime.now(timezone.utc),
                    status=TradeStatus.DETECTED,
                )
                opp.expires_at = expires_at
                opportunities.append(opp)

                logger.info(
                    f"[Example] Opportunity: {market.slug} — "
                    f"price=${yes_price:.4f}, net_edge={net_edge:.2f}%, "
                    f"confidence={confidence:.2f}, ttc={time_to_close:.0f}s"
                )

            except Exception as exc:
                logger.error(f"[Example] Error scanning {market.slug}: {exc}")

        return opportunities

    # ------------------------------------------------------------------
    # STEP 4 — Rank and limit the candidates
    # ------------------------------------------------------------------
    # Called with the list returned by scan_for_opportunities().
    # Sort by whatever metric matters to your strategy, then slice to limit.

    def get_best_opportunities(
        self, opportunities: List[TradeOpportunity], limit: int = 5
    ) -> List[TradeOpportunity]:
        # Rank by risk-adjusted score: edge × confidence.
        # Ties broken by higher edge (implicitly via net_edge weight).
        cap = min(limit, self._max_positions)
        return sorted(
            opportunities,
            key=lambda o: o.edge_percent * (o.confidence or 0.0),
            reverse=True,
        )[:cap]

    # ------------------------------------------------------------------
    # STEP 5 (optional) — Exit logic
    # ------------------------------------------------------------------
    # should_exit() is called every scan cycle for every open position.
    # Return True to trigger an immediate sell at get_exit_price().

    def should_exit(self, position, current_price: float) -> bool:
        # Default: exit when expires_at has passed (covers both hold-period
        # and market-close modes set in scan_for_opportunities).
        if position.expires_at and datetime.now(timezone.utc) >= position.expires_at:
            logger.info(
                f"[Example] Exiting {position.position_id} — "
                f"expires_at reached, current price ${current_price:.4f}"
            )
            return True
        return False

    def get_exit_price(self, position, current_price: float) -> float:
        # Settlement arb style: always expect YES to pay out $1.00.
        # For momentum strategies, use current_price instead.
        return 1.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _passes_edge_filter(self, net_edge: float, market_slug: str, gross_edge: float) -> bool:
        """
        Apply the configured edge filter mode.

        net_edge mode          — passes when net_edge > 0
        slippage_adjusted mode — passes when net_edge > slippage_buffer
        """
        taker_fee = config.TAKER_FEE_PERCENT

        if self._edge_filter_mode == "slippage_adjusted":
            if net_edge <= self._slippage_buffer:
                logger.debug(
                    f"[Example] Skipping {market_slug}: net edge {net_edge:.2f}% "
                    f"does not exceed slippage buffer {self._slippage_buffer:.2f}% "
                    f"(gross {gross_edge:.2f}% - {taker_fee:.1f}% fee)"
                )
                return False
            return True

        # "net_edge" mode — any positive edge after fees is sufficient
        if net_edge <= 0:
            logger.debug(
                f"[Example] Skipping {market_slug}: gross edge {gross_edge:.2f}% "
                f"wiped by {taker_fee:.1f}% fee"
            )
            return False
        return True

    def _calculate_confidence(
        self, yes_price: float, time_to_close: float, net_edge: float
    ) -> float:
        """
        Score an opportunity 0.0–1.0 based on three normalised factors.

        Adapt the weights and breakpoints to match your strategy's risk model.

        Factor              Weight   What it measures
        ──────────────────  ──────   ────────────────────────────────────────
        Price proximity       40%   How close YES price is to the top of the
                                    configured window (higher = more certain)
        Time-to-close         40%   Whether the market is in the entry sweet
                                    spot (not too soon, not too late)
        Edge size             20%   How much profit buffer remains after fees
                                    (normalised to a 5% maximum)
        """
        price_range = self._max_price - self._min_price
        price_factor = (yes_price - self._min_price) / price_range if price_range > 0 else 0.0

        gate = self._execute_before_close_seconds
        if time_to_close <= 0:
            time_factor = 0.0
        elif time_to_close < gate:
            time_factor = 0.2  # Inside the window but cutting it fine
        elif time_to_close <= 300:
            time_factor = 1.0  # Sweet spot — imminent, still fillable
        elif time_to_close <= 3600:
            time_factor = 0.6  # Approaching — reasonably certain
        else:
            time_factor = 0.3  # Far out — outcome still uncertain

        edge_factor = min(net_edge / 5.0, 1.0)

        score = 0.4 * price_factor + 0.4 * time_factor + 0.2 * edge_factor
        return round(min(max(score, 0.0), 1.0), 4)
