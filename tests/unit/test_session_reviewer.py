"""
Unit tests for SessionReviewer (utils/session_reviewer.py).

Covers:
- _fmt_hold: None → "n/a", zero, minutes-only, hours+minutes, large values
- _fmt_trade_log: empty list, single trade, truncates long slugs, handles None fields
- _REVIEW_SAFE_TRADE_FIELDS whitelist: known-safe fields present, known-sensitive absent
- generate_review sanitises trades before building the prompt (no token IDs, no UUIDs)
- generate_review returns None when Ollama is unreachable
- generate_review returns None when _ensure_model fails
- generate_review returns None when /api/generate raises
- generate_review returns review text on success
- _ensure_model returns True when model already present
- _ensure_model pulls model when missing and returns True
- _ensure_model returns False on network error
- host trailing slash stripped in __init__
"""

from unittest.mock import MagicMock, patch
import requests

from utils.session_reviewer import (
    SessionReviewer,
    _fmt_hold,
    _fmt_trade_log,
    _REVIEW_SAFE_TRADE_FIELDS,
)

# ── _fmt_hold ──────────────────────────────────────────────────────────────


class TestFmtHold:
    def test_none_returns_na(self):
        assert _fmt_hold(None) == "n/a"

    def test_zero_seconds(self):
        assert _fmt_hold(0) == "0m"

    def test_minutes_only(self):
        assert _fmt_hold(90) == "1m"

    def test_exact_one_hour(self):
        assert _fmt_hold(3600) == "1h00m"

    def test_hours_and_minutes(self):
        assert _fmt_hold(3661) == "1h01m"

    def test_large_value(self):
        # 25 h 30 m
        assert _fmt_hold(25 * 3600 + 30 * 60) == "25h30m"

    def test_fractional_seconds_truncated(self):
        # 90.9 s → 1 minute
        assert _fmt_hold(90.9) == "1m"


# ── _fmt_trade_log ─────────────────────────────────────────────────────────


class TestFmtTradeLog:
    def test_empty_list_returns_placeholder(self):
        result = _fmt_trade_log([])
        assert "no settled trades" in result

    def test_single_trade_has_header_and_row(self):
        trades = [
            {
                "market_slug": "will-btc-hit-100k",
                "entry_price": 0.985,
                "exit_price": 1.0,
                "hold_seconds": 1800,
                "edge_pct": 1.5,
                "net_pnl": 14.70,
                "outcome": "WIN",
            }
        ]
        result = _fmt_trade_log(trades)
        lines = result.splitlines()
        assert len(lines) == 2  # header + one data row
        assert "WIN" in lines[1]
        assert "0.985" in lines[1]

    def test_slug_truncated_to_22_chars(self):
        long_slug = "a" * 40
        trades = [
            {
                "market_slug": long_slug,
                "entry_price": 0.9,
                "exit_price": 1.0,
                "hold_seconds": 60,
                "edge_pct": 1.0,
                "net_pnl": 5.0,
                "outcome": "WIN",
            }
        ]
        result = _fmt_trade_log(trades)
        # The slug column is padded to exactly 22 chars
        row = result.splitlines()[1]
        assert "a" * 23 not in row  # never more than 22 a's in sequence

    def test_none_exit_price_renders_na(self):
        trades = [
            {
                "market_slug": "test",
                "entry_price": 0.9,
                "exit_price": None,
                "hold_seconds": 60,
                "edge_pct": 1.0,
                "net_pnl": None,
                "outcome": "UNKNOWN",
            }
        ]
        result = _fmt_trade_log(trades)
        assert "n/a" in result

    def test_multiple_rows_numbered(self):
        trade = {
            "market_slug": "mkt",
            "entry_price": 0.9,
            "exit_price": 1.0,
            "hold_seconds": 60,
            "edge_pct": 1.0,
            "net_pnl": 5.0,
            "outcome": "WIN",
        }
        result = _fmt_trade_log([trade, trade, trade])
        lines = result.splitlines()
        assert len(lines) == 4  # header + 3 rows
        assert lines[1].startswith("1  ")
        assert lines[2].startswith("2  ")
        assert lines[3].startswith("3  ")


# ── _REVIEW_SAFE_TRADE_FIELDS whitelist ────────────────────────────────────


class TestReviewSafeFields:
    _EXPECTED_SAFE = {
        "market_slug",
        "question",
        "entry_time",
        "exit_time",
        "hold_seconds",
        "entry_price",
        "exit_price",
        "edge_pct",
        "gross_pnl",
        "net_pnl",
        "outcome",
        "exit_reason",
    }

    _EXPECTED_EXCLUDED = {
        "winning_token_id",
        "position_id",
        "trade_id",
        "session_id",
        "market_id",
        "shares",
        "allocated_capital",
        "entry_fee",
        "exit_fee",
        "balance_after",
        "strategy_name",
    }

    def test_safe_fields_present(self):
        for field in self._EXPECTED_SAFE:
            assert field in _REVIEW_SAFE_TRADE_FIELDS, f"{field!r} missing from whitelist"

    def test_sensitive_fields_absent(self):
        for field in self._EXPECTED_EXCLUDED:
            assert (
                field not in _REVIEW_SAFE_TRADE_FIELDS
            ), f"{field!r} should NOT be in the whitelist — it is sensitive or non-useful"


# ── helpers ────────────────────────────────────────────────────────────────


def _make_session_data(*, trades=None):
    """Minimal session_data dict as produced by SessionStore.close_session()."""
    if trades is None:
        trades = [
            {
                "trade_id": "abc_pos-1",
                "session_id": "session-uuid-1234",
                "position_id": "pos-uuid-xyz",
                "market_id": "0x" + "b" * 62,
                "winning_token_id": "0x" + "f" * 62,
                "market_slug": "will-btc-hit-100k",
                "question": "Will BTC hit $100k by end of 2026?",
                "entry_time": "2026-04-11T10:00:00",
                "exit_time": "2026-04-11T10:30:00",
                "hold_seconds": 1800.0,
                "entry_price": 0.985,
                "exit_price": 1.0,
                "edge_pct": 1.5,
                "shares": 101.5,
                "allocated_capital": 100.0,
                "entry_fee": 2.0,
                "exit_fee": 0.0,
                "gross_pnl": 14.70,
                "net_pnl": 14.70,
                "balance_after": 10_014.70,
                "outcome": "WIN",
                "exit_reason": "settlement",
                "strategy_name": "settlement_arbitrage",
            }
        ]
    return {
        "session": {
            "session_id": "session-uuid-1234",
            "strategy": "settlement_arbitrage",
            "start_time": "2026-04-11T10:00:00",
            "end_time": "2026-04-11T11:00:00",
            "trading_mode": "paper",
            "starting_balance": 10_000.0,
            "ending_balance": 10_014.70,
        },
        "stats": {
            "total_trades": 1,
            "winning_trades": 1,
            "losing_trades": 0,
            "break_even_trades": 0,
            "win_rate": 1.0,
            "total_gross_pnl": 14.70,
            "total_net_pnl": 14.70,
            "total_fees": 2.0,
            "avg_hold_seconds": 1800.0,
            "avg_edge_pct": 1.5,
            "avg_entry_price": 0.985,
            "best_trade_pnl": 14.70,
            "worst_trade_pnl": 14.70,
            "profit_factor": None,
        },
        "trades": trades,
        "equity_curve": [],
    }


def _make_reviewer(host="http://localhost:11434", model="llama3.2:3b"):
    return SessionReviewer(host=host, model=model)


# ── SessionReviewer.__init__ ───────────────────────────────────────────────


class TestInit:
    def test_strips_trailing_slash(self):
        r = _make_reviewer(host="http://localhost:11434/")
        assert r._host == "http://localhost:11434"

    def test_stores_model(self):
        r = _make_reviewer(model="llama3.2:3b")
        assert r._model == "llama3.2:3b"


# ── _ensure_model ──────────────────────────────────────────────────────────


class TestEnsureModel:
    def test_returns_true_when_model_present(self):
        r = _make_reviewer()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
        with patch("utils.session_reviewer.requests.get", return_value=mock_resp):
            assert r._ensure_model() is True

    def test_matches_by_base_name(self):
        """'llama3.2' should match 'llama3.2:3b' in the available list."""
        r = _make_reviewer(model="llama3.2:3b")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": [{"name": "llama3.2:latest"}]}
        with patch("utils.session_reviewer.requests.get", return_value=mock_resp):
            assert r._ensure_model() is True

    def test_pulls_when_model_missing(self):
        r = _make_reviewer()
        tags_resp = MagicMock()
        tags_resp.json.return_value = {"models": []}
        pull_resp = MagicMock()
        with (
            patch("utils.session_reviewer.requests.get", return_value=tags_resp),
            patch("utils.session_reviewer.requests.post", return_value=pull_resp) as mock_post,
        ):
            result = r._ensure_model()
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "llama3.2:3b" in str(call_kwargs)

    def test_returns_false_on_connection_error(self):
        r = _make_reviewer()
        with patch(
            "utils.session_reviewer.requests.get",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            assert r._ensure_model() is False

    def test_returns_false_on_http_error(self):
        r = _make_reviewer()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("503")
        with patch("utils.session_reviewer.requests.get", return_value=mock_resp):
            assert r._ensure_model() is False


# ── generate_review ────────────────────────────────────────────────────────


class TestGenerateReview:
    def _patch_ensure_model(self, returns=True):
        return patch.object(SessionReviewer, "_ensure_model", return_value=returns)

    def test_returns_none_when_ensure_model_fails(self):
        r = _make_reviewer()
        with self._patch_ensure_model(returns=False):
            result = r.generate_review(_make_session_data())
        assert result is None

    def test_returns_review_text_on_success(self):
        r = _make_reviewer()
        gen_resp = MagicMock()
        gen_resp.json.return_value = {"response": "Strong session with 100% win rate."}
        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", return_value=gen_resp),
        ):
            result = r.generate_review(_make_session_data())
        assert result == "Strong session with 100% win rate."

    def test_strips_whitespace_from_response(self):
        r = _make_reviewer()
        gen_resp = MagicMock()
        gen_resp.json.return_value = {"response": "  Good session.  \n"}
        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", return_value=gen_resp),
        ):
            result = r.generate_review(_make_session_data())
        assert result == "Good session."

    def test_returns_none_on_generate_connection_error(self):
        r = _make_reviewer()
        with (
            self._patch_ensure_model(),
            patch(
                "utils.session_reviewer.requests.post",
                side_effect=requests.exceptions.ConnectionError("refused"),
            ),
        ):
            result = r.generate_review(_make_session_data())
        assert result is None

    def test_returns_none_on_generate_timeout(self):
        r = _make_reviewer()
        with (
            self._patch_ensure_model(),
            patch(
                "utils.session_reviewer.requests.post",
                side_effect=requests.exceptions.Timeout("timeout"),
            ),
        ):
            result = r.generate_review(_make_session_data())
        assert result is None

    def test_generate_called_with_correct_model_and_stream_false(self):
        r = _make_reviewer(model="llama3.2:3b")
        gen_resp = MagicMock()
        gen_resp.json.return_value = {"response": "ok"}
        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", return_value=gen_resp) as mock_post,
        ):
            r.generate_review(_make_session_data())
        _, kwargs = mock_post.call_args
        payload = kwargs.get("json") or mock_post.call_args[0][1]
        assert payload["model"] == "llama3.2:3b"
        assert payload["stream"] is False

    def test_prompt_contains_strategy_name(self):
        r = _make_reviewer()
        captured_prompt = []

        def capture(*args, **kwargs):
            captured_prompt.append(kwargs.get("json", {}).get("prompt", ""))
            m = MagicMock()
            m.json.return_value = {"response": "ok"}
            return m

        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", side_effect=capture),
        ):
            r.generate_review(_make_session_data())
        assert "settlement_arbitrage" in captured_prompt[0]

    def test_prompt_contains_win_rate(self):
        r = _make_reviewer()
        captured_prompt = []

        def capture(*args, **kwargs):
            captured_prompt.append(kwargs.get("json", {}).get("prompt", ""))
            m = MagicMock()
            m.json.return_value = {"response": "ok"}
            return m

        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", side_effect=capture),
        ):
            r.generate_review(_make_session_data())
        assert "100%" in captured_prompt[0]

    # ── Privacy: sanitisation of trade fields ─────────────────────────────

    def test_token_id_not_in_prompt(self):
        """winning_token_id must never appear in the text sent to the model."""
        r = _make_reviewer()
        token_id = "0x" + "f" * 62
        data = _make_session_data()  # trade has winning_token_id = token_id
        captured_prompt = []

        def capture(*args, **kwargs):
            captured_prompt.append(kwargs.get("json", {}).get("prompt", ""))
            m = MagicMock()
            m.json.return_value = {"response": "ok"}
            return m

        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", side_effect=capture),
        ):
            r.generate_review(data)
        assert token_id not in captured_prompt[0]

    def test_position_id_not_in_prompt(self):
        r = _make_reviewer()
        data = _make_session_data()
        captured_prompt = []

        def capture(*args, **kwargs):
            captured_prompt.append(kwargs.get("json", {}).get("prompt", ""))
            m = MagicMock()
            m.json.return_value = {"response": "ok"}
            return m

        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", side_effect=capture),
        ):
            r.generate_review(data)
        assert "pos-uuid-xyz" not in captured_prompt[0]

    def test_market_slug_in_prompt(self):
        """Safe fields must still reach the prompt after sanitisation."""
        r = _make_reviewer()
        captured_prompt = []

        def capture(*args, **kwargs):
            captured_prompt.append(kwargs.get("json", {}).get("prompt", ""))
            m = MagicMock()
            m.json.return_value = {"response": "ok"}
            return m

        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", side_effect=capture),
        ):
            r.generate_review(_make_session_data())
        assert "will-btc-hit-100k" in captured_prompt[0]

    def test_works_with_empty_trades(self):
        """generate_review must not crash when the session has no trades."""
        r = _make_reviewer()
        data = _make_session_data(trades=[])
        gen_resp = MagicMock()
        gen_resp.json.return_value = {"response": "No trades this session."}
        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", return_value=gen_resp),
        ):
            result = r.generate_review(data)
        assert result == "No trades this session."

    def test_works_with_missing_optional_stats(self):
        """generate_review must handle None profit_factor and avg_edge gracefully."""
        r = _make_reviewer()
        data = _make_session_data()
        data["stats"]["profit_factor"] = None
        data["stats"]["avg_edge_pct"] = None
        data["stats"]["best_trade_pnl"] = None
        data["stats"]["worst_trade_pnl"] = None
        gen_resp = MagicMock()
        gen_resp.json.return_value = {"response": "ok"}
        with (
            self._patch_ensure_model(),
            patch("utils.session_reviewer.requests.post", return_value=gen_resp),
        ):
            result = r.generate_review(data)
        assert result == "ok"
