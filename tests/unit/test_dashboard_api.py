"""
Unit tests for dashboard/api.py — FastAPI endpoints.
Tests run against the FastAPI app via httpx's AsyncClient (no real server needed).
"""

import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from datetime import datetime

from fastapi.testclient import TestClient

from dashboard.api import app, set_bot_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pnl_summary(**kwargs):
    defaults = dict(
        total_trades=0, wins=0, losses=0, total_pnl=0.0, win_rate=0.0,
        average_win=0.0, average_loss=0.0, profit_factor=0.0,
        max_drawdown=0.0, current_drawdown=0.0,
        peak_balance=10_000.0, initial_balance=10_000.0,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_bot(running=False, mode="paper"):
    bot = MagicMock()
    bot.running = running
    bot.start_time = datetime.now()

    # currency tracker
    bot.currency_tracker.get_balance.return_value = 10_000.0
    bot.currency_tracker.get_deployed.return_value = 0.0
    bot.currency_tracker.get_available.return_value = 10_000.0
    bot.currency_tracker.starting_balance = 10_000.0

    # pnl tracker
    bot.pnl_tracker.get_summary.return_value = _make_pnl_summary()

    # position tracker
    bot.position_tracker.get_position_count.return_value = 0
    bot.position_tracker.get_open_positions.return_value = []
    bot.position_tracker.get_settled_positions.return_value = []
    bot.position_tracker.get_all_positions.return_value = []

    # order executor
    bot.executor.get_order_history.return_value = []

    # loop controls
    bot.start_trading_loop.return_value = True
    bot.stop_trading_loop.return_value = True

    return bot


@pytest.fixture
def client_no_bot():
    """Test client with no bot registered."""
    set_bot_instance(None)
    return TestClient(app)


@pytest.fixture
def client_with_bot():
    """Test client with a mock bot registered."""
    bot = _make_bot()
    set_bot_instance(bot)
    yield TestClient(app), bot
    set_bot_instance(None)


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok_no_bot(self, client_no_bot):
        resp = client_no_bot.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["bot_running"] is False

    def test_health_ok_with_bot(self, client_with_bot):
        client, bot = client_with_bot
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["bot_running"] is False


# ---------------------------------------------------------------------------
# /api/status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_503_when_no_bot(self, client_no_bot):
        resp = client_no_bot.get("/api/status")
        assert resp.status_code == 503

    def test_status_200_with_bot(self, client_with_bot):
        client, bot = client_with_bot
        resp = client.get("/api/status")
        assert resp.status_code == 200

    def test_status_fields(self, client_with_bot):
        client, bot = client_with_bot
        data = client.get("/api/status").json()
        for field in ("running", "mode", "open_positions", "max_positions",
                      "balance", "deployed", "total_pnl", "win_rate",
                      "uptime", "last_update"):
            assert field in data, f"Missing field: {field}"

    def test_status_running_false(self, client_with_bot):
        client, bot = client_with_bot
        assert client.get("/api/status").json()["running"] is False

    def test_status_running_true(self):
        bot = _make_bot(running=True)
        set_bot_instance(bot)
        c = TestClient(app)
        assert c.get("/api/status").json()["running"] is True
        set_bot_instance(None)


# ---------------------------------------------------------------------------
# /api/portfolio
# ---------------------------------------------------------------------------

class TestPortfolio:
    def test_portfolio_503_no_bot(self, client_no_bot):
        assert client_no_bot.get("/api/portfolio").status_code == 503

    def test_portfolio_fields(self, client_with_bot):
        client, _ = client_with_bot
        data = client.get("/api/portfolio").json()
        for field in ("balance", "deployed", "available", "starting_balance"):
            assert field in data

    def test_portfolio_values(self, client_with_bot):
        client, _ = client_with_bot
        data = client.get("/api/portfolio").json()
        assert data["balance"] == 10_000.0
        assert data["deployed"] == 0.0


# ---------------------------------------------------------------------------
# /api/pnl
# ---------------------------------------------------------------------------

class TestPnL:
    def test_pnl_503_no_bot(self, client_no_bot):
        assert client_no_bot.get("/api/pnl").status_code == 503

    def test_pnl_200_with_bot(self, client_with_bot):
        client, _ = client_with_bot
        assert client.get("/api/pnl").status_code == 200

    def test_pnl_fields(self, client_with_bot):
        client, _ = client_with_bot
        data = client.get("/api/pnl").json()
        for field in ("total_trades", "wins", "losses", "total_pnl", "win_rate",
                      "average_win", "average_loss", "profit_factor",
                      "max_drawdown", "current_drawdown",
                      "peak_balance", "initial_balance"):
            assert field in data


# ---------------------------------------------------------------------------
# /api/positions
# ---------------------------------------------------------------------------

class TestPositions:
    def test_positions_503_no_bot(self, client_no_bot):
        assert client_no_bot.get("/api/positions").status_code == 503

    def test_positions_empty(self, client_with_bot):
        client, _ = client_with_bot
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_positions_with_open_position(self, client_with_bot):
        client, bot = client_with_bot
        pos = SimpleNamespace(
            position_id="p1", market_id="mkt-1", market_slug="slug-1",
            question="Will X?", shares=100.0, entry_price=0.985,
            allocated_capital=2000.0, expected_profit=30.0, edge_percent=1.5,
            status="OPEN",
            opened_at=datetime(2026,1,1,12,0,0),
            settled_at=None, settlement_price=None, realized_pnl=None,
        )
        bot.position_tracker.get_all_positions.return_value = [pos]
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["position_id"] == "p1"

    def test_positions_status_filter_open(self, client_with_bot):
        client, bot = client_with_bot
        client.get("/api/positions?status=open")
        bot.position_tracker.get_open_positions.assert_called()

    def test_positions_status_filter_settled(self, client_with_bot):
        client, bot = client_with_bot
        client.get("/api/positions?status=settled")
        bot.position_tracker.get_settled_positions.assert_called()


# ---------------------------------------------------------------------------
# /api/trades
# ---------------------------------------------------------------------------

class TestTrades:
    def test_trades_503_no_bot(self, client_no_bot):
        assert client_no_bot.get("/api/trades").status_code == 503

    def test_trades_empty(self, client_with_bot):
        client, _ = client_with_bot
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_trades_with_order(self, client_with_bot):
        client, bot = client_with_bot
        order = {
            "order_id": "p1_BUY", "position_id": "p1", "action": "BUY",
            "market_id": "mkt-1", "market_slug": "slug-1", "token_id": "tok",
            "quantity": 100.0, "price": 0.985, "total": 2000.0,
            "executed_at": datetime(2026,1,1,12,0,0),
            "status": "FILLED", "pnl": None,
        }
        bot.executor.get_order_history.return_value = [order]
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["action"] == "BUY"


# ---------------------------------------------------------------------------
# /api/config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_config_200(self, client_no_bot):
        resp = client_no_bot.get("/api/config")
        assert resp.status_code == 200

    def test_config_fields(self, client_no_bot):
        data = client_no_bot.get("/api/config").json()
        for field in ("max_positions", "capital_split_percent",
                      "scan_interval_ms", "fake_currency_balance"):
            assert field in data

    def test_config_no_arb_fields(self, client_no_bot):
        data = client_no_bot.get("/api/config").json()
        assert "min_price_threshold" not in data
        assert "max_price_threshold" not in data
        assert "execute_before_close_seconds" not in data


# ---------------------------------------------------------------------------
# /api/settings
# ---------------------------------------------------------------------------

class TestSettings:
    def test_settings_200(self, client_no_bot):
        assert client_no_bot.get("/api/settings").status_code == 200

    def test_settings_fields(self, client_no_bot):
        data = client_no_bot.get("/api/settings").json()
        for field in ("trading_mode", "scan_interval_ms", "max_positions",
                      "capital_split_percent", "min_confidence", "min_volume_usd",
                      "enable_email_alerts", "enable_discord_alerts", "log_level"):
            assert field in data, f"Missing field: {field}"

    def test_settings_no_arb_fields(self, client_no_bot):
        data = client_no_bot.get("/api/settings").json()
        assert "min_price_threshold" not in data
        assert "max_price_threshold" not in data
        assert "execute_before_close_seconds" not in data

    def test_settings_update_trading_mode(self, client_no_bot):
        resp = client_no_bot.post("/api/settings", json={"trading_mode": "simulation"})
        assert resp.status_code == 200
        assert "trading_mode" in resp.json()["updated"]

    def test_settings_update_invalid_mode(self, client_no_bot):
        resp = client_no_bot.post("/api/settings", json={"trading_mode": "live"})
        assert resp.status_code == 422

    def test_settings_update_partial(self, client_no_bot):
        resp = client_no_bot.post("/api/settings", json={"max_positions": 3})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/bot/start and /api/bot/stop
# ---------------------------------------------------------------------------

class TestBotControl:
    def test_start_503_no_bot(self, client_no_bot):
        assert client_no_bot.post("/api/bot/start").status_code == 503

    def test_stop_503_no_bot(self, client_no_bot):
        assert client_no_bot.post("/api/bot/stop").status_code == 503

    def test_start_success(self, client_with_bot):
        client, bot = client_with_bot
        bot.running = False
        resp = client.post("/api/bot/start")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_start_conflict_when_already_running(self, client_with_bot):
        client, bot = client_with_bot
        bot.running = True
        resp = client.post("/api/bot/start")
        assert resp.status_code == 409

    def test_stop_success(self, client_with_bot):
        client, bot = client_with_bot
        bot.running = True
        resp = client.post("/api/bot/stop")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_stop_conflict_when_not_running(self, client_with_bot):
        client, bot = client_with_bot
        bot.running = False
        resp = client.post("/api/bot/stop")
        assert resp.status_code == 409
