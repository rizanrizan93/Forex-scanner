from datetime import UTC, datetime, timedelta
from pathlib import Path

from fx_scanner.demo_xau_v218_htf_strategic_snapshot import (
    _snapshot,
    parity_against_v180,
)
from fx_scanner.research_xau_htf_strategic_regime_v180 import RegimePoint

ROOT = Path(__file__).resolve().parents[1]


def _point(
    *,
    map_at: datetime,
    raw_score: float = -0.30,
    raw_direction: str = "SHORT",
    strategic_bias: str = "SHORT",
) -> RegimePoint:
    return RegimePoint(
        map_at=map_at,
        close=4300.0,
        raw_score=raw_score,
        raw_direction=raw_direction,
        strategic_bias=strategic_bias,
        baseline_h4_direction="SHORT",
        switch_pending_direction=None,
        switch_pending_count=0,
        neutral_pending_count=0,
        components={
            "d1_close_ema20": -0.2,
            "d1_ema20_ema50": -0.1,
            "d1_ema20_slope": -0.05,
            "d1_return5": -0.1,
            "d1_structure": -1.0,
            "h4_close_ema20": -0.2,
            "h4_ema20_ema50": -0.1,
            "h4_ema20_slope": -0.05,
            "h4_return4": -0.1,
            "h4_structure": -1.0,
        },
    )


def _reference(point: RegimePoint) -> dict:
    return {
        "observed_at": "2026-09-25T00:30:00+00:00",
        "details": {
            "evaluation": {
                "current": _snapshot(point),
            }
        },
    }


def test_v218_snapshot_keeps_strategic_and_tactical_roles_separate() -> None:
    point = _point(map_at=datetime(2026, 9, 25, 0, tzinfo=UTC))
    snapshot = _snapshot(point)
    assert snapshot["strategic_bias"] == "SHORT"
    assert snapshot["tactical_first_leg"] == "LONG"
    assert snapshot["raw_direction"] == "SHORT"


def test_v218_parity_passes_for_same_map_and_small_numeric_drift() -> None:
    map_at = datetime(2026, 9, 25, 0, tzinfo=UTC)
    reference_point = _point(map_at=map_at, raw_score=-0.30)
    bounded_point = _point(map_at=map_at, raw_score=-0.295)
    result = parity_against_v180((bounded_point,), _reference(reference_point))
    assert result["state"] == "PASS"
    assert result["trusted_for_context"] is True
    assert result["raw_score_delta"] < 0.02


def test_v218_parity_fails_closed_on_direction_drift() -> None:
    map_at = datetime(2026, 9, 25, 0, tzinfo=UTC)
    reference_point = _point(map_at=map_at, raw_score=-0.30)
    bounded_point = _point(
        map_at=map_at,
        raw_score=0.25,
        raw_direction="LONG",
        strategic_bias="LONG",
    )
    result = parity_against_v180((bounded_point,), _reference(reference_point))
    assert result["state"] == "DRIFT"
    assert result["trusted_for_context"] is False


def test_v218_reference_outside_window_fails_closed() -> None:
    reference_point = _point(map_at=datetime(2026, 9, 24, 20, tzinfo=UTC))
    bounded_point = _point(map_at=datetime(2026, 9, 25, 0, tzinfo=UTC))
    result = parity_against_v180((bounded_point,), _reference(reference_point))
    assert result["state"] == "REFERENCE_OUTSIDE_WINDOW"
    assert result["trusted_for_context"] is False


def test_v218_workflow_is_h4_cadence_and_v180_is_weekly_anchor() -> None:
    v218 = (ROOT / ".github/workflows/ctrader-demo-xau-v218-htf-snapshot.yml").read_text()
    assert "10 0,4,8,12,16,20 * * 1-5" in v218
    assert "python -m fx_scanner.demo_xau_v218_htf_strategic_snapshot" in v218

    v180 = (ROOT / ".github/workflows/research-xau-htf-strategic-regime-v180.yml").read_text()
    assert "35 0 * * 1" in v180
