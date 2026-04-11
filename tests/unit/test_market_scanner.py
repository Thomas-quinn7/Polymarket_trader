"""
Unit tests for data/market_scanner.py — scan_categories.
"""

from unittest.mock import MagicMock

from data.market_scanner import scan_categories, ALL_CATEGORIES


def _make_client(markets_by_category=None):
    """Return a mock client whose get_all_markets returns per-category data."""
    client = MagicMock()
    if markets_by_category is None:
        markets_by_category = {cat: [] for cat in ALL_CATEGORIES}

    def _get_all_markets(category=None):
        return markets_by_category.get(category, [])

    client.get_all_markets.side_effect = _get_all_markets
    return client


def _market(slug, mid=None):
    return {"id": slug, "slug": slug, "question": f"Q {slug}"}


class TestAllCategories:
    def test_constant_has_four_entries(self):
        assert len(ALL_CATEGORIES) == 4
        assert set(ALL_CATEGORIES) == {"crypto", "fed", "regulatory", "other"}


class TestScanCategoriesBasic:
    def test_returns_list(self):
        client = _make_client()
        result = scan_categories(client)
        assert isinstance(result, list)

    def test_empty_markets_returns_empty(self):
        client = _make_client()
        assert scan_categories(client) == []

    def test_single_category_all_markets_returned(self):
        markets = [_market("mkt-1"), _market("mkt-2")]
        client = _make_client({"crypto": markets})
        result = scan_categories(client, categories=["crypto"])
        assert len(result) == 2

    def test_multiple_categories_merged(self):
        data = {
            "crypto": [_market("c1"), _market("c2")],
            "fed": [_market("f1")],
        }
        client = _make_client(data)
        result = scan_categories(client, categories=["crypto", "fed"])
        assert len(result) == 3


class TestDeduplication:
    def test_duplicate_by_id_removed(self):
        """Same id appearing in two categories → only one entry returned."""
        dup = _market("dup-1")
        data = {
            "crypto": [dup, _market("unique-1")],
            "regulatory": [dup, _market("unique-2")],
        }
        client = _make_client(data)
        result = scan_categories(client, categories=["crypto", "regulatory"])
        slugs = [m["slug"] for m in result]
        assert slugs.count("dup-1") == 1

    def test_dedup_false_allows_duplicates(self):
        dup = _market("dup-1")
        data = {
            "crypto": [dup],
            "regulatory": [dup],
        }
        client = _make_client(data)
        result = scan_categories(client, categories=["crypto", "regulatory"], deduplicate=False)
        assert len(result) == 2

    def test_dedup_by_slug_when_no_id(self):
        """Markets identified by slug when id is absent."""
        m1 = {"slug": "shared-slug", "question": "Q"}
        m2 = {"slug": "shared-slug", "question": "Q"}
        data = {"crypto": [m1], "fed": [m2]}
        client = _make_client(data)
        result = scan_categories(client, categories=["crypto", "fed"])
        assert len(result) == 1

    def test_unique_markets_all_preserved(self):
        data = {
            "crypto": [_market(f"c{i}") for i in range(5)],
            "fed": [_market(f"f{i}") for i in range(5)],
        }
        client = _make_client(data)
        result = scan_categories(client, categories=["crypto", "fed"])
        assert len(result) == 10


class TestDefaultCategories:
    def test_defaults_to_all_categories(self):
        """When categories=None, all four standard categories are fetched."""
        data = {cat: [_market(f"{cat}-1")] for cat in ALL_CATEGORIES}
        client = _make_client(data)
        result = scan_categories(client)
        assert len(result) == 4

    def test_calls_client_once_per_category(self):
        client = _make_client()
        scan_categories(client, categories=["crypto", "fed"])
        # get_all_markets called once per category
        assert client.get_all_markets.call_count == 2


class TestErrorHandling:
    def test_failed_category_returns_empty_for_that_category(self):
        """If one category fetch throws, others still succeed."""
        client = MagicMock()

        def _get(category=None):
            if category == "crypto":
                raise RuntimeError("API error")
            return [_market(f"{category}-1")]

        client.get_all_markets.side_effect = _get

        result = scan_categories(client, categories=["crypto", "fed"])
        # fed market should still be present
        slugs = [m["slug"] for m in result]
        assert "fed-1" in slugs
        assert not any("crypto" in s for s in slugs)

    def test_all_categories_fail_returns_empty(self):
        client = MagicMock()
        client.get_all_markets.side_effect = RuntimeError("network down")
        result = scan_categories(client)
        assert result == []

    def test_partial_failure_preserves_order(self):
        """Successful categories maintain their relative order."""

        def _get(category=None):
            if category == "fed":
                raise RuntimeError("oops")
            return [_market(f"{category}-1")]

        client = MagicMock()
        client.get_all_markets.side_effect = _get

        result = scan_categories(client, categories=["crypto", "fed", "other"])
        slugs = [m["slug"] for m in result]
        assert "crypto-1" in slugs
        assert "other-1" in slugs


class TestOrdering:
    def test_crypto_markets_appear_before_fed(self):
        """Category order is preserved in the merged result."""
        data = {
            "crypto": [_market("crypto-1")],
            "fed": [_market("fed-1")],
        }
        client = _make_client(data)
        result = scan_categories(client, categories=["crypto", "fed"])
        assert result[0]["slug"] == "crypto-1"
        assert result[1]["slug"] == "fed-1"
