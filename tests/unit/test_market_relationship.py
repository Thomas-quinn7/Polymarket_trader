"""
Unit tests for data/market_relationship.py
Covers RelationshipType, MarketRelationship, and MarketBasket.
"""

from data.market_relationship import (
    RelationshipType,
    MarketRelationship,
    MarketBasket,
)

# ---------------------------------------------------------------------------
# RelationshipType
# ---------------------------------------------------------------------------


class TestRelationshipType:
    def test_all_values_are_strings(self):
        for rt in RelationshipType:
            assert isinstance(rt.value, str)

    def test_expected_members(self):
        names = {rt.name for rt in RelationshipType}
        assert names == {"TEMPORAL", "CONDITIONAL", "CORRELATED", "COMPLEMENTARY", "MACRO_EVENT"}

    def test_is_string_subclass(self):
        assert isinstance(RelationshipType.TEMPORAL, str)

    def test_equality_with_plain_string(self):
        assert RelationshipType.TEMPORAL == "temporal"
        assert RelationshipType.CORRELATED == "correlated"


# ---------------------------------------------------------------------------
# MarketRelationship
# ---------------------------------------------------------------------------


class TestMarketRelationship:
    def _make(self, **kwargs):
        defaults = dict(
            market_id_a="mkt-a",
            market_id_b="mkt-b",
            relationship_type=RelationshipType.CORRELATED,
            expected_correlation=0.9,
            weight_a=0.5,
            weight_b=0.5,
            notes="test relationship",
        )
        defaults.update(kwargs)
        return MarketRelationship(**defaults)

    def test_construction_defaults(self):
        rel = MarketRelationship(
            market_id_a="a", market_id_b="b", relationship_type=RelationshipType.TEMPORAL
        )
        assert rel.expected_correlation == 1.0
        assert rel.weight_a == 0.5
        assert rel.weight_b == 0.5
        assert rel.notes == ""

    def test_to_dict_keys(self):
        rel = self._make()
        d = rel.to_dict()
        for key in (
            "market_id_a",
            "market_id_b",
            "relationship_type",
            "expected_correlation",
            "weight_a",
            "weight_b",
            "notes",
        ):
            assert key in d

    def test_to_dict_relationship_type_is_string(self):
        rel = self._make(relationship_type=RelationshipType.MACRO_EVENT)
        assert rel.to_dict()["relationship_type"] == "macro_event"

    def test_to_dict_values(self):
        rel = self._make(
            market_id_a="X",
            market_id_b="Y",
            expected_correlation=0.75,
            weight_a=0.6,
            weight_b=0.4,
        )
        d = rel.to_dict()
        assert d["market_id_a"] == "X"
        assert d["market_id_b"] == "Y"
        assert d["expected_correlation"] == 0.75
        assert d["weight_a"] == 0.6
        assert d["weight_b"] == 0.4

    def test_negative_correlation(self):
        rel = self._make(expected_correlation=-1.0)
        assert rel.to_dict()["expected_correlation"] == -1.0

    def test_complementary_type(self):
        rel = self._make(relationship_type=RelationshipType.COMPLEMENTARY)
        assert rel.to_dict()["relationship_type"] == "complementary"


# ---------------------------------------------------------------------------
# MarketBasket
# ---------------------------------------------------------------------------


class TestMarketBasket:
    def _make_rel(self, a="a", b="b"):
        return MarketRelationship(
            market_id_a=a, market_id_b=b, relationship_type=RelationshipType.CORRELATED
        )

    def _make_basket(self, **kwargs):
        defaults = dict(
            basket_id="basket-001",
            name="Test Basket",
            market_ids=["mkt-a", "mkt-b", "mkt-c"],
        )
        defaults.update(kwargs)
        return MarketBasket(**defaults)

    def test_construction_defaults(self):
        basket = self._make_basket()
        assert basket.relationships == []
        assert basket.category == "other"
        assert basket.event_date == ""
        assert basket.notes == ""

    def test_to_dict_keys(self):
        basket = self._make_basket()
        d = basket.to_dict()
        for key in (
            "basket_id",
            "name",
            "market_ids",
            "relationships",
            "category",
            "event_date",
            "notes",
        ):
            assert key in d

    def test_to_dict_market_ids(self):
        basket = self._make_basket(market_ids=["x", "y"])
        assert basket.to_dict()["market_ids"] == ["x", "y"]

    def test_to_dict_relationships_serialised(self):
        rel = self._make_rel("a", "b")
        basket = self._make_basket(relationships=[rel])
        d = basket.to_dict()
        assert len(d["relationships"]) == 1
        assert d["relationships"][0]["market_id_a"] == "a"

    def test_to_dict_empty_relationships(self):
        basket = self._make_basket()
        assert basket.to_dict()["relationships"] == []

    # -- get_relationship --

    def test_get_relationship_found_forward(self):
        rel = self._make_rel("mkt-a", "mkt-b")
        basket = self._make_basket(market_ids=["mkt-a", "mkt-b"], relationships=[rel])
        result = basket.get_relationship("mkt-a", "mkt-b")
        assert result is rel

    def test_get_relationship_found_reverse(self):
        """Order of arguments should not matter."""
        rel = self._make_rel("mkt-a", "mkt-b")
        basket = self._make_basket(market_ids=["mkt-a", "mkt-b"], relationships=[rel])
        result = basket.get_relationship("mkt-b", "mkt-a")
        assert result is rel

    def test_get_relationship_not_found(self):
        basket = self._make_basket()
        assert basket.get_relationship("unknown-a", "unknown-b") is None

    def test_get_relationship_multiple_rels(self):
        rel_ab = self._make_rel("a", "b")
        rel_ac = self._make_rel("a", "c")
        basket = self._make_basket(market_ids=["a", "b", "c"], relationships=[rel_ab, rel_ac])
        assert basket.get_relationship("a", "c") is rel_ac
        assert basket.get_relationship("a", "b") is rel_ab

    def test_category_field(self):
        basket = self._make_basket(category="fed")
        assert basket.to_dict()["category"] == "fed"

    def test_event_date_field(self):
        basket = self._make_basket(event_date="2026-03-18")
        assert basket.to_dict()["event_date"] == "2026-03-18"

    def test_notes_field(self):
        basket = self._make_basket(notes="FOMC March meeting")
        assert basket.to_dict()["notes"] == "FOMC March meeting"
