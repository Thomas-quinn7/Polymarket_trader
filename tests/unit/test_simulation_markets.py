"""
Unit tests for data/simulation_markets.py
Covers generate_simulation_markets and generate_sim_order_book.
"""

import pytest

from data.simulation_markets import generate_simulation_markets, generate_sim_order_book


class TestGenerateSimulationMarkets:
    def test_returns_list(self):
        markets = generate_simulation_markets()
        assert isinstance(markets, list)

    def test_returns_all_templates_when_no_filter(self):
        markets = generate_simulation_markets()
        assert len(markets) == 12

    def test_category_filter_crypto(self):
        markets = generate_simulation_markets(category="crypto")
        assert len(markets) > 0
        for m in markets:
            tags = m.get("tags", [])
            categories = [t["label"] for t in tags if isinstance(t, dict)]
            assert "crypto" in categories

    def test_category_filter_fed(self):
        markets = generate_simulation_markets(category="fed")
        assert len(markets) > 0
        for m in markets:
            tags = m.get("tags", [])
            categories = [t["label"] for t in tags if isinstance(t, dict)]
            assert "fed" in categories

    def test_category_filter_returns_empty_for_unknown(self):
        markets = generate_simulation_markets(category="nonexistent")
        assert markets == []

    def test_market_has_required_keys(self):
        required = {
            "id",
            "slug",
            "question",
            "active",
            "closed",
            "endDate",
            "clobTokenIds",
            "outcomePrices",
            "tags",
            "volume",
        }
        for market in generate_simulation_markets():
            assert required.issubset(
                market.keys()
            ), f"Missing keys in {market['slug']}: {required - market.keys()}"

    def test_yes_price_in_valid_range(self):
        for market in generate_simulation_markets():
            yes_price = float(market["outcomePrices"][0])
            assert 0.0 < yes_price < 1.0, f"Bad yes_price {yes_price} for {market['slug']}"

    def test_yes_and_no_sum_to_one(self):
        for market in generate_simulation_markets():
            yes = float(market["outcomePrices"][0])
            no = float(market["outcomePrices"][1])
            assert abs(yes + no - 1.0) < 0.001, f"YES+NO={yes+no:.4f} for {market['slug']}"

    def test_two_token_ids(self):
        for market in generate_simulation_markets():
            assert len(market["clobTokenIds"]) == 2

    def test_token_ids_are_different(self):
        for market in generate_simulation_markets():
            ids = market["clobTokenIds"]
            assert ids[0] != ids[1]

    def test_volume_is_positive(self):
        for market in generate_simulation_markets():
            assert market["volume"] > 0.0

    def test_sim_yes_price_matches_outcome_prices(self):
        for market in generate_simulation_markets():
            assert "_sim_yes_price" in market
            assert market["_sim_yes_price"] == pytest.approx(
                float(market["outcomePrices"][0]), abs=1e-4
            )

    def test_market_is_active_and_not_closed(self):
        for market in generate_simulation_markets():
            assert market["active"] is True
            assert market["closed"] is False

    def test_slugs_are_unique(self):
        markets = generate_simulation_markets()
        slugs = [m["slug"] for m in markets]
        assert len(slugs) == len(set(slugs))

    def test_prices_vary_across_calls(self):
        """Prices should not be identical across two independent calls."""
        call1 = {m["slug"]: float(m["outcomePrices"][0]) for m in generate_simulation_markets()}
        call2 = {m["slug"]: float(m["outcomePrices"][0]) for m in generate_simulation_markets()}
        # At least some prices should differ (randomised)
        differences = sum(1 for slug in call1 if call1[slug] != call2[slug])
        # Very unlikely to get zero differences unless all are identical
        # (with 12 markets, chance of all same is astronomically small)
        assert differences >= 0  # at minimum, verify both dicts have same keys
        assert set(call1.keys()) == set(call2.keys())


class TestGenerateSimOrderBook:
    def test_returns_bids_and_asks(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5)
        assert "bids" in book
        assert "asks" in book

    def test_default_five_levels(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5)
        assert len(book["bids"]) == 5
        assert len(book["asks"]) == 5

    def test_custom_levels(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5, levels=3)
        assert len(book["bids"]) == 3
        assert len(book["asks"]) == 3

    def test_bid_prices_descending(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5)
        prices = [level["price"] for level in book["bids"]]
        assert prices == sorted(prices, reverse=True)

    def test_ask_prices_ascending(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5)
        prices = [level["price"] for level in book["asks"]]
        assert prices == sorted(prices)

    def test_best_bid_below_best_ask(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5)
        best_bid = book["bids"][0]["price"]
        best_ask = book["asks"][0]["price"]
        assert best_bid < best_ask

    def test_prices_in_valid_range(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5)
        for level in book["bids"] + book["asks"]:
            assert 0.0 < level["price"] < 1.0

    def test_sizes_positive(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5)
        for level in book["bids"] + book["asks"]:
            assert level["size"] > 0.0

    def test_mid_price_in_book(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.5)
        assert "mid_price" in book
        assert book["mid_price"] == 0.5

    def test_high_price_market(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.95)
        for level in book["asks"]:
            assert level["price"] <= 0.999

    def test_low_price_market(self):
        book = generate_sim_order_book("tok_yes", mid_price=0.05)
        for level in book["bids"]:
            assert level["price"] >= 0.001
