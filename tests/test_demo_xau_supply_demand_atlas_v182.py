from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.demo_xau_supply_demand_atlas_v182 import (
    CONTRACT,
    SDZone,
    _age_bucket,
    _classify_pattern,
    _correct_side,
    _detect_base_departure_zones,
    _research_score,
    _session_bucket_wib,
    _zone_lifecycle,
)
from fx_scanner.models import Bar


def _zone(direction: str = "LONG") -> SDZone:
    now = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    return SDZone(
        zone_id="z1",
        timeframe="H4",
        zone_class="IMBALANCE",
        pattern="DBR" if direction == "LONG" else "RBD",
        direction=direction,
        low=100.0,
        high=102.0,
        proximal=102.0 if direction == "LONG" else 100.0,
        distal=100.0 if direction == "LONG" else 102.0,
        available_at=now,
        origin_at=now - timedelta(hours=4),
        departure_at=now,
        atr_points=4.0,
        base_bars=2,
        base_range_atr=0.5,
        departure_range_atr=1.6,
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
        tick_count=1,
        spread_avg=0.0,
        spread_max=0.0,
    )


def test_v182_contract_is_prepare_only_research():
    assert CONTRACT == "XAU_HTF_SUPPLY_DEMAND_ATLAS_V182"


def test_age_buckets_keep_h1_and_htf_semantics_separate():
    assert _age_bucket("H1", 12) == "H1_0_24H"
    assert _age_bucket("H1", 72) == "H1_48_96H"
    assert _age_bucket("H4", 20) == "H4_0_6_BARS"
    assert _age_bucket("D1", 120) == "D1_3_7_BARS"


def test_pattern_classifier_distinguishes_reversal_and_continuation():
    assert _classify_pattern(direction="LONG", pre_base_close=105, base_mid=101) == "DBR"
    assert _classify_pattern(direction="LONG", pre_base_close=99, base_mid=101) == "RBR"
    assert _classify_pattern(direction="SHORT", pre_base_close=99, base_mid=101) == "RBD"
    assert _classify_pattern(direction="SHORT", pre_base_close=105, base_mid=101) == "DBD"


def test_correct_side_allows_price_above_demand_and_below_supply():
    assert _correct_side(105.0, _zone("LONG")) is True
    assert _correct_side(99.0, _zone("LONG")) is False
    assert _correct_side(99.0, _zone("SHORT")) is True
    assert _correct_side(103.0, _zone("SHORT")) is False


def test_lifecycle_tracks_first_touch_and_break_without_execution_authority():
    zone = _zone("LONG")
    start = zone.available_at
    bars = (
        _bar(start, 104.0, 104.5, 103.5, 104.0),
        _bar(start + timedelta(minutes=15), 103.5, 103.8, 101.5, 102.5),
        _bar(start + timedelta(minutes=30), 102.4, 102.6, 100.8, 101.2),
        _bar(start + timedelta(minutes=45), 101.0, 101.2, 99.4, 99.8),
    )
    lifecycle = _zone_lifecycle(zone, bars=bars)
    assert lifecycle["touch_count"] == 1
    assert lifecycle["first_touch_at"] is not None
    assert lifecycle["invalidated_at"] is not None
    assert lifecycle["freshness"] == "BROKEN"
    assert lifecycle["active"] is False


def test_base_departure_detector_finds_compact_base_then_bullish_departure():
    t0 = datetime(2026, 9, 20, tzinfo=UTC)
    rows = []
    price = 100.0
    for i in range(18):
        rows.append(
            {
                "time": pd.Timestamp(t0 + timedelta(hours=i + 1)),
                "open": price,
                "high": price + 0.25,
                "low": price - 0.25,
                "close": price + (0.03 if i % 2 == 0 else -0.03),
            }
        )
        price += 0.01
    rows.append(
        {
            "time": pd.Timestamp(t0 + timedelta(hours=19)),
            "open": 100.05,
            "high": 100.22,
            "low": 99.95,
            "close": 100.10,
        }
    )
    rows.append(
        {
            "time": pd.Timestamp(t0 + timedelta(hours=20)),
            "open": 100.10,
            "high": 102.40,
            "low": 100.05,
            "close": 102.20,
        }
    )
    frame = pd.DataFrame(rows)
    zones = _detect_base_departure_zones(frame, timeframe="H1")
    assert zones
    assert zones[-1].direction == "LONG"
    assert zones[-1].zone_class == "IMBALANCE"
    assert zones[-1].departure_range_atr >= 0.95


def test_research_score_is_ranking_not_probability():
    zone = _zone("LONG")
    score = _research_score(
        zone=zone,
        lifecycle={"freshness": "FRESH"},
        distance_atr=0.3,
        nesting_count=1,
        liquidity_count=2,
        alignment="SEARAH",
    )
    assert 0.0 <= score <= 100.0


def test_wib_session_bucket_marks_afic_observation_window():
    # 12:45 UTC == 19:45 WIB.
    ts = datetime(2026, 9, 23, 12, 45, tzinfo=UTC)
    assert _session_bucket_wib(ts) == "US_MACRO_WINDOW_1930_2029_WIB"
