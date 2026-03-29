"""
TradingStrategy base class.

All strategies must inherit from BaseStrategy and implement the two abstract
methods.  The optional hook methods (should_exit, get_exit_price,
get_scan_categories) have sensible defaults and can be overridden as needed.
"""

from abc import ABC, abstractmethod
from typing import List

from data.polymarket_models import TradeOpportunity


class BaseStrategy(ABC):
    """
    Abstract base for every trading strategy.

    Required (must override)
    ------------------------
    scan_for_opportunities  – examine raw market dicts, return qualifying opportunities
    get_best_opportunities  – rank/limit a candidate list

    Optional hooks (override to customise behaviour)
    ------------------------------------------------
    should_exit             – return True when an open position should be closed
    get_exit_price          – return the target exit price for a position
    get_scan_categories     – list of Polymarket categories this strategy scans
    """

    # ── Required ───────────────────────────────────────────────────────────

    @abstractmethod
    def scan_for_opportunities(self, markets: list) -> List[TradeOpportunity]:
        """
        Examine a list of raw market dicts and return qualifying opportunities.

        Args:
            markets: Raw market dicts from PolymarketClient / multi-category scanner.

        Returns:
            List of TradeOpportunity objects (may be empty).
        """

    @abstractmethod
    def get_best_opportunities(
        self, opportunities: List[TradeOpportunity], limit: int = 5
    ) -> List[TradeOpportunity]:
        """
        Rank and return the top N opportunities from a candidate list.

        Args:
            opportunities: Candidates returned by scan_for_opportunities().
            limit: Maximum number of opportunities to return.

        Returns:
            Top opportunities, highest-priority first.
        """

    # ── Optional hooks ─────────────────────────────────────────────────────

    def should_exit(self, position, current_price: float) -> bool:
        """
        Return True if this open position should be closed now.

        The main loop calls this every scan cycle for each open position.
        Default: never auto-exit (the strategy holds until manual close or
        get_best_opportunities stops returning it).

        Args:
            position: Position dataclass from PositionTracker.
            current_price: Latest market price of the position's token.
        """
        return False

    def get_exit_price(self, position, current_price: float) -> float:
        """
        Return the price at which to close this position.

        Called only when should_exit() has returned True.
        Default: exit at the current market price.

        Args:
            position: Position dataclass from PositionTracker.
            current_price: Latest market price of the position's token.
        """
        return current_price

    def get_scan_categories(self) -> List[str]:
        """
        Return the Polymarket market categories this strategy wants to scan.

        Default: all four standard categories.
        Override to restrict or expand the scan scope.
        """
        return ["crypto", "fed", "regulatory", "other"]


# ---------------------------------------------------------------------------
# Backward-compatibility alias so existing code that imports TradingStrategy
# still resolves.
# ---------------------------------------------------------------------------
TradingStrategy = BaseStrategy
