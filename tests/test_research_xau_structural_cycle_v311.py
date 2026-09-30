from datetime import UTC, datetime, timedelta

from fx_scanner.research_xau_supply_demand_reaction_v183 import (
    ReactionEpisode,
    ReactionOutcome,
    ZoneDestination,
)
from fx_scanner.research_xau_structural_cycle_v311 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    _evaluate_cycles_from_dataset,
    _summary,
)


AT = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def _zone(zone_id: str, direction: str) -> ZoneDestination:
    return ZoneDestination(
        zone_id=zone_id,
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        direction=direction,
        available_at=AT - timedelta(hours=2),
        low=100.0 if direction == "LONG" else 110.0,
        high=102.0 if direction == "LONG" else 112.0,
        atr_points=4.0,
        observation_hours=240,
        touched=False,
        first_touch_at=None,
        invalidated_at=None,
        expired_at=AT + timedelta(days=2),
        observation_complete=True,
    )


def _episode(
    zone_id: str,
    direction: str,
    *,
    touch_offset: int,
    outcome_offset: int,
    status: str,
) -> ReactionEpisode:
    touch_at = AT + timedelta(minutes=touch_offset)
    outcome_at = AT + timedelta(minutes=outcome_offset)
    hold = status == "HOLD"
    outcome = ReactionOutcome(
        status=status,
        label_hold=hold,
        touch_at=touch_at,
        outcome_at=outcome_at,
        bars_to_outcome=max(0, (outcome_offset - touch_offset) // 15),
        max_favorable_excursion_atr=0.8 if hold else 0.2,
        max_adverse_excursion_atr=0.25,
        hit_025_before_break=hold,
        hit_050_before_break=hold,
        hit_075_before_break=hold,
        hit_100_before_break=False,
    )
    return ReactionEpisode(
        zone_id=zone_id,
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        direction=direction,
        available_at=AT - timedelta(hours=2),
        touch_at=touch_at,
        touch_ordinal=1,
        touch_bucket="FIRST_TEST",
        age_hours=2.0,
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


def test_v311_contract_is_research_only() -> None:
    assert ARTIFACT_CONTRACT == "XAU_STRUCTURAL_CYCLE_V311_EVIDENCE_1"
    assert POLICY_EFFECT == "RESEARCH_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False


def test_v311_clean_opposite_zone_can_complete_second_reaction_hold() -> None:
    demand = _zone("demand-next", "LONG")
    second = _episode(
        "demand-next",
        "LONG",
        touch_offset=45,
        outcome_offset=75,
        status="HOLD",
    )
    handoff = {
        "source_zone_id": "source-supply",
        "source_direction": "SHORT",
        "source_timeframe": "H1",
        "reaction_bar_at": AT.isoformat(),
        "reaction_at": (AT + timedelta(minutes=15)).isoformat(),
        "reaction_price_close": 104.0,
        "touch_ordinal": 1,
        "active_opposite_count": 1,
        "nearby_active_opposite_count": 1,
        "new_opposite_within_window_count": 0,
        "selected_origin": "ACTIVE_AT_REACTION",
        "selected_zone_id": "demand-next",
        "selected_zone_timeframe": "H1",
        "selected_zone_low": 100.0,
        "selected_zone_high": 102.0,
        "selected_gap_usd": 2.0,
        "selected_already_touched": False,
    }
    cycles = _evaluate_cycles_from_dataset(
        destinations=(demand,),
        episodes=(second,),
        handoffs=(handoff,),
    )
    assert len(cycles) == 1
    row = cycles[0]
    assert row["clean_opposite_entry_candidate"] is True
    assert row["cycle_state"] == "SECOND_REACTION_HOLD"
    assert row["structural_cycle_success"] is True
    assert row["second_reaction_at"] == (AT + timedelta(minutes=90)).isoformat()


def test_v311_already_touched_opposite_zone_is_not_clean_next_entry() -> None:
    supply = _zone("supply-used", "SHORT")
    handoff = {
        "source_zone_id": "source-demand",
        "source_direction": "LONG",
        "source_timeframe": "H1",
        "reaction_at": (AT + timedelta(minutes=15)).isoformat(),
        "reaction_price_close": 108.0,
        "selected_origin": "ACTIVE_AT_REACTION",
        "selected_zone_id": "supply-used",
        "selected_zone_timeframe": "H1",
        "selected_gap_usd": 2.0,
        "selected_already_touched": True,
    }
    cycles = _evaluate_cycles_from_dataset(
        destinations=(supply,),
        episodes=(),
        handoffs=(handoff,),
    )
    assert cycles[0]["cycle_state"] == "OPPOSITE_ALREADY_TOUCHED"
    assert cycles[0]["clean_opposite_entry_candidate"] is False
    assert cycles[0]["structural_cycle_success"] is False


def test_v311_summary_distinguishes_coverage_from_cycle_success() -> None:
    rows = (
        {
            "reaction_at": "2026-09-30T10:15:00+00:00",
            "selected_zone_id": "a",
            "selected_origin": "ACTIVE_AT_REACTION",
            "selected_zone_class": "STRUCTURAL",
            "selected_zone_timeframe": "H1",
            "clean_opposite_entry_candidate": True,
            "second_reaction_status": "HOLD",
            "structural_cycle_success": True,
            "minutes_reaction_to_second_touch": 30.0,
            "minutes_reaction_to_second_outcome": 60.0,
        },
        {
            "reaction_at": "2026-09-30T11:15:00+00:00",
            "selected_zone_id": "b",
            "selected_origin": "ACTIVE_AT_REACTION",
            "selected_zone_class": "STRUCTURAL",
            "selected_zone_timeframe": "H1",
            "clean_opposite_entry_candidate": False,
            "second_reaction_status": None,
            "structural_cycle_success": False,
        },
        {
            "reaction_at": "2026-09-30T12:15:00+00:00",
            "selected_zone_id": None,
            "selected_origin": None,
            "clean_opposite_entry_candidate": False,
            "second_reaction_status": None,
            "structural_cycle_success": False,
        },
    )
    result = _summary(rows)
    assert result["first_reaction_milestones"] == 3
    assert result["selected_opposite_any"] == 2
    assert result["clean_opposite_candidates"] == 1
    assert result["second_hold"] == 1
    assert result["second_hold_rate_all_clean"] == 1.0
    assert result["structural_cycle_completion_rate_of_first_reactions"] == 1 / 3
