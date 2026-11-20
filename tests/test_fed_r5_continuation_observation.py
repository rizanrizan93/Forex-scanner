"""M1 continuation observation: synthetic patterns only, NEVER win-rate."""
import pandas as pd
import pytest
from research.fed_expectation_r1.fomc_continuation_observation_r5 import evaluate_continuation

AT=pd.Timestamp("2023-09-20T19:35:00Z")

def bars(side):
    idx=pd.date_range(end=AT-pd.Timedelta(minutes=1),periods=130,
                      freq="min",tz="UTC")
    d=pd.DataFrame({"open":100.0,"high":100.4,"low":99.6,"close":100.0},index=idx)
    if side=="BUY":
        d.iloc[-1]=[100.0,103.0,99.8,102.5]
        bid,ask=102.45,102.55
    else:
        d.iloc[-1]=[100.0,100.2,97.0,97.5]
        bid,ask=97.45,97.55
    hidx=pd.date_range(end=AT-pd.Timedelta(minutes=5),periods=40,
                       freq="5min",tz="UTC")
    m5=pd.DataFrame({"open":100.0,"high":106.0,"low":94.0,"close":100.0},index=hidx)
    return d,m5,bid,ask

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_directional_three_bar_break_is_observed_but_not_traded(side):
    d,m5,bid,ask=bars(side)
    x=evaluate_continuation(d,m5,at=AT,side=side,
                             bid=bid,ask=ask,atr_m5=5.0)
    assert x["stage"]=="STRUCTURE_BREAK_OBSERVED"
    assert x["event_detected"] is True
    assert x["m1_closed_structure_break"]
    assert x["authorizes_entry"] is False
    assert x["authorizes_orders"] is False
    assert x["measured_80pct_win_rate"] is False

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_no_actual_bid_ask_cannot_pass(side):
    d,m5,_,_=bars(side)
    x=evaluate_continuation(d,m5,at=AT,side=side,atr_m5=5.0)
    assert x["stage"]=="WAIT_STRUCTURE"
    assert not x["event_detected"]

def test_wrong_side_never_continuation():
    d,m5,bid,ask=bars("BUY")
    x=evaluate_continuation(d,m5,at=AT,side="SELL",bid=bid,ask=ask,atr_m5=5)
    assert not x["event_detected"]

def test_live_forming_m1_rejected():
    d,m5,bid,ask=bars("SELL")
    d.index=d.index+pd.Timedelta(minutes=1)
    with pytest.raises(ValueError,match="FORMING_CANDLE"):
        evaluate_continuation(d,m5,at=AT,side="SELL",bid=bid,ask=ask,atr_m5=5)

def test_data_gap_rejected_not_filled():
    d,m5,bid,ask=bars("BUY")
    d=d.drop(d.index[-3])
    with pytest.raises(ValueError,match="M1_DATA_GAP"):
        evaluate_continuation(d,m5,at=AT,side="BUY",bid=bid,ask=ask,atr_m5=5)

def test_spread_or_chase_blocks_observation():
    d,m5,bid,ask=bars("BUY")
    x=evaluate_continuation(d,m5,at=AT,side="BUY",
                            bid=bid,ask=ask+3,atr_m5=5)
    assert not x["event_detected"]

def test_invalid_direction_rejected():
    d,m5,bid,ask=bars("BUY")
    with pytest.raises(ValueError,match="BAD_MACRO_DIRECTION"):
        evaluate_continuation(d,m5,at=AT,side="WAIT",bid=bid,ask=ask,atr_m5=5)
