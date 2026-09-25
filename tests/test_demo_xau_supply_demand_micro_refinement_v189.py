from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_supply_demand_micro_refinement_v189 import (
    CONTRACT,
    evaluate_micro_refinement,
)
from fx_scanner.models import Bar


def _bar(ts, o, h, l, c):
    return Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=ts,
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        tick_count=100,
        spread_avg=0.0,
        spread_max=0.0,
    )


def _path(direction="LONG", timeframe="H1"):
    source = {
        "zone_id": "source-1",
        "timeframe": timeframe,
        "direction": direction,
        "low": 100.0,
        "high": 110.0,
        "proximal": 105.0 if direction == "LONG" else 105.0,
        "distal": 100.0 if direction == "LONG" else 110.0,
        "available_at": "2026-09-23T18:00:00+00:00",
    }
    return {
        "active_path": {
            "reaction_direction": direction,
            "source_zone": source,
        }
    }


def test_v189_contract_is_shadow_only():
    result = evaluate_micro_refinement(
        (),
        path_map={},
        as_of=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert CONTRACT == "XAU_SUPPLY_DEMAND_M5_MICRO_REFINEMENT_V189"
    assert result["execution_influence"] is False
    assert result["execution_authority"] is False
    assert result["state"] == "NO_ACTIVE_REACTION_PATH"


def test_v189_waits_for_h1_precision_source():
    result = evaluate_micro_refinement(
        (),
        path_map=_path(timeframe="H4"),
        as_of=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert result["state"] == "WAIT_H1_PRECISION_SOURCE"


def test_long_refinement_detects_reclaim_mss_and_displacement():
    t0 = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    bars = []
    for i in range(22):
        ts = t0 + timedelta(minutes=5 * i)
        if i == 15:
            bars.append(_bar(ts, 107.5, 111.0, 106.5, 108.5))
        elif i in {14, 16}:
            bars.append(_bar(ts, 107.0, 109.0, 106.0, 107.5))
        else:
            bars.append(_bar(ts, 106.5, 109.0, 105.5, 107.0))

    # Deep touch/sweep candidate, then proximal reclaim, then bullish displacement
    # through the pre-sweep M5 swing high.
    bars.append(_bar(t0 + timedelta(minutes=110), 108.0, 108.5, 101.0, 103.0))
    bars.append(_bar(t0 + timedelta(minutes=115), 103.0, 107.0, 102.5, 106.0))
    bars.append(_bar(t0 + timedelta(minutes=120), 106.0, 113.0, 105.5, 112.0))

    # Add completed post-trigger bars so as_of is safely beyond the last bar.
    for i in range(25, 45):
        ts = t0 + timedelta(minutes=5 * i)
        bars.append(_bar(ts, 111.0, 113.0, 110.0, 112.0))

    result = evaluate_micro_refinement(
        tuple(bars),
        path_map=_path(),
        as_of=t0 + timedelta(minutes=5 * 46),
    )
    assert result["state"] == "M5_REFINEMENT_CONFIRMED_SHADOW"
    assert result["direction"] == "LONG"
    assert result["sweep"]["price"] == 101.0
    assert result["reclaim_confirmed"] is True
    assert result["mss_confirmed"] is True
    assert result["displacement_confirmed"] is True
    assert result["mss_level"] == 111.0
    assert result["refined_entry_pocket"] is not None
    assert result["refined_entry_pocket"]["source"] == "LAST_OPPOSITE_M5_CANDLE_BEFORE_DISPLACEMENT"
    assert result["execution_authority"] is False


def test_long_touch_without_mss_remains_prepare_only():
    t0 = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    bars = []
    for i in range(40):
        ts = t0 + timedelta(minutes=5 * i)
        if i == 20:
            bars.append(_bar(ts, 107.0, 111.0, 106.0, 108.0))
        elif i == 25:
            bars.append(_bar(ts, 108.0, 108.5, 101.5, 103.0))
        elif i >= 26:
            bars.append(_bar(ts, 103.0, 109.5, 102.5, 106.0))
        else:
            bars.append(_bar(ts, 106.0, 109.0, 105.0, 107.0))

    result = evaluate_micro_refinement(
        tuple(bars),
        path_map=_path(),
        as_of=t0 + timedelta(minutes=5 * 41),
    )
    assert result["reclaim_confirmed"] is True
    assert result["mss_confirmed"] is False
    assert result["state"] == "M5_RECLAIM_WAIT_MSS"
    assert result["refined_entry_pocket"] is None


def test_v189_ignores_touch_before_source_available_at():
    t0 = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    path = _path()
    path["active_path"]["source_zone"]["available_at"] = (
        t0 + timedelta(minutes=120)
    ).isoformat()
    bars = []
    for i in range(50):
        ts = t0 + timedelta(minutes=5 * i)
        if i == 10:
            bars.append(_bar(ts, 108.0, 109.0, 101.0, 103.0))
        else:
            bars.append(_bar(ts, 115.0, 116.0, 114.0, 115.0))

    result = evaluate_micro_refinement(
        tuple(bars),
        path_map=path,
        as_of=t0 + timedelta(minutes=5 * 51),
    )
    assert result["state"] == "WAIT_SOURCE_TOUCH"
    assert result["pre_source_touch_count_ignored"] == 1
    assert result["source_available_at"] == (
        t0 + timedelta(minutes=120)
    ).isoformat()


def test_v189_uses_only_post_source_touch_for_refinement():
    t0 = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    path = _path()
    available = t0 + timedelta(minutes=100)
    path["active_path"]["source_zone"]["available_at"] = available.isoformat()
    bars = []
    for i in range(50):
        ts = t0 + timedelta(minutes=5 * i)
        if i == 10:
            # Deeper stale touch before source availability. Must be ignored.
            bars.append(_bar(ts, 108.0, 109.0, 100.5, 103.0))
        elif i == 22:
            bars.append(_bar(ts, 107.0, 111.0, 106.0, 108.0))
        elif i == 25:
            # First eligible post-source sweep.
            bars.append(_bar(ts, 108.0, 108.5, 102.0, 103.0))
        elif i == 26:
            bars.append(_bar(ts, 103.0, 107.0, 102.5, 106.0))
        elif i == 27:
            bars.append(_bar(ts, 106.0, 113.5, 105.5, 112.5))
        else:
            bars.append(_bar(ts, 106.0, 109.0, 105.5, 107.0))

    result = evaluate_micro_refinement(
        tuple(bars),
        path_map=path,
        as_of=t0 + timedelta(minutes=5 * 51),
    )
    assert result["state"] == "M5_REFINEMENT_CONFIRMED_SHADOW"
    assert result["sweep"]["price"] == 102.0
    assert result["sweep"]["at"] == (t0 + timedelta(minutes=125)).isoformat()
    assert result["pre_source_touch_count_ignored"] >= 1
    assert result["refined_entry_pocket"]["origin_at"] >= available.isoformat()


def test_v189_fails_closed_when_source_available_at_missing():
    t0 = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    path = _path()
    path["active_path"]["source_zone"].pop("available_at")
    bars = tuple(
        _bar(
            t0 + timedelta(minutes=5 * i),
            106.0,
            109.0,
            105.0,
            107.0,
        )
        for i in range(50)
    )
    result = evaluate_micro_refinement(
        bars,
        path_map=path,
        as_of=t0 + timedelta(minutes=5 * 51),
    )
    assert result["state"] == "SOURCE_AVAILABILITY_UNKNOWN_NO_REFINEMENT"
    assert "refined_entry_pocket" not in result or result["refined_entry_pocket"] is None


def test_short_refinement_uses_local_post_touch_mss_before_far_structural_mss():
    t0 = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    path = _path(direction="SHORT")
    available = t0 + timedelta(minutes=100)
    path["active_path"]["source_zone"]["available_at"] = available.isoformat()

    bars = []
    for i in range(50):
        ts = t0 + timedelta(minutes=5 * i)
        if i == 15:
            # Old conservative 2-left/2-right structural swing, far from the
            # eventual source interaction.
            bars.append(_bar(ts, 94.0, 95.0, 90.0, 94.0))
        elif i < 20:
            bars.append(_bar(ts, 95.0, 96.0, 94.0, 95.0))
        elif i == 20:
            bars.append(_bar(ts, 104.0, 106.0, 103.8, 105.0))
        elif i == 21:
            bars.append(_bar(ts, 105.0, 106.5, 104.0, 105.5))
        elif i == 22:
            # Source-local 1-left/1-right internal low.
            bars.append(_bar(ts, 105.5, 106.0, 103.2, 104.8))
        elif i == 23:
            bars.append(_bar(ts, 104.8, 107.0, 103.5, 106.5))
        elif i == 24:
            # Lower low prevents the local pivot from also qualifying as the
            # conservative 2-left/2-right structural swing.
            bars.append(_bar(ts, 106.5, 108.5, 103.0, 108.0))
        elif i == 25:
            # High sweep inside the SHORT H1 source.
            bars.append(_bar(ts, 108.0, 109.5, 105.0, 106.5))
        elif i == 26:
            # Reclaim below proximal=105, but no close below local MSS yet.
            bars.append(_bar(ts, 106.5, 107.0, 102.8, 104.5))
        elif i == 27:
            # Bearish displacement breaks local MSS while the old structural
            # swing at 90 remains untouched.
            bars.append(_bar(ts, 104.5, 104.8, 101.0, 102.0))
        else:
            bars.append(_bar(ts, 102.5, 104.0, 101.0, 102.5))

    result = evaluate_micro_refinement(
        tuple(bars),
        path_map=path,
        as_of=t0 + timedelta(minutes=5 * 51),
    )

    assert result["direction"] == "SHORT"
    assert result["reclaim_confirmed"] is True
    assert result["mss_scope"] == "LOCAL_EXECUTABLE"
    assert result["mss_basis"] == "POST_SOURCE_TOUCH_INTERNAL_M5_SWING"
    assert result["mss_level"] == 103.2
    assert result["local_mss_level"] == 103.2
    assert result["structural_mss_level"] == 90.0
    assert result["mss_confirmed"] is True
    assert result["structural_mss_confirmed"] is False
    assert result["displacement_confirmed"] is True
    assert result["state"] == "M5_REFINEMENT_CONFIRMED_SHADOW"
    assert result["refined_entry_pocket"] is not None
    assert result["execution_authority"] is False




def test_v219_h1_child_break_inside_valid_h4_parent_preserves_candidate():
    t0 = datetime(2026, 9, 25, 7, 0, tzinfo=UTC)
    path = _path(direction="LONG")
    path["active_path"]["source_zone"]["available_at"] = t0.isoformat()
    parent = {
        "zone_id": "parent-h4",
        "timeframe": "H4",
        "direction": "LONG",
        "low": 95.0,
        "high": 115.0,
        "proximal": 105.0,
        "distal": 95.0,
        "available_at": t0.isoformat(),
        "lifecycle": {"active": True},
    }

    bars = []
    for i in range(45):
        ts = t0 + timedelta(minutes=5 * i)
        if i == 25:
            # H1 distal=100 is broken on close, but the sweep stays inside the
            # still-valid H4 parent. This is exactly the parent-reversal case
            # V219 must keep visible as a candidate.
            bars.append(_bar(ts, 102.0, 104.0, 97.0, 98.0))
        elif i > 25:
            bars.append(_bar(ts, 99.0, 103.0, 98.0, 100.0))
        else:
            bars.append(_bar(ts, 106.0, 109.0, 105.0, 107.0))

    result = evaluate_micro_refinement(
        tuple(bars),
        path_map=path,
        as_of=t0 + timedelta(minutes=5 * 46),
        parent_source_zone=parent,
    )

    rescue = result["parent_reversal_rescue"]
    assert rescue["active"] is True
    assert rescue["parent_timeframe"] == "H4"
    assert rescue["parent_contains_sweep"] is True
    assert rescue["mode"] in {
        "HTF_PARENT_OWNS_SWEEP_WAIT_CONFIRMATION",
        "HTF_PARENT_WITH_LIVE_M5_REVERSAL",
    }
    assert result["state"] != "SOURCE_INVALIDATED_NO_REFINEMENT"
    assert result["candidate_entry_pocket"]
    assert result["execution_authority"] is False
