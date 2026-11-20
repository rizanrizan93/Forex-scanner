"""Research-only FOMC directional continuation OBSERVATION after event.

Unlike V4 liquidity-sweep reversals, this is a **separate experimental
setup** to study whether trend continuation on completed M1 structural
breaks helps when post-FOMC V4 cannot offer a rejection entry.

NO signal eligibility, NO LIVE, NO buy/sell order authority.
Macro direction is supplied by an independent true PIT watch (future)
or by explicit EX-POST oracle research (historic only). It is never
inferred from the price outcome label. Only completed M1 and M5.
"""
from __future__ import annotations
import math
import pandas as pd

NAME="FOMC_M1_CONTINUATION_BREAK_RESEARCH_OBSERVATION_ONLY"

def evaluate_continuation(m1,m5,*,at,side,bid=None,ask=None,
                          atr_m5=None):
    if side not in ("BUY","SELL"):
        raise ValueError("BAD_MACRO_DIRECTION")
    now=pd.Timestamp(at)
    if now.tzinfo is None:raise ValueError("UTC_TIME_REQUIRED")
    now=now.tz_convert("UTC")
    if not isinstance(m1.index,pd.DatetimeIndex) or m1.index.tz is None:
        raise ValueError("UTC_M1_REQUIRED")
    if not isinstance(m5.index,pd.DatetimeIndex) or m5.index.tz is None:
        raise ValueError("UTC_M5_REQUIRED")
    if len(m1)<80 or len(m5)<20:
        raise ValueError("INSUFFICIENT_COMPLETED_HISTORY")
    if m1.index[-1]+pd.Timedelta(minutes=1)>now or m5.index[-1]>now:
        raise ValueError("FORMING_CANDLE_LOOKAHEAD")
    if not (m1.index.to_series().diff().iloc[-16:] == pd.Timedelta(minutes=1)).all():
        raise ValueError("M1_DATA_GAP")
    if atr_m5 is None or not math.isfinite(float(atr_m5)) or atr_m5<=0:
        raise ValueError("ATR_M5_NOT_VALID")
    atr=float(atr_m5)
    latest=m1.iloc[-1]
    earlier=m1.iloc[-4:-1]
    sign=1 if side=="BUY" else -1
    ema=m1.close.astype(float).ewm(span=9,adjust=False).mean()
    ema_now=float(ema.iloc[-1]);ema_past=float(ema.iloc[-4])
    spread=None if bid is None or ask is None else float(ask)-float(bid)
    quote_ok=bool(spread is not None and
                  all(math.isfinite(float(x)) for x in (bid,ask)) and
                  0<float(bid)<=float(ask) and spread<=.20*atr)
    px=float(ask if side=="BUY" else bid) if quote_ok else float(latest.close)
    span=float(latest.high-latest.low)
    body=abs(float(latest.close-latest.open))/max(1e-9,span)
    trend_ema=sign*(ema_now-ema_past)>0
    breakout=(float(latest.close)>float(earlier.high.max())
              if side=="BUY" else
              float(latest.close)<float(earlier.low.min()))
    momentum=sign*(float(latest.close-latest.open))>0 and body>=.40
    # A 3-bar pause/pullback is a diagnostic, not a hard gate.
    prior_pause=any(sign*(float(r.close-r.open))<=0 for _,r in earlier.iterrows())
    chase=sign*(px-ema_now)/atr
    chase_ok=0<=chase<=.60
    reasonable_span=.04*atr<=span<=1.25*atr
    detected=bool(trend_ema and breakout and momentum and
                  reasonable_span and quote_ok and chase_ok)
    reasons=[]
    if not trend_ema:reasons.append("M1_EMA9_NOT_ALIGNED")
    if not breakout:reasons.append("NO_CLOSED_M1_THREE_BAR_BREAK")
    if not momentum:reasons.append("NO_DIRECTIONAL_BODY")
    if not reasonable_span:reasons.append("EVENT_BAR_TOO_SMALL_OR_SPIKE")
    if not quote_ok:reasons.append("MISSING_OR_WIDE_REAL_BID_ASK")
    if not chase_ok:reasons.append("FAR_FROM_EMA9_OR_WRONG_SIDE")
    return {
        "contract":"RIZAN_R5_FOMC_CONTINUATION_OBSERVATION_ONLY",
        "setup_type":NAME,
        "side":side,"at_utc":now.isoformat(),
        "stage":"STRUCTURE_BREAK_OBSERVED" if detected else "WAIT_STRUCTURE",
        "event_detected":detected,
        "prior_three_bar_pause":prior_pause,
        "m1_closed_structure_break":breakout,
        "m1_ema9_trend_confirmed":trend_ema,
        "m1_body_fraction":round(body,4),
        "distance_ema9_atr":round(chase,4),
        "spread_assumed_usd_oz":spread,
        "reasons":reasons,
        "authorizes_entry":False,
        "authorizes_orders":False,
        "measured_80pct_win_rate":False,
    }
