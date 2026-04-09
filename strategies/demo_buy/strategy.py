"""
Demo Buy Strategy — proof of concept only.

Buys the YES token of every market that passes a basic liquidity check,
with no price or edge filter.  Exits each position after a short hold period
(hold_seconds) to prove the full open → monitor → close path works.

Never use this strategy with real money.
"""

from datetime import datetime, timezone, timedelta
from typing import List

from data.polymarket_client import PolymarketClient
from data.polymarket_models import TradeOpportunity, TradeStatus
from data.market_schema import PolymarketMarket
from strategies.base import BaseStrategy
from strategies.config_loader import load_strategy_config
from utils.logger import logger

_DEFAULTS = dict(
    hold_seconds=60,
    scan_categories=["crypto"],
)


class DemoBuy(BaseStrategy):
    """
    Demo strategy: enter YES on every liquid market, exit after
    hold_seconds at whatever the current market price is.
    """

    def __init__(self, client: PolymarketClient):
        self.client = client

        cfg = {**_DEFAULTS, **load_strategy_config("demo_buy")}
        self._hold_seconds: int = int(cfg["hold_seconds"])
        self._scan_categories: List[str] = list(cfg["scan_categories"])

    def get_scan_categories(self) -> List[str]:
        return self._scan_categories

    def scan_for_opportunities(self, markets: list) -> List[TradeOpportunity]:
        opportunities = []

        for raw_market in markets:
            try:
                market = PolymarketMarket.from_api(raw_market)
                if market is None:
                    continue

                if len(market.token_ids) < 2:
                    continue

                token_id_yes = market.token_ids[0]
                token_id_no  = market.token_ids[1]

                yes_price = (
                    market.outcome_prices[0]
                    if market.outcome_prices
                    else self.client.get_price(token_id_yes)
                )
                if yes_price == 0:
                    yes_price = 0.50  # fallback for thinly traded markets

                opportunity = TradeOpportunity(
                    market_id=market.market_id,
                    market_slug=market.slug,
                    question=market.question,
                    category=market.category,
                    token_id_yes=token_id_yes,
                    token_id_no=token_id_no,
                    winning_token_id=token_id_yes,
                    side="YES",
                    current_price=yes_price,
                    edge_percent=0.0,
                    confidence=1.0,
                    detected_at=datetime.now(timezone.utc),
                    status=TradeStatus.DETECTED,
                )
                opportunity.expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._hold_seconds)

                opportunities.append(opportunity)
                logger.info(
                    f"[DEMO] Opportunity: {market.slug} YES @ ${yes_price:.4f} "
                    f"— will exit in {self._hold_seconds}s"
                )

            except Exception as e:
                logger.error(f"[DEMO] Error scanning {raw_market.get('slug', '?')}: {e}")

        return opportunities

    def get_best_opportunities(
        self, opportunities: List[TradeOpportunity], limit: int = 5
    ) -> List[TradeOpportunity]:
        return opportunities[:limit]

    def should_exit(self, position, current_price: float) -> bool:
        """Exit once the demo hold period has elapsed."""
        if position.expires_at and datetime.now(timezone.utc) >= position.expires_at:
            return True
        return False

    def get_exit_price(self, position, current_price: float) -> float:
        """Exit at the current market price (no fixed settlement assumption)."""
        return current_price
