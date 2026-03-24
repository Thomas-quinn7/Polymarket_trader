"""
Demo Buy Strategy
Buys the YES token of every detected market immediately — no price or edge
filter. Intended only for simulation/demo runs to prove the full execution
path (scan → timer → buy → settle) works end-to-end.

Never use this strategy with real money.
"""

from datetime import datetime, timezone
from typing import List

from data.polymarket_client import PolymarketClient
from data.polymarket_models import ArbitrageOpportunity, ArbitrageStatus
from data.market_schema import PolymarketMarket
from utils.logger import logger


# How many seconds from now the "close time" is set to for every market.
# Must be less than EXECUTE_BEFORE_CLOSE_SECONDS (default 30) so the
# execution_timer fires on the very next loop iteration.
_DEMO_CLOSE_IN_SECONDS = 5


class DemoBuy:
    """
    Demo strategy: buy YES on every market that passes the basic liquidity
    check, regardless of price or edge.  Close time is forced to
    _DEMO_CLOSE_IN_SECONDS so the execution timer fires immediately.
    """

    def __init__(self, client: PolymarketClient):
        self.client = client

    def scan_for_opportunities(self, markets: list) -> List[ArbitrageOpportunity]:
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

                yes_price = self.client.get_price(token_id_yes)
                if yes_price == 0:
                    yes_price = 0.50   # fallback so the position has a sane entry price

                opportunity = ArbitrageOpportunity(
                    market_id=market.market_id,
                    market_slug=market.slug,
                    question=market.question,
                    category=market.category,
                    token_id_yes=token_id_yes,
                    token_id_no=token_id_no,
                    winning_token_id=token_id_yes,
                    current_price=yes_price,
                    edge_percent=0.0,          # no edge required for demo
                    confidence=1.0,
                    time_to_close_seconds=_DEMO_CLOSE_IN_SECONDS,
                    detected_at=datetime.now(timezone.utc),
                    status=ArbitrageStatus.DETECTED,
                )

                opportunities.append(opportunity)
                logger.info(
                    f"[DEMO] Opportunity: {market.slug} "
                    f"YES @ ${yes_price:.4f} — will execute in {_DEMO_CLOSE_IN_SECONDS}s"
                )

            except Exception as e:
                logger.error(f"[DEMO] Error scanning {raw_market.get('slug', '?')}: {e}")

        return opportunities

    def get_best_opportunities(
        self, opportunities: List[ArbitrageOpportunity], limit: int = 5
    ) -> List[ArbitrageOpportunity]:
        # Return the first `limit` markets; order doesn't matter for demo
        return opportunities[:limit]
