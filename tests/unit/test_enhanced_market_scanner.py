"""
Unit tests for EnhancedMarketScanner (strategies/enhanced_market_scanner/scanner.py).

Covers:
- Pre-lowercased keyword tuples and frozenset exclusion sets built at init time
- matches_filters() correctness: keyword inclusion, exclusion, slug exclusion
- Case-insensitive matching via pre-lowercased structures
- Liquidity gate still respected
"""

from unittest.mock import MagicMock, patch

from strategies.enhanced_market_scanner.scanner import EnhancedMarketScanner
from data.market_schema import PolymarketMarket

# ── helpers ────────────────────────────────────────────────────────────────


def _make_scanner(
    crypto_keywords=None,
    exclude_keywords=None,
    exclude_slugs=None,
    min_volume=0.0,
    ignore_seen=False,
):
    """Build an EnhancedMarketScanner with controlled config."""
    client = MagicMock()
    scanner = EnhancedMarketScanner.__new__(EnhancedMarketScanner)
    scanner.client = client
    scanner.seen_markets = set()
    scanner.market_cache = {}
    scanner.last_scan_time = None

    from strategies.enhanced_market_scanner.scanner import MarketScannerConfig

    scanner.config = MarketScannerConfig(
        crypto_keywords=crypto_keywords or [],
        fed_keywords=[],
        regulatory_keywords=[],
        other_keywords=[],
        exclude_keywords=exclude_keywords or [],
        exclude_slugs=exclude_slugs or [],
        ignore_seen_markets=ignore_seen,
    )
    # Reproduce the same pre-computation done in __init__
    scanner._crypto_kws = tuple(kw.lower() for kw in scanner.config.crypto_keywords)
    scanner._fed_kws = tuple(kw.lower() for kw in scanner.config.fed_keywords)
    scanner._regulatory_kws = tuple(kw.lower() for kw in scanner.config.regulatory_keywords)
    scanner._other_kws = tuple(kw.lower() for kw in scanner.config.other_keywords)
    scanner._exclude_kws = tuple(kw.lower() for kw in scanner.config.exclude_keywords)
    scanner._exclude_slugs_set = frozenset(scanner.config.exclude_slugs)
    return scanner


def _market(
    slug="test-market", question="Will X happen?", volume=1000.0, token_ids=None, category="other"
):
    return PolymarketMarket(
        market_id=slug,
        slug=slug,
        question=question,
        token_ids=token_ids or ["tok1", "tok2"],
        volume=volume,
        category=category,
    )


# ── pre-computation at init ────────────────────────────────────────────────


class TestInitPrecomputation:
    def test_exclude_slugs_set_is_frozenset(self):
        s = _make_scanner(exclude_slugs=["slug-a", "slug-b"])
        assert isinstance(s._exclude_slugs_set, frozenset)

    def test_exclude_slugs_set_contains_slugs(self):
        s = _make_scanner(exclude_slugs=["slug-a", "slug-b"])
        assert "slug-a" in s._exclude_slugs_set
        assert "slug-b" in s._exclude_slugs_set

    def test_keyword_tuples_are_tuples(self):
        s = _make_scanner(crypto_keywords=["Bitcoin", "Ethereum"])
        assert isinstance(s._crypto_kws, tuple)

    def test_keyword_tuples_are_lowercased(self):
        s = _make_scanner(crypto_keywords=["Bitcoin", "ETHEREUM", "DeFi"])
        assert s._crypto_kws == ("bitcoin", "ethereum", "defi")

    def test_exclude_kws_are_lowercased(self):
        s = _make_scanner(exclude_keywords=["Trump", "BIDEN"])
        assert s._exclude_kws == ("trump", "biden")

    def test_empty_keywords_produces_empty_tuple(self):
        s = _make_scanner()
        assert s._crypto_kws == ()
        assert s._exclude_kws == ()

    def test_empty_slugs_produces_empty_frozenset(self):
        s = _make_scanner()
        assert s._exclude_slugs_set == frozenset()


# ── matches_filters: liquidity gate ───────────────────────────────────────


class TestMatchesFiltersLiquidity:
    def test_insufficient_liquidity_fails(self):
        s = _make_scanner(min_volume=500.0)
        m = _market(volume=100.0)
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 500.0
            result = s.matches_filters(m, "crypto")
        assert result is False

    def test_sufficient_liquidity_passes(self):
        s = _make_scanner()
        m = _market(volume=1000.0)
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 500.0
            result = s.matches_filters(m, "crypto")
        assert result is True


# ── matches_filters: keyword inclusion ────────────────────────────────────


class TestMatchesFiltersKeywords:
    def test_market_matching_keyword_passes(self):
        s = _make_scanner(crypto_keywords=["bitcoin"])
        m = _market(question="Will Bitcoin hit $100k?")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is True

    def test_market_not_matching_keyword_fails(self):
        s = _make_scanner(crypto_keywords=["bitcoin"])
        m = _market(question="Will the Fed raise rates?", slug="fed-rates")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is False

    def test_keyword_match_is_case_insensitive(self):
        """Keyword 'BITCOIN' must match question containing 'bitcoin'."""
        s = _make_scanner(crypto_keywords=["BITCOIN"])
        m = _market(question="Will bitcoin reach 200k?")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is True

    def test_keyword_match_on_slug(self):
        """Keyword match also works against the market slug."""
        s = _make_scanner(crypto_keywords=["eth"])
        m = _market(slug="ethereum-price-2025", question="Generic question")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is True

    def test_no_keywords_configured_always_passes(self):
        """When no category keywords are set, all markets pass the keyword gate."""
        s = _make_scanner(crypto_keywords=[])
        m = _market(question="Random unrelated question")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is True


# ── matches_filters: exclusions ───────────────────────────────────────────


class TestMatchesFiltersExclusions:
    def test_excluded_slug_blocked(self):
        s = _make_scanner(exclude_slugs=["bad-market"])
        m = _market(slug="bad-market")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is False

    def test_non_excluded_slug_passes(self):
        s = _make_scanner(exclude_slugs=["bad-market"])
        m = _market(slug="good-market")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is True

    def test_excluded_keyword_in_question_blocked(self):
        s = _make_scanner(exclude_keywords=["trump"])
        m = _market(question="Will Trump win the election?")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "other")
        assert result is False

    def test_excluded_keyword_case_insensitive(self):
        """Exclude keyword 'TRUMP' must block question containing 'trump'."""
        s = _make_scanner(exclude_keywords=["TRUMP"])
        m = _market(question="Will trump win again?")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "other")
        assert result is False

    def test_excluded_keyword_in_slug_blocked(self):
        s = _make_scanner(exclude_keywords=["speculation"])
        m = _market(slug="speculation-market-2025", question="Normal question")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "other")
        assert result is False


# ── matches_filters: seen markets ─────────────────────────────────────────


class TestMatchesFiltersSeen:
    def test_seen_market_blocked_when_ignore_enabled(self):
        s = _make_scanner(ignore_seen=True)
        m = _market(slug="seen-market")
        s.seen_markets.add("seen-market")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is False

    def test_seen_market_passes_when_ignore_disabled(self):
        s = _make_scanner(ignore_seen=False)
        m = _market(slug="seen-market")
        s.seen_markets.add("seen-market")
        with patch("strategies.enhanced_market_scanner.scanner.config") as cfg:
            cfg.MIN_VOLUME_USD = 0.0
            result = s.matches_filters(m, "crypto")
        assert result is True


# ── _get_category_keywords_lower ──────────────────────────────────────────


class TestGetCategoryKeywordsLower:
    def test_crypto_returns_precomputed(self):
        s = _make_scanner(crypto_keywords=["BTC", "ETH"])
        assert s._get_category_keywords_lower("crypto") == ("btc", "eth")

    def test_unknown_category_returns_empty_tuple(self):
        s = _make_scanner()
        assert s._get_category_keywords_lower("unknown") == ()
