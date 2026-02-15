"""
98.5 Cent Settlement Arbitrage Strategy
Core arbitrage logic for Polymarket
"""

from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from config.polymarket_config import config
from data.polymarket_client import PolymarketClient
from data.polymarket_models import ArbitrageOpportunity, ArbitrageStatus
from utils.logger import logger


class SettlementArbitrage:
    """
    98.5 cent settlement arbitrage strategy

    Strategy:
    1. Monitor market prices continuously
    2. Execute when price is in [0.985, 1.00]
    3. Execute 1-2 seconds before market close (configurable)
    4. Buy YES token (always buy winning outcome)
    5. Max 5 positions, equal capital split (20% each)
    6. No external confirmation needed (price threshold IS confirmation)
    """

    def __init__(self, client: PolymarketClient):
        self.client = client
        self.active_positions: List = []

    def scan_for_opportunities(self, markets: list) -> List[ArbitrageOpportunity]:
        """
        Scan markets for 98.5 cent arbitrage opportunities

        Args:
            markets: List of markets to scan

        Returns:
            List of arbitrage opportunities
        """
        opportunities = []

        for market in markets:
            try:
                # Get token IDs
                token_ids = market.get("clobTokenIds", [])
                if len(token_ids) != 2:
                    continue

                token_id_yes = token_ids[0]
                token_id_no = token_ids[1]

                # Get current price of YES token
                yes_price = self.client.get_price(token_id_yes)

                if yes_price == 0:
                    continue

                # Check if price is in [0.985, 1.00]
                if (
                    config.MIN_PRICE_THRESHOLD
                    <= yes_price
                    <= config.MAX_PRICE_THRESHOLD
                ):
                    # Calculate edge
                    edge = (1.00 - yes_price) * 100

                    # Calculate time to close
                    end_time = market.get("end_time")
                    time_to_close = self._calculate_time_to_close(end_time)

                    opportunity = ArbitrageOpportunity(
                        market_id=market.get("id"),
                        market_slug=market.get("slug"),
                        question=market.get("question"),
                        category=self._get_category_name(market),
                        token_id_yes=token_id_yes,
                        token_id_no=token_id_no,
                        winning_token_id=token_id_yes,
                        current_price=yes_price,
                        edge_percent=edge,
                        confidence=1.0,  # High confidence since price is the actual
                        time_to_close_seconds=time_to_close,
                        detected_at=datetime.utcnow(),
                        status=ArbitrageStatus.DETECTED,
                    )

                    opportunities.append(opportunity)
                    logger.info(
                        f"✅ Opportunity: {market.get('slug')} - "
                        f"Price: ${yes_price:.4f}, "
                        f"Edge: {edge:.2f}%, "
                        f"Time to close: {time_to_close:.0f}s"
                    )
                else:
                    # Price outside target range
                    logger.debug(
                        f"Price outside range: {market.get('slug')} - ${yes_price:.4f} "
                        f"(Range: ${config.MIN_PRICE_THRESHOLD:.2f}-{config.MAX_PRICE_THRESHOLD:.2f})"
                    )

            except Exception as e:
                logger.error(f"Error scanning market {market.get('slug')}: {e}")
                continue

        return opportunities

    def _get_category_name(self, market: dict) -> str:
        """
        Get category name from tags"""
        tags = market.get("tags", [])

        if not tags:
            return "other"

        for tag in tags:
            if isinstance(tag, dict):
                label = tag.get("label", "").lower()
            elif isinstance(tag, str):
                label = tag.lower()
            else:
                continue

            if "crypto" in label:
                return "crypto"
            elif "fed" in label:
                return "fed"
            elif "regulatory" in label or "sec" in label:
                return "regulatory"
            elif "economic" in label:
                return "economic"

        return "other"

    def _calculate_time_to_close(self, end_time_str: str) -> float:
        """
        Calculate time to market close in seconds"""
        try:
            end_time = datetime.fromisoformat(end_time_str)
            time_diff = (end_time - datetime.utcnow()).total_seconds()
            return max(0.0, time_diff)
        except Exception as e:
            logger.error(f"Error parsing end time: {e}")
            return 0.0

    def get_best_opportunities(
        self, opportunities: List[ArbitrageOpportunity], limit: int = 5
    ) -> List[ArbitrageOpportunity]:
        """
        Get best opportunities prioritized by edge

        Args:
            opportunities: List of opportunities
            limit: Maximum number to return

        Returns:
            Sorted list of best opportunities
        """
        # Sort by edge percent descending
        sorted_ops = sorted(opportunities, key=lambda x: x.edge_percent, reverse=True)

        return sorted_ops[:limit]

    def execute_opportunity(
        self, opportunity: ArbitrageOpportunity, capital: float
    ) -> Optional[float]:
        """
        Calculate position size and expected profit

        Args:
            opportunity: Arbitrage opportunity
            capital: Available capital

        Returns:
            Expected profit or None
        """
        # Equal split: 20% of capital per position
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
            f"Expected profit: ${expected_profit:.2f} ({expected_profit / (shares * opportunity.current_price) * 100:.2f}% edge)"
        )

        return expected_profit
