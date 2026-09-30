from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fx_scanner.demo_xau_decision_center_v296 import (
    _engine_direction,
    _geometry_candidates,
    _v171_direction,
)
from fx_scanner.xau_decision_meta_v296 import (
    build_meta_decision,
    calibrate_outcomes,
)


def _calibrated(wins: int, losses: int):
    rows = [
        {"tp1_hit": True, "stop_hit": False, "outcome_class": "TP1", "mfe_r": 1.2, "mae_r": 0.2}
        for _ in range(wins)
    ] + [
        {"tp1_hit": False, "stop_hit": True, "outcome_class": "STOP", "mfe_r": 0.2, "mae_r": 1.0}
        for _ in range(losses)
    ]
    return calibrate_outcomes(rows)


def test_v296_large_forward_sample_gets_more_reliability_than_no_sample() -> None:
    empty = calibrate_outcomes([])
    proven = _calibrated(24, 6)
    assert empty["state"] == "NO_DECISIVE_SAMPLE"
    assert proven["state"] == "CALIBRATED"
    assert proven["reliability_multiplier"] > empty["reliability_multiplier"]
    assert proven["win_rate"] == 0.8


def test_v296_meta_consensus_is_weighted_and_selects_one_intact_geometry() -> None:
    votes = [
        {
            "engine": "RIZAN_DEPTH",
            "direction": "SHORT",
            "available": True,
            "base_weight": 1.2,
            "freshness_factor": 1.0,
            "calibration": _calibrated(22, 8),
        },
        {
            "engine": "V182_STRUCTURE",
            "direction": "SHORT",
            "available": True,
            "base_weight": 0.6,
            "freshness_factor": 1.0,
            "calibration": _calibrated(20, 10),
        },
        {
            "engine": "M15_SMC_RECLAIM",
            "direction": "LONG",
            "available": True,
            "base_weight": 0.7,
            "freshness_factor": 1.0,
            "calibration": _calibrated(8, 12),
        },
    ]
    geometry = [
        {
            "engine": "RIZAN_DEPTH",
            "signal_id": "rizan",
            "direction": "SHORT",
            "state": "ARMED",
            "score": 93,
            "entry_low": 4180.2,
            "entry_high": 4198.0,
            "sl": 4200.6,
            "tp1": 4149.7,
            "tp2": 4149.7,
            "rr2": 3.4,
            "active_guards": ["M5_ACTUAL_ENTRY_REQUIRED"],
            "geometry_authority": True,
            "research_probe_eligible": True,
            "calibration": _calibrated(22, 8),
        },
        {
            "engine": "OTHER",
            "signal_id": "other",
            "direction": "SHORT",
            "state": "SETUP_FORMING",
            "score": 99,
            "entry_low": 4190.0,
            "entry_high": 4191.0,
            "sl": 4202.0,
            "tp1": 4160.0,
            "tp2": 4150.0,
            "rr2": 2.0,
            "active_guards": [],
            "geometry_authority": False,
            "research_probe_eligible": False,
            "calibration": _calibrated(28, 2),
        },
    ]

    decision = build_meta_decision(
        votes=votes,
        geometry_candidates=geometry,
        gates=[],
        possible_base_weight=2.5,
    )

    assert decision["consensus_direction"] == "SHORT"
    assert decision["geometry"]["signal_id"] == "rizan"
    assert decision["geometry"]["entry_low"] == 4180.2
    assert decision["geometry"]["entry_high"] == 4198.0
    assert decision["action"] == "DEMO_RESEARCH_PROBE_ELIGIBLE"
    assert decision["execution_authority"] is False


def test_v296_hard_gate_overrides_execution_ready_geometry() -> None:
    votes = [
        {
            "engine": "RIZAN_DEPTH",
            "direction": "LONG",
            "available": True,
            "base_weight": 1.2,
            "freshness_factor": 1.0,
            "calibration": _calibrated(24, 6),
        }
    ]
    geometry = [
        {
            "engine": "RIZAN_DEPTH",
            "signal_id": "ready",
            "direction": "LONG",
            "state": "EXECUTION_READY",
            "score": 95,
            "entry_low": 4172.0,
            "entry_high": 4175.0,
            "sl": 4143.0,
            "tp1": 4200.0,
            "tp2": 4250.0,
            "rr2": 2.5,
            "active_guards": [],
            "geometry_authority": True,
            "research_probe_eligible": True,
            "calibration": _calibrated(24, 6),
        }
    ]
    gates = [{"name": "PRESSURE", "hard_block": True, "warning": False}]

    decision = build_meta_decision(
        votes=votes,
        geometry_candidates=geometry,
        gates=gates,
        possible_base_weight=1.2,
    )

    assert decision["broker_eligible"] is False
    assert decision["research_probe_eligible"] is False
    assert decision["action"] == "PREPARE_WAIT_CONFIRMATION"


def test_v296_v171_excludes_rizan_component_from_macro_prior() -> None:
    details = {
        "ensemble": {
            "components": {
                "rizan": {"available": True, "direction": "LONG", "direction_score": 1.0},
                "conditional": {"available": True, "direction": "SHORT", "direction_score": -0.7},
                "cot": {"available": True, "direction": "SHORT", "direction_score": -0.35},
                "acd": {"available": False},
            }
        }
    }
    assert _v171_direction(details) == "SHORT"


def test_v296_engine_no_trade_is_abstain() -> None:
    hb = {
        "details": {
            "signal_direction": "LONG",
            "signal_reason": "MODEL_NO_TRADE",
            "execution_ready": 0,
        }
    }
    direction, reason = _engine_direction("M15_SMC_RECLAIM", hb)
    assert direction is None
    assert reason == "MODEL_NO_TRADE"


def test_v296_rizan_geometry_marks_research_probe_only_when_runtime_gates_allow() -> None:
    signals = [
        {
            "id": "sig",
            "observed_at": datetime.now(tz=UTC).isoformat(),
            "state": "ARMED",
            "direction": "SHORT",
            "setup_type": "RIZAN_DEPTH_RETEST_CONFIRMATION_WINDOW",
            "final_score": 93,
            "entry_low": 4180.2,
            "entry_high": 4198.0,
            "sl": 4200.6,
            "tp1": 4149.7,
            "tp2": 4149.7,
            "rr1": 3.4,
            "rr2": 3.4,
            "active_guards": ["M5_ACTUAL_ENTRY_REQUIRED"],
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
    ]
    child_hb = {
        "details": {
            "pressure_transition": {
                "hard_block": False,
                "calibration_entry_allowed": True,
            },
            "reversal_stage": {
                "hard_execution_block": False,
                "setup_invalid": False,
                "terminal_rr_ok": True,
            },
            "dynamic_depth_hazard": {
                "action": "ENTRY_WINDOW",
                "current_depth": 0.846,
            },
        }
    }
    rows = _geometry_candidates(
        signals,
        {"RIZAN_DEPTH": _calibrated(20, 10)},
        child_hb,
        datetime.now(tz=UTC),
    )
    assert len(rows) == 1
    assert rows[0]["research_probe_eligible"] is True
    assert rows[0]["geometry_authority"] is True



def test_v296_dashboard_and_execution_lane_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    dashboard = (root / "streamlit_app.py").read_text()
    workflow = (
        root / ".github" / "workflows" / "ctrader-demo-xau-execution-lane.yml"
    ).read_text()

    assert '"ctrader_demo_xau_decision_center_v296"' in dashboard
    assert "Kesimpulan Final Ensemble V296" in dashboard
    assert "Confidence ensemble bukan winrate" in dashboard
    assert "Entry/SL/TP antar-engine tidak pernah dirata-ratakan" in dashboard
    assert "Lihat keputusan & kalibrasi tiap engine" in dashboard
    assert "python -m fx_scanner.demo_xau_decision_center_v296" in workflow
    assert "continue-on-error: true" in workflow



def test_v298_wait_keeps_dominant_bias_and_reference_geometry() -> None:
    votes = [
        {
            "engine": "V182_STRUCTURE",
            "direction": "SHORT",
            "available": True,
            "base_weight": 0.60,
            "freshness_factor": 1.0,
            "calibration": {"reliability_multiplier": 0.35},
        },
        {
            "engine": "M15_SMC_RECLAIM",
            "direction": "LONG",
            "available": True,
            "base_weight": 0.70,
            "freshness_factor": 1.0,
            "calibration": {"reliability_multiplier": 0.35},
        },
        {
            "engine": "V171_ENSEMBLE",
            "direction": "SHORT",
            "available": True,
            "base_weight": 0.50,
            "freshness_factor": 1.0,
            "calibration": {"reliability_multiplier": 0.35},
        },
    ]
    geometry = [
        {
            "engine": "RIZAN_DEPTH",
            "signal_id": "short-ref",
            "direction": "SHORT",
            "entry_low": 4190.0,
            "entry_high": 4198.0,
            "sl": 4202.0,
            "tp1": 4175.0,
            "tp2": 4149.0,
            "rr2": 2.5,
            "state": "ARMED",
            "geometry_authority": True,
            "research_probe_eligible": False,
            "active_guards": ["WAIT_CONFIRMATION"],
        },
        {
            "engine": "M15_SMC_RECLAIM",
            "signal_id": "long-ref",
            "direction": "LONG",
            "entry_low": 4170.0,
            "entry_high": 4174.0,
            "sl": 4158.0,
            "tp1": 4190.0,
            "tp2": 4200.0,
            "rr2": 2.0,
            "state": "ARMED",
            "geometry_authority": False,
            "research_probe_eligible": False,
            "active_guards": [],
        },
    ]
    decision = build_meta_decision(
        votes=votes,
        geometry_candidates=geometry,
        gates=[],
    )

    assert decision["consensus_direction"] == "WAIT"
    assert decision["dominant_direction"] == "SHORT"
    assert decision["geometry"] == {}
    assert decision["reference_geometry"]["signal_id"] == "short-ref"
    assert decision["reference_geometry_execution_authority"] is False
    assert decision["action"] == "WAIT_ENGINE_CONFLICT"
