"""Unit tests for _kelly_position_size (execution/order_executor.py).

Pins the no-signal floor semantics: Kelly's size must be increasing in
information. No probability signal -> minimum (default: refuse), never the
per-position cap. Also pins the confidence-fallback cap (a blended score is
not a win probability) and the degenerate-price refusals.
"""

import pytest

from execution.order_executor import _kelly_position_size

BAL = 1000.0
MAX_F = 0.20
KELLY_F = 0.25


def test_no_signal_refuses_by_default():
    # The old behavior bet balance * max_fraction here — the maximum stake on
    # zero information. It must now bet nothing.
    assert _kelly_position_size(BAL, 0.5, 0.0, MAX_F, KELLY_F) == 0.0


def test_no_signal_floor_is_a_floor_not_the_cap():
    size = _kelly_position_size(BAL, 0.5, 0.0, MAX_F, KELLY_F, no_signal_fraction=0.02)
    assert size == pytest.approx(BAL * 0.02)
    assert size < BAL * MAX_F


def test_no_signal_floor_cannot_exceed_cap():
    size = _kelly_position_size(BAL, 0.5, 0.0, MAX_F, KELLY_F, no_signal_fraction=0.50)
    assert size == pytest.approx(BAL * MAX_F)


def test_degenerate_price_refuses():
    for price in (0.0, -0.1, 1.0, 1.5, None):
        assert _kelly_position_size(BAL, price, 0.8, MAX_F, KELLY_F) == 0.0


def test_negative_model_prob_refuses_even_with_floor():
    # An explicit "this bet loses" must not stake even the no-signal floor.
    size = _kelly_position_size(
        BAL, 0.5, 0.9, MAX_F, KELLY_F, model_prob=0.0, no_signal_fraction=0.02
    )
    assert size == 0.0


def test_model_prob_takes_priority_over_confidence():
    with_model = _kelly_position_size(BAL, 0.5, 0.99, MAX_F, KELLY_F, model_prob=0.60)
    plain = _kelly_position_size(BAL, 0.5, 0.60, MAX_F, KELLY_F)
    assert with_model == pytest.approx(plain)


def test_confidence_fallback_is_capped():
    # confidence=1.0 is a score, not certainty; it must size as if p=0.95.
    at_one = _kelly_position_size(BAL, 0.5, 1.0, MAX_F, KELLY_F)
    at_cap = _kelly_position_size(BAL, 0.5, 0.95, MAX_F, KELLY_F)
    assert at_one == pytest.approx(at_cap)


def test_edge_sizes_positive_and_capped():
    # p=0.6 vs price 0.5: f* = (0.6*1 - 0.4)/1 = 0.2, quarter Kelly = 0.05.
    size = _kelly_position_size(BAL, 0.5, 0.6, MAX_F, KELLY_F)
    assert size == pytest.approx(BAL * 0.05)
    assert size <= BAL * MAX_F


def test_no_edge_sizes_zero():
    # p below the market price: Kelly is negative -> stake nothing.
    assert _kelly_position_size(BAL, 0.5, 0.4, MAX_F, KELLY_F) == 0.0
