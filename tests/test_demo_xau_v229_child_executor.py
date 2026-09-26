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
