"""RIZAN R6 SMC/ICT-inspired CAUSALLY CONFIRMED M5 swing liquidity.

No price level or pivot can be recognized until TWO complete M5 bars
have closed to the RIGHT of the potential swing. Input M5 timestamps
are CLOSE times. Consequently a swing at bar i only becomes known
at timestamp i+2. Same-bar ties or gaps disqualify that pivot.

This is a structural-level hypothesis for the zero-entries R5/V4
problem, not a probability, liquidity guarantee, or trade signal.
Does not modify original V4, Frozen V1 or live order routing.
"""
from __future__ import annotations
from math import isfinite
import pandas as pd

R6_CONTRACT="RIZAN_CONFIRMED_M5_SWING_OPPOSING_ROOM_R6_RESEARCH"
MIN_ROOM_ATR=.80
LEFT=2
RIGHT=2
LOOKBACK=96
ROOM_V4_REASON="Insufficient verified room to opposing M5 swing"
VALID_PATTERN_STAGES=frozenset(("MSS_CONFIRMED","RECLAIM_DETECTED"))

def _check_m5(m5,now):
    ts=pd.Timestamp(now)
    if ts.tzinfo is None:
        raise ValueError("AWARE_UTC_ASOF_REQUIRED")
    ts=ts.tz_convert("UTC")
    if not isinstance(m5,pd.DataFrame) or len(m5)<LEFT+RIGHT+2:
        raise ValueError("INSUFFICIENT_M5")
    if not isinstance(m5.index,pd.DatetimeIndex) or m5.index.tz is None:
        raise ValueError("M5_UTC_CLOSE_TIMESTAMPS_REQUIRED")
    if not m5.index.is_monotonic_increasing or m5.index.has_duplicates:
        raise ValueError("UNSORTED_OR_DUPLICATED_M5")
    if m5.index[-1].tz_convert("UTC")>ts:
        raise ValueError("FUTURE_M5_BAR_LOOKAHEAD")
    if not set(("high","low")).issubset(m5.columns):
        raise ValueError("M5_HIGH_LOW_REQUIRED")
    if not all(isfinite(float(x)) for x in m5[["high","low"]].to_numpy().ravel()):
        raise ValueError("M5_NONFINITE")
    if (m5.high<=0).any() or (m5.low<=0).any() or (m5.high<m5.low).any():
        raise ValueError("INVALID_M5_HIGH_LOW")
    return ts

def confirmed_m5_pivots(m5,*,now,lookback=LOOKBACK,left=LEFT,right=RIGHT):
    """Return ONLY points that were confirmed by right closed bars by NOW.

    The m5 series itself may contain missing sessions; local five-bar
    continuity is required to prevent false pivots across market gaps.
    """
    at=_check_m5(m5,now)
    if not (2<=left<=5 and 2<=right<=5 and 30<=lookback<=200):
        raise ValueError("INVALID_PIVOT_PROTOCOL")
    d=m5.iloc[-(lookback+left+right):].copy()
    if len(d)<left+right+1:
        return []
    pivots=[]
    for i in range(left,len(d)-right):
        window=d.iloc[i-left:i+right+1]
        # EXACT five-minute sequence around pivot (M5 close index).
        if not (window.index.to_series().diff().iloc[1:]==
                pd.Timedelta(minutes=5)).all():
            continue
        center=d.iloc[i]
        highs=window.high.astype(float).to_numpy()
        lows=window.low.astype(float).to_numpy()
        if center.high==max(highs) and sum(x>=center.high for x in highs)==1:
            pivots.append({
                "kind":"SWING_HIGH","level":round(float(center.high),5),
                "pivot_at_utc":d.index[i].tz_convert("UTC").isoformat(),
                "confirmed_at_utc":d.index[i+right].tz_convert("UTC").isoformat(),
                "confirmed_closed_m5_to_right":right,
            })
        if center.low==min(lows) and sum(x<=center.low for x in lows)==1:
            pivots.append({
                "kind":"SWING_LOW","level":round(float(center.low),5),
                "pivot_at_utc":d.index[i].tz_convert("UTC").isoformat(),
                "confirmed_at_utc":d.index[i+right].tz_convert("UTC").isoformat(),
                "confirmed_closed_m5_to_right":right,
            })
    if any(pd.Timestamp(p["confirmed_at_utc"])>at for p in pivots):
        raise ValueError("FUTURE_PIVOT_ASSERTION")
    return pivots

def pivot_opposing_room(m5,*,side,price,atr_m5,now):
    """BUY must have past-confirmed swing high ABOVE ask; SELL
    past-confirmed swing low BELOW bid. Unknown room is *not* infinity.
    """
    if side not in ("BUY","SELL"):
        raise ValueError("BAD_SIDE")
    if not isfinite(float(price)) or price<=0 or not isfinite(float(atr_m5)) or atr_m5<=0:
        raise ValueError("PRICE_OR_ATR_INVALID")
    pivots=confirmed_m5_pivots(m5,now=now)
    candidates=[p for p in pivots if (
        p["kind"]=="SWING_HIGH" and p["level"]>price if side=="BUY"
        else p["kind"]=="SWING_LOW" and p["level"]<price)]
    if not candidates:
        return {
            "contract":R6_CONTRACT,"side":side,
            "room_atr":None,"opposing_swing":None,
            "room_verified":False,"reason":"NO_CAUSALLY_CONFIRMED_OPPOSING_SWING",
            "candidates_considered":len(pivots),
            "authority_to_trade":False,
        }
    nearest=min(candidates,key=lambda p:abs(p["level"]-price))
    room=abs(nearest["level"]-price)/float(atr_m5)
    return {
        "contract":R6_CONTRACT,"side":side,
        "room_atr":round(room,4),
        "opposing_swing":nearest,
        "room_verified":bool(room>=MIN_ROOM_ATR),
        "reason":"CONFIRMED_SWING_ROOM_OK" if room>=MIN_ROOM_ATR
                 else "TOO_CLOSE_TO_CONFIRMED_OPPOSING_SWING",
        "candidates_considered":len(pivots),
        "authority_to_trade":False,
    }

def compare_v4_candidate(candidate,m5,*,price,atr_m5,now):
    """A/B isolate ONLY the opposing-room metric.

    Prior V4 quote, anti-chase, HTF, failed-rejection cooldown and
    actual pattern stage MUST already be satisfied. Research outputs
    never become cTrader entries, even when an old room veto clears.
    """
    side=candidate.get("side")
    if side not in ("BUY","SELL"):
        raise ValueError("V4_SIDE_UNVERIFIED")
    stage=candidate.get("stage")
    existing=list(candidate.get("reasons") or [])
    unrelated=[r for r in existing if r!=ROOM_V4_REASON]
    eligible_without_room=bool(
        stage in VALID_PATTERN_STAGES and
        candidate.get("quote_ok") is True and
        not unrelated and
        candidate.get("entry_status") in (
            "BLOCKED","ENTRY_CANDIDATE"))
    pivot=pivot_opposing_room(
        m5,side=side,price=price,atr_m5=atr_m5,now=now)
    baseline=candidate.get("entry_status")=="ENTRY_CANDIDATE"
    r6=bool(eligible_without_room and pivot["room_verified"])
    return {
        "contract":"RIZAN_R6_V4_OPPOSING_ROOM_AB_RESEARCH",
        "side":side,"v4_setup_type":candidate.get("setup_type"),
        "v4_stage":stage,"v4_raw_entry_candidate":baseline,
        "v4_room_atr":candidate.get("room_atr"),
        "v4_unrelated_blockers":unrelated,
        "pattern_and_other_gates_ok":eligible_without_room,
        "r6_pivot_room":pivot,
        "r6_hypothetical_candidate":r6,
        "r6_recovered_old_room_only":bool(r6 and not baseline),
        "r6_blocked_old_candidate":bool(baseline and not r6),
        "authority_to_trade":False,
        "backtested_80pct":False,
    }
