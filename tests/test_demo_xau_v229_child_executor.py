from __future__ import annotations

from types import SimpleNamespace

from fx_scanner.demo_xau_v229_child_executor import (
    _activation_entry,
    _cancel_pending_plan,
    _existing_slots,
    _limit_side_valid,
)
from fx_scanner.demo_xau_v229_ladder_plan import child_client_order_id


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


def test_v229_invalidated_source_cannot_activate_l3_with_old_flags():
    entry, reason = _activation_entry(
        slot=3, direction="LONG", child={},
        micro={"direction": "LONG", "state": "SOURCE_INVALIDATED_NO_REFINEMENT",
               "reclaim_confirmed": True, "mss_confirmed": True,
               "candidate_entry_pocket": {"low": 100.2, "high": 100.7}},
    )
    assert entry is None
    assert reason == "M5_SOURCE_INVALIDATED"


def _runtime_fixture(monkeypatch, *, invalid_source=False, broken_parent=False, stale=False):
    from datetime import UTC, datetime, timedelta
    from fx_scanner import demo_xau_v229_child_executor as module

    now = datetime.now(tz=UTC)
    parent_at = now - timedelta(minutes=20)
    source_at = now - timedelta(hours=2)
    zone = {"zone_id": "h4", "timeframe": "H4", "direction": "LONG",
            "low": 98.0, "high": 104.0,
            "lifecycle": {"active": not broken_parent, "touch_count": 1, "freshness": "FIRST_TEST"}}
    children = [{"slot": i, "reference_price": 100.0 + i * 0.1} for i in range(1, 5)]
    payload = {"plan_id": "RZ229-integration", "candidate_key": "frozen-key",
               "direction": "LONG", "planned_sl": 97.4, "h4_zone_id": "h4",
               "h4_zone_snapshot": dict(zone), "source_layer": "H1_NESTED_LOCATOR",
               "precision_source_snapshot": {"zone_id": "h1", "available_at": source_at.isoformat()},
               "children": children}
    micro = {"state": "SOURCE_INVALIDATED_NO_REFINEMENT" if invalid_source else "M5_REFINEMENT_CONFIRMED_SHADOW",
             "direction": "LONG", "source_zone_id": "h1", "source_timeframe": "H1",
             "source_available_at": source_at.isoformat(),
             "sweep": {"at": (parent_at + timedelta(minutes=5)).isoformat()},
             "reclaim_confirmed": True, "mss_confirmed": True, "displacement_confirmed": True,
             "reclaim_at": (parent_at + timedelta(minutes=10)).isoformat(),
             "mss_at": (parent_at + timedelta(minutes=10)).isoformat(),
             "displacement_at": (parent_at + timedelta(minutes=15)).isoformat(),
             "candidate_entry_pocket": {"low": 99.5, "high": 100.5},
             "refined_entry_pocket": {"low": 99.6, "high": 100.6}}
    atlas = {"as_of": now.isoformat(), "zones": [zone], "micro_refinement": micro}
    heartbeat = {"healthy": True, "observed_at": (now - timedelta(minutes=15) if stale else now).isoformat(),
                 "details": {"evaluation": atlas}}
    signal = {"state": "COOLDOWN", "observed_at": parent_at.isoformat(),
              "expires_at": (now + timedelta(hours=1)).isoformat()}
    pending = [SimpleNamespace(orderId=i, clientOrderId=child_client_order_id(payload["plan_id"], i))
               for i in (1, 2)]
    reconcile = SimpleNamespace(order=pending, position=[])
    session = _Session()
    session.reconcile = lambda: reconcile
    session.close = lambda: None
    gateway = SimpleNamespace(market_quote=lambda symbol: SimpleNamespace(bid=101.0, ask=101.2))
    submitted, updates, heartbeats = [], [], []

    class Query:
        def update(self, row):
            updates.append(row)
            return self
        def eq(self, *args):
            return self
        def in_(self, *args):
            return self
        def execute(self):
            return SimpleNamespace(data=[])

    store = SimpleNamespace(client=SimpleNamespace(table=lambda name: Query()),
                            write_heartbeat=lambda *a, **k: heartbeats.append(k))
    policy = SimpleNamespace(ctrader={"environment": "DEMO", "require_demo": True},
                             live_safety={}, demo_safety={"max_concurrent_positions": 10})
    def execute(intent):
        submitted.append(intent)
        return SimpleNamespace(accepted=True, broker_order_id="test", message="test")

    monkeypatch.setenv("CTRADER_DEMO_DEPTH_EXECUTION_ENABLED", "1")
    monkeypatch.setattr(module, "load_execution_policy", lambda p: policy)
    monkeypatch.setattr(module, "replace", lambda p, **k: p)
    monkeypatch.setattr(module.SupabaseOperationalStore, "from_env", lambda **k: store)
    monkeypatch.setattr(module, "build_broker_gateway", lambda *a, **k: (gateway, session))
    monkeypatch.setattr(module, "ControlPlaneGate", lambda **k: object())
    monkeypatch.setattr(module, "ControlPlaneRefreshWorker", lambda *a, **k: SimpleNamespace(refresh_once=lambda: None))
    monkeypatch.setattr(module, "ExecutionRouter", lambda *a, **k: SimpleNamespace(execute=execute))
    monkeypatch.setattr(module, "SupabaseOrderAuditSink", lambda s: object())
    monkeypatch.setattr(module, "_latest_parent_rows", lambda s: [{"signal_key": "parent", "payload": payload}])
    monkeypatch.setattr(module, "_latest_heartbeat", lambda *a: heartbeat)
    monkeypatch.setattr(module, "_signal_row", lambda *a: signal)
    monkeypatch.setattr(module, "_record_child_event", lambda *a, **k: None)
    monkeypatch.setattr(module, "_slot_target", lambda *a, **k: (118.0, {"terminal_rr_eligible": True}))
    return module, session, submitted, updates, heartbeats


def test_v229_runtime_keeps_l1_l2_after_touch_and_submits_confirmed_l3_l4(monkeypatch):
    module, session, submitted, updates, heartbeats = _runtime_fixture(monkeypatch)
    assert module.run() == 0
    assert session.cancelled == []
    assert len(submitted) == 2
    assert [intent.signal_id.rsplit(":", 1)[1] for intent in submitted] == ["L3", "L4"]
    assert all(intent.volume == 0.01 for intent in submitted)
    assert updates == []


def test_v229_runtime_rejects_invalid_m5_without_cancelling_valid_parent(monkeypatch):
    module, session, submitted, updates, heartbeats = _runtime_fixture(monkeypatch, invalid_source=True)
    assert module.run() == 0
    assert submitted == []
    assert session.cancelled == []


def test_v229_runtime_parent_break_cancels_pending_and_retires_signal(monkeypatch):
    module, session, submitted, updates, heartbeats = _runtime_fixture(monkeypatch, broken_parent=True)
    assert module.run() == 0
    assert session.cancelled == [1, 2]
    assert submitted == []
    assert updates[0]["state"] == "INVALIDATED"


def test_v229_runtime_stale_atlas_blocks_new_submissions(monkeypatch):
    module, session, submitted, updates, heartbeats = _runtime_fixture(monkeypatch, stale=True)
    assert module.run() == 0
    assert submitted == []
    assert session.cancelled == []
