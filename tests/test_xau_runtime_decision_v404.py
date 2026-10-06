from __future__ import annotations

import fx_scanner.xau_runtime_decision_v404 as mod


def _v390(state: str, direction: str) -> dict:
    return {
        "state": state,
        "direction": direction,
        "price_now": 4200.0,
        "selected_zone": {"liquidity": [{"side": "SELL_SIDE", "price": 4198.0}]},
        "entry": {
            "low": 4198.0,
            "high": 4202.0,
            "invalidation": 4190.0,
            "tp1_opposite_local_zone": 4230.0,
        },
    }


def _v403(state: str, direction: str, reason: str = "TEST") -> dict:
    return {
        "state": state,
        "direction": direction,
        "reason": reason,
        "price_now": 4200.0,
        "entry_band": {"low": 4199.0, "high": 4201.0},
        "structural_invalidation": 4191.0,
        "validation_level": 4205.0,
        "targets": [4232.0],
        "liquidity": [{"side": "SELL_SIDE", "price": 4198.0}],
        "rr_first_target": 2.1,
    }


def _patch(monkeypatch, v390: dict, v403: dict) -> None:
    monkeypatch.setattr(mod, "evaluate_simple_reversal", lambda sd: v390)
    monkeypatch.setattr(
        mod,
        "evaluate_afiq_scanner_bridge_v403",
        lambda sd, event_risk=None: v403,
    )


def test_confirmed_alignment_becomes_grade_a_shadow(monkeypatch):
    _patch(monkeypatch, _v390("READY_LONG", "LONG"), _v403("CONFIRMED", "LONG"))

    result = mod.evaluate_runtime_decision_v404({"price_now": 4200.0})

    assert result["state"] == "READY_CONFIRMED"
    assert result["direction"] == "LONG"
    assert result["grade"] == "A"
    assert result["research_candidate"] is True
    assert result["execution_authority"] is False
    assert result["demo_auto_execution"] is False
    assert result["live_execution_enabled"] is False
    assert result["entry_band"] == {"low": 4199.0, "high": 4201.0}
    assert result["targets"] == [4232.0]


def test_early_alignment_becomes_grade_b_but_not_executable(monkeypatch):
    _patch(monkeypatch, _v390("READY_SHORT", "SHORT"), _v403("EARLY_TAKE_RISK", "SHORT"))

    result = mod.evaluate_runtime_decision_v404({})

    assert result["state"] == "READY_EARLY"
    assert result["direction"] == "SHORT"
    assert result["grade"] == "B"
    assert result["research_candidate"] is True
    assert result["demo_auto_execution"] is False


def test_direction_conflict_fails_closed(monkeypatch):
    _patch(monkeypatch, _v390("READY_LONG", "LONG"), _v403("CONFIRMED", "SHORT"))

    result = mod.evaluate_runtime_decision_v404({})

    assert result["state"] == "WAIT_CONFLICT"
    assert result["direction"] == "WAIT"
    assert result["grade"] == "NONE"
    assert result["research_candidate"] is False


def test_event_block_has_priority(monkeypatch):
    _patch(
        monkeypatch,
        _v390("READY_LONG", "LONG"),
        _v403("BLOCKED_EVENT", "LONG", "HIGH_IMPACT_EVENT"),
    )

    result = mod.evaluate_runtime_decision_v404({}, event_risk={"state": "BLOCK"})

    assert result["state"] == "BLOCKED_EVENT"
    assert result["direction"] == "WAIT"
    assert result["reason"] == "HIGH_IMPACT_EVENT"
    assert result["research_candidate"] is False


def test_v403_unavailable_fails_closed(monkeypatch):
    _patch(monkeypatch, _v390("READY_LONG", "LONG"), _v403("UNAVAILABLE", "WAIT", "NO_DATA"))

    result = mod.evaluate_runtime_decision_v404({})

    assert result["state"] == "WAIT_V403_UNAVAILABLE"
    assert result["direction"] == "WAIT"
    assert result["reason"] == "NO_DATA"
    assert result["research_candidate"] is False


def test_geometry_falls_back_to_v390_when_v403_has_no_geometry(monkeypatch):
    v403 = _v403("WATCH_ZONE", "LONG")
    v403["entry_band"] = {}
    v403["structural_invalidation"] = None
    v403["targets"] = []
    _patch(monkeypatch, _v390("READY_LONG", "LONG"), v403)

    result = mod.evaluate_runtime_decision_v404({})

    assert result["state"] == "WATCH_QUALITY_GATE"
    assert result["entry_band"] == {"low": 4198.0, "high": 4202.0}
    assert result["structural_invalidation"] == 4190.0
    assert result["targets"] == [4230.0]
