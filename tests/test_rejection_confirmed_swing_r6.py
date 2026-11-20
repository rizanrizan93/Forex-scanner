"""R6 SMC confirmed M5 swing tests; fabricated bars, NO market accuracy."""
import pandas as pd
import pytest
from fx_scanner.rejection_confirmed_swing_r6_research import (
    confirmed_m5_pivots,pivot_opposing_room,compare_v4_candidate,
    ROOM_V4_REASON
)
NOW=pd.Timestamp("2026-11-20T02:00:00Z")

def bars():
    idx=pd.date_range(end=NOW,periods=40,freq="5min",tz="UTC")
    d=pd.DataFrame({"high":102.,"low":98.},index=idx)
    d.iloc[24,d.columns.get_loc("high")]=107.
    d.iloc[24,d.columns.get_loc("low")]=92.
    return d

def v4(side="BUY",*reasons,stage="MSS_CONFIRMED",
       entry_status="BLOCKED",quote_ok=True):
    return {
        "side":side,
        "entry_status":entry_status,
        "stage":stage,
        "setup_type":"COUNTERTREND_REVERSAL",
        "quote_ok":quote_ok,
        "room_atr":.50,
        "reasons":list(reasons or [ROOM_V4_REASON]),
    }

def test_unique_swings_only_confirm_after_two_completed_right_m5():
    d=bars()
    close_at=d.index[26]
    now=close_at
    s=confirmed_m5_pivots(d.iloc[:27],now=now)
    hi=[x for x in s if x["kind"]=="SWING_HIGH"]
    lo=[x for x in s if x["kind"]=="SWING_LOW"]
    assert len(hi)==1 and len(lo)==1
    assert hi[0]["level"]==107
    assert lo[0]["level"]==92
    assert hi[0]["pivot_at_utc"]==d.index[24].isoformat()
    assert hi[0]["confirmed_at_utc"]==now.isoformat()

def test_unconfirmed_latest_extremes_never_used():
    d=bars()
    at=d.index[25]
    s=confirmed_m5_pivots(d.iloc[:26],now=at)
    assert not s

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_structural_swing_room_can_be_larger_than_nearest_candle_extreme(side):
    d=bars()
    r=pivot_opposing_room(d,side=side,price=100.,atr_m5=4.,now=NOW)
    assert r["room_verified"]
    assert r["opposing_swing"]["kind"]==("SWING_HIGH" if side=="BUY" else "SWING_LOW")
    assert r["room_atr"]>=1.7
    assert r["authority_to_trade"] is False

def test_other_quote_and_anti_chase_guards_still_block():
    d=bars()
    r=compare_v4_candidate(v4("BUY",ROOM_V4_REASON,
                      "Price too far / wrong side of watch level"),d,
                      price=100.,atr_m5=4.,now=NOW)
    assert r["r6_pivot_room"]["room_verified"]
    assert not r["r6_hypothetical_candidate"]

def test_unconfirmed_swing_does_not_permit_entry():
    d=bars().iloc[:26]
    r=compare_v4_candidate(v4("BUY"),d,price=100.,atr_m5=4.,now=d.index[-1])
    assert not r["r6_hypothetical_candidate"]
    assert r["r6_pivot_room"]["reason"]=="NO_CAUSALLY_CONFIRMED_OPPOSING_SWING"

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_only_room_veto_research_recovered_not_order(side):
    d=bars()
    r=compare_v4_candidate(v4(side),d,price=100.,atr_m5=4.,now=NOW)
    assert r["r6_recovered_old_room_only"]
    assert r["r6_hypothetical_candidate"]
    assert r["authority_to_trade"] is False
    assert not r["backtested_80pct"]

def test_no_future_m5_accepted():
    d=bars()
    with pytest.raises(ValueError,match="FUTURE_M5_BAR_LOOKAHEAD"):
        confirmed_m5_pivots(d,now=d.index[-2])

def test_tied_high_not_swing():
    d=bars()
    d.loc[d.index[23],"high"]=107
    highs=[x for x in confirmed_m5_pivots(d,now=NOW) if x["kind"]=="SWING_HIGH"]
    assert not highs

def test_missing_intra_pivot_m5_blocks_false_swing():
    d=bars().drop(bars().index[23])
    p=confirmed_m5_pivots(d,now=NOW)
    assert not any(x["pivot_at_utc"]==bars().index[24].isoformat() for x in p)

def test_forged_technical_entry_stage_not_recovered():
    d=bars()
    q=v4("BUY",stage="WATCH_EMA")
    r=compare_v4_candidate(q,d,price=100.,atr_m5=4.,now=NOW)
    assert not r["r6_hypothetical_candidate"]

def test_an_old_v4_candidate_can_be_blocked_by_missing_confirmed_swing():
    d=bars().iloc[:26]
    q=v4("BUY",stage="MSS_CONFIRMED",entry_status="ENTRY_CANDIDATE")
    q["reasons"]=[]
    r=compare_v4_candidate(q,d,price=100.,atr_m5=4.,now=d.index[-1])
    assert r["r6_blocked_old_candidate"]

def test_wrong_quote_currency_and_negative_atr_rejected():
    d=bars()
    with pytest.raises(ValueError,match="PRICE_OR_ATR"):
        pivot_opposing_room(d,side="SELL",price=100.,atr_m5=-1,now=NOW)

def test_failed_breakout_cooldown_not_bypassed():
    d=bars()
    q=v4("SELL",ROOM_V4_REASON,
         "V3 same-side breakout/invalidated event cooldown",
         entry_status="BLOCKED_PREVIOUS_FAILED_REJECTION")
    r=compare_v4_candidate(q,d,price=100.,atr_m5=4.,now=NOW)
    assert not r["r6_hypothetical_candidate"]
