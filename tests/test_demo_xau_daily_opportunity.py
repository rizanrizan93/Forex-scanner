from fx_scanner.demo_xau_daily_opportunity import _grade, _score


def test_daily_xau_opportunity_grade_never_implies_forced_execution():
    assert _grade("EXECUTION_READY", broker_authorized=True) == "EXECUTION_READY"
    assert _grade("EXECUTION_READY", broker_authorized=False) == "SHADOW_SETUP_READY"
    assert _grade("ARMED") == "VALID_SETUP_FORMING"
    assert _grade("SETUP_FORMING") == "VALID_SETUP_FORMING"
    assert _grade("WATCH") == "WATCH"
    assert _grade("NO_TRADE") == "NO_TRADE"


def test_daily_xau_opportunity_prefers_state_then_score_then_recency():
    watch_high = {"state": "WATCH", "final_score": 99, "observed_at": "2026-09-19T01:00:00+00:00"}
    ready_low = {"state": "EXECUTION_READY", "final_score": 70, "observed_at": "2026-09-19T00:00:00+00:00"}
    ready_high = {"state": "EXECUTION_READY", "final_score": 85, "observed_at": "2026-09-19T00:30:00+00:00"}
    assert max((watch_high, ready_low, ready_high), key=_score) is ready_high
