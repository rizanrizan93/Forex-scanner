"""Research-only XAU macro horizon labels: H4 and D1/D3/D5/D10 sessions.

This is an OUTCOME LABELER, never a signal generator. It takes the signal
timestamp and price, then measures future H4/daily/weekly behavior.
No +$3 profit target is used to define whether macro direction was correct.

D1, D3, D5 and D10 are subsequent FULL UTC trading dates' final recorded
M1 closes, not calendar elapsed days. Holidays, partial or missing weekday
sessions are conservatively censored (no synthetic prices / interpolation).
Bid/ask historical costs are unknown; caller supplies an explicit assumption.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from math import isfinite
import pandas as pd

HORIZONS={"H4":4,"D1":1,"D3":3,"D5":5,"D10":10}
MIN_FULL_SESSION_M1=1000
MAX_WITHIN_SESSION_GAP_MINUTES=120
MAX_ENTRY_QUOTE_LAG_MINUTES=0

def _censor(reason, *, detail=None):
    return {"status":"CENSORED","reason":reason,
            "detail":detail,"direction_correct":None,
            "terminal_net_usd_oz":None,"signed_net_return_pct":None,
            "mfe_usd_oz":None,"mae_usd_oz":None,"end_at_utc":None}

def _eval(path,entry_price,entry_at,side,cost):
    sign=1 if side=="BUY" else -1
    end_price=float(path.close.iloc[-1])
    net=sign*(end_price-entry_price)-cost
    high=float(path.high.max());low=float(path.low.min())
    mfe=(high-entry_price if sign==1 else entry_price-low)
    mae=(entry_price-low if sign==1 else high-entry_price)
    return {
        "status":"EVALUATED",
        "reason":None,"detail":None,
        "entry_at_utc":entry_at.isoformat(),
        "end_at_utc":(path.index[-1]+pd.Timedelta(minutes=1)).isoformat(),
        "entry_price":round(entry_price,5),"end_price":round(end_price,5),
        "direction_correct":bool(net>0),
        "gross_directional_move_usd_oz":round(sign*(end_price-entry_price),4),
        "terminal_net_usd_oz":round(net,4),
        "signed_net_return_pct":round(100*net/entry_price,6),
        "mfe_usd_oz":round(max(0,mfe-cost),4),
        "mae_usd_oz":round(max(0,mae),4),
        "cost_assumed_usd_oz":cost,
    }

def _full_session(g):
    if len(g)<MIN_FULL_SESSION_M1:
        return False,"INSUFFICIENT_MINUTES"
    if g.index[0].hour>2:
        return False,"SESSION_START_MISSING"
    if g.index[-1].hour<19:
        return False,"SESSION_END_MISSING"
    gaps=g.index.to_series().diff().iloc[1:]
    if not gaps.empty and gaps.max()>pd.Timedelta(minutes=MAX_WITHIN_SESSION_GAP_MINUTES):
        return False,"INTRADAY_M1_GAP"
    return True,None

def evaluate_macro_horizons(
    m1:pd.DataFrame, *,signal_at,side:str,cost_usd_oz:float=0.50,
):
    """Return causal-label audit for both intraday and daily/weekly movement.

    Signal must already be frozen by another module at 'signal_at' UTC. A
    future label is scored only when the relevant price data exists.
    """
    if side not in ("BUY","SELL"):raise ValueError("BAD_SIDE")
    if not isfinite(float(cost_usd_oz)) or not (0<=cost_usd_oz<=20):
        raise ValueError("INVALID_COST")
    if not isinstance(m1.index,pd.DatetimeIndex) or m1.index.tz is None:
        raise ValueError("UTC_AWARE_M1_REQUIRED")
    data=m1[["open","high","low","close"]].copy()
    data.index=data.index.tz_convert("UTC")
    if data.index.has_duplicates or not data.index.is_monotonic_increasing:
        raise ValueError("M1_ORDER_OR_DUPLICATES")
    if data.isna().any().any():
        raise ValueError("NONFINITE_PRICE")
    at=pd.Timestamp(signal_at)
    if at.tzinfo is None:raise ValueError("UTC_AWARE_SIGNAL_REQUIRED")
    at=at.tz_convert("UTC")
    if at.second or at.microsecond:
        raise ValueError("SIGNAL_MUST_ALIGN_TO_M1_OPEN")
    res={"contract":"FED_XAU_MULTI_HORIZON_OUTCOME_LABELS_V1",
         "signal_at_utc":at.isoformat(),"side":side,
         "cost_assumption_usd_oz":cost_usd_oz,
         "timestamp_semantics":"M1 UTC OPEN / signal at prior M1 CLOSE",
         "daily_semantics":"next 1/3/5/10 complete weekday UTC trading-session CLOSES",
         "release_provenance_requirement":"EXTERNAL_SIGNAL_DECISION_MUST_BE_PIT_VERIFIED",
         "not_a_trading_signal":True,"authority_to_deploy":False,
         "outcomes":{}}
    k=data.index.get_indexer([at])
    if int(k[0])<0:
        res["outcomes"]={h:_censor("NO_EXACT_NEXT_M1_OPEN") for h in HORIZONS}
        return res
    i=int(k[0])
    if i==0 or data.index[i-1]!=at-pd.Timedelta(minutes=1):
        res["outcomes"]={h:_censor("NO_COMPLETE_PRE_SIGNAL_M1") for h in HORIZONS}
        return res
    entry=float(data.open.iloc[i])
    if entry<=0 or not isfinite(entry):
        raise ValueError("INVALID_ENTRY_PRICE")
    res["entry_price"]=round(entry,5)
    target=at+pd.Timedelta(hours=4)
    # H4 terminal requires *all* minute bars until end. Trading breaks
    # cannot be silently filled even if the last quote looks favorable.
    window=data.loc[(data.index>=at)&(data.index<target)]
    if (len(window)==240 and window.index[0]==at and
        window.index[-1]==target-pd.Timedelta(minutes=1) and
        (window.index.to_series().diff().iloc[1:]==pd.Timedelta(minutes=1)).all()):
        res["outcomes"]["H4"]=_eval(window,entry,at,side,cost_usd_oz)
    else:
        res["outcomes"]["H4"]=_censor("H4_NOT_FULL_CONTIGUOUS_240M1",
              detail={"observed_minutes":len(window),"expected_minutes":240})
    # UTC weekday sessions after event day. Weekend/Sunday partial hours
    # are deliberately not counted as one of 5 weekly trading sessions.
    cursor=at.date()+timedelta(days=1)
    last=data.index[-1].date()
    count=0;blocked=None
    while cursor<=last and count<10:
        if cursor.weekday()<5:
            day=data.loc[(data.index.date==cursor)]
            ok,why=_full_session(day)
            if not ok:
                blocked={"date":cursor.isoformat(),"reason":why}
                break
            count+=1
            path=data.loc[(data.index>=at)&(data.index<=day.index[-1])]
            # All observed prices up to evaluation close, with weekend
            # gaps allowed only after each full weekday. Do not impute.
            h=f"D{count}"
            if h in ("D1","D3","D5","D10"):
                res["outcomes"][h]=_eval(path,entry,at,side,cost_usd_oz)
                res["outcomes"][h]["completed_utc_trading_sessions"]=count
                res["outcomes"][h]["label_session_date_utc"]=cursor.isoformat()
        cursor+=timedelta(days=1)
    for h in ("D1","D3","D5","D10"):
        if h not in res["outcomes"]:
            res["outcomes"][h]=_censor(
                "MISSING_OR_PARTIAL_TRADING_SESSION" if blocked
                else "INSUFFICIENT_FUTURE_FULL_TRADING_SESSIONS",
                detail=blocked if blocked else {"complete_future_sessions":count})
    return res
