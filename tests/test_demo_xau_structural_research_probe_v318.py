from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fx_scanner.demo_xau_structural_research_probe_v318 import (
    _explicit_risk_block,
    _select_probe_geometry,
    probe_signal_id,
)


def test_v318_confirmation_only_h1_can_form_early_demo_probe_without_m15() -> None:
    plan = {
        "direction": "SHORT",
        "source_timeframe": "H1",
        "entry_low": 100.0,
        "entry_high": 120.0,
        "sl": 125.0,
        "tp1": 100.0,
        "tp2": 90.0,
        "confirmation_window_only": True,
        "confirmation_entry_reference": 110.0,
        "broker_entry_authorized": False,
        "plan_id": "RZ229-test",
        "candidate_key": "candidate-short-h1",
        "source_layer": "V182_ACTIVE_H1_HISTORICAL_HOTSPOT",
        "structural_stop_zone_id": "h1-supply",
        "children": [],
    }
    geometry, reason = _select_probe_geometry(
        plan=plan,
        bid=105.0,
        ask=105.2,
    )
    assert reason == "STRUCTURAL_PROBE_ELIGIBLE"
    assert geometry is not None
    assert geometry["entry"] == 110.0
    assert geometry["tp"] == 90.0
    assert geometry["rr"] > 1.0
    assert geometry["m15_confirmation_bypassed_for_demo_research"] is True
    assert geometry["strict_broker_entry_authorized"] is False


def test_v318_pretouch_h4_uses_first_structural_reference() -> None:
    plan = {
        "direction": "LONG",
        "source_timeframe": "H4",
        "entry_low": 85.0,
        "entry_high": 95.0,
        "sl": 80.0,
        "tp1": 100.0,
        "tp2": 110.0,
        "confirmation_window_only": False,
        "broker_entry_authorized": True,
        "plan_id": "RZ229-long",
        "candidate_key": "candidate-long-h4",
        "source_layer": "H4_HISTORICAL_HOTSPOT",
        "structural_stop_zone_id": "h4-demand",
        "children": [
            {"slot": 1, "reference_price": 90.0},
            {"slot": 2, "reference_price": 88.0},
        ],
    }
    geometry, reason = _select_probe_geometry(
        plan=plan,
        bid=96.0,
        ask=96.2,
    )
    assert reason == "STRUCTURAL_PROBE_ELIGIBLE"
    assert geometry is not None
    assert geometry["entry"] == 90.0
    assert geometry["tp"] == 100.0
    assert geometry["rr"] == 1.0


def test_v318_rejects_m15_only_source_and_chasing_price() -> None:
    m15_plan = {
        "direction": "SHORT",
        "source_timeframe": "M15",
        "entry_low": 100.0,
        "entry_high": 110.0,
        "sl": 115.0,
        "tp1": 90.0,
    }
    geometry, reason = _select_probe_geometry(
        plan=m15_plan,
        bid=95.0,
        ask=95.2,
    )
    assert geometry is None
    assert reason == "STRUCTURAL_SOURCE_NOT_H4_H1"

    passed_plan = {
        "direction": "SHORT",
        "source_timeframe": "H1",
        "entry_low": 100.0,
        "entry_high": 110.0,
        "sl": 115.0,
        "tp1": 90.0,
        "confirmation_window_only": False,
        "children": [{"slot": 1, "reference_price": 105.0}],
    }
    geometry, reason = _select_probe_geometry(
        plan=passed_plan,
        bid=110.0,
        ask=110.2,
    )
    assert geometry is None
    assert reason == "NO_CHASE_LIMIT_SIDE_INVALID"


def test_v318_blocks_only_explicit_fresh_event_window_or_shock() -> None:
    now = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    event = {
        "healthy": True,
        "observed_at": now.isoformat(),
        "details": {"risk": {"state": "EVENT_WINDOW", "action": "NO_CHASE_WAIT_PRICE_DISCOVERY"}},
    }
    normal_shock = {
        "healthy": True,
        "observed_at": now.isoformat(),
        "details": {"state": "NORMAL", "shadow_action": "NO_SHADOW_BLOCK"},
    }
    blocked, reason, _ = _explicit_risk_block(
        event_heartbeat=event,
        shock_heartbeat=normal_shock,
        now=now,
    )
    assert blocked is True
    assert reason == "EVENT_WINDOW_BLOCK"

    clear_event = {
        "healthy": True,
        "observed_at": now.isoformat(),
        "details": {"risk": {"state": "CLEAR", "action": "NORMAL_EVENT_RISK_CONTEXT"}},
    }
    shock = {
        "healthy": True,
        "observed_at": now.isoformat(),
        "details": {"state": "SHOCK", "shadow_action": "OBSERVE_ONLY"},
    }
    blocked, reason, _ = _explicit_risk_block(
        event_heartbeat=clear_event,
        shock_heartbeat=shock,
        now=now,
    )
    assert blocked is True
    assert reason == "VOLATILITY_SHOCK_BLOCK"


def test_v318_signal_id_is_deterministic_per_structural_candidate() -> None:
    assert probe_signal_id("same") == probe_signal_id("same")
    assert probe_signal_id("same") != probe_signal_id("other")


def test_v318_runtime_contract_is_demo_only_and_not_dashboard_or_pressure_gated() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_structural_research_probe_v318.py"
    ).read_text()
    assert '"m15_confirmation_required": False' in source
    assert '"pressure_confirmation_required": False' in source
    assert '"structure_admission_required": False' in source
    assert '"dashboard_bridge_required": False' in source
    assert 'volume=LOT' in source
    assert 'LOT = 0.01' in source
    assert 'order_type=OrderType.LIMIT' in source
    assert 'stop_loss=float(geometry["sl"])' in source
    assert 'take_profit=float(geometry["tp"])' in source
