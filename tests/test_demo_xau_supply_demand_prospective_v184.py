from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_supply_demand_atlas_v182 import SDZone
from fx_scanner.demo_xau_supply_demand_prospective_v184 import (
    CONTRACT,
    PRIMARY_CANDIDATE,
    _post_enrollment_touch_indices,
    _prospective_summary,
)
from fx_scanner.models import Bar


def _zone(direction: str = "LONG") -> SDZone:
    now = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    return SDZone(
        zone_id="z1",
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        direction=direction,
        low=100.0,
        high=102.0,
        proximal=102.0 if direction == "LONG" else 100.0,
        distal=100.0 if direction == "LONG" else 102.0,
        available_at=now - timedelta(hours=24),
        origin_at=now - timedelta(hours=25),
        departure_at=now - timedelta(hours=24),
        atr_points=4.0,
        base_bars=1,
        base_range_atr=0.5,
        departure_range_atr=1.4,
        departure_body_fraction=0.7,
        structural_bos=True,
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


def test_v184_contract_is_shadow_only():
    assert CONTRACT == "XAU_SUPPLY_DEMAND_PROSPECTIVE_LIFECYCLE_V184"
    assert PRIMARY_CANDIDATE == {
        "timeframe": "H1",
        "direction": "LONG",
        "nesting_bucket": "MULTI_HTF_NESTING",
        "approach_state": "AGGRESSIVE_APPROACH",
    }


def test_no_backfill_touches_before_enrollment():
    zone = _zone()
    t0 = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = (
        _bar(t0, 103, 103.5, 102.5, 103),
        _bar(t0 + timedelta(minutes=15), 102.5, 102.8, 101.0, 102.2),
        _bar(t0 + timedelta(minutes=30), 103, 103.4, 102.5, 103.1),
        _bar(t0 + timedelta(minutes=45), 103, 103.4, 102.5, 103.2),
    )
    enrolled_at = t0 + timedelta(minutes=30)
    assert _post_enrollment_touch_indices(
        rows,
        zone=zone,
        enrolled_at=enrolled_at,
    ) == ()


def test_inside_at_enrollment_does_not_create_false_prospective_touch():
    zone = _zone()
    t0 = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
    rows = [
        _bar(t0, 103, 103.5, 102.5, 103),
        _bar(t0 + timedelta(minutes=15), 102.5, 102.8, 101.0, 102.2),
        _bar(t0 + timedelta(minutes=30), 102.2, 102.7, 101.2, 102.0),
        _bar(t0 + timedelta(minutes=45), 103.0, 103.5, 102.5, 103.2),
    ]
    # Add enough outside bars so the non-overlap horizon is satisfied, then re-enter.
    for i in range(16):
        ts = t0 + timedelta(minutes=60 + 15 * i)
        rows.append(_bar(ts, 103.0, 103.4, 102.4, 103.1))
    touch_ts = t0 + timedelta(minutes=60 + 15 * 16)
    rows.append(_bar(touch_ts, 102.5, 102.8, 101.4, 102.1))

    indices = _post_enrollment_touch_indices(
        tuple(rows),
        zone=zone,
        enrolled_at=t0 + timedelta(minutes=30),
    )
    assert len(indices) == 1
    assert rows[indices[0]].timestamp == touch_ts


def test_prospective_summary_never_grants_promotion_authority():
    rows = []
    for i in range(60):
        hold = i < 50
        rows.append(
            {
                "episode_type": "SUPPLY_DEMAND_V184_REACTION",
                "status": "HOLD" if hold else "BREAK",
                "direction": "LONG",
                "metadata": {
                    "timeframe": "H1",
                    "primary_candidate_match": True,
                },
            }
        )
    summary = _prospective_summary(rows)
    candidate = summary["primary_candidate"]
    assert candidate["n"] == 60
    assert candidate["precision_hold"] == 50 / 60
    assert candidate["promotion_authority"] is False
    assert summary["decision"] in {
        "PROSPECTIVE_REPLICATION_SIGNAL_NOT_PROMOTED",
        "COLLECTING_PROSPECTIVE_EVIDENCE",
    }


def test_small_high_precision_sample_stays_collecting():
    rows = [
        {
            "episode_type": "SUPPLY_DEMAND_V184_REACTION",
            "status": "HOLD",
            "direction": "LONG",
            "metadata": {
                "timeframe": "H1",
                "primary_candidate_match": True,
            },
        }
        for _ in range(20)
    ]
    summary = _prospective_summary(rows)
    assert summary["primary_candidate"]["precision_hold"] == 1.0
    assert summary["primary_candidate"]["replication_gate_met"] is False
    assert summary["decision"] == "COLLECTING_PROSPECTIVE_EVIDENCE"
