"""
98.5 Cent Settlement Arbitrage Strategy
Core arbitrage logic for Polymarket
"""

from typing import List, Optional
from datetime import datetime, timezone

from config.polymarket_config import config
from data.polymarket_client import PolymarketClient
from data.polymarket_models import TradeOpportunity, TradeStatus
from data.market_schema import PolymarketMarket
from strategies.base import BaseStrategy
from strategies.config_loader import load_strategy_config
from utils.logger import logger

# Defaults used when no YAML config is present
_DEFAULTS = dict(
    min_price_threshold=0.985,
    max_price_threshold=1.00,
    execute_before_close_seconds=30,
    edge_filter_mode="net_edge",
    expected_slippage_buffer_pct=1.0,
)


class SettlementArbitrage(BaseStrategy):
    """
    98.5 cent settlement arbitrage strategy

    Strategy:
    1. Monitor market prices continuously
    2. Execute when price is in [min_price_threshold, max_price_threshold]
    3. Execute within execute_before_close_seconds of market close
    4. Buy YES token (always buy winning outcome)
    5. Max 5 positions, equal capital split (20% each)
    6. No external confirmation needed (price threshold IS confirmation)

    Edge filter modes (set via strategies/configs/settlement_arbitrage.yaml)
    -------------------------------------------------------------------------
    net_edge          — Allow entry when net_edge = gross_edge - fee > 0.
                        Original behaviour; any positive edge after fees suffices.

    slippage_adjusted — Allow entry only when net_edge > expected_slippage_buffer_pct.
                        Ensures the trade remains profitable after absorbing
                        typical fill slippage.
    """

    def __init__(self, client: PolymarketClient):
        self.client = client
        self.active_positions: List = []

        # Load strategy parameters from YAML (env-var overrides applied inside)
        cfg = {**_DEFAULTS, **load_strategy_config("settlement_arbitrage")}

        self._min_price_threshold: float = cfg["min_price_threshold"]
        self._max_price_threshold: float = cfg["max_price_threshold"]
        self._execute_before_close_seconds: int = int(cfg["execute_before_close_seconds"])
        self._edge_filter_mode: str = cfg["edge_filter_mode"]
        self._expected_slippage_buffer_pct: float = cfg["expected_slippage_buffer_pct"]

        logger.info(
            f"SettlementArbitrage initialised — "
            f"price window=[{self._min_price_threshold}, {self._max_price_threshold}], "
            f"edge_filter_mode={self._edge_filter_mode!r}"
            + (
                f", slippage_buffer={self._expected_slippage_buffer_pct}%"
                if self._edge_filter_mode == "slippage_adjusted"
                else ""
            )
        )

    # ------------------------------------------------------------------
    # BaseStrategy hooks
    # ------------------------------------------------------------------

    def get_scan_categories(self):
        return ["crypto", "fed", "regulatory", "other"]

    def should_exit(self, position, current_price: float) -> bool:
        """Exit when the market's close time has passed (position.expires_at)."""
        if position.expires_at and datetime.now(timezone.utc) >= position.expires_at:
            return True
        return False

    def get_exit_price(self, position, current_price: float) -> float:
        """Settlement arb always expects YES to resolve at $1.00."""
        return 1.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _passes_edge_filter(self, net_edge: float, market_slug: str, gross_edge: float) -> bool:
        """
        Apply the configured edge filter.

        Returns True if the opportunity clears the entry bar, False otherwise.
        Logs the rejection reason when returning False.
        """
        taker_fee = config.TAKER_FEE_PERCENT

        if self._edge_filter_mode == "slippage_adjusted":
            buffer = self._expected_slippage_buffer_pct
            if net_edge <= buffer:
                logger.debug(
                    f"Skipping {market_slug}: net edge {net_edge:.2f}% does not exceed "
                    f"slippage buffer {buffer:.2f}% "
                    f"(gross {gross_edge:.2f}% - {taker_fee:.1f}% fee = {net_edge:.2f}%)"
                )
                return False
            return True

        # Default: "net_edge" mode — any positive net edge is acceptable
        if net_edge <= 0:
            logger.debug(
                f"Skipping {market_slug}: gross edge {gross_edge:.2f}% "
                f"wiped by {taker_fee:.1f}% fee"
            )
            return False
        return True

    def _calculate_confidence(
        self, yes_price: float, time_to_close: float, net_edge: float
    ) -> float:
        """
        Calculate a confidence score (0.0–1.0) for a settlement arbitrage opportunity.

        Three factors, each normalised to [0, 1]:

        - Price proximity (40%): how close the YES price is to 1.0 within the
          configured scan window.  A price of 0.999 is far more certain to settle
          YES than one at min_price_threshold.

        - Time-to-close (40%): whether the market is in the execution sweet spot.
          Too far from close and outcome uncertainty is high; inside
          execute_before_close_seconds and there may not be time to fill.

        - Edge size (20%): larger net edge provides more buffer against slippage
          and fee variation.  Normalised against a 5% maximum expected edge.
        """
        price_range = self._max_price_threshold - self._min_price_threshold
        price_factor = (
            (yes_price - self._min_price_threshold) / price_range
            if price_range > 0
            else 0.0
        )

        execute_floor = self._execute_before_close_seconds
        if time_to_close <= 0:
            time_factor = 0.0
        elif time_to_close < execute_floor:
            # Inside the execution window but right at the edge — risky fill
            time_factor = 0.2
        elif time_to_close <= 300:
            # Sweet spot: imminent close, still time to fill
            time_factor = 1.0
        elif time_to_close <= 3600:
            # Approaching — outcome still reasonably certain
            time_factor = 0.6
        else:
            # Far from close — high outcome uncertainty
            time_factor = 0.3

        edge_factor = min(net_edge / 5.0, 1.0)

        confidence = (0.4 * price_factor) + (0.4 * time_factor) + (0.2 * edge_factor)
        return round(min(max(confidence, 0.0), 1.0), 4)

    # ------------------------------------------------------------------
    # Core strategy methods
    # ------------------------------------------------------------------

    def scan_for_opportunities(self, markets: list) -> List[TradeOpportunity]:
        """
        Scan markets for 98.5 cent arbitrage opportunities.

        Args:
            markets: List of markets to scan

        Returns:
            List of arbitrage opportunities
        """
        taker_fee = config.TAKER_FEE_PERCENT
        opportunities = []

        for raw_market in markets:
            try:
                market = PolymarketMarket.from_api(raw_market)
                if market is None:
                    logger.debug("Skipping market with missing id/token_ids")
                    continue

                # Liquidity filter
                if not market.has_sufficient_liquidity(config.MIN_VOLUME_USD):
                    logger.debug(
                        f"Skipping illiquid market {market.slug} "
                        f"(volume=${market.volume:.0f} < min=${config.MIN_VOLUME_USD:.0f})"
                    )
                    continue

                if len(market.token_ids) != 2:
                    continue

                token_id_yes = market.token_ids[0]
                token_id_no = market.token_ids[1]

                # Use the price already embedded in the Gamma API response when
                # available — avoids an extra per-market CLOB API call and is
                # immune to the CLOB client returning a non-float type.
                if market.outcome_prices:
                    yes_price = market.outcome_prices[0]
                else:
                    yes_price = self.client.get_price(token_id_yes)

                if yes_price == 0:
                    continue

                # Check if price is in [min_price_threshold, max_price_threshold]
                if self._min_price_threshold <= yes_price <= self._max_price_threshold:
                    gross_edge = (1.00 - yes_price) * 100
                    net_edge = gross_edge - taker_fee

                    if not self._passes_edge_filter(net_edge, market.slug, gross_edge):
                        continue

                    time_to_close = market.seconds_to_close() or 0.0
                    confidence = self._calculate_confidence(yes_price, time_to_close, net_edge)

                    if confidence < config.MIN_CONFIDENCE:
                        logger.debug(
                            f"Skipping {market.slug}: confidence {confidence:.2f} "
                            f"below minimum {config.MIN_CONFIDENCE:.2f}"
                        )
                        continue

                    opportunity = TradeOpportunity(
                        market_id=market.market_id,
                        market_slug=market.slug,
                        question=market.question,
                        category=market.category,
                        token_id_yes=token_id_yes,
                        token_id_no=token_id_no,
                        winning_token_id=token_id_yes,
                        current_price=yes_price,
                        edge_percent=net_edge,
                        confidence=confidence,
                        detected_at=datetime.now(timezone.utc),
                        status=TradeStatus.DETECTED,
                    )
                    opportunity.expires_at = market.end_time

                    opportunities.append(opportunity)

                    filter_label = (
                        f"buffer={self._expected_slippage_buffer_pct}%"
                        if self._edge_filter_mode == "slippage_adjusted"
                        else "net_edge>0"
                    )
                    logger.info(
                        f"Opportunity: {market.slug} - "
                        f"Price: ${yes_price:.4f}, "
                        f"Net edge: {net_edge:.2f}% (gross {gross_edge:.2f}% - {taker_fee:.1f}% fee) "
                        f"[filter: {filter_label}], "
                        f"Confidence: {confidence:.2f}, "
                        f"Time to close: {time_to_close:.0f}s"
                    )
                else:
                    logger.debug(
                        f"Price outside range: {market.slug} - ${yes_price:.4f} "
                        f"(Range: ${self._min_price_threshold:.3f}-{self._max_price_threshold:.3f})"
                    )

            except Exception as e:
                logger.error(f"Error scanning market {raw_market.get('slug', 'unknown')}: {e}")
                continue

        return opportunities

    def get_best_opportunities(
        self, opportunities: List[TradeOpportunity], limit: int = 5
    ) -> List[TradeOpportunity]:
        """
        Get best opportunities ranked by risk-adjusted score (edge × confidence).

        Args:
            opportunities: List of opportunities
            limit: Maximum number to return

        Returns:
            Sorted list of best opportunities
        """
        sorted_ops = sorted(
            opportunities,
            key=lambda x: x.edge_percent * (x.confidence or 0.0),
            reverse=True,
        )
        return sorted_ops[:limit]

    def execute_opportunity(
        self, opportunity: TradeOpportunity, capital: float
    ) -> Optional[float]:
        """
        Calculate position size and expected profit.

        Args:
            opportunity: Arbitrage opportunity
            capital: Available capital

        Returns:
            Expected profit or None
        """
        position_size = capital * config.CAPITAL_SPLIT_PERCENT

        if position_size < opportunity.current_price:
            logger.warning(
                f"Insufficient capital for {opportunity.market_slug} - "
                f"Need ${opportunity.current_price:.4f}, have ${position_size:.2f}"
            )
            return None

        shares = position_size / opportunity.current_price
        expected_profit = shares * (1.00 - opportunity.current_price)

        logger.info(
            f"Position size: {shares:.4f} shares, "
            f"Entry: ${opportunity.current_price:.4f}, "
            f"Expected profit: ${expected_profit:.2f} "
            f"({expected_profit / (shares * opportunity.current_price) * 100:.2f}% edge)"
        )

        return expected_profit
