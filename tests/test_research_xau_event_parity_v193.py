from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_event_parity_v193 import (
    _reaction,
    _summarize_time_shift_stats,
    parity_validation,
)


def _bar(ts, o, h, l, c):
    return Bar(
        "XAUUSD",
        "M1",
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
    for i in range(160):
        ts = start + timedelta(minutes=i)
        open_ = price
        close = price + 0.5
        bars.append(_bar(ts, open_, close + 0.2, open_ - 0.2, close))
        price = close
    out = _reaction(tuple(bars), event)
    assert out["reference_price"] is not None
    assert out["atr14"] is not None
    assert out["bar_interval_minutes"] == 1.0
    assert out["r5m_points"] is not None
    assert out["r15m_points"] is not None
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


def test_v193_time_shift_forensics_identifies_best_offset_without_changing_gate():
    stats = {
        offset: {
            minutes: {"agree": 0, "n": 0, "diffs": []}
            for minutes in (5, 15, 30)
        }
        for offset in (-30, 0, 30)
    }
    stats[-30][15] = {"n": 10, "agree": 9, "diffs": [1.0] * 10}
    stats[0][15] = {"n": 10, "agree": 5, "diffs": [4.0] * 10}
    stats[30][15] = {"n": 10, "agree": 6, "diffs": [3.0] * 10}
    out = _summarize_time_shift_stats(stats)
    assert out["best_offset_minutes_by_15m_sign_agreement"] == -30
    assert out["best_15m_directional_agreement"] == 0.9
    assert out["zero_offset_15m_directional_agreement"] == 0.5
    assert out["best_vs_zero_15m_agreement_improvement"] == 0.4
    assert out["changes_validation_gate"] is False
