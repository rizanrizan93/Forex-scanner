from datetime import date, datetime, timezone

from fx_scanner.research_xau_v138_gold_driver_attribution_v139 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _driver_change,
)


def test_v139_is_directional_forensic_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_driver_change_uses_strictly_prior_observations():
    values = {
        date(2026, 1, d): float(d)
        for d in range(1, 32)
    }
    signal = date(2026, 1, 31)
    delta = _driver_change(values, signal, relative=False)
    # latest allowed = Jan 30; 20-observation prior = Jan 10
    assert delta == 20.0
