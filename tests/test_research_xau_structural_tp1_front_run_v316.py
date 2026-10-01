from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_structural_tp1_front_run_v316 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    _gate,
    _structural_tp1_atr,
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


def _zone(
    zone_id: str,
    direction: str,
    low: float,
    high: float,
    atr_points: float = 10.0,
) -> ZoneDestination:
    return ZoneDestination(
        zone_id=zone_id,
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        direction=direction,
        available_at=AT - timedelta(hours=1),
        low=low,
        high=high,
        atr_points=atr_points,
        observation_hours=240,
        touched=False,
        first_touch_at=None,
        invalidated_at=None,
        expired_at=AT + timedelta(days=2),
        observation_complete=True,
    )


def test_v316_contract_is_research_only():
    assert ARTIFACT_CONTRACT == "XAU_STRUCTURAL_TP1_FRONT_RUN_V316_EVIDENCE_1"
    assert POLICY_EFFECT == "RESEARCH_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False


def test_v316_structural_tp1_front_runs_opposite_h1_zone():
    demand = _zone("demand", "LONG", 100.0, 102.0, 10.0)
    supply = _zone("supply", "SHORT", 106.0, 108.0, 10.0)
    rows = (
        _bar(0, 104.0, 104.2, 103.8, 104.0),
        _bar(1, 104.0, 104.1, 101.8, 102.2),
        _bar(2, 102.2, 103.0, 102.0, 102.8),
    )
    tp_atr, meta = _structural_tp1_atr(
        mode="OPP_H1_FRONT_RUN_0P50_USD",
        zone=demand,
        pocket={"low": 101.0, "high": 102.0},
        confirmation_at=AT,
        m5_rows=rows,
        destinations=(demand, supply),
    )
    assert tp_atr is not None
    assert meta["state"] == "STRUCTURAL_TARGET_AVAILABLE"
    assert meta["opposite_h1"]["zone_id"] == "supply"
    assert meta["structural_target"] == 105.5
    assert 0 < tp_atr < 1.0


def test_v316_hybrid_uses_nearer_of_fixed_and_structural():
    demand = _zone("demand", "LONG", 100.0, 102.0, 10.0)
    supply = _zone("supply", "SHORT", 103.0, 104.0, 10.0)
    rows = (
        _bar(0, 104.0, 104.2, 103.8, 104.0),
        _bar(1, 104.0, 104.1, 101.8, 102.2),
        _bar(2, 102.2, 102.8, 102.0, 102.6),
    )
    tp_atr, meta = _structural_tp1_atr(
        mode="HYBRID_NEARER_FIXED_0P25_OR_STRUCT_0P50",
        zone=demand,
        pocket={"low": 101.0, "high": 102.0},
        confirmation_at=AT,
        m5_rows=rows,
        destinations=(demand, supply),
    )
    assert tp_atr is not None
    assert tp_atr <= 0.25 + 1e-12
    assert meta["target_basis"] in {"FIXED_0P25", "STRUCTURAL_0P50"}


def test_v316_holdout_gate_remains_strict():
    passing = {
        "fills": 40,
        "fill_rate": 0.50,
        "tp1_hit_rate": 0.70,
        "tp1_wilson_lower_95": 0.58,
        "precision_5_and_tp1_rate": 0.60,
        "profit_factor": 1.5,
        "profit_factor_unbounded": False,
        "avg_net_r": 0.20,
    }
    failing = {**passing, "tp1_hit_rate": 0.61}
    assert _gate(passing)["passed"] is True
    assert _gate(failing)["passed"] is False
