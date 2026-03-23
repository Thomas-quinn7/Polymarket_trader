"""
Normalized market schema for Polymarket API responses.

Handles field name inconsistencies across the Gamma and CLOB APIs
by normalising all raw API dicts into a single PolymarketMarket dataclass.
"""

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

    # Keep raw dict for any fields not explicitly mapped
    _raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, raw: dict) -> Optional["PolymarketMarket"]:
        """
        Build a PolymarketMarket from a raw API response dict.

        Returns None if required fields (market_id, token_ids) are missing.
        """
        # --- market_id ---
        market_id = (
            raw.get("id")
            or raw.get("conditionId")
            or raw.get("marketSlug")
            or raw.get("slug")
        )
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
        volume = float(
            raw.get("volume")
            or raw.get("volumeNum")
            or raw.get("volumeClob")
            or 0.0
        )

        # --- category from tags ---
        category = _classify_category(raw.get("tags", []))

        return cls(
            market_id=str(market_id),
            slug=slug,
            question=question,
            token_ids=token_ids,
            category=category,
            volume=volume,
            end_time=end_time,
            _raw=raw,
        )

    def seconds_to_close(self) -> Optional[float]:
        """Return seconds until market closes, or None if end_time is unknown."""
        if self.end_time is None:
            return None
        delta = self.end_time - datetime.now(timezone.utc)
        return max(0.0, delta.total_seconds())

    def has_sufficient_liquidity(self, min_volume: float) -> bool:
        return self.volume >= min_volume


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
