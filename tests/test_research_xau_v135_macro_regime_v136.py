from datetime import date, datetime, timedelta, timezone

from fx_scanner.research_xau_v135_macro_regime_v136 import (
    EXECUTION_INFLUENCE,
    LOOKBACK_OBSERVATIONS,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    _asof_change,
    macro_snapshot,
)

UTC = timezone.utc


def _series(start: date, values):
    return {start + timedelta(days=i): float(v) for i, v in enumerate(values)}


def test_v136_is_shadow_only_and_not_promotion_eligible():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_asof_change_never_uses_same_day_observation():
    start = date(2026, 1, 1)
    values = _series(start, range(1, 40))
    signal_date = start + timedelta(days=25)
    asof, delta = _asof_change(values, signal_date, relative=False)
    assert asof == signal_date - timedelta(days=1)
    assert delta == 20.0


def test_macro_state_uses_only_real_yield_and_usd_for_gate():
    start = date(2026, 1, 1)
    n = LOOKBACK_OBSERVATIONS + 5
    rising = _series(start, range(100, 100 + n))
    falling = _series(start, range(200, 200 - n, -1))
    signal_at = datetime.combine(start + timedelta(days=n), datetime.min.time(), tzinfo=UTC)

    hostile = macro_snapshot(
        {
            "real_yield_10y": rising,
            "usd_broad": rising,
            "policy_2y": falling,
            "vix": falling,
        },
        signal_at,
    )
    assert hostile.state == "HOSTILE"
    assert hostile.non_hostile is False

    mixed = macro_snapshot(
        {
            "real_yield_10y": rising,
            "usd_broad": falling,
            "policy_2y": rising,
            "vix": rising,
        },
        signal_at,
    )
    assert mixed.state == "MIXED"
    assert mixed.non_hostile is True

    supportive = macro_snapshot(
        {
            "real_yield_10y": falling,
            "usd_broad": falling,
            "policy_2y": rising,
            "vix": falling,
        },
        signal_at,
    )
    assert supportive.state == "SUPPORTIVE"
    assert supportive.non_hostile is True
