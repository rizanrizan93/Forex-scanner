from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_reusable_primary_reversal_v312 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    _episode_state_index,
    _lifecycle_at,
    _select_candidate,
)
from fx_scanner.research_xau_supply_demand_reaction_v183 import (
    ReactionEpisode,
    ReactionOutcome,
    ZoneDestination,
)


AT = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def _bar(at, o, h, l, c):
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=at,
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=100,
        spread_avg=0.2,
        spread_max=0.3,
    )


def _zone(zone_id="z1", direction="LONG"):
    return ZoneDestination(
        zone_id=zone_id,
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        direction=direction,
        available_at=AT - timedelta(hours=1),
        low=100.0,
        high=102.0,
        atr_points=4.0,
        observation_hours=240,
        touched=True,
        first_touch_at=AT,
        invalidated_at=None,
        expired_at=AT + timedelta(days=3),
        observation_complete=True,
    )


def _episode(zone_id="z1", direction="LONG", ordinal=1):
    outcome = ReactionOutcome(
        status="HOLD",
        label_hold=True,
        touch_at=AT,
        outcome_at=AT,
        bars_to_outcome=0,
        max_favorable_excursion_atr=0.5,
        max_adverse_excursion_atr=0.1,
        hit_025_before_break=True,
        hit_050_before_break=True,
        hit_075_before_break=False,
        hit_100_before_break=False,
    )
    return ReactionEpisode(
        zone_id=zone_id,
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        direction=direction,
        available_at=AT - timedelta(hours=1),
        touch_at=AT,
        touch_ordinal=ordinal,
        touch_bucket="FIRST_TEST" if ordinal == 1 else "SECOND_TEST",
        age_hours=1.0,
        age_bucket="YOUNG",
        session_context="LONDON_WIB",
        approach_state="CONTROLLED_APPROACH",
        htf_nesting_count=1,
        nesting_bucket="ONE_HTF_PARENT",
        liquidity_sources=(),
        liquidity_bucket="NO_LIQUIDITY_CONFLUENCE",
        departure_range_atr=1.0,
        departure_body_fraction=0.7,
        base_range_atr=0.4,
        structural_bos=True,
        outcome=outcome,
    )


def test_v312_contract_is_research_only():
    assert ARTIFACT_CONTRACT == "XAU_REUSABLE_PRIMARY_REVERSAL_CYCLE_V312_EVIDENCE_1"
    assert POLICY_EFFECT == "RESEARCH_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False


def test_v312_touch_is_not_known_before_m15_bar_close():
    rows = (_bar(AT, 103, 103.5, 101.6, 102.5),)
    zone = _zone()
    episode = _episode()
    index = _episode_state_index(rows, (episode,), (zone,))

    before_close = _lifecycle_at(
        zone=zone,
        cutoff=AT + timedelta(minutes=10),
        rows=rows,
        episode_index=index,
    )
    at_close = _lifecycle_at(
        zone=zone,
        cutoff=AT + timedelta(minutes=15),
        rows=rows,
        episode_index=index,
    )

    assert before_close["state"] == "FRESH_PARENT_ZONE"
    assert before_close["touch_count_proxy"] == 0
    assert at_close["state"] == "FIRST_TEST_PARENT_ACTIVE"
    assert at_close["reusable_without_new_micro"] is True


def test_v312_deep_first_touch_requires_new_micro():
    rows = (_bar(AT, 103, 103.5, 100.2, 102.5),)
    zone = _zone()
    episode = _episode()
    index = _episode_state_index(rows, (episode,), (zone,))

    state = _lifecycle_at(
        zone=zone,
        cutoff=AT + timedelta(minutes=15),
        rows=rows,
        episode_index=index,
    )

    assert state["mitigation_depth_proxy"] >= 0.75
    assert state["state"] == "DEEPLY_MITIGATED_REQUIRE_NEW_MICRO"
    assert state["reusable_without_new_micro"] is False


def test_v312_reuse_policy_can_select_first_test_parent_but_fresh_only_cannot():
    reused = {
        "zone_id": "reuse",
        "timeframe": "H1",
        "gap_usd": 1.0,
        "authority_score": 60.0,
        "lifecycle": {
            "touch_count_proxy": 1,
            "reusable_without_new_micro": True,
        },
    }

    assert _select_candidate((reused,), allow_reuse=False) is None
    selected = _select_candidate((reused,), allow_reuse=True)
    assert selected is not None
    assert selected["zone_id"] == "reuse"


def test_v312_micro_required_reuse_is_not_selected():
    blocked = {
        "zone_id": "blocked",
        "timeframe": "H1",
        "gap_usd": 0.5,
        "authority_score": 90.0,
        "lifecycle": {
            "touch_count_proxy": 2,
            "reusable_without_new_micro": False,
        },
    }
    fresh = {
        "zone_id": "fresh",
        "timeframe": "H1",
        "gap_usd": 2.0,
        "authority_score": 50.0,
        "lifecycle": {
            "touch_count_proxy": 0,
            "reusable_without_new_micro": True,
        },
    }

    selected = _select_candidate((blocked, fresh), allow_reuse=True)
    assert selected is not None
    assert selected["zone_id"] == "fresh"
