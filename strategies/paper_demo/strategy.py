"""
Paper Demo Strategy

Purely for testing the full buy → monitor → exit pipeline with real
Polymarket data and zero real money.

Behaviour
---------
1. On the first scan, finds the single most-liquid active market.
2. Buys the YES side at the current real market price (paper only).
3. Holds the position for hold_seconds, then exits at the live price.

This deliberately has NO edge filter — the point is to prove that
real prices are fetched, a paper order lands correctly, and the
position shows up in the dashboard/logs. Do not use with real funds.
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
    hold_seconds=300,
    min_volume=500.0,
    primary_scan_category="crypto",
    scan_categories=["crypto", "fed", "regulatory", "other"],
)


class PaperDemo(BaseStrategy):
    """
    Minimal paper-trading demo:
    - Finds the first real, liquid market from the Polymarket API.
    - Enters a YES paper position at the live price.
    - Exits after hold_seconds at the live price.

    Useful for verifying that end-to-end order flow works correctly
    (real API → paper buy → position tracker → dashboard → paper sell).
    """

    def __init__(self, client: PolymarketClient):
        self.client = client
        self._entered = False  # True once we have an open position

        cfg = {**_DEFAULTS, **load_strategy_config("paper_demo")}
        self._hold_seconds: int = int(cfg["hold_seconds"])
        self._min_volume: float = float(cfg["min_volume"])
        self._primary_scan_category: str = str(cfg["primary_scan_category"])
        self._scan_categories: List[str] = list(cfg["scan_categories"])

        logger.info(
            f"PaperDemo initialised — hold={self._hold_seconds}s, "
            f"min_volume=${self._min_volume:.0f}, "
            f"primary_category={self._primary_scan_category!r}"
        )

    def get_scan_categories(self) -> List[str]:
        return self._scan_categories

    # ------------------------------------------------------------------
    # scan_for_opportunities
    # ------------------------------------------------------------------

    def scan_for_opportunities(self, markets: list) -> List[TradeOpportunity]:
        """
        Return at most ONE opportunity — the most-liquid market found.
        Once we already have an open position we return nothing so the
        main loop does not try to open a second one.
        """
        if self._entered:
            logger.debug("[PaperDemo] Already holding a position — skipping scan")
            return []

        best_market: PolymarketMarket | None = None
        best_volume: float = -1.0

        for raw in markets:
            try:
                market = PolymarketMarket.from_api(raw)
                if market is None:
                    continue
                if len(market.token_ids) < 2:
                    continue
                if market.volume < self._min_volume:
                    continue

                if market.volume > best_volume:
                    best_volume = market.volume
                    best_market = market

            except Exception as e:
                logger.debug("[PaperDemo] Skipping malformed market: %s", e)

        if best_market is None:
            logger.info("[PaperDemo] No suitable market found in this scan")
            return []

        # Use embedded price from Gamma API response when available —
        # avoids an extra CLOB call and is immune to dict/float type issues.
        token_yes = best_market.token_ids[0]
        token_no = best_market.token_ids[1]

        if best_market.outcome_prices:
            yes_price = best_market.outcome_prices[0]
        else:
            raw_price = self.client.get_price(token_yes)
            yes_price = float(raw_price) if raw_price else 0.0

        if yes_price <= 0.0 or yes_price >= 1.0:
            logger.warning(
                "[PaperDemo] Skipping %s — price %.4f is not tradable",
                best_market.slug,
                yes_price,
            )
            return []

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._hold_seconds)

        opp = TradeOpportunity(
            market_id=best_market.market_id,
            market_slug=best_market.slug,
            question=best_market.question,
            category=best_market.category,
            token_id_yes=token_yes,
            token_id_no=token_no,
            winning_token_id=token_yes,
            side="YES",
            opportunity_type="single",
            current_price=yes_price,
            edge_percent=0.0,  # No edge filter — this is a demo
            confidence=1.0,
            detected_at=datetime.now(timezone.utc),
            status=TradeStatus.DETECTED,
        )
        opp.expires_at = expires_at

        logger.info(
            "[PaperDemo] Selected market: %s\n"
            "  Question : %s\n"
            "  YES price: $%.4f\n"
            "  Volume   : $%.0f\n"
            "  Hold for : %ds (exits ~%s UTC)",
            best_market.slug,
            best_market.question,
            yes_price,
            best_volume,
            self._hold_seconds,
            expires_at.strftime("%H:%M:%S"),
        )

        self._entered = True
        return [opp]

    # ------------------------------------------------------------------
    # get_best_opportunities
    # ------------------------------------------------------------------

    def get_best_opportunities(
        self, opportunities: List[TradeOpportunity], limit: int = 5
    ) -> List[TradeOpportunity]:
        # We only ever return one; just pass it through.
        return opportunities[:1]

    # ------------------------------------------------------------------
    # Exit hooks
    # ------------------------------------------------------------------

    def should_exit(self, position, current_price: float) -> bool:
        """Exit once the hold period has elapsed."""
        if position.expires_at and datetime.now(timezone.utc) >= position.expires_at:
            logger.info(
                "[PaperDemo] Hold period expired for %s — exiting at $%.4f",
                position.position_id,
                current_price,
            )
            # Reset so we can open a new position next scan
            self._entered = False
            return True
        return False

    def get_exit_price(self, position, current_price: float) -> float:
        """Exit at the live market price — whatever Polymarket says right now."""
        return current_price
