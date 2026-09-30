from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_h1_m5_reconfirmation_v313 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    _gate,
    _post_anchor_outcome,
    _select_micro_candidate,
)
from fx_scanner.research_xau_supply_demand_reaction_v183 import ZoneDestination


AT = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def _bar(i: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=AT + timedelta(minutes=5 * i),
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )


def _zone(direction="LONG") -> ZoneDestination:
    return ZoneDestination(
        zone_id="h1-z",
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        direction=direction,
        available_at=AT - timedelta(hours=2),
        low=100.0,
        high=102.0,
        atr_points=4.0,
        observation_hours=240,
        touched=True,
        first_touch_at=AT - timedelta(hours=1),
        invalidated_at=None,
        expired_at=AT + timedelta(days=2),
        observation_complete=True,
    )


def _candidate(
    zone_id: str,
    *,
    timeframe="H1",
    zone_class="STRUCTURAL",
    prior_status="HOLD",
    refresh=True,
    touches=2,
    score=70.0,
):
    return {
        "zone_id": zone_id,
        "timeframe": timeframe,
        "zone_class": zone_class,
        "gap_usd": 1.0,
        "authority_score": score,
        "lifecycle": {
            "touch_count_proxy": touches,
            "fresh_micro_refresh_required": refresh,
            "latest_reaction_status": prior_status,
        },
    }


def test_v313_contract_is_research_only():
    assert ARTIFACT_CONTRACT == "XAU_H1_M5_RECONFIRMATION_V313_EVIDENCE_1"
    assert POLICY_EFFECT == "RESEARCH_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False


def test_v313_primary_policy_requires_h1_structural_prior_hold_and_micro_refresh():
    rows = (
        _candidate("h4", timeframe="H4", score=99),
        _candidate("imbalance", zone_class="IMBALANCE", score=95),
        _candidate("prior-break", prior_status="BREAK", score=90),
        _candidate("no-refresh", refresh=False, score=85),
        _candidate("eligible", score=70),
    )
    selected = _select_micro_candidate(
        rows,
        policy="STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED",
    )
    assert selected is not None
    assert selected["zone_id"] == "eligible"


def test_v313_all_h1_policy_still_rejects_fresh_or_non_refresh_candidates():
    rows = (
        _candidate("fresh", touches=0, refresh=False, score=100),
        _candidate("first-active", touches=1, refresh=False, score=95),
        _candidate("micro-required", touches=2, refresh=True, score=60),
    )
    selected = _select_micro_candidate(
        rows,
        policy="ALL_H1_MICRO_REQUIRED",
    )
    assert selected is not None
    assert selected["zone_id"] == "micro-required"


def test_v313_post_confirmation_hold_uses_anchor_price_not_zone_edge():
    zone = _zone("LONG")
    rows = (
        _bar(0, 103.0, 103.5, 102.8, 103.2),
        _bar(1, 103.2, 104.0, 103.0, 103.8),
        _bar(2, 103.8, 105.3, 103.6, 105.0),
    )
    times = tuple(row.timestamp for row in rows)
    out = _post_anchor_outcome(
        rows=rows,
        times=times,
        zone=zone,
        anchor_at=AT,
        anchor_price=103.0,
    )
    # Target is +2.0 (=0.50 * ATR 4.0) from confirmation anchor 103.0.
    assert out["status"] == "HOLD"


def test_v313_distal_close_break_wins_before_same_bar_favorable_move():
    zone = _zone("LONG")
    rows = (
        _bar(0, 101.0, 104.0, 99.0, 99.5),
    )
    times = tuple(row.timestamp for row in rows)
    out = _post_anchor_outcome(
        rows=rows,
        times=times,
        zone=zone,
        anchor_at=AT,
        anchor_price=101.0,
    )
    assert out["status"] == "BREAK"


def test_v313_gate_requires_quality_uplift_and_fast_confirmation():
    passing = {
        "m5_confirmed": 40,
        "confirmation_rate_of_selected": 0.20,
        "post_confirm_hold_rate": 0.66,
        "post_confirm_wilson_lower_95": 0.52,
        "uplift_pp_vs_touch_baseline": 10.0,
        "median_minutes_touch_to_confirmation": 35.0,
    }
    failing = {
        **passing,
        "post_confirm_hold_rate": 0.55,
    }
    assert _gate(passing)["passed"] is True
    assert _gate(failing)["passed"] is False
