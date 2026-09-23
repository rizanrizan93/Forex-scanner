from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_afic_path_shadow_observer import OriginZone
from fx_scanner.demo_xau_premap_candidate_v181 import (
    CONTRACT,
    LiquidityEvidence,
    _alignment,
    _candidate_correct_side,
    _research_score,
)


def _zone(direction: str) -> OriginZone:
    now = datetime(2026, 9, 23, tzinfo=UTC)
    return OriginZone(
        direction=direction,
        available_at=now,
        bos_at=now,
        bos_level=100.0,
        low=100.0,
        high=102.0,
        h1_atr=4.0,
        origin_at=now - timedelta(hours=1),
        displacement_range_atr=1.8,
        displacement_body_fraction=0.7,
    )


def test_candidate_correct_side_requires_supply_above_and_demand_below():
    assert _candidate_correct_side(95.0, _zone("SHORT")) is True
    assert _candidate_correct_side(101.0, _zone("SHORT")) is False
    assert _candidate_correct_side(105.0, _zone("LONG")) is True
    assert _candidate_correct_side(101.0, _zone("LONG")) is False


def test_alignment_separates_strategic_and_tactical_context():
    assert _alignment(
        "SHORT",
        strategic_bias="SHORT",
        tactical_direction="LONG",
    ) == ("SEARAH", "BERLAWANAN")
    assert _alignment(
        "LONG",
        strategic_bias="NEUTRAL",
        tactical_direction="LONG",
    ) == ("NETRAL", "SEARAH")


def test_research_score_is_contextual_not_execution_authority():
    liquidity = LiquidityEvidence(
        sources=("H1_SWING_HIGH", "ROUND_NUMBER"),
        nearest_distance_atr=0.05,
        confluence_count=2,
        round_number=100.0,
        nearby_levels=(),
    )
    high = _research_score(
        zone=_zone("SHORT"),
        age_hours=1.0,
        distance_atr=0.2,
        liquidity=liquidity,
        strategic_alignment="SEARAH",
        tactical_alignment="SEARAH",
    )
    low = _research_score(
        zone=_zone("SHORT"),
        age_hours=20.0,
        distance_atr=1.9,
        liquidity=LiquidityEvidence(
            sources=(),
            nearest_distance_atr=None,
            confluence_count=0,
            round_number=None,
            nearby_levels=(),
        ),
        strategic_alignment="BERLAWANAN",
        tactical_alignment="BERLAWANAN",
    )
    assert high > low
    assert 0.0 <= low <= 100.0
    assert high <= 100.0


def test_v181_contract_is_prepare_only():
    assert CONTRACT == "XAU_PREMAP_CANDIDATE_V181"
