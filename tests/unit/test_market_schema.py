"""
Unit tests for market_schema.py — PolymarketMarket, _classify_category, seconds_to_close.
"""

import pytest
from datetime import datetime, timezone, timedelta

from data.market_schema import PolymarketMarket, _classify_category


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw(
    market_id="mkt-001",
    slug="test-market",
    question="Will X happen?",
    token_ids=None,
    tags=None,
    volume=5000.0,
    end_date=None,
):
    d = {
        "id": market_id,
        "slug": slug,
        "question": question,
        "clobTokenIds": token_ids if token_ids is not None else ["tok_yes", "tok_no"],
        "tags": tags if tags is not None else [],
        "volume": volume,
    }
    if end_date is not None:
        d["endDate"] = end_date
    return d


def _future_date(seconds=300) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _past_date(seconds=300) -> str:
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# from_api — required fields
# ---------------------------------------------------------------------------

class TestFromApiRequired:
    def test_returns_none_when_no_market_id(self):
        # No id, conditionId, marketSlug, or slug — all fallbacks exhausted
        raw = {"clobTokenIds": ["t1"], "question": "Will X?"}
        assert PolymarketMarket.from_api(raw) is None

    def test_market_id_from_id_field(self):
        m = PolymarketMarket.from_api(_raw(market_id="abc-123"))
        assert m.market_id == "abc-123"

    def test_market_id_fallback_conditionId(self):
        raw = {"conditionId": "cond-99", "clobTokenIds": ["t1"]}
        m = PolymarketMarket.from_api(raw)
        assert m is not None
        assert m.market_id == "cond-99"

    def test_market_id_fallback_slug_when_no_id(self):
        raw = {"slug": "my-slug", "clobTokenIds": ["t1"]}
        m = PolymarketMarket.from_api(raw)
        assert m is not None
        assert m.market_id == "my-slug"

    def test_token_ids_populated(self):
        m = PolymarketMarket.from_api(_raw(token_ids=["yes", "no"]))
        assert m.token_ids == ["yes", "no"]

    def test_empty_token_ids_allowed(self):
        """Missing clobTokenIds → empty list, not None."""
        raw = {"id": "x", "slug": "s"}
        m = PolymarketMarket.from_api(raw)
        assert m is not None
        assert m.token_ids == []

    def test_non_list_token_ids_becomes_empty(self):
        raw = _raw()
        raw["clobTokenIds"] = "not-a-list"
        m = PolymarketMarket.from_api(raw)
        assert m.token_ids == []


# ---------------------------------------------------------------------------
# from_api — optional / alternative fields
# ---------------------------------------------------------------------------

class TestFromApiOptionalFields:
    def test_question_fallback_to_title(self):
        raw = {"id": "x", "title": "Is it true?", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.question == "Is it true?"

    def test_question_fallback_to_slug(self):
        raw = {"id": "x", "slug": "fallback-slug", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.question == "fallback-slug"

    def test_volume_from_volume_field(self):
        m = PolymarketMarket.from_api(_raw(volume=12345.67))
        assert m.volume == pytest.approx(12345.67)

    def test_volume_fallback_volumeNum(self):
        raw = {"id": "x", "volumeNum": 9999.0, "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.volume == pytest.approx(9999.0)

    def test_volume_fallback_volumeClob(self):
        raw = {"id": "x", "volumeClob": 4321.0, "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.volume == pytest.approx(4321.0)

    def test_volume_defaults_to_zero_when_missing(self):
        raw = {"id": "x", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.volume == 0.0

    def test_end_time_parsed_from_endDate(self):
        m = PolymarketMarket.from_api(_raw(end_date=_future_date(600)))
        assert m.end_time is not None
        assert m.end_time.tzinfo is not None

    def test_end_time_none_when_missing(self):
        m = PolymarketMarket.from_api(_raw())
        assert m.end_time is None

    def test_end_time_accepts_end_date_underscore(self):
        raw = _raw()
        raw["end_date"] = _future_date(60)
        m = PolymarketMarket.from_api(raw)
        assert m.end_time is not None

    def test_raw_preserved(self):
        raw = _raw()
        m = PolymarketMarket.from_api(raw)
        assert m._raw is raw


# ---------------------------------------------------------------------------
# _classify_category
# ---------------------------------------------------------------------------

class TestClassifyCategory:
    def test_dict_tag_crypto(self):
        assert _classify_category([{"label": "crypto"}]) == "crypto"

    def test_dict_tag_bitcoin_maps_to_crypto(self):
        assert _classify_category([{"label": "bitcoin"}]) == "crypto"

    def test_dict_tag_fomc_maps_to_fed(self):
        assert _classify_category([{"label": "fomc"}]) == "fed"

    def test_dict_tag_regulatory(self):
        assert _classify_category([{"label": "regulatory"}]) == "regulatory"

    def test_dict_tag_economic(self):
        assert _classify_category([{"label": "economic"}]) == "economic"

    def test_string_tag_crypto(self):
        assert _classify_category(["crypto"]) == "crypto"

    def test_string_tag_case_insensitive(self):
        assert _classify_category(["BITCOIN"]) == "crypto"

    def test_unknown_tag_returns_other(self):
        assert _classify_category([{"label": "sports"}]) == "other"

    def test_empty_tags_returns_other(self):
        assert _classify_category([]) == "other"

    def test_non_string_non_dict_tag_skipped(self):
        assert _classify_category([42, None, {"label": "fed"}]) == "fed"

    def test_first_matching_tag_wins(self):
        result = _classify_category([{"label": "crypto"}, {"label": "fed"}])
        assert result == "crypto"

    def test_dict_tag_uses_name_key(self):
        assert _classify_category([{"name": "ethereum"}]) == "crypto"


# ---------------------------------------------------------------------------
# seconds_to_close
# ---------------------------------------------------------------------------

class TestSecondsToClose:
    def test_returns_none_when_end_time_unknown(self):
        m = PolymarketMarket.from_api(_raw())
        assert m.seconds_to_close() is None

    def test_positive_for_future_market(self):
        m = PolymarketMarket.from_api(_raw(end_date=_future_date(300)))
        secs = m.seconds_to_close()
        assert secs is not None
        assert secs > 0.0

    def test_zero_for_past_market(self):
        m = PolymarketMarket.from_api(_raw(end_date=_past_date(300)))
        secs = m.seconds_to_close()
        assert secs == 0.0

    def test_close_to_expected_value(self):
        m = PolymarketMarket.from_api(_raw(end_date=_future_date(600)))
        secs = m.seconds_to_close()
        # Allow ±5 s for test execution time
        assert 595 <= secs <= 605


# ---------------------------------------------------------------------------
# has_sufficient_liquidity
# ---------------------------------------------------------------------------

class TestHasSufficientLiquidity:
    def test_passes_when_volume_equals_min(self):
        m = PolymarketMarket.from_api(_raw(volume=1000.0))
        assert m.has_sufficient_liquidity(1000.0) is True

    def test_passes_when_volume_above_min(self):
        m = PolymarketMarket.from_api(_raw(volume=5000.0))
        assert m.has_sufficient_liquidity(1000.0) is True

    def test_fails_when_volume_below_min(self):
        m = PolymarketMarket.from_api(_raw(volume=500.0))
        assert m.has_sufficient_liquidity(1000.0) is False

    def test_zero_volume_fails(self):
        raw = {"id": "x", "clobTokenIds": []}
        m = PolymarketMarket.from_api(raw)
        assert m.has_sufficient_liquidity(1.0) is False
