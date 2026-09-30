from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_m5_pocket_entry_replay_v314 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    _holdout_gate,
    _raw_entry,
    _raw_stop,
    _replay,
    _summary,
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
        zone_id="h1",
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


def test_v314_contract_is_research_only():
    assert ARTIFACT_CONTRACT == "XAU_M5_POCKET_ENTRY_REPLAY_V314_EVIDENCE_1"
    assert POLICY_EFFECT == "RESEARCH_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False


def test_v314_entry_geometry_is_directional():
    pocket = {"low": 101.0, "high": 102.0}
    assert _raw_entry(
        entry_mode="POCKET_PROXIMAL_LIMIT",
        direction="LONG",
        pocket=pocket,
    ) == 102.0
    assert _raw_entry(
        entry_mode="POCKET_DEEP_LIMIT",
        direction="LONG",
        pocket=pocket,
    ) == 101.0
    assert _raw_entry(
        entry_mode="POCKET_PROXIMAL_LIMIT",
        direction="SHORT",
        pocket=pocket,
    ) == 101.0
    assert _raw_entry(
        entry_mode="POCKET_DEEP_LIMIT",
        direction="SHORT",
        pocket=pocket,
    ) == 102.0


def test_v314_h1_and_pocket_stop_are_distinct():
    zone = _zone("LONG")
    pocket = {"low": 101.0, "high": 102.0}
    pocket_stop = _raw_stop(
        stop_mode="POCKET_DISTAL_0P10_ATR",
        direction="LONG",
        pocket=pocket,
        zone=zone,
    )
    h1_stop = _raw_stop(
        stop_mode="H1_DISTAL_0P10_ATR",
        direction="LONG",
        pocket=pocket,
        zone=zone,
    )
    assert pocket_stop == 100.6
    assert h1_stop == 99.6
    assert h1_stop < pocket_stop


def test_v314_limit_replay_can_fill_and_hit_tp_with_stop_first_contract():
    zone = _zone("LONG")
    pocket = {"low": 101.0, "high": 102.0}
    rows = (
        _bar(0, 104.0, 104.2, 103.8, 104.0),
        _bar(1, 104.0, 104.1, 101.8, 102.2),
        _bar(2, 102.2, 103.0, 102.0, 102.8),
        _bar(3, 102.8, 105.5, 102.7, 105.2),
    )
    times = tuple(row.timestamp for row in rows)
    out = _replay(
        rows=rows,
        times=times,
        zone=zone,
        confirmation_at=AT,
        pocket=pocket,
        entry_mode="POCKET_PROXIMAL_LIMIT",
        stop_mode="POCKET_DISTAL_0P10_ATR",
        target_atr=0.75,
    )
    assert out["filled"] is True
    assert out["state"] == "TP"
    assert out["rr"] >= 1.5
    assert out["precision_5_and_tp"] is True


def test_v314_rr_floor_rejects_wide_h1_stop_for_small_target():
    zone = _zone("LONG")
    pocket = {"low": 101.0, "high": 102.0}
    rows = (
        _bar(0, 104.0, 104.1, 101.8, 102.0),
        _bar(1, 102.0, 103.0, 101.8, 102.5),
    )
    times = tuple(row.timestamp for row in rows)
    out = _replay(
        rows=rows,
        times=times,
        zone=zone,
        confirmation_at=AT,
        pocket=pocket,
        entry_mode="POCKET_PROXIMAL_LIMIT",
        stop_mode="H1_DISTAL_0P10_ATR",
        target_atr=0.50,
    )
    assert out["filled"] is False
    assert out["state"] == "RR_BELOW_1P5"


def test_v314_holdout_gate_requires_profit_and_precision():
    passing = {
        "fills": 40,
        "fill_rate": 0.50,
        "tp_rate": 0.65,
        "tp_wilson_lower_95": 0.50,
        "profit_factor": 1.8,
        "profit_factor_unbounded": False,
        "avg_net_r": 0.30,
        "precision_5_and_tp_rate": 0.60,
    }
    failing = {**passing, "profit_factor": 1.1}
    assert _holdout_gate(passing)["passed"] is True
    assert _holdout_gate(failing)["passed"] is False


def test_v314_summary_does_not_emit_infinite_profit_factor():
    rows = (
        {
            "filled": True,
            "state": "TP",
            "net_r": 1.0,
            "precision_5_and_tp": True,
            "minutes_confirmation_to_fill": 5.0,
            "max_adverse_usd": 0.5,
        },
    )
    out = _summary(rows, opportunities=1)
    assert out["profit_factor"] is None
    assert out["profit_factor_unbounded"] is True
