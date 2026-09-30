from datetime import UTC, datetime, timedelta

from fx_scanner.models import Bar
from fx_scanner.research_xau_precision_tp_ladder_v315 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    _holdout_gate,
    _replay_ladder,
    _summary,
)
from fx_scanner.research_xau_precision_tp_ladder_v315_runtime import (
    _heartbeat_evaluation,
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
    zone_id="demand",
    direction="LONG",
    low=100.0,
    high=102.0,
) -> ZoneDestination:
    return ZoneDestination(
        zone_id=zone_id,
        timeframe="H1",
        zone_class="STRUCTURAL",
        pattern="STRUCTURAL_DEMAND" if direction == "LONG" else "STRUCTURAL_SUPPLY",
        direction=direction,
        available_at=AT - timedelta(hours=2),
        low=low,
        high=high,
        atr_points=4.0,
        observation_hours=240,
        touched=False,
        first_touch_at=None,
        invalidated_at=None,
        expired_at=AT + timedelta(days=2),
        observation_complete=True,
    )


def test_v315_contract_is_research_only():
    assert ARTIFACT_CONTRACT == "XAU_PRECISION_TP_LADDER_V315_EVIDENCE_1"
    assert POLICY_EFFECT == "RESEARCH_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False


def test_v315_tp1_partial_then_runner_can_hit():
    source = _zone()
    opposite = _zone(
        zone_id="supply-next",
        direction="SHORT",
        low=103.0,
        high=104.0,
    )
    rows = (
        _bar(0, 104.0, 104.2, 103.8, 104.0),
        _bar(1, 104.0, 104.1, 101.8, 102.2),
        _bar(2, 102.2, 103.7, 102.0, 103.4),
        _bar(3, 103.4, 105.6, 102.6, 105.2),
    )
    times = tuple(row.timestamp for row in rows)
    result = _replay_ladder(
        rows=rows,
        times=times,
        zone=source,
        confirmation_at=AT,
        pocket={"low": 101.0, "high": 102.0},
        tp1_atr=0.25,
        tp1_fraction=0.50,
        runner_atr=0.75,
        destinations=(source, opposite),
    )
    assert result["filled"] is True
    assert result["tp1_hit"] is True
    assert result["runner_tp"] is True
    assert result["state"] == "TP1_AND_RUNNER_TP"
    assert result["precision_5_and_tp1"] is True
    assert result["net_r"] > 0
    assert result["tp1_next_opposite_h1"]["zone_id"] == "supply-next"
    assert result["tp1_next_opposite_h1"]["within_5_usd"] is True


def test_v315_break_even_only_activates_after_tp1_bar():
    source = _zone()
    rows = (
        _bar(0, 104.0, 104.2, 103.8, 104.0),
        _bar(1, 104.0, 104.1, 101.8, 102.2),
        # This bar goes below fill but not below original stop, then reaches TP1.
        # BE must not retroactively stop the trade on the TP1 bar.
        _bar(2, 102.2, 103.7, 101.9, 103.4),
        # Next bar revisits entry, so remaining runner exits at BE.
        _bar(3, 103.4, 103.6, 102.0, 102.4),
    )
    times = tuple(row.timestamp for row in rows)
    result = _replay_ladder(
        rows=rows,
        times=times,
        zone=source,
        confirmation_at=AT,
        pocket={"low": 101.0, "high": 102.0},
        tp1_atr=0.25,
        tp1_fraction=0.50,
        runner_atr=0.75,
        destinations=(source,),
    )
    assert result["filled"] is True
    assert result["tp1_hit"] is True
    assert result["runner_state"] == "BE_STOP"
    assert result["state"] == "TP1_THEN_BE"


def test_v315_summary_tracks_precision_and_opposite_zone_proximity():
    rows = (
        {
            "filled": True,
            "state": "TP1_AND_RUNNER_TP",
            "tp1_hit": True,
            "precision_5_and_tp1": True,
            "runner_tp": True,
            "runner_state": "RUNNER_TP",
            "net_r": 1.2,
            "max_adverse_usd": 1.0,
            "minutes_confirmation_to_fill": 10.0,
            "tp1_next_opposite_h1": {"gap_usd": 2.0, "within_5_usd": True},
        },
        {
            "filled": True,
            "state": "STOP_BEFORE_TP1",
            "tp1_hit": False,
            "precision_5_and_tp1": False,
            "runner_tp": False,
            "runner_state": "STOP_BEFORE_TP1",
            "net_r": -1.0,
            "max_adverse_usd": 2.0,
            "minutes_confirmation_to_fill": 20.0,
            "tp1_next_opposite_h1": None,
        },
    )
    summary = _summary(rows, opportunities=2)
    assert summary["fills"] == 2
    assert summary["tp1_hit_rate"] == 0.5
    assert summary["precision_5_and_tp1_rate"] == 0.5
    assert summary["runner_tp_rate_after_tp1"] == 1.0
    assert summary["tp1_opposite_h1_within_5_rate"] == 1.0


def test_v315_holdout_gate_requires_tp1_precision_and_expectancy():
    passing = {
        "fills": 40,
        "fill_rate": 0.50,
        "tp1_hit_rate": 0.72,
        "tp1_wilson_lower_95": 0.58,
        "precision_5_and_tp1_rate": 0.62,
        "profit_factor": 1.6,
        "profit_factor_unbounded": False,
        "avg_net_r": 0.25,
    }
    failing = {**passing, "precision_5_and_tp1_rate": 0.45}
    assert _holdout_gate(passing)["passed"] is True
    assert _holdout_gate(failing)["passed"] is False


def test_v315_supabase_heartbeat_excludes_full_grid_and_row_evidence():
    evaluation = {
        "research_version": "XAU_PRECISION_TP_LADDER_V315",
        "closed_m15_bars": 50000,
        "closed_m5_bars": 99999,
        "confirmed_v313_opportunities": 200,
        "development_opportunities": 120,
        "holdout_opportunities": 80,
        "entry_contract": {"entry_mode": "POCKET_PROXIMAL_LIMIT"},
        "selection_contract": {"selected_key": "X"},
        "selected_holdout": {
            "tp1_atr": 0.35,
            "tp1_fraction": 0.5,
            "runner_atr": 1.0,
            "summary": {"fills": 40},
            "results": [{"large": "row"}],
        },
        "development_grid": {"very": "large"},
        "holdout_gate": {"passed": True},
        "decision": "HOLDOUT_GATE_PASSED_FORWARD_DEMO_SHADOW_NEXT",
    }
    compact = _heartbeat_evaluation(evaluation)
    assert "development_grid" not in compact
    assert "results" not in compact["selected_holdout"]
    assert compact["selected_holdout"]["summary"]["fills"] == 40
    assert compact["full_evidence_location"] == "GITHUB_ACTIONS_ARTIFACT"
