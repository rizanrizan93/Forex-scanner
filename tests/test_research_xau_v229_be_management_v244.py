from datetime import UTC, datetime, timedelta

import pandas as pd

from fx_scanner.research_xau_v229_be_management_v244 import (
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    MANAGEMENT_VARIANTS,
    _managed_completed_trade,
    apply_management_variants,
)
from fx_scanner.research_xau_v229_historical_v242 import price_arrays


def _frame(rows):
    t=datetime(2026,1,5,0,0,tzinfo=UTC)
    return pd.DataFrame([
        {"timestamp":t+timedelta(minutes=i),"open":o,"high":h,"low":l,"close":c}
        for i,(o,h,l,c) in enumerate(rows)
    ])


def _trade():
    t=datetime(2026,1,5,0,0,tzinfo=UTC)
    return {
        "plan_id":"P1","year":2026,"cost_mode":"BASE","slot":1,
        "direction":"LONG","state":"LOSS","reason":"STOP_HIT",
        "entry_at":t.isoformat(),"exit_at":(t+timedelta(minutes=10)).isoformat(),
        "planned_entry":100.0,"fill_price":100.0,"exit_price":90.0,
        "stop":90.0,"target":120.0,"risk_pips":1000.0,
        "gross_r":-1.0,"cost_r":0.0002,"net_r":-1.0002,
        "net_pnl_usd":-10.002,"mae_r":1.0,"mfe_r":0.6,
        "ambiguous_bar":False,"spread_pips":0.0,"slippage_pips":0.0,
        "elapsed_days":0.0,"candidate_source":"H4",
        "signal_expires_at":(t+timedelta(hours=16)).isoformat(),
        "order_at":(t-timedelta(minutes=1)).isoformat(),
    }


def test_v244_variant_family_is_frozen() -> None:
    assert MANAGEMENT_VARIANTS == {
        "BASELINE": None,
        "BE_AFTER_0_5R": 0.50,
        "BE_AFTER_1_0R": 1.00,
    }


def test_v244_be_arms_after_trigger_and_acts_next_m1_only() -> None:
    px=price_arrays(_frame([
        (100,101,99,100),
        (100,106,99,105),  # reaches +0.5R; BE not active inside this bar
        (105,105,99,100),  # BE active here and is hit
        (100,101,99,100),
    ]))
    out=_managed_completed_trade(px=px,row=_trade(),trigger_r=0.5)
    assert out["reason"]=="BE_STOP_HIT"
    assert out["be_armed_at"]=="2026-01-05T00:01:00+00:00"
    assert out["be_active_at"]=="2026-01-05T00:02:00+00:00"
    assert abs(float(out["net_r"])) < 1e-12
    assert out["state"]=="BREAKEVEN"


def test_v244_original_stop_wins_if_trigger_and_stop_share_same_bar() -> None:
    px=price_arrays(_frame([
        (100,101,99,100),
        (100,106,89,95),   # reaches trigger and original stop in same M1
        (95,100,94,98),
    ]))
    out=_managed_completed_trade(px=px,row=_trade(),trigger_r=0.5)
    assert out["state"]=="LOSS"
    assert out["reason"]=="STOP_HIT"
    assert out["be_armed_at"] is None


def test_v244_one_r_trigger_is_not_silently_lowered() -> None:
    px=price_arrays(_frame([
        (100,101,99,100),
        (100,109.9,99,108),  # below +1R
        (108,120.5,107,120), # target before any prior completed +1R trigger
    ]))
    out=_managed_completed_trade(px=px,row=_trade(),trigger_r=1.0)
    assert out["reason"]=="TARGET_HIT"
    assert out["be_armed_at"] is None
    assert out["state"]=="WIN"


def test_v244_apply_management_keeps_baseline_and_adds_two_managed_copies() -> None:
    frame=_frame([
        (100,101,99,100),(100,106,99,105),(105,105,99,100),(100,101,99,100)
    ])
    base={"plans":[{"plan_id":"P1"}],"trades":[_trade()],"trade_record_count":1}
    out=apply_management_variants(price_m1=frame,base_result=base)
    assert len(out["trades"])==3
    assert {row["management_variant"] for row in out["trades"]}==set(MANAGEMENT_VARIANTS)
    baseline=[r for r in out["trades"] if r["management_variant"]=="BASELINE"][0]
    assert baseline["net_r"]==-1.0002


def test_v244_is_shadow_only() -> None:
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False
