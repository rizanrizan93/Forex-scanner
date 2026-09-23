from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_supply_demand_atlas_v182 import SDZone
from fx_scanner.models import Bar
from fx_scanner.research_xau_supply_demand_reaction_v183 import (
    evaluate_reaction_outcome,
)
from fx_scanner.research_xau_supply_demand_timeframe_v185 import (
    ARTIFACT_CONTRACT,
    PRIMARY_HORIZON_M15,
    SENSITIVITY_HORIZONS_M15,
    TimeframeEpisode,
    _candidate_groups,
    _scan_touch_indices,
    _summary,
)


def _zone(timeframe: str = "D1", direction: str = "LONG") -> SDZone:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return SDZone(
        zone_id=f"{timeframe}-{direction}",
        timeframe=timeframe,
        zone_class="IMBALANCE",
        pattern="DBR" if direction == "LONG" else "RBD",
        direction=direction,
        low=100.0,
        high=102.0,
        proximal=102.0 if direction == "LONG" else 100.0,
        distal=100.0 if direction == "LONG" else 102.0,
        available_at=now,
        origin_at=now - timedelta(hours=1),
        departure_at=now,
        atr_points=4.0,
        base_bars=1,
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


def test_v185_horizon_contract_is_timeframe_aware():
    assert ARTIFACT_CONTRACT == "XAU_SUPPLY_DEMAND_TIMEFRAME_AWARE_V185_EVIDENCE_1"
    assert PRIMARY_HORIZON_M15 == {"H1": 16, "H4": 96, "D1": 288}
    assert SENSITIVITY_HORIZONS_M15["H4"] == (64, 96)
    assert SENSITIVITY_HORIZONS_M15["D1"] == (192, 288, 480)


def test_d1_can_hold_on_72h_horizon_after_missing_48h_horizon():
    zone = _zone("D1", "LONG")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [_bar(t0, 102.5, 102.7, 101.0, 102.2)]
    # Stay below +0.50 ATR (= +2 points above zone high) for 200 M15 bars.
    for i in range(1, 201):
        ts = t0 + timedelta(minutes=15 * i)
        bars.append(_bar(ts, 102.2, 103.8, 101.5, 102.8))
    # At bar 201 (~50.25h), reach 104.2 without distal invalidation.
    bars.append(
        _bar(
            t0 + timedelta(minutes=15 * 201),
            102.8,
            104.2,
            102.4,
            103.9,
        )
    )
    # Fill enough future data for 72h evaluation.
    for i in range(202, 290):
        ts = t0 + timedelta(minutes=15 * i)
        bars.append(_bar(ts, 103.8, 104.3, 103.2, 104.0))

    short = evaluate_reaction_outcome(
        tuple(bars),
        touch_index=0,
        zone=zone,
        horizon_m15=192,
    )
    primary = evaluate_reaction_outcome(
        tuple(bars),
        touch_index=0,
        zone=zone,
        horizon_m15=288,
    )
    assert short.status == "STALL"
    assert short.label_hold is False
    assert primary.status == "HOLD"
    assert primary.label_hold is True


def test_scan_excludes_right_edge_touch_without_full_sensitivity_horizon():
    zone = _zone("D1", "LONG")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    bars = []
    for i in range(100):
        ts = t0 + timedelta(minutes=15 * i)
        if i == 90:
            bars.append(_bar(ts, 102.5, 102.8, 101.0, 102.2))
        else:
            bars.append(_bar(ts, 104.0, 104.5, 103.5, 104.0))
    times = tuple(row.timestamp for row in bars)
    touches, invalidated_at = _scan_touch_indices(
        tuple(bars),
        times,
        zone=zone,
    )
    assert touches == ()
    assert invalidated_at is None


def _episode(index: int, hold: bool) -> TimeframeEpisode:
    zone = _zone("H1", "LONG")
    touch_at = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    bars = (
        _bar(touch_at, 102.5, 102.7, 101.0, 102.2),
        _bar(
            touch_at + timedelta(minutes=15),
            102.2,
            104.2 if hold else 102.8,
            101.8 if hold else 99.0,
            104.0 if hold else 99.5,
        ),
    )
    outcome = evaluate_reaction_outcome(
        bars,
        touch_index=0,
        zone=zone,
        horizon_m15=1,
    )
    return TimeframeEpisode(
        zone_id=f"z-{index}",
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND",
        direction="LONG",
        available_at=touch_at - timedelta(hours=2),
        touch_at=touch_at,
        touch_index=0,
        touch_ordinal=1,
        touch_bucket="FIRST_TEST",
        age_hours=2.0,
        age_bucket="H1_0_24H",
        session_context="PRE_NY_1700_1929_WIB",
        approach_state="AGGRESSIVE_APPROACH",
        htf_nesting_count=2,
        nesting_bucket="MULTI_HTF_NESTING",
        liquidity_sources=("ROUND_NUMBER",),
        liquidity_bucket="ONE_LIQUIDITY_CONFLUENCE",
        departure_range_atr=1.5,
        departure_body_fraction=0.75,
        base_range_atr=0.5,
        structural_bos=True,
        primary_horizon_m15=16,
        primary_outcome=outcome,
        sensitivity=((16, outcome),),
    )


def test_candidate_subsets_remain_research_only():
    rows = tuple(_episode(i, i < 28) for i in range(32))
    candidates = _candidate_groups(rows)
    assert candidates
    assert all(item["promotion_authority"] is False for item in candidates)
    assert _summary(rows)["n"] == 32
