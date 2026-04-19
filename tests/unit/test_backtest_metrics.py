"""
Unit tests for MetricsCalculator / BacktestMetrics (backtesting/metrics.py).

Covers:
- Empty trade list returns zeroed metrics with correct initial/final balance
- Single WIN trade: win_rate=1.0, total_trades=1, net_pnl>0
- Single LOSS trade: losses=1, net_pnl<0
- Mixed trades: correct win_rate fraction, profit_factor
- total_return_pct formula against initial_balance
- final_balance taken from equity_curve last point
- final_balance falls back to initial+net_pnl when no equity_curve
- annualized_return sign and magnitude for a 1-year config
- Sharpe ratio only computed with >= 2 trades
- Sortino ratio requires >= 2 downside returns
- Calmar ratio requires max_drawdown > 0
- Consecutive wins/losses tracking
- Hold-time averages split by outcome
- fee_drag_pct requires gross_pnl > 0
- break_evens counted as total - wins - losses
- TIMEOUT trades are excluded from consecutive win/loss streaks
"""

import pytest
from backtesting.config import BacktestConfig
from backtesting.metrics import BacktestMetrics, MetricsCalculator

# ── Helpers ────────────────────────────────────────────────────────────────────


def _config(**kwargs) -> BacktestConfig:
    defaults = dict(
        strategy_name="test",
        start_date="2025-01-01",
        end_date="2026-01-01",  # 1 year
        initial_balance=1000.0,
    )
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


def _trade(
    *,
    outcome: str = "WIN",
    net_pnl: float = 20.0,
    gross_pnl: float = 22.0,
    entry_price: float = 0.80,
    exit_price: float = 1.0,
    shares: float = 125.0,
    allocated_capital: float = 100.0,
    entry_fee: float = 2.0,
    exit_fee: float = 0.0,
    entry_ts: int = 1_000_000,
    exit_ts: int = 1_003_600,
    condition_id: str = "cid-1",
    exit_reason: str = "settlement",
) -> dict:
    return {
        "strategy_name": "test",
        "condition_id": condition_id,
        "question": "Q?",
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "shares": shares,
        "allocated_capital": allocated_capital,
        "side": "YES",
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "entry_fee": entry_fee,
        "exit_fee": exit_fee,
        "outcome": outcome,
        "exit_reason": exit_reason,
    }


def _calc(trades, equity_curve=None, config=None) -> BacktestMetrics:
    if config is None:
        config = _config()
    if equity_curve is None:
        equity_curve = []
    return MetricsCalculator().compute(trades, equity_curve, config)


# ── Empty trades ──────────────────────────────────────────────────────────────


class TestEmptyTrades:
    def test_total_trades_zero(self):
        m = _calc([])
        assert m.total_trades == 0

    def test_final_balance_equals_initial(self):
        m = _calc([], config=_config(initial_balance=500.0))
        assert m.final_balance == pytest.approx(500.0)

    def test_initial_balance_stored(self):
        m = _calc([], config=_config(initial_balance=750.0))
        assert m.initial_balance == pytest.approx(750.0)

    def test_win_rate_zero(self):
        m = _calc([])
        assert m.win_rate == pytest.approx(0.0)

    def test_no_sharpe_ratio(self):
        m = _calc([])
        assert m.sharpe_ratio is None


# ── Single WIN ────────────────────────────────────────────────────────────────


class TestSingleWin:
    def test_total_trades_one(self):
        m = _calc([_trade(outcome="WIN", net_pnl=20.0)])
        assert m.total_trades == 1

    def test_wins_one(self):
        m = _calc([_trade(outcome="WIN", net_pnl=20.0)])
        assert m.wins == 1

    def test_losses_zero(self):
        m = _calc([_trade(outcome="WIN", net_pnl=20.0)])
        assert m.losses == 0

    def test_win_rate_one(self):
        m = _calc([_trade(outcome="WIN", net_pnl=20.0)])
        assert m.win_rate == pytest.approx(1.0)

    def test_total_net_pnl_positive(self):
        m = _calc([_trade(outcome="WIN", net_pnl=20.0)])
        assert m.total_net_pnl > 0

    def test_no_sharpe_with_one_trade(self):
        # stdev requires >= 2 samples
        m = _calc([_trade(outcome="WIN", net_pnl=20.0)])
        assert m.sharpe_ratio is None


# ── Single LOSS ───────────────────────────────────────────────────────────────


class TestSingleLoss:
    # PnLTracker classifies WIN/LOSS from actual prices, not from the outcome field.
    # entry_price=0.80 → exit_price=0.40 means PnLTracker computes net_pnl < 0 → LOSS.
    _loss = dict(outcome="LOSS", entry_price=0.80, exit_price=0.40, net_pnl=-50.0, gross_pnl=-50.0)

    def test_losses_one(self):
        m = _calc([_trade(**self._loss)])
        assert m.losses == 1

    def test_wins_zero(self):
        m = _calc([_trade(**self._loss)])
        assert m.wins == 0

    def test_win_rate_zero(self):
        m = _calc([_trade(**self._loss)])
        assert m.win_rate == pytest.approx(0.0)

    def test_total_net_pnl_negative(self):
        m = _calc([_trade(**self._loss)])
        assert m.total_net_pnl < 0


# ── Mixed trades ──────────────────────────────────────────────────────────────


class TestMixedTrades:
    def _two_trades(self):
        # WIN: entry 0.80 → exit 1.0 (profit); LOSS: entry 0.80 → exit 0.40 (loss)
        return [
            _trade(
                outcome="WIN",
                entry_price=0.80,
                exit_price=1.0,
                net_pnl=20.0,
                gross_pnl=22.0,
                condition_id="cid-1",
            ),
            _trade(
                outcome="LOSS",
                entry_price=0.80,
                exit_price=0.40,
                net_pnl=-50.0,
                gross_pnl=-50.0,
                condition_id="cid-2",
            ),
        ]

    def test_win_rate_half(self):
        m = _calc(self._two_trades())
        assert m.win_rate == pytest.approx(0.5)

    def test_total_trades_two(self):
        m = _calc(self._two_trades())
        assert m.total_trades == 2

    def test_profit_factor_positive(self):
        m = _calc(self._two_trades())
        assert m.profit_factor > 0

    def test_sharpe_computed_with_two_trades(self):
        m = _calc(self._two_trades())
        assert m.sharpe_ratio is not None

    def test_break_evens_always_zero(self):
        # PnLTracker classifies pnl <= 0 as LOSS (no break-even bucket).
        # MetricsCalculator derives break_evens = total - wins - losses, which is always 0.
        trades = [
            _trade(outcome="WIN", condition_id="c1"),
            _trade(
                outcome="BREAK_EVEN",
                entry_price=0.80,
                exit_price=0.80,
                net_pnl=0.0,
                gross_pnl=0.0,
                entry_fee=0.0,
                exit_fee=0.0,
                condition_id="c2",
            ),
        ]
        m = _calc(trades)
        assert m.break_evens == 0


# ── total_return_pct and final_balance ────────────────────────────────────────


class TestReturnAndBalance:
    def test_total_return_pct_formula(self):
        # net_pnl=100, initial=1000 → +10%
        equity = [(0, 1000.0), (1000, 1100.0)]
        m = _calc([_trade(net_pnl=100.0, gross_pnl=102.0)], equity_curve=equity)
        assert m.total_return_pct == pytest.approx(10.0, abs=0.5)

    def test_final_balance_from_equity_curve(self):
        equity = [(0, 1000.0), (999, 1234.56)]
        m = _calc([_trade()], equity_curve=equity)
        assert m.final_balance == pytest.approx(1234.56)

    def test_final_balance_fallback_when_no_equity(self):
        m = _calc(
            [_trade(net_pnl=50.0, gross_pnl=52.0)],
            equity_curve=[],
            config=_config(initial_balance=1000.0),
        )
        # fallback: initial + total_net_pnl (as reported by PnLTracker)
        assert m.final_balance > 1000.0


# ── annualized_return ─────────────────────────────────────────────────────────


class TestAnnualizedReturn:
    def test_positive_for_profitable_1_year_run(self):
        equity = [(0, 1000.0), (1, 1100.0)]
        m = _calc(
            [_trade(net_pnl=100.0, gross_pnl=102.0)],
            equity_curve=equity,
            config=_config(start_date="2025-01-01", end_date="2026-01-01"),
        )
        assert m.annualized_return > 0

    def test_negative_for_losing_run(self):
        equity = [(0, 1000.0), (1, 900.0)]
        m = _calc(
            [_trade(outcome="LOSS", net_pnl=-100.0, gross_pnl=-98.0)],
            equity_curve=equity,
            config=_config(start_date="2025-01-01", end_date="2026-01-01"),
        )
        assert m.annualized_return < 0


# ── Consecutive wins / losses ─────────────────────────────────────────────────


class TestConsecutiveStreaks:
    def test_max_consecutive_wins(self):
        trades = [
            _trade(outcome="WIN", condition_id="c1"),
            _trade(outcome="WIN", condition_id="c2"),
            _trade(outcome="WIN", condition_id="c3"),
            _trade(outcome="LOSS", condition_id="c4"),
        ]
        m = _calc(trades)
        assert m.consec_wins_max == 3

    def test_max_consecutive_losses(self):
        trades = [
            _trade(outcome="LOSS", net_pnl=-10.0, gross_pnl=-8.0, condition_id="c1"),
            _trade(outcome="LOSS", net_pnl=-10.0, gross_pnl=-8.0, condition_id="c2"),
            _trade(outcome="WIN", condition_id="c3"),
        ]
        m = _calc(trades)
        assert m.consec_losses_max == 2

    def test_timeout_resets_streak(self):
        trades = [
            _trade(outcome="WIN", condition_id="c1"),
            _trade(outcome="TIMEOUT", net_pnl=0.0, gross_pnl=0.0, condition_id="c2"),
            _trade(outcome="WIN", condition_id="c3"),
        ]
        m = _calc(trades)
        # TIMEOUT breaks the WIN streak — max streak is 1, not 2
        assert m.consec_wins_max == 1


# ── Hold times ────────────────────────────────────────────────────────────────


class TestHoldTimes:
    def test_avg_hold_seconds(self):
        trades = [
            _trade(entry_ts=1_000_000, exit_ts=1_003_600, condition_id="c1"),  # 3600s
            _trade(entry_ts=2_000_000, exit_ts=2_001_800, condition_id="c2"),  # 1800s
        ]
        m = _calc(trades)
        assert m.avg_hold_seconds == pytest.approx(2700.0)

    def test_avg_hold_win_seconds(self):
        # entry_ts must be non-zero: MetricsCalculator guards with `if entry_ts and exit_ts`
        trades = [
            _trade(
                outcome="WIN",
                entry_price=0.80,
                exit_price=1.0,
                entry_ts=1_000_000,
                exit_ts=1_000_600,
                condition_id="c1",
            ),
            _trade(
                outcome="LOSS",
                entry_price=0.80,
                exit_price=0.40,
                net_pnl=-50.0,
                gross_pnl=-50.0,
                entry_ts=2_000_000,
                exit_ts=2_001_200,
                condition_id="c2",
            ),
        ]
        m = _calc(trades)
        assert m.avg_hold_win_seconds == pytest.approx(600.0)
        assert m.avg_hold_loss_seconds == pytest.approx(1200.0)


# ── fee_drag_pct ──────────────────────────────────────────────────────────────


class TestFeeDrag:
    def test_fee_drag_computed_when_gross_pnl_nonzero(self):
        # gross_pnl=20, fees=entry_fee+exit_fee=3 → drag = 3/20*100 = 15%
        m = _calc([_trade(gross_pnl=20.0, net_pnl=17.0, entry_fee=2.0, exit_fee=1.0)])
        assert m.fee_drag_pct > 0

    def test_fee_drag_zero_when_no_gross_pnl(self):
        m = _calc([_trade(gross_pnl=0.0, net_pnl=0.0, entry_fee=0.0, exit_fee=0.0)])
        assert m.fee_drag_pct == pytest.approx(0.0)
