"""
Market relationship models.

Pure data structures that describe how two or more Polymarket markets are
related.  Strategies use these to build market baskets for statistical
arbitrage, correlated-pair trading, or macro event analysis.

No strategy logic lives here — only the data model.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class RelationshipType(str, Enum):
    """How two markets are related."""

    # Same underlying event, different time windows.
    # e.g. "Will Fed raise rates in March?" ↔ "Will Fed raise rates in Q1?"
    TEMPORAL = "temporal"

    # One outcome logically implies the other.
    # e.g. "Will X win state A?" → "Will X win the election?"
    CONDITIONAL = "conditional"

    # Historically move together (positive) or against each other (negative).
    # e.g. two crypto price markets during the same macro move.
    CORRELATED = "correlated"

    # YES + NO prices of the same market; should sum to ~1.0.
    # Useful for detecting arbitrage in thinly traded markets.
    COMPLEMENTARY = "complementary"

    # Market resolves based on an external macro event (Fed meeting, CPI print, etc.).
    MACRO_EVENT = "macro_event"


@dataclass
class MarketRelationship:
    """
    Describes the statistical or logical relationship between two markets.

    Attributes
    ----------
    market_id_a, market_id_b : str
        Polymarket market IDs (or slugs).
    relationship_type : RelationshipType
        How these markets are related.
    expected_correlation : float
        Theoretical correlation coefficient [-1.0, 1.0].
        +1.0 = should move identically, -1.0 = should move inversely.
    weight_a, weight_b : float
        Capital allocation weights for a paired trade (must sum to 1.0).
    notes : str
        Human-readable description of why this relationship exists.
    """

    market_id_a: str
    market_id_b: str
    relationship_type: RelationshipType
    expected_correlation: float = 1.0
    weight_a: float = 0.5
    weight_b: float = 0.5
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "market_id_a":          self.market_id_a,
            "market_id_b":          self.market_id_b,
            "relationship_type":    self.relationship_type.value,
            "expected_correlation": self.expected_correlation,
            "weight_a":             self.weight_a,
            "weight_b":             self.weight_b,
            "notes":                self.notes,
        }


@dataclass
class MarketBasket:
    """
    A named collection of related markets to be scanned and potentially
    traded as a coordinated group.

    Used by statistical arbitrage strategies to define the universe of
    markets that should be evaluated together for spread divergence.

    Attributes
    ----------
    basket_id : str
        Unique identifier for this basket (e.g. "fed-rate-march-q1-2026").
    name : str
        Human-readable label.
    market_ids : List[str]
        All market IDs in this basket.
    relationships : List[MarketRelationship]
        Pairwise relationships between markets in the basket.
    category : str
        Primary Polymarket category (crypto, fed, regulatory, other).
    event_date : str | None
        ISO date string of the underlying event, if applicable (e.g. FOMC meeting date).
    notes : str
        Any additional context.
    """

    basket_id:     str
    name:          str
    market_ids:    List[str]
    relationships: List[MarketRelationship] = field(default_factory=list)
    category:      str = "other"
    event_date:    str = ""
    notes:         str = ""

    def to_dict(self) -> dict:
        return {
            "basket_id":     self.basket_id,
            "name":          self.name,
            "market_ids":    self.market_ids,
            "relationships": [r.to_dict() for r in self.relationships],
            "category":      self.category,
            "event_date":    self.event_date,
            "notes":         self.notes,
        }

    def get_relationship(
        self, market_id_a: str, market_id_b: str
    ) -> "MarketRelationship | None":
        """Return the relationship between two specific markets, if defined."""
        for rel in self.relationships:
            if (rel.market_id_a == market_id_a and rel.market_id_b == market_id_b) or \
               (rel.market_id_a == market_id_b and rel.market_id_b == market_id_a):
                return rel
        return None
