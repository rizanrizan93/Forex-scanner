from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_event_parity_v193 import (
    _reaction,
    parity_validation,
)


def _bar(ts, o, h, l, c):
    return Bar(
        "XAUUSD",
        "M5",
        ts,
        float(o),
        float(h),
        float(l),
        float(c),
        1,
        0.0,
        0.0,
    )


def test_ctrader_parity_reaction_is_atr_normalized():
    event = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    bars = []
    start = event - timedelta(minutes=90)
    price = 2000.0
    for i in range(31):
        ts = start + timedelta(minutes=5 * i)
        open_ = price
        close = price + 0.5
        bars.append(_bar(ts, open_, close + 0.2, open_ - 0.2, close))
        price = close
    out = _reaction(tuple(bars), event)
    assert out["r5m_atr"] is not None
    assert out["r15m_atr"] is not None
    assert out["r15m_atr"] > 0


def _horizons(agree_5=0.8, agree_15=0.85, agree_30=0.82, diff_15=0.6):
    return {
        "5m": {
            "n": 60,
            "directional_agreement": agree_5,
            "median_abs_atr_difference": 0.6,
        },
        "15m": {
            "n": 60,
            "directional_agreement": agree_15,
            "median_abs_atr_difference": diff_15,
        },
        "30m": {
            "n": 60,
            "directional_agreement": agree_30,
            "median_abs_atr_difference": 0.8,
        },
        "60m": {
            "n": 60,
            "directional_agreement": 0.7,
            "median_abs_atr_difference": 1.0,
        },
    }


def test_parity_validation_is_preregistered_and_strict():
    out = parity_validation(
        attempted=60,
        available=60,
        horizon_stats=_horizons(),
    )
    assert out["passed"] is True
    assert out["decision"] == "PARITY_VALIDATED"


def test_parity_descriptive_does_not_mean_validated():
    out = parity_validation(
        attempted=60,
        available=60,
        horizon_stats=_horizons(agree_15=0.61, diff_15=2.0),
    )
    assert out["passed"] is False
    assert out["decision"] == "PARITY_DESCRIPTIVE_AVAILABLE"


def test_parity_insufficient_when_coverage_is_low():
    out = parity_validation(
        attempted=60,
        available=40,
        horizon_stats=_horizons(),
    )
    assert out["passed"] is False
    assert out["decision"] == "PARITY_INSUFFICIENT"
