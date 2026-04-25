"""
Normalized market schema for Polymarket API responses.

Handles field name inconsistencies across the Gamma and CLOB APIs
by normalising all raw API dicts into a single PolymarketMarket dataclass.
"""

import json as _json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

# Maps raw tag labels (lowercased) to canonical category names.
# Uses exact/prefix matching to avoid false positives from substring matching.
_TAG_CATEGORY_MAP: dict = {
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "bitcoin": "crypto",
    "ethereum": "crypto",
    "defi": "crypto",
    "blockchain": "crypto",
    "fed": "fed",
    "federal reserve": "fed",
    "fomc": "fed",
    "interest rate": "fed",
    "monetary policy": "fed",
    "regulatory": "regulatory",
    "regulation": "regulatory",
    "sec": "regulatory",
    "cftc": "regulatory",
    "legislation": "regulatory",
    "economic": "economic",
    "economy": "economic",
    "gdp": "economic",
    "inflation": "economic",
    "cpi": "economic",
}


@dataclass
class PolymarketMarket:
    """
    Normalised representation of a Polymarket market.

    Accepts fields from both the Gamma API (/events, /markets) and
    the CLOB API, resolving all known field name variants.
    """

    market_id: str
    slug: str
    question: str
    token_ids: List[str]
    category: str
    volume: float
    end_time: Optional[datetime] = None
    outcome_prices: List[float] = field(default_factory=list)  # YES price at [0], NO at [1]

    # Set by MarketProvider after applying the strategy's price_source_preference.
    # Strategies should read this field instead of fetching prices themselves.
    # None means the provider has not yet resolved the price for this market.
    resolved_price: Optional[float] = field(default=None, repr=False, compare=False)

    @classmethod
    def from_api(cls, raw: dict) -> Optional["PolymarketMarket"]:
        """
        Build a PolymarketMarket from a raw API response dict.

        Returns None if required fields (market_id, token_ids) are missing.
        """
        # --- market_id ---
        # Only stable IDs are accepted; human-readable slugs are not globally
        # unique across time periods and must not be used as primary keys.
        market_id = raw.get("id") or raw.get("conditionId")
        if not market_id:
            return None

        # --- token IDs ---
        token_ids = raw.get("clobTokenIds") or []
        if not isinstance(token_ids, list):
            token_ids = []

        # --- slug ---
        slug = raw.get("slug") or raw.get("marketSlug") or str(market_id)

        # --- question / title ---
        question = raw.get("question") or raw.get("title") or slug

        # --- end time ---
        end_time = _parse_end_time(raw)

        # --- volume ---
        volume = float(raw.get("volume") or raw.get("volumeNum") or raw.get("volumeClob") or 0.0)

        # --- category from tags ---
        category = _classify_category(raw.get("tags", []))

        # --- outcome prices (YES at [0], NO at [1]) ---
        outcome_prices = _parse_outcome_prices(raw)

        # --- normalise YES/NO orientation ---
        # Polymarket's `outcomes` field is the labels parallel to clobTokenIds
        # and outcomePrices. The API has been observed to return the NO side
        # first for some markets; if so, flip both arrays so token_ids[0] is
        # always the YES token and outcome_prices[0] is always the YES price.
        # When outcomes is missing or unrecognised we leave order unchanged.
        token_ids, outcome_prices = _orient_yes_no(raw.get("outcomes"), token_ids, outcome_prices)

        return cls(
            market_id=str(market_id),
            slug=slug,
            question=question,
            token_ids=token_ids,
            category=category,
            volume=volume,
            end_time=end_time,
            outcome_prices=outcome_prices,
        )

    def seconds_to_close(self) -> Optional[float]:
        """Return seconds until market closes, or None if end_time is unknown."""
        if self.end_time is None:
            return None
        delta = self.end_time - datetime.now(timezone.utc)
        return max(0.0, delta.total_seconds())

    def has_sufficient_liquidity(self, min_volume: float) -> bool:
        """Return True only when the market has known, positive volume >= min_volume.

        The ``volume > 0`` guard is intentional: Polymarket markets with no
        recorded trades store volume as 0.0, which is indistinguishable from
        markets whose volume data simply failed to load.  Passing
        ``min_volume=0`` therefore does NOT disable the filter — it still
        rejects zero-volume markets.  If you want to include zero-volume
        markets, filter on ``volume >= 0`` at the call site instead of using
        this method.
        """
        return self.volume > 0 and self.volume >= min_volume


# Outcome labels that mean "YES" at index 0. Anything that maps to NO at index
# 0 triggers a flip. Case-insensitive. Unknown labels => no flip (preserves
# whatever order the API gave us, matching pre-2026-04 behaviour).
_YES_LABELS = frozenset({"yes", "y", "true", "up", "for"})
_NO_LABELS = frozenset({"no", "n", "false", "down", "against"})


def _orient_yes_no(
    outcomes,
    token_ids: List[str],
    outcome_prices: List[float],
) -> tuple:
    """
    Reorder (token_ids, outcome_prices) so YES is at index 0 when the
    `outcomes` field tells us the API returned them flipped.

    Returns the (possibly reordered) token_ids and outcome_prices.

    Behaviour:
      outcomes=["Yes","No"]  -> no change
      outcomes=["No","Yes"]  -> flipped
      outcomes missing       -> no change (preserves API order)
      outcomes unrecognised  -> no change (defensive: don't guess)
    """
    if not outcomes or len(token_ids) < 2:
        return token_ids, outcome_prices
    # outcomes can arrive as a JSON-encoded string from Gamma
    if isinstance(outcomes, str):
        try:
            outcomes = _json.loads(outcomes)
        except Exception:
            return token_ids, outcome_prices
    if not isinstance(outcomes, list) or len(outcomes) < 2:
        return token_ids, outcome_prices
    first = str(outcomes[0]).strip().lower()
    second = str(outcomes[1]).strip().lower()
    if first in _YES_LABELS and second in _NO_LABELS:
        return token_ids, outcome_prices
    if first in _NO_LABELS and second in _YES_LABELS:
        # Flip both arrays in lockstep so price[i] still pairs with token[i].
        flipped_tokens = [token_ids[1], token_ids[0]] + list(token_ids[2:])
        flipped_prices = (
            [outcome_prices[1], outcome_prices[0]] + list(outcome_prices[2:])
            if len(outcome_prices) >= 2
            else outcome_prices
        )
        return flipped_tokens, flipped_prices
    return token_ids, outcome_prices


def _parse_outcome_prices(raw: dict) -> List[float]:
    """
    Parse outcomePrices from the Gamma API market dict.

    The field may arrive as a JSON-encoded string '["0.985","0.015"]'
    or as a plain Python list.  Returns a list of floats (empty on failure).
    """
    raw_prices = raw.get("outcomePrices")
    if not raw_prices:
        return []
    try:
        if isinstance(raw_prices, str):
            raw_prices = _json.loads(raw_prices)  # _json imported at top of module
        return [float(p) for p in raw_prices]
    except Exception:
        return []


def _parse_end_time(raw: dict) -> Optional[datetime]:
    """Try all known end-time field names and return a UTC-aware datetime."""
    for key in ("endDate", "end_date", "end_time", "closeTime", "close_time"):
        value = raw.get(key)
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            # Ensure timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            continue
    return None


def _classify_category(tags: list) -> str:
    """
    Map API tags to a canonical category name.

    Uses exact lookup against _TAG_CATEGORY_MAP to avoid substring false-positives.
    Returns 'other' if no tag matches.
    """
    for tag in tags:
        if isinstance(tag, dict):
            label = tag.get("label") or tag.get("name") or ""
        elif isinstance(tag, str):
            label = tag
        else:
            continue

        label = label.strip().lower()
        if label in _TAG_CATEGORY_MAP:
            return _TAG_CATEGORY_MAP[label]

    return "other"


classify_category = _classify_category
