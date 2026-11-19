"""V4 symmetric BUY/SELL filters. Tests use invented bars, NEVER market accuracy."""
import pandas as pd
import pytest
from fx_scanner.rejection_v4_research import evaluate_v4

NOW=pd.Timestamp("2026-11-19T04:30:00Z")

def frame(side="BUY"):
    ix=pd.date_range(end=NOW-pd.Timedelta(minutes=1),periods=160,freq="min",tz="UTC")
    d=pd.DataFrame({"open":100.0,"close":100.0,
                    "high":100.2,"low":99.8},index=ix)
    if side=="BUY":
        d.loc[ix[-1],["open","high","low","close"]]=[100.0,100.9,99.0,100.8]
    else:
        d.loc[ix[-1],["open","high","low","close"]]=[100.0,101.0,99.1,99.2]
    hm=pd.date_range(end=NOW-pd.Timedelta(minutes=5),periods=40,freq="5min",tz="UTC")
    m5=pd.DataFrame({"open":100.0,"close":100.0,
                     "high":103.0,"low":97.0},index=hm)
    return d,m5

def result(side="BUY",h1=None,h4=None,quote=True):
    d,m5=frame(side)
    h1=h1 if h1 is not None else ("SELL" if side=="BUY" else "BUY")
    h4=h4 if h4 is not None else h1
    bid,ask=((100.77,100.82) if side=="BUY" else (99.18,99.23))
    return evaluate_v4(d,m5,h1_bias=h1,h4_bias=h4,atr_m5=2.0,
                       now=NOW,quote_valid=quote,bid=bid,ask=ask)

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_countertrend_sweep_reclaim_mss_can_qualify_both_sides(side):
    out=result(side)
    c=next(x for x in out if x["side"]==side)
    assert c["setup_type"]=="COUNTERTREND_REVERSAL"
    assert c["stage"]=="MSS_CONFIRMED"
    assert c["entry_status"]=="ENTRY_CANDIDATE"
    assert c["mss_closed"] and c["room_atr"]>.8
    other=next(x for x in out if x["side"]!=side)
    assert other["entry_status"]!="ENTRY_CANDIDATE"

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_unknown_htf_context_cannot_create_entry(side):
    d,m5=frame(side)
    r=evaluate_v4(d,m5,h1_bias="UNAVAILABLE",h4_bias="SELL",
                  atr_m5=2,now=NOW,quote_valid=True,bid=99.99,ask=100.01)
    assert all(x["entry_status"]!="ENTRY_CANDIDATE" for x in r)
    assert all(x["setup_type"]=="HTF_CONTEXT_UNAVAILABLE" for x in r)

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_missing_quote_blocks_both_directions(side):
    r=result(side,quote=False)
    assert all(x["entry_status"]!="ENTRY_CANDIDATE" for x in r)

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_stale_ema_trend_does_not_reclassify_countertrend_as_trend(side):
    r=result(side)
    c=next(x for x in r if x["side"]==side)
    assert c["setup_type"]=="COUNTERTREND_REVERSAL"

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_trend_rejection_uses_different_setup_type(side):
    d,m5=frame(side)
    if side=="BUY":
        d.iloc[-1,d.columns.get_loc("open")]=100.1
        d.iloc[-1,d.columns.get_loc("low")]=99.8
        d.iloc[-1,d.columns.get_loc("close")]=100.4
        bid,ask=100.37,100.42
    else:
        d.iloc[-1,d.columns.get_loc("open")]=99.9
        d.iloc[-1,d.columns.get_loc("high")]=100.2
        d.iloc[-1,d.columns.get_loc("close")]=99.6
        bid,ask=99.58,99.63
    r=evaluate_v4(d,m5,h1_bias=side,h4_bias=side,atr_m5=2,
                  now=NOW,quote_valid=True,bid=bid,ask=ask)
    c=next(x for x in r if x["side"]==side)
    assert c["setup_type"]=="TREND_REJECTION"
    assert c["entry_status"]=="ENTRY_CANDIDATE"

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_low_room_to_opposing_level_blocks_entry(side):
    d,m5=frame(side)
    if side=="BUY":m5["high"]=101.0
    else:m5["low"]=99.0
    h1="SELL" if side=="BUY" else "BUY"
    bid,ask=((100.77,100.82) if side=="BUY" else (99.18,99.23))
    r=evaluate_v4(d,m5,h1_bias=h1,h4_bias=h1,atr_m5=2,
                  now=NOW,quote_valid=True,bid=bid,ask=ask)
    c=next(x for x in r if x["side"]==side)
    assert c["entry_status"]=="BLOCKED"
    assert any("opposing" in x for x in c["reasons"])

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_chasing_beyond_atr_blocks_entry(side):
    d,m5=frame(side)
    h1="SELL" if side=="BUY" else "BUY"
    bid,ask=((101.6,101.65) if side=="BUY" else (98.4,98.45))
    r=evaluate_v4(d,m5,h1_bias=h1,h4_bias=h1,atr_m5=2,
                  now=NOW,quote_valid=True,bid=bid,ask=ask)
    c=next(x for x in r if x["side"]==side)
    assert c["entry_status"]=="BLOCKED"

def test_forming_m1_candle_cannot_be_used():
    d,m5=frame()
    d.index=d.index+pd.Timedelta(minutes=1)
    with pytest.raises(ValueError,match="forming"):
        evaluate_v4(d,m5,h1_bias="SELL",h4_bias="SELL",
                    atr_m5=2,now=NOW,quote_valid=False)

def test_gapped_candle_rejected():
    d,m5=frame()
    d=d.drop(d.index[-3])
    with pytest.raises(ValueError,match="GAP"):
        evaluate_v4(d,m5,h1_bias="SELL",h4_bias="SELL",
                    atr_m5=2,now=NOW,quote_valid=False)
