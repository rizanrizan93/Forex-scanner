from datetime import date, datetime, timedelta, timezone

from fx_scanner.research_xau_v138_driver_interaction_forensic_v139 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _driver_snapshot,
)


def _series(start, values):
    return {start + timedelta(days=i): float(v) for i, v in enumerate(values)}


def test_v139_is_diagnostic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_driver_states_use_sign_interactions_only():
    start = date(2026, 1, 1)
    n = 30
    rising = _series(start, range(100, 100 + n))
    falling = _series(start, range(200, 200 - n, -1))
    signal = datetime(2026, 1, 30, tzinfo=timezone.utc)
    snap = _driver_snapshot(
        {
            "real_yield_10y": rising,
            "usd_broad": rising,
            "vix": rising,
            "breakeven_10y": rising,
            "sp500": falling,
            "oil_wti": rising,
        },
        signal,
    )
    assert snap["opportunity_state"] == "HEADWIND"
    assert snap["risk_state"] == "RISK_OFF"
    assert snap["inflation_state"] == "INFLATION_UP"
