from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_supply_demand_atlas_v182 import SDZone
from fx_scanner.models import Bar
from fx_scanner.research_xau_supply_demand_reaction_v183 import (
    ARTIFACT_CONTRACT,
    ReactionEpisode,
    ReactionOutcome,
    _age_bucket,
    _candidate_subsets,
    _liquidity_bucket,
    _nesting_bucket,
    _touch_bucket,
    evaluate_reaction_outcome,
)


def _zone(direction: str = "LONG") -> SDZone:
    now = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    return SDZone(
        zone_id="zone-1",
        timeframe="H1",
        zone_class="IMBALANCE",
        pattern="DBR" if direction == "LONG" else "RBD",
        direction=direction,
        low=100.0,
        high=102.0,
        proximal=102.0 if direction == "LONG" else 100.0,
        distal=100.0 if direction == "LONG" else 102.0,
        available_at=now - timedelta(hours=4),
        origin_at=now - timedelta(hours=5),
        departure_at=now - timedelta(hours=4),
        atr_points=4.0,
        base_bars=2,
        base_range_atr=0.5,
        departure_range_atr=1.5,
        departure_body_fraction=0.75,
        structural_bos=False,
    )


def _bar(ts: datetime, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=ts,
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=10,
        spread_avg=0.0,
        spread_max=0.0,
    )


def test_v183_contract_is_research_only():
    assert ARTIFACT_CONTRACT == "XAU_SUPPLY_DEMAND_REACTION_PROFILER_V183_EVIDENCE_1"


def test_hold_requires_half_atr_before_distal_break():
    zone = _zone("LONG")
    t0 = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    bars = (
        _bar(t0, 102.5, 102.7, 101.0, 102.2),
        _bar(t0 + timedelta(minutes=15), 102.2, 103.0, 101.8, 102.8),
        _bar(t0 + timedelta(minutes=30), 102.8, 104.2, 102.7, 104.0),
        _bar(t0 + timedelta(minutes=45), 104.0, 104.3, 103.5, 104.1),
    )
    result = evaluate_reaction_outcome(bars, touch_index=0, zone=zone)
    assert result.status == "HOLD"
    assert result.label_hold is True
    assert result.hit_050_before_break is True
    assert result.bars_to_outcome == 2


def test_break_wins_same_bar_ambiguity():
    zone = _zone("LONG")
    t0 = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    bars = (
        _bar(t0, 102.5, 102.7, 101.0, 102.2),
        # This bar trades above +0.50 ATR from zone high but closes below distal.
        _bar(t0 + timedelta(minutes=15), 102.2, 104.5, 99.0, 99.5),
    )
    result = evaluate_reaction_outcome(
        bars,
        touch_index=0,
        zone=zone,
        horizon_m15=1,
    )
    assert result.status == "BREAK"
    assert result.label_hold is False
    assert result.hit_050_before_break is False


def test_touch_nesting_and_liquidity_buckets_are_explicit():
    assert _touch_bucket(1) == "FIRST_TEST"
    assert _touch_bucket(2) == "SECOND_TEST"
    assert _touch_bucket(4) == "MULTI_TESTED"
    assert _nesting_bucket(0) == "NO_HTF_NESTING"
    assert _nesting_bucket(2) == "MULTI_HTF_NESTING"
    assert _liquidity_bucket(0) == "NO_LIQUIDITY_CONFLUENCE"
    assert _liquidity_bucket(2) == "MULTI_LIQUIDITY_CONFLUENCE"
    assert _age_bucket("H1", 72) == "H1_48_96H"


def _episode(index: int, hold: bool) -> ReactionEpisode:
    touch_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    outcome = ReactionOutcome(
        status="HOLD" if hold else "BREAK",
        label_hold=hold,
        touch_at=touch_at,
        outcome_at=touch_at + timedelta(minutes=15),
        bars_to_outcome=1,
        max_favorable_excursion_atr=0.7 if hold else 0.1,
        max_adverse_excursion_atr=0.2 if hold else 0.8,
        hit_025_before_break=hold,
        hit_050_before_break=hold,
        hit_075_before_break=False,
        hit_100_before_break=False,
    )
    return ReactionEpisode(
        zone_id=f"z-{index}",
        timeframe="H4",
        zone_class="IMBALANCE",
        pattern="DBR",
        direction="LONG",
        available_at=touch_at - timedelta(hours=8),
        touch_at=touch_at,
        touch_ordinal=1,
        touch_bucket="FIRST_TEST",
        age_hours=8.0,
        age_bucket="H4_0_6_BARS",
        session_context="NY_OPEN_2030_2229_WIB",
        approach_state="CONTROLLED_APPROACH",
        htf_nesting_count=1,
        nesting_bucket="ONE_HTF_PARENT",
        liquidity_sources=("ROUND_NUMBER",),
        liquidity_bucket="ONE_LIQUIDITY_CONFLUENCE",
        departure_range_atr=1.6,
        departure_body_fraction=0.75,
        base_range_atr=0.5,
        structural_bos=False,
        outcome=outcome,
    )


def test_high_precision_subset_is_never_granted_promotion_authority():
    rows = tuple(_episode(i, i < 28) for i in range(32))
    candidates = _candidate_subsets(rows)
    assert candidates
    assert all(candidate["promotion_authority"] is False for candidate in candidates)
    assert all(
        candidate["interpretation"]
        == "EXPLORATORY_HOLDOUT_SUBSET_NOT_PRODUCTION_CLAIM"
        for candidate in candidates
    )
