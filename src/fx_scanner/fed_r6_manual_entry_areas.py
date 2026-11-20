"""RIZAN Fed R6 — read-only, causal XAUUSD manual entry-area map.

Price source is an independently validated cTrader public M1 market-only
snapshot (via manual_r3_feed). Source candle timestamps are OPEN times;
a 5-minute pivot cannot be used until two M5 RIGHT bars have closed.
No ex-post USMPD data can authorize a live entry. A missing live Fed R4
macro confirmation means WAIT, while WATCH zones may be displayed.

This module NEVER sends orders, reads portfolio secrets or claims 80%.
"""
from __future__ import annotations
from datetime import UTC, datetime, timedelta
from math import isfinite
from urllib.parse import urlsplit
import pandas as pd

CONTRACT = "RIZAN_XAU_FED_R6_MANUAL_AREA_V1"
EXPECTED_MACRO = "FED_R4_POLICY_INFORMATION_XAU_READONLY_V1"
LOOKBACK_M5 = 96
PIVOT_LEFT = 2
PIVOT_RIGHT = 2
MAX_ZONE_AGE_H = 36
MAX_QUOTE_AGE_S = 30
MAX_M1_AGE_S = 90


def _utc(v):
    t = pd.Timestamp(v)
    if t.tzinfo is None:
        raise ValueError("TZ_AWARE_REQUIRED")
    return t.tz_convert("UTC")


def _finite(v):
    try:
        x = float(v)
        return x if isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _out(now, reason):
    return {
        "contract": CONTRACT, "as_of": now.isoformat(),
        "status": "WAIT", "reason": reason, "macro_direction": "WAIT",
        "macro_reason": "NO_VERIFIED_R4_REALTIME_FEED",
        "price": None, "quote_at": None, "last_closed_m1": None,
        "atr_m5": None, "bias_h1": "UNKNOWN", "bias_h4": "UNKNOWN",
        "zones": [], "entry_allowed": False,
        "authority_to_send_orders": False, "authority_to_modify_cbots": False,
        "score_is_accuracy": False, "backtested_80pct_both_sides": False,
        "market_context": {"direction":"WAIT","strength":"UNAVAILABLE","mode":"UNAVAILABLE"},
    }


def verified_macro_direction(macro, now):
    """Only a future genuine, original event-matched Fed R4 source can pass.

    Currently no live, minute-precise intraday OIS/TIPS input is wired.
    This explicitly refuses to label existing daily FRED as intraday.
    """
    if not isinstance(macro, dict) or macro.get("contract") != EXPECTED_MACRO:
        return "WAIT", "NO_VERIFIED_R4_REALTIME_FEED"
    if (macro.get("authority_to_send_orders") is not False or
        macro.get("authority_to_deploy") is not False or
        macro.get("predicted_probability") is not None or
        macro.get("verified_80pct_both_sides") is not False or
        macro.get("market_data_status") != "VALIDATED_CAPTURED_PRE_POST_INTRADAY" or
        macro.get("policy_information_regime") != "POLICY_LIKE"):
        return "WAIT", "UNVERIFIED_FED_MACRO_PROVENANCE"
    side = macro.get("direction")
    if side not in ("BUY", "SELL"):
        return "WAIT", "MACRO_MIXED_OR_WAIT"
    if macro.get("watch_bias") != ("SEARCH_BUY_DIP" if side == "BUY" else
                                  "SEARCH_SELL_REBOUND"):
        return "WAIT", "CONTRADICTORY_R4_DIRECTION"
    event = macro.get("event_id")
    if not isinstance(event, str) or not event.strip():
        return "WAIT", "NO_IDENTIFIED_FOMC_EVENT"
    try:
        released = _utc(macro["release_at"])
        decided = _utc(macro["decision_at"])
        if not (released <= decided <= now and
                (now-decided).total_seconds() <= 600 and
                (now-released).total_seconds() <= 9000):
            return "WAIT", "MACRO_EXPIRED_OR_FUTURE"
    except (KeyError, ValueError, TypeError):
        return "WAIT", "MACRO_TIMESTAMP_MISSING"
    return side, "VALID_R4_READONLY_WATCH"


def _completed_tf(frame, minutes, now):
    # M1 input index is M1 OPEN; resample index is higher-TF CLOSE.
    g = frame.resample(f"{minutes}min", label="right", closed="left")
    d = g.agg({"open":"first","high":"max","low":"min","close":"last"})
    n = g["close"].count()
    d = d[n == minutes]
    return d[d.index <= now]


def _atr(d, n=14):
    prev = d.close.shift()
    tr = pd.concat([d.high-d.low,(d.high-prev).abs(),
                    (d.low-prev).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean().iloc[-1]


def _bias(d):
    if len(d)<24:
        return "UNKNOWN"
    e = d.close.ewm(span=20,adjust=False,min_periods=20).mean()
    recent = float(d.close.iloc[-1])
    if recent>float(e.iloc[-1]) and e.iloc[-1]>e.iloc[-4]:
        return "BUY"
    if recent<float(e.iloc[-1]) and e.iloc[-1]<e.iloc[-4]:
        return "SELL"
    return "MIXED"


def confirmed_pivots(m5, now):
    """Strict 2-left, 2-right M5 pivots; ties and gaps disqualify."""
    d = m5.iloc[-(LOOKBACK_M5 + PIVOT_LEFT + PIVOT_RIGHT):]
    pts = []
    for i in range(PIVOT_LEFT, len(d)-PIVOT_RIGHT):
        w = d.iloc[i-PIVOT_LEFT:i+PIVOT_RIGHT+1]
        if not (w.index.to_series().diff().iloc[1:]==
                pd.Timedelta(minutes=5)).all():
            continue
        at = d.index[i+PIVOT_RIGHT]
        if at>now:
            continue
        high = float(d.high.iloc[i])
        low = float(d.low.iloc[i])
        if high>max(float(v) for j,v in enumerate(w.high) if j != PIVOT_LEFT):
            pts.append({"kind":"SWING_HIGH", "price":high,
                        "pivot_at":d.index[i].isoformat(),
                        "confirmed_at":at.isoformat(), "confirm_index":i+PIVOT_RIGHT})
        if low<min(float(v) for j,v in enumerate(w.low) if j != PIVOT_LEFT):
            pts.append({"kind":"SWING_LOW", "price":low,
                        "pivot_at":d.index[i].isoformat(),
                        "confirmed_at":at.isoformat(), "confirm_index":i+PIVOT_RIGHT})
    return pts


def _news_ok(news, now):
    if news is None:
        return False, "CALENDAR_UNVERIFIED"
    if not isinstance(news, list):
        return False, "CALENDAR_INVALID"
    for e in news:
        if e.get("event") not in ("FOMC","CPI","PPI","NFP"):
            continue
        try:
            when = _utc(e["at"])
        except (KeyError, ValueError, TypeError):
            return False, "CALENDAR_INVALID"
        mins = 60 if e["event"] == "FOMC" else 30
        if abs((now-when).total_seconds()) <= mins*60:
            return False, "HIGH_IMPACT_NEWS_WINDOW"
    return True, "CALENDAR_OK"


def evaluate_areas(frame, *, now, bid=None, ask=None, quote_at=None,
                   news_events=None, macro=None, market_context=None):
    """Compute at most two WATCH zones per side with conditional levels.

    A zone can be mapped despite macro WAIT, but no entry or alert is
    authorized. Prior touched/broken zones are never represented fresh.
    """
    now = _utc(now)
    out = _out(now, "MARKET_DATA_UNAVAILABLE")
    if isinstance(market_context,dict) and market_context.get("contract")=="RIZAN_XAU_R61_MARKET_DIRECTION_CONTEXT_V1":
        out["market_context"]=market_context
    if not isinstance(frame, pd.DataFrame) or not set(
            ("open","high","low","close")).issubset(frame.columns):
        return out
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None:
        return out
    d = frame[["open","high","low","close"]].copy()
    d.index = d.index.tz_convert("UTC")
    d = d[d.index + pd.Timedelta(minutes=1) <= now]
    if (len(d)<2000 or d.index.has_duplicates or
        not d.index.is_monotonic_increasing or d.isna().any().any()):
        out["reason"] = "NEED_2000_VALID_SORTED_M1"
        return out
    valid_ohlc=((d.low>0)&(d.high>=d.low)&
                (d.low<=d[["open","close"]].min(axis=1))&
                (d.high>=d[["open","close"]].max(axis=1)))
    if not valid_ohlc.all():
        out["reason"] = "INVALID_M1_OHLC"
        return out
    last_closed = d.index[-1] + pd.Timedelta(minutes=1)
    out["last_closed_m1"] = last_closed.isoformat()
    if (now-last_closed).total_seconds() > MAX_M1_AGE_S:
        out["reason"] = "STALE_M1_NO_LIVE_AREAS"
        return out
    m5 = _completed_tf(d,5,now)
    h1 = _completed_tf(d,60,now)
    h4 = _completed_tf(d,240,now)
    if len(m5)<50:
        out["reason"]="M5_NOT_ENOUGH_FULL_BARS"
        return out
    atr = _finite(_atr(m5))
    if atr is None or atr<=0:
        out["reason"]="ATR_NOT_READY"
        return out
    out["atr_m5"]=round(atr,4)
    out["bias_h1"]=_bias(h1)
    out["bias_h4"]=_bias(h4)
    out["macro_direction"],out["macro_reason"]=verified_macro_direction(macro,now)
    quote_valid=False
    try:
        qt=_utc(quote_at)
        b,a=_finite(bid),_finite(ask)
        quote_valid=bool(b is not None and a is not None and 0<b<=a and
                         -5 <= (now-qt).total_seconds() <= MAX_QUOTE_AGE_S)
    except (ValueError,TypeError):
        qt=None
    ref=(b+a)/2 if quote_valid else float(d.close.iloc[-1])
    out["price"]=round(ref,3)
    out["quote_at"]=qt.isoformat() if quote_valid else None
    news_ok,news_reason=_news_ok(news_events,now)
    pts=confirmed_pivots(m5,now)
    zones=[]
    for p in pts:
        side="BUY" if p["kind"]=="SWING_LOW" else "SELL"
        at=_utc(p["confirmed_at"])
        age=(now-at).total_seconds()/3600
        if not 0<=age<=MAX_ZONE_AGE_H:
            continue
        base=p["price"]
        # Only a confirmed swing BELOW bid or ABOVE ask is a pending
        # buy-the-dip / sell-on-rebound area, respectively.
        if (side=="BUY" and base>=ref) or (side=="SELL" and base<=ref):
            continue
        width=.25*atr
        lo=base if side=="BUY" else base-width
        hi=base+width if side=="BUY" else base
        # A swing may have been revisited or broken AFTER confirmation.
        newer=m5.loc[m5.index>at]
        touched=bool(((newer.low<=hi)&(newer.high>=lo)).any())
        broken=bool((newer.close<base).any()) if side=="BUY" else bool((newer.close>base).any())
        if broken:
            continue
        entry=hi if side=="BUY" else lo
        cushion=.25*atr
        stop=base-cushion if side=="BUY" else base+cushion
        risk=abs(entry-stop)
        opposites=[x["price"] for x in pts if
                   x["kind"]==("SWING_HIGH" if side=="BUY" else "SWING_LOW") and
                   (x["price"]>entry if side=="BUY" else x["price"]<entry)]
        opposite=min(opposites,key=lambda z:abs(entry-z)) if opposites else None
        room=(abs(opposite-entry)/risk) if opposite is not None else None
        dist=(lo-ref if side=="SELL" else ref-hi)
        zone={
            "side":side,"family":"CONFIRMED_M5_SWING_RETEST",
            "low":round(lo,3),"high":round(hi,3),
            "entry_reference":round(entry,3),
            "trigger_line":round(hi if side=="BUY" else lo,3),
            "sl_scenario":round(stop,3),
            "tp1_scenario":round(entry+(1.5*risk if side=="BUY" else -1.5*risk),3),
            "tp2_scenario":round(entry+(2*risk if side=="BUY" else -2*risk),3),
            "opposing_swing":round(opposite,3) if opposite is not None else None,
            "room_rr":round(room,2) if room is not None else None,
            "atr_distance":round(max(0.,dist)/atr,2),
            "fresh_first_touch":not touched,
            "formed_at":p["pivot_at"],"confirmed_at":p["confirmed_at"],
            "status":"WATCH_FRESH" if not touched else "WATCH_RETESTED",
            "macro_alignment":"WAIT" if out["macro_direction"]=="WAIT" else
                              ("ALIGNED" if out["macro_direction"]==side else "OPPOSITE"),
            "entry_eligible":False,"trigger_confirmed":False,
            "execution_authority":False,
        }
        # A confirmed M1 reclaim may be observed, but it is never
        # automatically a trade; require LIVE Fed, H1/H4 and quote.
        last=d.iloc[-1]
        recent=d.iloc[-5:]
        continuous=bool(len(recent)==5 and
            (recent.index.to_series().diff().iloc[1:]==pd.Timedelta(minutes=1)).all())
        hit=bool(((recent.low<=hi)&(recent.high>=lo)).any()) if continuous else False
        reclaim=(float(last.close)>hi and float(last.close)>float(last.open)
                 if side=="BUY" else
                 float(last.close)<lo and float(last.close)<float(last.open))
        zone["trigger_confirmed"]=bool(hit and reclaim and continuous)
        direction_ok=(out["macro_direction"]==side)
        htf_ok=out["bias_h1"]==side and out["bias_h4"]==side
        quote_ok=quote_valid and (a-b)<=.2*atr
        zone["checks"]={
            "MACRO_R4_VERIFIED":direction_ok,
            "OPERATIONAL_CONTEXT_ALIGNED":out["market_context"].get("direction")==side,
            "H1_H4_CONFIRMED":htf_ok,
            "QUOTE_SPREAD_FRESH":quote_ok,
            "NEWS_WINDOW_OK":news_ok,
            "SWING_ROOM_GE_1_5R":room is not None and room>=1.5,
            "M1_TOUCH_RECLAIM":zone["trigger_confirmed"],
            "ZONE_NOT_USED":not touched,
            "NO_CHASE":abs((a if side=="BUY" else b)-entry)<=.6*atr if quote_valid else False,
        }
        # A fresh-first-touch zone becomes used as soon as reclaim occurs;
        # maintain the observed trigger for display, but no LIVE signal
        # if historical touch already occurred on completed M5.
        zone["entry_eligible"]=bool(all(zone["checks"].values()))
        zone["state"]=("CONDITIONAL_TRIGGER_NOT_AN_ORDER" if zone["entry_eligible"]
                       else "WAIT_CHECKLIST")
        zones.append(zone)
    # Nearest zones on each side, always ordered by distance then age.
    for side in ("BUY","SELL"):
        candidates=sorted((z for z in zones if z["side"]==side),
                          key=lambda z:(not z["fresh_first_touch"],z["atr_distance"],
                                        -_utc(z["confirmed_at"]).timestamp()))
        out["zones"].extend(candidates[:2])
    out["status"]="WATCH" if out["zones"] else "WAIT"
    out["reason"]=("WATCH_ZONES_NO_AUTOMATIC_ENTRY" if out["zones"] else
                   "NO_VALID_CONFIRMED_M5_SWINGS_NEAR_PRICE")
    if not quote_valid:
        out["reason"]="QUOTE_UNAVAILABLE_ZONES_ARE_INDICATIVE"
    if not news_ok:
        out["news_reason"]=news_reason
    # Never expose eligibility as an approved order action.
    out["entry_allowed"]=False
    return out
