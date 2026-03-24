"""
TradingStrategy Protocol
All strategies must satisfy this interface to be usable by TradingBot.
"""

from typing import List, Protocol, runtime_checkable

from data.polymarket_models import ArbitrageOpportunity


@runtime_checkable
class TradingStrategy(Protocol):
    """
    Protocol that every trading strategy must implement.

    TradingBot depends only on this interface, not on any concrete strategy,
    so new strategies can be dropped in without modifying core orchestration code.
    """

    def scan_for_opportunities(self, markets: list) -> List[ArbitrageOpportunity]:
        """
        Examine a list of raw market dicts and return qualifying opportunities.

        Args:
            markets: Raw market dicts from PolymarketClient.get_all_markets()

        Returns:
            List of ArbitrageOpportunity objects (may be empty)
        """
        ...

    def get_best_opportunities(
        self, opportunities: List[ArbitrageOpportunity], limit: int = 5
    ) -> List[ArbitrageOpportunity]:
        """
        Rank and return the top N opportunities from a candidate list.

        Args:
            opportunities: Candidates returned by scan_for_opportunities()
            limit: Maximum number of opportunities to return

        Returns:
            Top opportunities, highest-edge first
        """
        ...
