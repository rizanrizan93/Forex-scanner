from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fx_scanner.demo_calibration_features_v2 import (
    build_signal_feature_snapshot_v2,
    classify_regime_v2,
)
from fx_scanner.models import Bar
from fx_scanner.technical import DisplacementSignal, StructureSnapshot

UTC = timezone.utc


def _snapshot(*, trend, bos=None, mss=None, displacement=None):
    return StructureSnapshot(
        trend=trend,
        last_swing_high=1.12,
        last_swing_low=1.08,
        bos=bos,
        mss=mss,
        displacement=displacement,
        fvg=None,
        sweep=None,
    )


def _analysis(*, h1, m15, m5, direction="LONG"):
    return SimpleNamespace(
        symbol="EURUSD",
        direction=direction,
        setup_type="TREND_CONTINUATION",
        trigger_confirmed=True,
        h1=h1,
        m15=m15,
        m5=m5,
        stale_timeframes=(),
        conviction_components={"structure": 72.0, "execution_quality": 81.0},
        computed_guards={"STRUCTURE_INVALID": False, "CHASE_BLOCK": False},
    )


def _bars(tf, count=20):
    step = {"H1": 3600, "M15": 900, "M5": 300}[tf]
    start = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    rows = []
    for index in range(count):
        base = 1.10 + 0.0002 * index
        rows.append(
            Bar(
                symbol="EURUSD",
                timeframe=tf,
                timestamp=start + timedelta(seconds=step * index),
                open=base,
                high=base + 0.0010,
                low=base - 0.0008,
                close=base + 0.0004,
                tick_count=100 + index,
                spread_avg=0.0001,
                spread_max=0.0002,
            )
        )
    return tuple(rows)


def test_regime_v2_distinguishes_strong_trend_range_and_transition():
    bullish_disp = DisplacementSignal("BULLISH", 2.0, 1.4, 0.9, 1.2, True)
    strong = _analysis(
        h1=_snapshot(trend="BULLISH", bos="BULLISH"),
        m15=_snapshot(trend="BULLISH", bos="BULLISH"),
        m5=_snapshot(trend="BULLISH", bos="BULLISH", displacement=bullish_disp),
    )
    assert classify_regime_v2(strong) == "TREND_STRONG"

    ranged = _analysis(
        h1=_snapshot(trend="RANGE"),
        m15=_snapshot(trend="RANGE"),
        m5=_snapshot(trend="RANGE"),
    )
    assert classify_regime_v2(ranged) == "RANGE"

    transition = _analysis(
        h1=_snapshot(trend="RANGE"),
        m15=_snapshot(trend="RANGE", bos="BULLISH", displacement=bullish_disp),
        m5=_snapshot(trend="RANGE"),
    )
    assert classify_regime_v2(transition) == "TRANSITION"


def test_regime_v2_marks_opposing_h1_with_lower_transition_as_reversal():
    bullish_disp = DisplacementSignal("BULLISH", 2.0, 1.4, 0.9, 1.2, True)
    analysis = _analysis(
        h1=_snapshot(trend="BEARISH", bos="BEARISH"),
        m15=_snapshot(trend="RANGE", mss="BULLISH", displacement=bullish_disp),
        m5=_snapshot(trend="BULLISH", bos="BULLISH", displacement=bullish_disp),
    )
    assert classify_regime_v2(analysis) == "REVERSAL"


def test_signal_snapshot_captures_decision_features_without_inventing_execution_features():
    bullish_disp = DisplacementSignal("BULLISH", 2.0, 1.4, 0.9, 1.2, True)
    analysis = _analysis(
        h1=_snapshot(trend="BULLISH", bos="BULLISH"),
        m15=_snapshot(trend="BULLISH", bos="BULLISH"),
        m5=_snapshot(trend="BULLISH", bos="BULLISH", displacement=bullish_disp),
    )
    observed_at = datetime(2026, 9, 4, 13, 30, tzinfo=UTC)
    row = {
        "id": "sig-v2",
        "run_id": "run-v2",
        "observed_at": observed_at.isoformat(),
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "TREND_CONTINUATION",
        "final_score": 64.5,
        "entry_low": 1.101,
        "entry_high": 1.102,
        "sl": 1.098,
        "tp1": 1.106,
        "tp2": 1.109,
        "rr1": 1.4,
        "rr2": 2.4,
        "active_guards": [],
        "data_coverage": 0.95,
    }
    geometry = {
        "entry_mode": "HL_PULLBACK",
        "confirmation": "BOS",
        "pullback_atr": 0.35,
        "zone_distance_atr": 0.20,
        "fvg_status": "OPEN",
        "fvg_age_minutes": 15.0,
    }
    sessions = {
        "sessions": {
            "LONDON": {"timezone": "UTC", "start": "07:00", "end": "16:00"},
            "NEW_YORK": {"timezone": "UTC", "start": "13:00", "end": "22:00"},
        }
    }
    snapshot = build_signal_feature_snapshot_v2(
        analysis=analysis,
        bars_by_timeframe={"H1": _bars("H1"), "M15": _bars("M15"), "M5": _bars("M5")},
        signal_row=row,
        geometry_payload=geometry,
        session_config=sessions,
        atr_period=14,
    )

    assert snapshot["regime"] == "TREND_STRONG"
    assert snapshot["session"] == "LONDON_NY_OVERLAP"
    assert snapshot["atr_m5"] > 0
    assert snapshot["atr_pct_m5"] > 0
    assert snapshot["volatility_regime"] in {
        "LOW_VOLATILITY", "NORMAL_VOLATILITY", "HIGH_VOLATILITY"
    }
    assert snapshot["structure_h1"]["directional_score"] is not None
    assert snapshot["evidence_scores"]["structure"] == 72.0
    assert snapshot["entry_mode"] == "HL_PULLBACK"
    assert snapshot["pullback_atr"] == 0.35
    assert snapshot["spread_pips_at_entry"] is None
    assert snapshot["live_entry_drift_r"] is None
    assert snapshot["entry_execution_snapshot_required"] is True
    assert snapshot["policy_effect"] == "OBSERVATION_ONLY"
    assert snapshot["snapshot_complete_for_regime"] is True
