from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from datetime import datetime

from fx_scanner.demo_xau_v229_child_executor import (
    CHILD_CANCEL_EVENT_CODE,
    CHILD_CANCEL_EVENT_TYPE,
    _activation_entry,
    _calibration_probe_already_accepted,
    _calibration_probe_entry,
    _calibration_rejection_exit_stop_entry,
    _calibration_rejection_retest_entry,
    _cancel_pending_plan,
    _entry_inside_active_source,
    _existing_slots,
    _limit_side_valid,
    _pending_side_valid,
    _promote_armed_calibration_parent,
    _promote_armed_confirmation_window,
    _read_with_transient_retry,
    _slot_target,
    _source_depth_boundary_price,
    _target_with_min_rr,
)
from fx_scanner.demo_xau_v229_ladder_plan import child_client_order_id
from fx_scanner.execution.models import OrderType


def _plan():
    return {
        "plan_id": "RZ229-test-parent",
        "direction": "LONG",
        "children": [
            {"slot":1,"reference_price":101.8},
            {"slot":2,"reference_price":101.3},
            {"slot":3,"reference_price":100.8},
            {"slot":4,"reference_price":100.3},
        ],
    }


def test_v229_child_ids_are_four_distinct_broker_safe_ids():
    ids=[child_client_order_id(_plan()["plan_id"],slot) for slot in range(1,5)]
    assert len(set(ids))==4
    assert all(len(x)<=50 for x in ids)
    assert all(x.startswith("RZ229:") for x in ids)


def test_v229_slots_3_and_4_require_progressive_m5_evidence():
    child3={"slot":3,"reference_price":100.8}
    child4={"slot":4,"reference_price":100.3}
    waiting,_reason=_activation_entry(
        slot=3,direction="LONG",child=child3,
        micro={"direction":"LONG","reclaim_confirmed":True,"mss_confirmed":False},
    )
    assert waiting is None

    entry3,reason3=_activation_entry(
        slot=3,direction="LONG",child=child3,
        micro={
            "direction":"LONG","reclaim_confirmed":True,"mss_confirmed":True,
            "candidate_entry_pocket":{"low":100.2,"high":100.7},
        },
    )
    assert entry3==100.7
    assert reason3=="M5_RECLAIM_MSS_RETEST"

    entry4,reason4=_activation_entry(
        slot=4,direction="LONG",child=child4,
        micro={
            "direction":"LONG","displacement_confirmed":True,
            "refined_entry_pocket":{"low":100.4,"high":100.9},
        },
    )
    assert entry4==100.9
    assert reason4=="M5_DISPLACEMENT_RETEST"


def test_v229_limit_side_is_fail_closed():
    assert _limit_side_valid("LONG",100.0,bid=101.0,ask=101.2) is True
    assert _limit_side_valid("LONG",101.3,bid=101.0,ask=101.2) is False
    assert _limit_side_valid("SHORT",102.0,bid=101.0,ask=101.2) is True
    assert _limit_side_valid("SHORT",100.9,bid=101.0,ask=101.2) is False


def test_v229_reconcile_counts_pending_and_open_child_slots():
    plan=_plan()
    cid1=child_client_order_id(plan["plan_id"],1)
    cid3=child_client_order_id(plan["plan_id"],3)
    reconcile=SimpleNamespace(
        order=[SimpleNamespace(clientOrderId=cid1,orderId=11)],
        position=[
            SimpleNamespace(
                tradeData=SimpleNamespace(comment=f"FXIS:{cid3}"),
                stopLoss=98.0,
                takeProfit=118.0,
            )
        ],
    )
    assert _existing_slots(plan,reconcile)=={1,3}


class _Session:
    def __init__(self):
        self.cancelled=[]
    def cancel_order(self,order_id):
        self.cancelled.append(order_id)
        return SimpleNamespace(executionType=5)


def test_v229_parent_invalidation_cancels_only_its_pending_children():
    plan=_plan()
    cid1=child_client_order_id(plan["plan_id"],1)
    reconcile=SimpleNamespace(
        order=[
            SimpleNamespace(clientOrderId=cid1,orderId=11),
            SimpleNamespace(clientOrderId="OTHER",orderId=99),
        ],
        position=[],
    )
    session=_Session()
    outcomes=_cancel_pending_plan(session,plan,reconcile)
    assert session.cancelled==[11]
    assert outcomes==["CANCELLED:11"]



class _AuditStore:
    def __init__(self):
        self.events=[]

    def record_order_event(self, **kwargs):
        self.events.append(kwargs)


class _ReconcileCancelSession(_Session):
    def reconcile(self):
        return SimpleNamespace(order=[],position=[])


def test_v292_cancel_ack_is_durably_audited_and_reconciled_absent():
    plan=_plan()
    cid1=child_client_order_id(plan["plan_id"],1)
    reconcile=SimpleNamespace(
        order=[SimpleNamespace(clientOrderId=cid1,orderId=50942017)],
        position=[],
    )
    session=_ReconcileCancelSession()
    store=_AuditStore()

    outcomes=_cancel_pending_plan(
        session,
        plan,
        reconcile,
        store=store,
        parent_signal_id="parent-signal",
        reason="PARENT_INVALID_OR_SUPERSEDED",
    )

    assert outcomes==["CANCELLED:50942017"]
    assert session.cancelled==[50942017]
    assert len(store.events)==1
    event=store.events[0]
    assert event["event_type"]==CHILD_CANCEL_EVENT_TYPE
    assert event["code"]==CHILD_CANCEL_EVENT_CODE
    assert event["broker_order_id"]=="50942017"
    assert event["accepted"] is True
    assert event["message"]=="CANCEL_ACK_RECONCILED_ABSENT"
    assert event["payload"]["parent_signal_id"]=="parent-signal"
    assert event["payload"]["child_id"]==cid1
    assert event["payload"]["cancel_reason"]=="PARENT_INVALID_OR_SUPERSEDED"
    assert event["payload"]["reconciled_absent"] is True


def test_v229_child_executor_requires_pressure_transition_and_demo_lane_refresh():
    source = (Path(__file__).resolve().parents[1] / "src/fx_scanner/demo_xau_v229_child_executor.py").read_text()
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ctrader-demo-xau-execution-lane.yml").read_text()
    assert "evaluate_pressure_transition" in source
    assert "pre_touch_entry_allowed" in source
    assert "confirmation_entry_allowed" in source
    assert "PRESSURE_BLOCK" in source
    assert "build_dynamic_depth_hazard" in source
    assert "WAIT_DEEPER_HAZARD" in source
    assert "execution_enabled" in source
    assert "demo_xau_dom_v191" in workflow
    assert "steps.refresh_xau_pressure.outcome == 'success'" in workflow


def test_v294_transient_read_retries_then_recovers_without_sleep():
    attempts = []

    def operation():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise RuntimeError("Server disconnected")
        return {"ok": True}

    result = _read_with_transient_retry(
        operation,
        delays=(0.0, 0.0, 0.0),
        sleeper=lambda _delay: None,
    )
    assert result == {"ok": True}
    assert attempts == [1, 2, 3]


def test_v294_transient_read_does_not_retry_permanent_schema_error():
    attempts = []

    def operation():
        attempts.append(1)
        raise ValueError("missing column")

    try:
        _read_with_transient_retry(
            operation,
            delays=(0.0, 0.0, 0.0),
            sleeper=lambda _delay: None,
        )
    except ValueError as exc:
        assert str(exc) == "missing column"
    else:
        raise AssertionError("permanent backend error was retried/swallowed")
    assert attempts == [1]


def test_v294_child_uses_dedicated_control_plane_store():
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    assert "control_store = SupabaseOperationalStore.from_env" in source
    assert "ControlPlaneRefreshWorker(control_store, gate" in source
    assert '"control_plane_dedicated_store": True' in source
    assert "operational_read_transient_retry_delays" in source


def test_v263_child_rechecks_terminal_rr_from_actual_m5_entry() -> None:
    demand = {
        "zone_id": "target-demand",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 95.0,
        "high": 98.0,
        "status": "ACTIVE",
        "lifecycle": {"active": True},
    }
    atlas = {
        "chart_bars_m15": [],
        "zones": [demand],
        "path_map": {"supply_to_demand": {"destination_stack": [demand]}},
    }
    too_shallow, shallow_plan = _slot_target(
        slot=3,
        direction="SHORT",
        entry=103.0,
        stop=121.5,
        atlas_evaluation=atlas,
    )
    assert too_shallow is None
    assert shallow_plan["terminal_rr_eligible"] is False

    deep_enough, deep_plan = _slot_target(
        slot=3,
        direction="SHORT",
        entry=115.0,
        stop=121.5,
        atlas_evaluation=atlas,
    )
    assert deep_enough is not None
    assert deep_plan["terminal_rr_eligible"] is True
    assert deep_plan["terminal_structural_target"]["rr"] >= 1.5


class _PromotionQuery:
    def __init__(self, store):
        self.store = store
        self.filters = []
    def update(self, payload):
        self.store.updated_payload = dict(payload)
        return self
    def eq(self, key, value):
        self.filters.append((key, value))
        return self
    def execute(self):
        self.store.filters = list(self.filters)
        state_filter = dict(self.filters).get("state")
        return SimpleNamespace(
            data=[{"id": "signal-1"}] if state_filter == "ARMED" else []
        )


class _PromotionClient:
    def __init__(self, store):
        self.store = store
    def table(self, name):
        self.store.table_name = name
        return _PromotionQuery(self.store)


class _PromotionStore:
    def __init__(self):
        self.table_name = None
        self.updated_payload = None
        self.filters = []
        self.client = _PromotionClient(self)


def test_v264_armed_confirmation_window_promotes_atomically_before_broker_submit():
    store = _PromotionStore()
    assert _promote_armed_confirmation_window(store, "signal-1") is True
    assert store.table_name == "signals"
    assert store.updated_payload == {
        "state": "EXECUTION_READY",
        "active_guards": [],
    }
    assert ("id", "signal-1") in store.filters
    assert ("state", "ARMED") in store.filters


def test_v266_demo_probe_uses_real_m5_pocket_favorable_edge() -> None:
    short_entry, short_state = _calibration_probe_entry(
        direction="SHORT",
        micro={
            "direction": "SHORT",
            "candidate_entry_pocket": {"low": 4141.20, "high": 4143.75},
        },
    )
    assert short_entry == 4143.75
    assert short_state == "M5_CANDIDATE_CALIBRATION_PROBE"

    long_entry, long_state = _calibration_probe_entry(
        direction="LONG",
        micro={
            "direction": "LONG",
            "candidate_entry_pocket": {"low": 4141.20, "high": 4143.75},
        },
    )
    assert long_entry == 4141.20
    assert long_state == "M5_CANDIDATE_CALIBRATION_PROBE"


def test_v266_demo_probe_must_remain_inside_active_source_zone() -> None:
    atlas = {
        "path_map": {
            "active_path": {
                "source_zone": {
                    "direction": "SHORT",
                    "low": 4136.55,
                    "high": 4160.48,
                }
            }
        }
    }
    assert _entry_inside_active_source(
        direction="SHORT",
        entry=4143.75,
        atlas_evaluation=atlas,
    ) is True
    assert _entry_inside_active_source(
        direction="SHORT",
        entry=4165.0,
        atlas_evaluation=atlas,
    ) is False


def test_v266_probe_can_use_opposing_demand_at_1r_while_strict_path_stays_1_5r() -> None:
    demand = {
        "zone_id": "m15-demand",
        "timeframe": "M15",
        "direction": "LONG",
        "low": 4114.53,
        "high": 4121.93,
        "status": "ACTIVE",
        "lifecycle": {"active": True},
    }
    atlas = {
        "chart_bars_m15": [],
        "zones": [demand],
        "path_map": {"supply_to_demand": {"destination_stack": [demand]}},
    }
    probe_target, probe_structural = _target_with_min_rr(
        direction="SHORT",
        entry=4143.75,
        stop=4163.424944768374,
        atlas_evaluation=atlas,
        minimum_rr=1.0,
    )
    assert probe_target is not None
    assert probe_structural["terminal_rr_eligible"] is True
    assert probe_structural["terminal_structural_target"]["source"] == "OPPOSING_SUPPLY_DEMAND"
    assert probe_structural["terminal_structural_target"]["rr"] >= 1.0

    strict_target, strict_structural = _slot_target(
        slot=3,
        direction="SHORT",
        entry=4143.75,
        stop=4163.424944768374,
        atlas_evaluation=atlas,
    )
    assert strict_target is None
    assert strict_structural["terminal_rr_eligible"] is False


def test_v266_workflow_enables_bounded_demo_calibration_probe() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/ctrader-demo-xau-execution-lane.yml"
    ).read_text()
    assert 'CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_ENABLED: "1"' in workflow
    assert 'CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_MIN_RR: "1.00"' in workflow
    assert 'CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_MAX_DEPTH: "0.85"' in workflow
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    assert 'float(recommended_high) + 0.10' in source
    assert 'effective_probe_max_depth' in source


class _ProbeAuditQuery:
    def __init__(self, rows):
        self.rows = rows
    def select(self, *_args, **_kwargs):
        return self
    def eq(self, *_args, **_kwargs):
        return self
    def order(self, *_args, **_kwargs):
        return self
    def limit(self, *_args, **_kwargs):
        return self
    def execute(self):
        return SimpleNamespace(data=self.rows)


class _ProbeAuditClient:
    def __init__(self, rows):
        self.rows = rows
    def table(self, _name):
        return _ProbeAuditQuery(self.rows)


class _ProbeAuditStore:
    def __init__(self, rows):
        self.client = _ProbeAuditClient(rows)


def test_v266_parent_allows_only_one_accepted_calibration_probe() -> None:
    accepted = _ProbeAuditStore(
        [
            {
                "accepted": True,
                "payload": {"calibration_only": True, "slot": 1},
                "event_type": "DEMO_XAU_RIZAN_DEPTH_CHILD",
            }
        ]
    )
    assert _calibration_probe_already_accepted(accepted, "parent-1") is True

    rejected_only = _ProbeAuditStore(
        [
            {
                "accepted": False,
                "payload": {"calibration_only": True, "slot": 1},
                "event_type": "DEMO_XAU_RIZAN_DEPTH_CHILD",
            }
        ]
    )
    assert _calibration_probe_already_accepted(rejected_only, "parent-1") is False


def test_v267_child_executor_keeps_control_plane_fresh_until_submit() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    assert "control.refresh_once()" in source
    assert "control.start()" in source
    assert "control.stop(timeout=2.0)" in source
    submit_anchor = source.index("accepted, detail = _submit_child(")
    pre_submit_refresh = source.rfind("control.refresh_once()", 0, submit_anchor)
    assert pre_submit_refresh != -1
    assert "control_plane_pre_submit_refresh" in source
    assert "control_plane_refresh_worker" in source


def test_v270_short_deep_m5_pocket_rejection_rearms_limit_inside_no_chase_band() -> None:
    entry, state = _calibration_rejection_retest_entry(
        direction="SHORT",
        micro={
            "direction": "SHORT",
            "last_closed_m5_price": 4151.83,
            "candidate_entry_pocket": {
                "low": 4155.01,
                "high": 4158.74,
                "origin_at": "2026-09-29T12:30:00+00:00",
            },
        },
        depth_hazard={
            "calibration_probe_depth_eligible": True,
            "recommended_price_low": 4150.908,
            "recommended_price_high": 4153.301,
        },
        now=datetime.fromisoformat("2026-09-29T13:00:00+00:00"),
        max_age_seconds=3600,
    )
    assert entry == 4153.301
    assert state == "M5_CANDIDATE_REJECTION_RETEST_PROBE"


def test_v270_long_deep_m5_pocket_rejection_rearms_limit_inside_no_chase_band() -> None:
    entry, state = _calibration_rejection_retest_entry(
        direction="LONG",
        micro={
            "direction": "LONG",
            "last_closed_m5_price": 101.5,
            "candidate_entry_pocket": {
                "low": 98.0,
                "high": 100.0,
                "origin_at": "2026-09-29T12:30:00+00:00",
            },
        },
        depth_hazard={
            "calibration_probe_depth_eligible": True,
            "recommended_price_low": 96.5,
            "recommended_price_high": 97.5,
        },
        now=datetime.fromisoformat("2026-09-29T13:00:00+00:00"),
        max_age_seconds=3600,
    )
    assert entry == 96.5
    assert state == "M5_CANDIDATE_REJECTION_RETEST_PROBE"


def test_v270_rejection_retest_fails_closed_without_closed_m5_exit_or_freshness() -> None:
    waiting, reason = _calibration_rejection_retest_entry(
        direction="SHORT",
        micro={
            "direction": "SHORT",
            "last_closed_m5_price": 4156.0,
            "candidate_entry_pocket": {
                "low": 4155.01,
                "high": 4158.74,
                "origin_at": "2026-09-29T12:30:00+00:00",
            },
        },
        depth_hazard={
            "calibration_probe_depth_eligible": True,
            "recommended_price_low": 4150.908,
            "recommended_price_high": 4153.301,
        },
        now=datetime.fromisoformat("2026-09-29T13:00:00+00:00"),
        max_age_seconds=3600,
    )
    assert waiting is None
    assert reason == "PROBE_REJECTION_WAIT_CLOSED_M5_EXIT"

    stale, stale_reason = _calibration_rejection_retest_entry(
        direction="SHORT",
        micro={
            "direction": "SHORT",
            "last_closed_m5_price": 4151.0,
            "candidate_entry_pocket": {
                "low": 4155.01,
                "high": 4158.74,
                "origin_at": "2026-09-29T10:00:00+00:00",
            },
        },
        depth_hazard={
            "calibration_probe_depth_eligible": True,
            "recommended_price_low": 4150.908,
            "recommended_price_high": 4153.301,
        },
        now=datetime.fromisoformat("2026-09-29T13:00:00+00:00"),
        max_age_seconds=3600,
    )
    assert stale is None
    assert stale_reason == "PROBE_REJECTION_M5_TOO_OLD"


def test_v270_rejection_retest_remains_demo_bounded_and_limit_only() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/ctrader-demo-xau-execution-lane.yml"
    ).read_text()
    assert "M5_CANDIDATE_REJECTION_RETEST_PROBE" in source
    assert "calibration_probe_depth_eligible" in source
    assert "OrderType.LIMIT" in source
    assert "CTRADER_DEMO_DEPTH_CALIBRATION_REJECTION_MAX_AGE_SECONDS" in workflow
    assert '"3600"' in workflow


def test_v271_child_pressure_bypass_is_calibration_only_and_strict_stays_two_sample() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    assert 'str(pressure_transition.get("state") or "") == "WAIT_SECOND_SAMPLE"' in source
    assert 'pressure_transition.get("calibration_entry_allowed")' in source
    assert "calibration_pressure_bypass" in source
    assert "armed_confirmation_window" in source
    assert "calibration_probe_enabled" in source
    assert '"strict_pressure_transition_requires_two_samples": True' in source
    assert '"calibration_single_sample_pressure_allowed": True' in source
    assert '"calibration_single_sample_max_opposing_pressure": 15.0' in source
    assert 'pressure_transition.get("confirmation_entry_allowed")' in source


def test_v274_source_depth_boundary_price_is_direction_aware() -> None:
    short_atlas = {
        "path_map": {
            "active_path": {
                "source_zone": {
                    "direction": "SHORT",
                    "low": 100.0,
                    "high": 120.0,
                }
            }
        }
    }
    long_atlas = {
        "path_map": {
            "active_path": {
                "source_zone": {
                    "direction": "LONG",
                    "low": 100.0,
                    "high": 120.0,
                }
            }
        }
    }
    assert _source_depth_boundary_price(
        atlas_evaluation=short_atlas,
        direction="SHORT",
        depth=0.70,
    ) == 114.0
    assert _source_depth_boundary_price(
        atlas_evaluation=long_atlas,
        direction="LONG",
        depth=0.70,
    ) == 106.0


def test_v274_deep_rejection_can_stage_short_exit_stop_at_no_chase_boundary() -> None:
    atlas = {
        "path_map": {
            "active_path": {
                "source_zone": {
                    "direction": "SHORT",
                    "low": 4136.55,
                    "high": 4160.48,
                }
            }
        }
    }
    entry, state = _calibration_rejection_exit_stop_entry(
        direction="SHORT",
        micro={
            "direction": "SHORT",
            "candidate_entry_pocket": {
                "low": 4155.0,
                "high": 4159.0,
                "origin_at": "2026-09-29T13:40:00+00:00",
            },
            "last_closed_m5_price": 4154.5,
        },
        atlas_evaluation=atlas,
        max_depth=0.70,
        now=datetime.fromisoformat("2026-09-29T14:00:00+00:00"),
        max_age_seconds=3600.0,
    )
    assert round(float(entry), 3) == 4153.301
    assert state == "M5_CANDIDATE_DEEP_REJECTION_EXIT_STOP"


def test_v274_deep_rejection_can_stage_long_exit_stop_at_no_chase_boundary() -> None:
    atlas = {
        "path_map": {
            "active_path": {
                "source_zone": {
                    "direction": "LONG",
                    "low": 100.0,
                    "high": 120.0,
                }
            }
        }
    }
    entry, state = _calibration_rejection_exit_stop_entry(
        direction="LONG",
        micro={
            "direction": "LONG",
            "candidate_entry_pocket": {
                "low": 101.0,
                "high": 105.0,
                "origin_at": "2026-09-29T13:40:00+00:00",
            },
            "last_closed_m5_price": 105.5,
        },
        atlas_evaluation=atlas,
        max_depth=0.70,
        now=datetime.fromisoformat("2026-09-29T14:00:00+00:00"),
        max_age_seconds=3600.0,
    )
    assert entry == 106.0
    assert state == "M5_CANDIDATE_DEEP_REJECTION_EXIT_STOP"


def test_v274_pending_side_validation_distinguishes_limit_and_stop() -> None:
    assert _pending_side_valid(
        "SHORT", OrderType.LIMIT, 102.0, bid=101.0, ask=101.2
    ) is True
    assert _pending_side_valid(
        "SHORT", OrderType.STOP, 100.0, bid=101.0, ask=101.2
    ) is True
    assert _pending_side_valid(
        "SHORT", OrderType.STOP, 102.0, bid=101.0, ask=101.2
    ) is False

    assert _pending_side_valid(
        "LONG", OrderType.LIMIT, 100.0, bid=101.0, ask=101.2
    ) is True
    assert _pending_side_valid(
        "LONG", OrderType.STOP, 102.0, bid=101.0, ask=101.2
    ) is True
    assert _pending_side_valid(
        "LONG", OrderType.STOP, 100.0, bid=101.0, ask=101.2
    ) is False


def test_v274_stop_is_calibration_fallback_only_and_strict_default_remains_limit() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    assert "order_type: OrderType = OrderType.LIMIT" in source
    assert "child_order_type = OrderType.LIMIT" in source
    assert "child_order_type = OrderType.STOP" in source
    assert "PROBE_DEEP_REJECTION_EXIT_STOP_ARMED" in source
    assert "calibration_probe_exit_stop_enabled" in source


def test_v275_armed_calibration_parent_promotes_atomically_when_strict_ready() -> None:
    store = _PromotionStore()
    assert _promote_armed_calibration_parent(store, "signal-1") is True
    assert store.updated_payload == {
        "state": "EXECUTION_READY",
        "active_guards": [],
    }
    assert ("id", "signal-1") in store.filters
    assert ("state", "ARMED") in store.filters


def test_v275_child_allows_only_l1_before_strict_promotion() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    assert "armed_calibration_first_touch" in source
    assert "ARMED_FRESH_FIRST_TOUCH_CALIBRATION_L1_ONLY" in source
    assert "FRESH_FIRST_TOUCH_CALIBRATION_LIMIT" in source
    assert "DISABLED_CALIBRATION_ARM" in source
    assert "slot != 1" in source
    assert "CALIBRATION_PARENT_PROMOTED_STRICT" in source
    assert "fresh_first_touch_calibration_slots" in source


def test_v280_child_cancels_pending_and_invalidates_on_hard_stage() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    assert "evaluate_reversal_stage" in source
    assert "_invalidate_signal_for_reversal_stage" in source
    assert "V280_CANCEL" in source
    assert "V280_BLOCK" in source
    assert '"state": "INVALIDATED"' in source
    assert 'for prior_state in ("ARMED", "EXECUTION_READY", "COOLDOWN")' in source


def test_v295_research_probe_ceiling_is_85pct_without_changing_strict_children() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/ctrader-demo-xau-execution-lane.yml"
    ).read_text()
    assert '_float_env(CALIBRATION_PROBE_MAX_DEPTH_ENV, 0.85)' in source
    assert 'CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_MAX_DEPTH: "0.85"' in workflow
    assert "if slot >= 3 and not bool(" in source
    assert "confirmation_entry_allowed" in source
    assert "MIN_TERMINAL_RR" in source
    assert '"child_lot": CHILD_LOT' in source



def test_v301_child_heartbeat_exposes_only_current_aligned_parent_ids() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_xau_v229_child_executor.py"
    ).read_text()
    assert "aligned_parent_signal_ids: list[str] = []" in source
    assert "aligned_parent_signal_ids.append(parent_signal_id)" in source
    assert '"aligned_parent_signal_ids": (' in source
    assert '"current_candidate_key": current_key' in source
