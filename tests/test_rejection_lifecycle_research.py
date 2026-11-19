"""Causal rejection lifecycle regression tests; synthetic prices, no win-rate claim."""
import pandas as pd
import pytest
from fx_scanner.rejection_lifecycle_research import advance_events

T=pd.Timestamp("2026-11-19T04:00:00+00:00")

def data(side="SELL"):
    ix=pd.date_range(T,periods=5,freq="min",tz="UTC")
    if side=="SELL":
        lows=[3726.8,3726.7,3726.9,3727.0,3727.3]
        highs=[3728.0,3728.0,3728.0,3728.1,3728.6]
        opens=[3727.5,3727.5,3727.5,3727.5,3728.1]
        closes=[3727.4,3727.4,3727.4,3727.5,3727.7]
        zone=dict(side="SELL",name="M5 RESISTANCE",price=3728.0,
                  low=3727.8,high=3728.2,stage="EARLY REJECTION")
    else:
        lows=[3719.8,3719.8,3719.7,3719.8,3719.4]
        highs=[3721.0,3721.0,3721.1,3721.0,3720.5]
        opens=[3720.3,3720.3,3720.3,3720.3,3719.9]
        closes=[3720.4,3720.4,3720.4,3720.3,3720.1]
        zone=dict(side="BUY",name="M5 SUPPORT",price=3720.0,
                  low=3719.8,high=3720.2,stage="EARLY REJECTION")
    return pd.DataFrame(dict(open=opens,high=highs,low=lows,close=closes),index=ix),zone

def append_bar(d,close,high,low):
    opened=d.index[-1]+pd.Timedelta(minutes=1)
    row=pd.DataFrame(dict(open=[d.close.iloc[-1]],close=[close],high=[high],low=[low]),index=[opened])
    assert row.high.iloc[0]>=max(row.open.iloc[0],close)
    assert row.low.iloc[0]<=min(row.open.iloc[0],close)
    return pd.concat([d,row])

def evaluate(d,prior,zones=None,m5=None,now=None,atr=2,**kw):
    if now is None: now=d.index[-1]+pd.Timedelta(minutes=1)
    if m5 is None:
        m5=pd.DataFrame({"close":[]},index=pd.DatetimeIndex([],tz="UTC"))
    return advance_events(prior,d,m5,zones or [],now=now,atr=atr,**kw)

@pytest.mark.parametrize('side',["BUY","SELL"])
def test_rejection_then_structural_confirmation_then_breakout_reverses_state(side):
    d,zone=data(side)
    e=evaluate(d,[],[zone],now=T+pd.Timedelta(minutes=5,seconds=20))
    assert len(e)==1 and e[0]['state']=="EARLY_REJECTION"
    initial=e[0]['invalidation']
    if side=="SELL":
        d=append_bar(d,close=3723,high=3727.8,low=3722.7)
    else:
        d=append_bar(d,close=3722.5,high=3722.8,low=3720.0)
    e=evaluate(d,e)
    assert e[0]['state']=="REJECTION_CONFIRMED"
    assert e[0]['invalidation']==initial
    if side=="SELL":
        d=append_bar(d,close=3735,high=3735.5,low=3722.0)
    else:
        d=append_bar(d,close=3715,high=3723.0,low=3714.0)
    e=evaluate(d,e)
    assert e[0]['state']=="REJECTION_INVALIDATED"
    assert e[0]['invalidation']==initial
    m5=pd.DataFrame({"close":[3732 if side=="SELL" else 3716]},
                    index=pd.DatetimeIndex([T+pd.Timedelta(minutes=10)]))
    e=evaluate(d,e,m5=m5,now=T+pd.Timedelta(minutes=10))
    assert e[0]['state']=="BREAKOUT_CONFIRMED"
    assert e[0]['invalidation']==initial

@pytest.mark.parametrize("side",["BUY","SELL"])
def test_fresh_quote_breach_warns_before_candle_close(side):
    d,zone=data(side)
    quote={"ask":3735,"bid":3734.9} if side=="SELL" else {"bid":3715,"ask":3715.1}
    e=evaluate(d,[],[zone],now=T+pd.Timedelta(minutes=5,seconds=10),
               quote_valid=True,**quote)
    assert len(e)==1 and e[0]["state"]=="EARLY_REJECTION"
    assert e[0]["display_state"]=="BREAKOUT_RISK"

def test_dynamic_zone_shift_cannot_move_frozen_invalidation():
    d,zone=data("SELL")
    e=evaluate(d,[],[zone])
    old=e[0]["invalidation"]
    d=append_bar(d,close=3727.4,high=3727.8,low=3727.1)
    shifted=dict(zone,price=3733,low=3732,high=3734,stage="MONITOR")
    e=evaluate(d,e,[shifted])
    assert len(e)==1 and e[0]["invalidation"]==old

def test_missing_m1_between_signal_and_next_check_is_data_gap():
    d,zone=data("SELL")
    e=evaluate(d,[],[zone])
    d=append_bar(d,close=3727.4,high=3727.9,low=3727.0)
    d=append_bar(d,close=3727.4,high=3727.9,low=3727.0)
    d=d.drop(d.index[-2])
    e=evaluate(d,e)
    assert e[0]["state"]=="DATA_GAP"

def test_repeat_same_signal_does_not_rearm():
    d,zone=data("SELL")
    e=evaluate(d,[],[zone],now=T+pd.Timedelta(minutes=5,seconds=10))
    e=evaluate(d,e,[zone],now=T+pd.Timedelta(minutes=5,seconds=35))
    assert len(e)==1

def test_both_sides_can_be_tracked_independently():
    d,zone=data("SELL")
    e=evaluate(d,[],[zone])
    d2,buy=data("BUY")
    e=evaluate(d2,e,[buy],now=T+pd.Timedelta(minutes=5))
    assert {v["side"] for v in e}=={"SELL","BUY"}
