from fx_scanner.demo_fresh_ready_handoff import (
    DEMO_STACKING_ENV,
    DEMO_STACK_MAX_POSITIONS_ENV,
    DEMO_STACK_MIN_COVERAGE_ENV,
    DEMO_STACK_MIN_SCORE_ENV,
    DEMO_STACK_MIN_SPACING_ENV,
    load_demo_execution_policy,
)


def test_active_demo_profile_accepts_four_independent_same_symbol_setups(monkeypatch):
    monkeypatch.setenv(DEMO_STACKING_ENV, "1")
    monkeypatch.setenv(DEMO_STACK_MIN_SCORE_ENV, "50.01")
    monkeypatch.setenv(DEMO_STACK_MIN_COVERAGE_ENV, "0.80")
    monkeypatch.setenv(DEMO_STACK_MAX_POSITIONS_ENV, "4")
    monkeypatch.setenv(DEMO_STACK_MIN_SPACING_ENV, "0")

    policy = load_demo_execution_policy()

    assert policy.demo_safety["allow_same_symbol_stacking"] is True
    assert policy.demo_safety["stack_min_score"] == 50.01
    assert policy.demo_safety["stack_min_coverage"] == 0.80
    assert policy.demo_safety["max_same_symbol_positions"] == 4
    assert policy.demo_safety["min_stack_spacing_seconds"] == 0.0
    assert policy.demo_safety["max_concurrent_positions"] <= 10
    assert policy.demo_safety["max_order_lots"] <= 0.50
