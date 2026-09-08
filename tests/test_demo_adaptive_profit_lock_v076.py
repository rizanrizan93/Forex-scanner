import pytest

from fx_scanner.demo_adaptive_profit_lock import evaluate_profit_lock


def test_long_stays_on_original_stop_below_half_r():
    decision = evaluate_profit_lock(
        side="BUY",
        entry_price=100.0,
        current_price=104.9,
        current_stop=90.0,
        original_stop=90.0,
    )
    assert decision.amend is False
    assert decision.reason == "BELOW_ACTIVATION"


def test_long_at_half_r_locks_small_positive_profit():
    decision = evaluate_profit_lock(
        side="BUY",
        entry_price=100.0,
        current_price=105.0,
        current_stop=90.0,
        original_stop=90.0,
    )
    assert decision.amend is True
    assert decision.lock_r == pytest.approx(0.05)
    assert decision.target_stop == pytest.approx(100.5)


def test_short_at_one_point_two_r_advances_stop_monotonically():
    decision = evaluate_profit_lock(
        side="SELL",
        entry_price=100.0,
        current_price=88.0,
        current_stop=110.0,
        original_stop=110.0,
    )
    assert decision.amend is True
    assert decision.lock_r == pytest.approx(0.55)
    assert decision.target_stop == pytest.approx(94.5)


def test_never_moves_an_existing_protected_stop_backward():
    decision = evaluate_profit_lock(
        side="BUY",
        entry_price=100.0,
        current_price=109.0,
        current_stop=103.0,
        original_stop=90.0,
    )
    assert decision.amend is False
    assert decision.reason == "NO_MONOTONIC_IMPROVEMENT"


def test_beyond_two_point_five_r_trails_three_quarters_r_behind_price():
    decision = evaluate_profit_lock(
        side="BUY",
        entry_price=100.0,
        current_price=130.0,
        current_stop=110.0,
        original_stop=90.0,
    )
    assert decision.amend is True
    assert decision.favorable_r == pytest.approx(3.0)
    assert decision.lock_r == pytest.approx(2.25)
    assert decision.target_stop == pytest.approx(122.5)


def test_invalid_original_risk_fails_closed():
    decision = evaluate_profit_lock(
        side="BUY",
        entry_price=100.0,
        current_price=110.0,
        current_stop=100.0,
        original_stop=101.0,
    )
    assert decision.amend is False
    assert decision.reason == "ORIGINAL_RISK_INVALID"
