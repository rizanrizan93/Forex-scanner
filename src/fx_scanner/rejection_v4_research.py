"""XAU Rejection V4: symmetric trend and countertrend signals, RESEARCH ONLY.

A setup is a CANDIDATE, not a probability or instruction to trade. Evaluated
on past closed M1 bars and past completed M5/H1/H4 information only.
"""
from __future__ import annotations
import math
import pandas as pd

def _side(s):
    if s not in ("BUY","SELL"): raise ValueError("side")
    return 1 if s=="BUY" else -1

def _sweep_info(d: pd.DataFrame, i: int, side: str, atr5: float):
    # The 12 prior CLOSED M1 bars and sweep candle must be consecutive.
    if i<16:return None
    bars=d.iloc[i-15:i+1]
    if not (bars.index.to_series().diff().iloc[1:]==pd.Timedelta(minutes=1)).all():
        return None
    p=d.iloc[i-12:i]; row=d.iloc[i]
    prior_low=float(p.low.min()); prior_high=float(p.high.max())
    span=max(float(row.high-row.low),1e-9)
    sign=_side(side)
    if sign==1:
        swept=float(row.low)<prior_low-.015*atr5
        reclaim=float(row.close)>prior_low
        wick=float(min(row.open,row.close)-row.low)/span
        extreme=float(row.low)
        reclaim_level=prior_low
        trigger=float(d.high.iloc[i-3:i].max())
    else:
        swept=float(row.high)>prior_high+.015*atr5
        reclaim=float(row.close)<prior_high
        wick=float(row.high-max(row.open,row.close))/span
        extreme=float(row.high)
        reclaim_level=prior_high
        trigger=float(d.low.iloc[i-3:i].min())
    if not (swept and reclaim and wick>=.25): return None
    return {"event_at":(d.index[i]+pd.Timedelta(minutes=1)).isoformat(),
            "swept_level":round(reclaim_level,5),
            "sweep_extreme":round(extreme,5),
            "mss_trigger":round(trigger,5),
            "wick_fraction":round(wick,3)}

def _opposing_room(m5:pd.DataFrame,side:str,price:float,atr5:float):
    # Levels known strictly prior to signal; no hindsight swing pivot.
    prev=m5.iloc[-36:]
    if len(prev)<20:return None
    levels=(prev.high if side=="BUY" else prev.low).astype(float)
    valid=levels[levels>price] if side=="BUY" else levels[levels<price]
    if valid.empty:return None
    opposing=float(valid.min() if side=="BUY" else valid.max())
    return round(abs(opposing-price)/atr5,3)

def evaluate_v4(d: pd.DataFrame, m5:pd.DataFrame, *, h1_bias:str,
                h4_bias:str, atr_m5:float, now, quote_valid:bool,
                bid=None,ask=None)->list[dict]:
    """Return BUY/SELL candidate statuses; requires CLOSED UTC-indexed M1/M5.

    Current trend rejection uses EMA20 from completed M5. Countertrend
    reversal uses M1 liquidity sweep and reclaim plus *observed* M1 MSS.
    All thresholds fixed research hypotheses; no live execution hook.
    """
    at=pd.Timestamp(now)
    if at.tzinfo is None:raise ValueError("timezone-aware now required")
    at=at.tz_convert("UTC")
    if not math.isfinite(float(atr_m5)) or atr_m5<=0:raise ValueError("ATR_M5_INVALID")
    if len(d)<32 or len(m5)<25:raise ValueError("M1_M5_INSUFFICIENT")
    if d.index.tz is None or m5.index.tz is None or m5.index[-1]>at:
        raise ValueError("M1/M5 as-of violation")
    if d.index[-1]+pd.Timedelta(minutes=1)>at:
        raise ValueError("forming M1")
    if not (d.index.to_series().diff().iloc[-16:]==pd.Timedelta(minutes=1)).all():
        raise ValueError("GAP_LAST_16_M1")
    quote_price=(float(ask)+float(bid))/2 if quote_valid else float(d.close.iloc[-1])
    spread=float(ask-bid) if quote_valid else None
    if quote_valid and (not all(math.isfinite(float(z)) for z in (ask,bid)) or bid<=0 or ask<bid):
        raise ValueError("INVALID_QUOTE")
    e20=float(m5.close.ewm(span=20,adjust=False).mean().iloc[-1])
    last=d.iloc[-1]
    span=max(float(last.high-last.low),1e-9)
    out=[]
    for side in ("BUY","SELL"):
        sign=_side(side)
        adverse={"BUY":"SELL","SELL":"BUY"}[side]
        htf_available=h1_bias in ("BUY","SELL") and h4_bias in ("BUY","SELL")
        trend=htf_available and h1_bias==h4_bias==side
        counter=htf_available and (h1_bias==adverse or h4_bias==adverse) and not trend
        regime="TREND" if trend else "COUNTERTREND" if counter else "HTF_UNVERIFIED"
        px=float(ask if side=="BUY" else bid) if quote_valid else float(last.close)
        room=_opposing_room(m5,side,px,atr_m5)
        room_ok=room is not None and room>=.8
        # Event may have swept on this bar (early) or last 1-3 bars
        # (MSS confirmed). Search past only, never future.
        sweeps=[x for i in range(len(d)-4,len(d))
                if (x:=_sweep_info(d,i,side,atr_m5)) is not None]
        recent=sweeps[-1] if sweeps else None
        sweep_age=(at-pd.Timestamp(recent["event_at"])).total_seconds()/60 if recent else None
        momentum=(last.close>last.open if sign==1 else last.close<last.open)
        body=abs(float(last.close-last.open))/span
        # Confirmed MSS is a CLOSED candle *after* the sweep, or the
        # sweep candle itself if it breaks the pre-sweep structure.
        mss=bool(recent and sign*(float(last.close)-recent["mss_trigger"])>.0 and
                 momentum and body>=.30 and sweep_age is not None and 0<=sweep_age<=3)
        invalid=(recent["sweep_extreme"]-.10*atr_m5 if sign==1 else
                 recent["sweep_extreme"]+.10*atr_m5) if recent else None
        still_valid=bool(invalid is not None and
                         sign*(float(last.close)-invalid)>0)
        chase=(sign*(px-recent["swept_level"])/atr_m5 if recent else None)
        chase_ok=chase is not None and 0<=chase<=.65
        spread_ok=quote_valid and spread<=.20*atr_m5
        # Trend setup: completed M5 EMA touched and directional M1
        # closed-candle rejection. This is separate from countertrend.
        near_ema=float(last.low)<=e20<=float(last.high)
        wick=(float(min(last.open,last.close)-last.low)/span if sign==1 else
              float(last.high-max(last.open,last.close))/span)
        ema_reclaim=(sign*(float(last.close)-e20)>0 and
                     momentum and wick>=.25 and near_ema)
        if trend:
            category="TREND_REJECTION"
            stage="RECLAIM_DETECTED" if ema_reclaim else "WATCH_EMA"
            signal=ema_reclaim
            level=e20
            invalidation=(float(last.low)-.10*atr_m5 if sign==1
                          else float(last.high)+.10*atr_m5)
            entry_distance=sign*(px-level)/atr_m5
            timing_ok=0<=entry_distance<=.65
        elif counter:
            category="COUNTERTREND_REVERSAL"
            stage=("MSS_CONFIRMED" if mss and still_valid else
                   "SWEEP_RECLAIM_WATCH" if recent and still_valid else "WAIT_SWEEP")
            signal=mss and still_valid
            level=recent["swept_level"] if recent else None
            invalidation=invalid
            timing_ok=chase_ok
        else:
            category="HTF_CONTEXT_UNAVAILABLE"
            stage="WATCH_ONLY"
            signal=False
            level=recent["swept_level"] if recent else e20
            invalidation=invalid
            timing_ok=False
        eligible=bool(signal and spread_ok and timing_ok and room_ok)
        reasons=[]
        if not quote_valid:reasons.append("No fresh bid/ask quote")
        elif not spread_ok:reasons.append("Spread exceeds 0.2 ATR M5")
        if not timing_ok:reasons.append("Price too far / wrong side of watch level")
        if not room_ok:reasons.append("Insufficient verified room to opposing M5 swing")
        if regime=="HTF_UNVERIFIED":reasons.append("H1/H4 incomplete or ambiguous")
        out.append({
            "side":side,"setup_type":category,"regime":regime,
            "stage":stage,"entry_status":("ENTRY_CANDIDATE" if eligible else
                        "WATCH_ONLY" if not signal else "BLOCKED"),
            "watch_level":round(float(level),4) if level is not None else None,
            "invalidation":round(float(invalidation),4) if invalidation is not None else None,
            "room_atr":room,"sweep":recent,
            "mss_closed":bool(mss),"quote_ok":bool(quote_valid),
            "reasons":reasons,
            "note":"Uncalibrated read-only candidate; not executable or LIVE signal",
        })
    return out
