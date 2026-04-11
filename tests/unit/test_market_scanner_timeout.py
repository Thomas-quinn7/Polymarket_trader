"""
Tests for data/market_scanner.py

Covers:
- scan_categories merges results from all category threads
- Deduplication removes markets appearing in multiple categories
- A category that raises is returned as an empty list (no crash)
- Thread join timeout: a thread that hangs is detected and a warning is logged
- deduplicate=False returns all markets including duplicates
"""

import threading
import time
import logging
import pytest
from unittest.mock import MagicMock, patch

from data.market_scanner import scan_categories, ALL_CATEGORIES


def _client_returning(category_map: dict):
    """Build a mock client whose get_all_markets returns per-category lists."""
    client = MagicMock()

    def _get(category=None):
        return list(category_map.get(category, []))

    client.get_all_markets.side_effect = _get
    return client


# ── basic merging ──────────────────────────────────────────────────────────


class TestMerge:
    def test_results_from_all_categories_merged(self):
        client = _client_returning(
            {
                "crypto": [{"id": "c1"}, {"id": "c2"}],
                "fed": [{"id": "f1"}],
                "regulatory": [],
                "other": [{"id": "o1"}],
            }
        )
        result = scan_categories(client)
        ids = {m["id"] for m in result}
        assert ids == {"c1", "c2", "f1", "o1"}

    def test_subset_of_categories(self):
        client = _client_returning(
            {
                "crypto": [{"id": "c1"}],
                "fed": [{"id": "f1"}],
            }
        )
        result = scan_categories(client, categories=["crypto", "fed"])
        assert len(result) == 2

    def test_empty_categories_returns_empty(self):
        client = _client_returning({})
        result = scan_categories(client, categories=[])
        assert result == []


# ── deduplication ──────────────────────────────────────────────────────────


class TestDeduplication:
    def test_duplicate_id_removed(self):
        market = {"id": "shared-mkt"}
        client = _client_returning(
            {
                "crypto": [market],
                "fed": [market],
            }
        )
        result = scan_categories(client, categories=["crypto", "fed"])
        assert len(result) == 1

    def test_duplicate_slug_removed(self):
        market = {"slug": "same-slug"}
        client = _client_returning(
            {
                "crypto": [market],
                "other": [market],
            }
        )
        result = scan_categories(client, categories=["crypto", "other"])
        assert len(result) == 1

    def test_deduplicate_false_keeps_duplicates(self):
        market = {"id": "dup"}
        client = _client_returning(
            {
                "crypto": [market],
                "fed": [market],
            }
        )
        result = scan_categories(client, categories=["crypto", "fed"], deduplicate=False)
        assert len(result) == 2


# ── error resilience ───────────────────────────────────────────────────────


class TestErrorResilience:
    def test_failing_category_does_not_crash(self):
        client = MagicMock()
        client.get_all_markets.side_effect = RuntimeError("API error")
        result = scan_categories(client)  # must not raise
        assert result == []

    def test_one_failing_category_others_still_returned(self):
        call_count = {"n": 0}

        def _get(category=None):
            call_count["n"] += 1
            if category == "crypto":
                raise RuntimeError("crypto API down")
            return [{"id": f"{category}-1"}]

        client = MagicMock()
        client.get_all_markets.side_effect = _get
        result = scan_categories(client, categories=["crypto", "fed", "other"])
        ids = {m["id"] for m in result}
        assert "fed-1" in ids
        assert "other-1" in ids
        # crypto results absent — no crash
        assert not any(m["id"].startswith("crypto") for m in result)


# ── thread join timeout ────────────────────────────────────────────────────


class TestThreadTimeout:
    def test_slow_thread_logged_as_warning(self, caplog):
        """A thread that blocks past the 30 s join timeout should log a warning.

        We patch threading.Thread so that join() immediately returns without
        blocking, but is_alive() reports True — simulating a hung thread.
        """
        import data.market_scanner as scanner_mod

        real_thread_cls = threading.Thread

        class SlowThread(real_thread_cls):
            def join(self, timeout=None):
                # Return immediately (don't actually wait) but pretend still alive
                pass

            def is_alive(self):
                return True  # pretend we're still running

        client = _client_returning({"crypto": [{"id": "c1"}]})

        with patch.object(scanner_mod.threading, "Thread", SlowThread):
            with caplog.at_level(logging.WARNING):
                scan_categories(client, categories=["crypto"])

        assert any("did not finish" in r.message or "30s" in r.message for r in caplog.records)
