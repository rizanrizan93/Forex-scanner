from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_scanner.demo_xau_v220_direction_prospective_calibration import (
    _first_full_m15_at_or_after,
    build_forecast_candidates,
    evaluate_forecast_outcome,
    score_categorical_forecast,
)
from fx_scanner.models import Bar

ROOT = Path(__file__).resolve().parents[1]


def _bar(ts: datetime, *, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=100,
        spread_avg=0.20,
        spread_max=0.30,
    )


def _heartbeats(*, touched: bool = False) -> tuple[dict, dict]:
    forecast_at = "2026-09-25T10:02:00+00:00"
    v217 = {
        "observed_at": forecast_at,
        "healthy": True,
        "details": {
            "code_version": "abc",
            "evaluation": {
                "tactical_first_leg": {
                    "p_long": 0.65,
                    "p_short": 0.25,
                    "p_neutral": 0.10,
                },
                "opposing_next_leg": {
                    "p_long": 0.25,
                    "p_short": 0.65,
                    "p_neutral": 0.10,
                },
                "strategic_htf": {
                    "htf_context": {
                        "source": "V218_HTF_STRATEGIC_SNAPSHOT",
                        "strategic_bias": "SHORT",
                        "parity_state": "PASS",
                    }
                },
                "source_freshness": {"v218_observed_at": "2026-09-25T10:00:00+00:00"},
            },
        },
    }
    first_touch = "2026-09-25T10:00:00+00:00" if touched else None
    v213 = {
        "details": {
            "evaluation": {
                "current_leg": {
                    "stage": "PRE_TOUCH",
                    "source_zone": {
                        "zone_id": "zone-current",
                        "direction": "LONG",
                        "timeframe": "H1",
                        "zone_class": "IMBALANCE",
                        "pattern": "RBR",
                        "available_at": "2026-09-25T09:00:00+00:00",
                        "origin_at": "2026-09-25T08:00:00+00:00",
                        "low": 100.0,
                        "high": 101.0,
                        "distal": 100.0,
                        "atr_points": 4.0,
                        "lifecycle": {
                            "active": True,
                            "touch_count": 1 if touched else 0,
                            "first_touch_at": first_touch,
                            "invalidated_at": None,
                            "freshness": "FRESH",
                        },
                    },
                },
                "next_leg": {
                    "stage": "PRE_TOUCH",
                    "source_zone": {
                        "zone_id": "zone-next",
                        "direction": "SHORT",
                        "timeframe": "H1",
                        "zone_class": "IMBALANCE",
                        "pattern": "RBD",
                        "available_at": "2026-09-25T09:00:00+00:00",
                        "origin_at": "2026-09-25T08:00:00+00:00",
                        "low": 110.0,
                        "high": 111.0,
                        "distal": 111.0,
                        "atr_points": 4.0,
                        "lifecycle": {
                            "active": True,
                            "touch_count": 0,
                            "first_touch_at": None,
                            "invalidated_at": None,
                            "freshness": "FRESH",
                        },
                    },
                },
            }
        }
    }
    return v217, v213


def test_v220_records_only_pre_touch_forecasts() -> None:
    v217, v213 = _heartbeats(touched=True)
    rows = build_forecast_candidates(v217, v213)
    assert len(rows) == 1
    assert rows[0]["role"] == "next_leg"
    assert rows[0]["forecast_timing"] == "PRE_TOUCH_NO_LEAKAGE"
    assert rows[0]["execution_authority"] is False


def test_v220_aligns_to_first_full_post_forecast_m15_bar() -> None:
    value = datetime(2026, 9, 25, 10, 2, 31, tzinfo=UTC)
    assert _first_full_m15_at_or_after(value) == datetime(
        2026, 9, 25, 10, 15, tzinfo=UTC
    )


def test_v220_long_hold_maps_to_long_actual_class() -> None:
    forecast_at = datetime(2026, 9, 25, 10, 2, tzinfo=UTC)
    start = datetime(2026, 9, 25, 10, 15, tzinfo=UTC)
    bars = [
        _bar(start, o=102.0, h=102.5, l=100.5, c=101.0),
        _bar(start + timedelta(minutes=15), o=101.0, h=103.2, l=100.8, c=103.0),
    ]
    outcome = evaluate_forecast_outcome(
        bars,
        forecast_at=forecast_at,
        direction="LONG",
        low=100.0,
        high=101.0,
        distal=99.0,
        atr_points=4.0,
        now=start + timedelta(hours=1),
    )
    assert outcome.status == "HOLD_0_50"
    assert outcome.actual_class == "LONG"
    assert outcome.bars_to_outcome == 1


def test_v220_break_wins_same_bar_ambiguity() -> None:
    forecast_at = datetime(2026, 9, 25, 10, 2, tzinfo=UTC)
    start = datetime(2026, 9, 25, 10, 15, tzinfo=UTC)
    bars = [
        _bar(start, o=110.0, h=111.5, l=109.5, c=110.5),
        _bar(start + timedelta(minutes=15), o=110.5, h=112.5, l=107.0, c=112.0),
    ]
    outcome = evaluate_forecast_outcome(
        bars,
        forecast_at=forecast_at,
        direction="SHORT",
        low=110.0,
        high=111.0,
        distal=111.0,
        atr_points=4.0,
        now=start + timedelta(hours=1),
    )
    assert outcome.status == "BREAK"
    assert outcome.actual_class == "LONG"


def test_v220_multiclass_scores_are_finite_and_directional() -> None:
    score = score_categorical_forecast(
        {"LONG": 0.65, "SHORT": 0.25, "NEUTRAL": 0.10},
        "LONG",
    )
    assert abs(score["brier_multiclass"] - 0.195) < 1e-12
    assert score["log_loss"] > 0
    assert score["dominant_class"] == "LONG"
    assert score["dominant_correct"] is True


def test_v220_is_after_v217_and_remains_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    v217 = "python -m fx_scanner.demo_xau_v217_direction_probability"
    v220 = "python -m fx_scanner.demo_xau_v220_direction_prospective_calibration"
    assert workflow.index(v217) < workflow.index(v220)

    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "V220 — Prospective Direction Calibration" in dashboard
    assert "V220 tetap shadow-only" in dashboard
