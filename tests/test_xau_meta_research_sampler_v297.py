from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import fx_scanner.demo_xau_meta_research_sampler_v297 as sampler


def _decision() -> dict:
    return {
        "decision_signature": "a" * 24,
        "action": "DEMO_RESEARCH_PROBE_ELIGIBLE",
        "consensus_direction": "SHORT",
        "confidence": 44.0,
        "agreement": 0.71,
        "coverage": 0.62,
        "research_probe_eligible": True,
        "hard_blocks": [],
        "geometry": {
            "engine": "RIZAN_DEPTH",
            "signal_id": "parent",
            "direction": "SHORT",
            "state": "ARMED",
            "aligned_parent": True,
            "research_probe_eligible": True,
            "entry_low": 4190.0,
            "entry_high": 4198.0,
            "sl": 4202.0,
            "tp1": 4175.0,
            "tp2": 4150.0,
        },
    }


def test_v297_meta_signal_id_is_deterministic_uuid_per_signature() -> None:
    first = sampler.meta_signal_id("abc")
    second = sampler.meta_signal_id("abc")
    other = sampler.meta_signal_id("def")
    assert first == second
    assert first != other
    assert str(UUID(first)) == first


def test_v297_research_eligibility_requires_meta_action_rizan_geometry_and_no_block() -> None:
    decision = _decision()
    assert sampler._research_eligible(decision) == (
        True,
        "META_RESEARCH_ELIGIBLE:CONSENSUS_RESEARCH",
    )

    blocked = dict(decision, hard_blocks=[{"name": "PRESSURE"}])
    assert sampler._research_eligible(blocked)[0] is False

    wrong_action = dict(decision, action="PREPARE_WAIT_CONFIRMATION")
    assert sampler._research_eligible(wrong_action)[0] is False

    wrong_geometry = dict(decision)
    wrong_geometry["geometry"] = dict(decision["geometry"], engine="OTHER")
    assert sampler._research_eligible(wrong_geometry)[0] is False


def test_v297_actual_micro_entry_reuses_real_m5_pocket_and_depth_gate(monkeypatch) -> None:
    atlas = {
        "micro_refinement": {
            "direction": "SHORT",
            "refined_entry_pocket": {"low": 4193.0, "high": 4195.0},
        },
        "path_map": {
            "active_path": {
                "source_zone": {
                    "direction": "SHORT",
                    "low": 4190.0,
                    "high": 4198.0,
                }
            }
        },
    }
    child_details = {
        "dynamic_depth_hazard": {
            "recommended_depth_low": 0.70,
            "recommended_depth_high": 0.90,
        },
        "pressure_transition": {
            "hard_block": False,
            "calibration_entry_allowed": True,
        },
        "reversal_stage": {
            "hard_execution_block": False,
            "setup_invalid": False,
        },
    }
    monkeypatch.setattr(
        sampler,
        "child_reference_depth",
        lambda **_kwargs: 0.82,
    )
    entry, depth, activation = sampler._actual_micro_entry(
        direction="SHORT",
        geometry=_decision()["geometry"],
        atlas_eval=atlas,
        v226_eval={},
        child_details=child_details,
        bid=4192.0,
        ask=4192.2,
    )
    assert entry == 4195.0
    assert depth == 0.82
    assert activation == "M5_REFINED_CALIBRATION_PROBE"


def test_v297_actual_micro_entry_blocks_beyond_85pct(monkeypatch) -> None:
    atlas = {
        "micro_refinement": {
            "direction": "SHORT",
            "candidate_entry_pocket": {"low": 4193.0, "high": 4195.0},
        },
        "path_map": {
            "active_path": {
                "source_zone": {
                    "direction": "SHORT",
                    "low": 4190.0,
                    "high": 4198.0,
                }
            }
        },
    }
    child_details = {
        "dynamic_depth_hazard": {
            "recommended_depth_low": 0.70,
            "recommended_depth_high": 0.90,
        },
        "pressure_transition": {
            "hard_block": False,
            "calibration_entry_allowed": True,
        },
        "reversal_stage": {
            "hard_execution_block": False,
            "setup_invalid": False,
        },
    }
    monkeypatch.setattr(
        sampler,
        "child_reference_depth",
        lambda **_kwargs: 0.86,
    )
    monkeypatch.setattr(
        sampler,
        "_calibration_rejection_retest_entry",
        lambda **_kwargs: (None, "NO_REJECTION_RETEST"),
    )
    entry, depth, reason = sampler._actual_micro_entry(
        direction="SHORT",
        geometry=_decision()["geometry"],
        atlas_eval=atlas,
        v226_eval={},
        child_details=child_details,
        bid=4192.0,
        ask=4192.2,
    )
    assert entry is None
    assert depth == 0.86
    assert reason == "META_NO_CHASE_DEPTH"



def test_v297_deep_primary_can_fallback_to_v229_rejection_retest(monkeypatch) -> None:
    atlas = {
        "micro_refinement": {
            "direction": "SHORT",
            "candidate_entry_pocket": {"low": 4195.04, "high": 4199.01},
        },
        "path_map": {
            "active_path": {
                "source_zone": {
                    "direction": "SHORT",
                    "low": 4179.03,
                    "high": 4197.99,
                }
            }
        },
    }
    child_details = {
        "dynamic_depth_hazard": {
            "recommended_depth_low": 0.60,
            "recommended_depth_high": 0.70,
        },
        "pressure_transition": {
            "hard_block": False,
            "calibration_entry_allowed": True,
        },
        "reversal_stage": {
            "hard_execution_block": False,
            "setup_invalid": False,
        },
    }

    def depth(**kwargs):
        return 0.70 if float(kwargs["price"]) < 4194.0 else 0.95

    monkeypatch.setattr(sampler, "child_reference_depth", depth)
    monkeypatch.setattr(
        sampler,
        "_calibration_rejection_retest_entry",
        lambda **_kwargs: (4192.302, "M5_CANDIDATE_REJECTION_RETEST_PROBE"),
    )

    entry, depth_value, activation = sampler._actual_micro_entry(
        direction="SHORT",
        geometry={
            "entry_low": 4180.23,
            "entry_high": 4197.99,
        },
        atlas_eval=atlas,
        v226_eval={},
        child_details=child_details,
        bid=4192.02,
        ask=4192.16,
    )

    assert entry == 4192.302
    assert depth_value == 0.70
    assert activation == "M5_CANDIDATE_REJECTION_RETEST_PROBE"


def test_v297_target_requires_at_least_one_r() -> None:
    target, rr = sampler._target_for_rr(
        direction="SHORT",
        entry=4195.0,
        stop=4202.0,
        geometry={"tp1": 4190.0, "tp2": 4175.0},
    )
    assert target == 4175.0
    assert rr is not None and rr > 2.0

    target, rr = sampler._target_for_rr(
        direction="SHORT",
        entry=4195.0,
        stop=4202.0,
        geometry={"tp1": 4190.0, "tp2": 4191.0},
    )
    assert target is None
    assert rr is None


class _SignalStore:
    def __init__(self):
        self.rows = []

    def write_signal_rows(self, rows):
        self.rows.extend(rows)


def test_v297_signal_row_is_outcome_ledger_compatible() -> None:
    store = _SignalStore()
    signal_id = sampler.meta_signal_id("sample")
    now = __import__("datetime").datetime.now(
        tz=__import__("datetime").timezone.utc
    )
    sampler._write_signal(
        store,
        signal_id=signal_id,
        decision=_decision(),
        direction="SHORT",
        entry=4195.0,
        stop=4202.0,
        target=4175.0,
        rr=20.0 / 7.0,
        now=now,
    )
    row = store.rows[0]
    assert row["id"] == signal_id
    assert row["setup_type"] == sampler.SETUP_TYPE
    assert row["state"] == "ARMED"
    assert row["entry_low"] == row["entry_high"] == 4195.0
    assert row["tp1"] == row["tp2"] == 4175.0
    assert row["active_guards"] == ["DEMO_META_RESEARCH_ONLY"]


class _CancelStore:
    def __init__(self):
        self.events = []

    def record_order_event(self, **kwargs):
        self.events.append(kwargs)


class _CancelSession:
    account_id = 123

    def __init__(self, order):
        self.order = order
        self.cancelled = []

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return SimpleNamespace(executionType=5)

    def reconcile(self):
        return SimpleNamespace(order=[], position=[])


def test_v297_stale_pending_is_cancelled_and_durably_audited() -> None:
    signal_id = sampler.meta_signal_id("old")
    order = SimpleNamespace(clientOrderId=signal_id, orderId=991)
    reconcile = SimpleNamespace(order=[order], position=[])
    store = _CancelStore()
    session = _CancelSession(order)

    actions, safe = sampler._cancel_stale_meta_pending(
        store=store,
        session=session,
        reconcile=reconcile,
        known_meta_ids={signal_id},
        keep_signal_id=None,
    )

    assert safe is True
    assert session.cancelled == [991]
    assert any("CANCEL_ACK" in action for action in actions)
    assert len(store.events) == 1
    assert store.events[0]["event_type"] == sampler.CANCEL_EVENT_TYPE
    assert store.events[0]["payload"]["reconciled_absent"] is True


def test_v297_workflow_and_dashboard_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / ".github" / "workflows" / "ctrader-demo-xau-execution-lane.yml"
    ).read_text()
    dashboard = (root / "streamlit_app.py").read_text()
    source = (
        root / "src" / "fx_scanner" / "demo_xau_meta_research_sampler_v297.py"
    ).read_text()

    assert 'CTRADER_DEMO_XAU_META_RESEARCH_SAMPLER_ENABLED: "1"' in workflow
    assert "python -m fx_scanner.demo_xau_meta_research_sampler_v297" in workflow
    assert "steps.build_xau_meta_decision.outcome == 'success'" in workflow
    assert '"ctrader_demo_xau_meta_research_sampler_v297"' in dashboard
    assert "Executed sample" in dashboard
    assert "Executed TP/Win rate" in dashboard
    assert "Wilson lower 95%" in dashboard
    assert "one_meta_position_or_pending_max" in source
    assert "DEMO_META_RESEARCH_ONLY" in source



def test_v301_conflict_research_selection_uses_dominant_reference_geometry() -> None:
    decision = {
        "action": "DEMO_CONFLICT_RESEARCH_PROBE_ELIGIBLE",
        "consensus_direction": "WAIT",
        "dominant_direction": "SHORT",
        "hard_blocks": [],
        "conflict_research_probe_eligible": True,
        "reference_geometry": {
            "engine": "RIZAN_DEPTH",
            "direction": "SHORT",
            "state": "ARMED",
            "aligned_parent": True,
            "research_probe_eligible": True,
            "signal_id": "parent-short",
        },
    }

    direction, geometry, mode = sampler._research_selection(decision)
    assert direction == "SHORT"
    assert geometry["signal_id"] == "parent-short"
    assert mode == "CONFLICT_DOMINANT_RESEARCH"
    assert sampler._research_eligible(decision) == (
        True,
        "META_RESEARCH_ELIGIBLE:CONFLICT_DOMINANT_RESEARCH",
    )


def test_v301_conflict_research_rejects_unaligned_reference_geometry() -> None:
    decision = {
        "action": "DEMO_CONFLICT_RESEARCH_PROBE_ELIGIBLE",
        "consensus_direction": "WAIT",
        "dominant_direction": "SHORT",
        "hard_blocks": [],
        "conflict_research_probe_eligible": True,
        "reference_geometry": {
            "engine": "RIZAN_DEPTH",
            "direction": "SHORT",
            "state": "ARMED",
            "aligned_parent": False,
            "research_probe_eligible": True,
            "signal_id": "stale-parent",
        },
    }
    assert sampler._research_eligible(decision) == (
        False,
        "META_GEOMETRY_PARENT_NOT_ALIGNED",
    )
