from datetime import UTC, datetime, timedelta

from fx_scanner.research_xau_supply_demand_reaction_v183 import ZoneDestination
from fx_scanner.research_xau_zone_transition_ledger_v310 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    HANDOFF_GAP_USD,
    HANDOFF_WINDOW_MINUTES,
    POLICY_EFFECT,
    active_opposite_zones_at,
)


AT = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def _zone(
    zone_id: str,
    direction: str,
    low: float,
    high: float,
    *,
    available_offset: int = -60,
    invalidated_offset: int | None = None,
    expired_offset: int = 600,
    first_touch_offset: int | None = None,
) -> ZoneDestination:
    return ZoneDestination(
        zone_id=zone_id,
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="RBR" if direction == "LONG" else "RBD",
        direction=direction,
        available_at=AT + timedelta(minutes=available_offset),
        low=low,
        high=high,
        atr_points=10.0,
        observation_hours=10,
        touched=first_touch_offset is not None,
        first_touch_at=(
            None
            if first_touch_offset is None
            else AT + timedelta(minutes=first_touch_offset)
        ),
        invalidated_at=(
            None
            if invalidated_offset is None
            else AT + timedelta(minutes=invalidated_offset)
        ),
        expired_at=AT + timedelta(minutes=expired_offset),
        observation_complete=True,
    )


def test_v310_contract_is_research_only() -> None:
    assert ARTIFACT_CONTRACT == "XAU_ZONE_TRANSITION_LEDGER_V310_EVIDENCE_1"
    assert POLICY_EFFECT == "RESEARCH_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert HANDOFF_WINDOW_MINUTES == 30
    assert HANDOFF_GAP_USD == 5.0


def test_v310_active_opposite_zones_are_ranked_by_gap() -> None:
    rows = (
        _zone("far", "SHORT", 110.0, 112.0),
        _zone("near", "SHORT", 103.0, 104.0),
        _zone("same-side", "LONG", 100.0, 101.0),
    )
    result = active_opposite_zones_at(
        destinations=rows,
        direction="LONG",
        at=AT,
        price=102.0,
    )
    assert [row["zone_id"] for row in result] == ["near", "far"]
    assert result[0]["gap_usd"] == 1.0


def test_v310_invalidated_or_expired_opposite_zone_is_not_active() -> None:
    rows = (
        _zone("invalid", "SHORT", 103.0, 104.0, invalidated_offset=-1),
        _zone("expired", "SHORT", 105.0, 106.0, expired_offset=-1),
        _zone("active", "SHORT", 107.0, 108.0),
    )
    result = active_opposite_zones_at(
        destinations=rows,
        direction="LONG",
        at=AT,
        price=102.0,
    )
    assert [row["zone_id"] for row in result] == ["active"]


def test_v310_marks_opposite_zone_already_touched_before_handoff() -> None:
    rows = (
        _zone("touched", "SHORT", 103.0, 104.0, first_touch_offset=-10),
        _zone("untouched", "SHORT", 105.0, 106.0),
    )
    result = active_opposite_zones_at(
        destinations=rows,
        direction="LONG",
        at=AT,
        price=102.0,
    )
    assert result[0]["zone_id"] == "touched"
    assert result[0]["already_touched"] is True
    assert result[1]["already_touched"] is False
