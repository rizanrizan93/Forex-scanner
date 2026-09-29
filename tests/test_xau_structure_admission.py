from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from fx_scanner.xau_structure_admission import evaluate_structure_admission
from test_demo_xau_v229_depth_execution import _atlas, _v226

NOW = datetime(2026, 9, 29, 3, tzinfo=UTC)


def _hb(evaluation, age=0):
    timestamp = (NOW - timedelta(seconds=age)).isoformat()
    return {"healthy": True, "observed_at": timestamp,
            "details": {"evaluation": {**evaluation, "as_of": timestamp}}}


def _admit(v=None, a=None):
    return evaluate_structure_admission(
        v226_heartbeat=v or _hb(_v226()), atlas_heartbeat=a or _hb(_atlas()),
        now=NOW,
    )


def test_current_structural_plan_remains_eligible():
    assert _admit()["allowed"] is True


@pytest.mark.parametrize("layer,age", [("V226", 601), ("ATLAS", 901)])
def test_stale_structure_blocks_both_workers(layer, age):
    out = _admit(v=_hb(_v226(), age) if layer == "V226" else None,
                 a=_hb(_atlas(), age) if layer == "ATLAS" else None)
    assert not out["allowed"]
    assert "STALE" in out["reason"]


@pytest.mark.parametrize("timestamp", [None, "2026-09-29T03:00:00", "2026-09-30T03:00:00Z", "2026-09-28T03:00:00Z"])
def test_fresh_heartbeat_cannot_hide_bad_evaluation_timestamp(timestamp):
    v = _hb(_v226())
    v["details"]["evaluation"]["as_of"] = timestamp
    assert not _admit(v=v)["allowed"]


def test_child_run_cancels_stale_parent_pending_orders_without_submitting(monkeypatch):
    from fx_scanner import demo_xau_v229_child_executor as child
    from fx_scanner.demo_xau_v229_ladder_plan import child_client_order_id

    @dataclass
    class Policy:
        mode: object = None
        ctrader: dict = field(default_factory=lambda: {"environment": "DEMO", "require_demo": True})
        live_safety: dict = field(default_factory=dict)
        demo_safety: dict = field(default_factory=dict)

    cancelled, heartbeats = [], []
    plan_id = "RZ229-stale-test"
    parent = {"signal_key": "parent", "payload": {
        "plan_id": plan_id, "candidate_key": "old", "direction": "LONG", "planned_sl": 98,
        "children": [{"slot": n} for n in range(1, 5)]}}
    pending = SimpleNamespace(clientOrderId=child_client_order_id(plan_id, 1), orderId=11)
    session = SimpleNamespace(
        reconcile=lambda: SimpleNamespace(order=[pending], position=[]),
        cancel_order=lambda oid: (cancelled.append(oid) or SimpleNamespace(executionType=5)),
        close=lambda: None,
    )
    store = SimpleNamespace(write_heartbeat=lambda *a, **kw: heartbeats.append(kw))
    monkeypatch.setenv("CTRADER_DEMO_DEPTH_EXECUTION_ENABLED", "1")
    monkeypatch.setattr(child, "load_execution_policy", lambda _: Policy())
    monkeypatch.setattr(child.SupabaseOperationalStore, "from_env", lambda **kw: store)
    monkeypatch.setattr(child, "build_broker_gateway", lambda *a, **kw: (
        SimpleNamespace(market_quote=lambda _: SimpleNamespace(ask=103.0, bid=102.9)), session))
    monkeypatch.setattr(child, "ControlPlaneRefreshWorker", lambda *a, **kw: SimpleNamespace(refresh_once=lambda: None))
    monkeypatch.setattr(child, "ExecutionRouter", lambda *a, **kw: None)
    monkeypatch.setattr(child, "_latest_parent_rows", lambda _: [parent])
    monkeypatch.setattr(child, "_latest_heartbeat", lambda _, name:
                        _hb(_v226(), 86400) if name == child.V226_WORKER else
                        _hb(_atlas(), 86400) if name == child.ATLAS_WORKER else {})
    monkeypatch.setattr(child, "_signal_row", lambda *a: {
        "state": "COOLDOWN", "expires_at": "2099-01-01T00:00:00Z"})
    assert child.run() == 0
    assert cancelled == [11]
    assert any("STRUCTURE_BLOCK" in action for action in heartbeats[-1]["details"]["actions"])
