"""Read-only XAU rejection watch engine. Timestamps UTC; M1 indices are OPEN times.

Never submits orders, reports calibrated probabilities, or interpolates missing candles.
A candidate pattern in CLOSED bars is not an executable-fill recommendation.
"""
from __future__ import annotations
import math
import pandas as pd
from fx_scanner.rejection_lifecycle_research import advance_events
from fx_scanner.rejection_v4_research import evaluate_v4

OHLC = ('open', 'high', 'low', 'close')

def clean_m1(frame: pd.DataFrame, now) -> pd.DataFrame:
    now = pd.Timestamp(now)
    if now.tzinfo is None: raise ValueError('now must be timezone aware')
    now = now.tz_convert('UTC')
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError('M1 index must have timezone-aware OPEN timestamps')
    if len(frame) < 300 or any(k not in frame for k in OHLC):
        raise ValueError('M1 OHLC requires at least 300 bars')
    d = frame.loc[:, OHLC].copy()
    d.index = d.index.tz_convert('UTC')
    if not d.index.is_monotonic_increasing or d.index.has_duplicates:
        raise ValueError('M1 index must be ascending without duplicates')
    if (d.index.second != 0).any() or (d.index.microsecond != 0).any():
        raise ValueError('M1 open timestamps must be minute-aligned')
    if not all(pd.api.types.is_numeric_dtype(d[c]) for c in OHLC):
        raise ValueError('M1 OHLC must be numeric')
    if not d.notna().all().all() or not all(math.isfinite(float(v)) for v in d.to_numpy().ravel()):
        raise ValueError('M1 OHLC contains NaN or infinity')
    if ((d.high < d.low) | (d.high < d[['open', 'close']].max(axis=1)) |
            (d.low > d[['open', 'close']].min(axis=1)) | (d.low <= 0)).any():
        raise ValueError('Invalid M1 OHLC geometry')
    if (d.index[-1] + pd.Timedelta(minutes=1)) > now:
        raise ValueError('Forming M1 candle present: reject rather than peek')
    if (now - d.index[-1] - pd.Timedelta(minutes=1)).total_seconds() > 90:
        raise ValueError('M1 source stale')
    return d

def completed(d: pd.DataFrame, minutes: int, now) -> pd.DataFrame:
    """Require all M1 minutes per HTF bar and a completed end timestamp."""
    now = pd.Timestamp(now).tz_convert('UTC')
    g = d.resample(f'{minutes}min', label='right', closed='left')
    agg = g.agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    count = g['close'].count()
    return agg.loc[(count == minutes) & (agg.index <= now)].copy()

def _trend(d: pd.DataFrame, short=20, long=50):
    if len(d) < long + 5: return 'UNAVAILABLE'
    a = d.close.ewm(span=short, adjust=False).mean()
    b = d.close.ewm(span=long, adjust=False).mean()
    if d.close.iloc[-1] > a.iloc[-1] > b.iloc[-1] and a.iloc[-1] > a.iloc[-4]:
        return 'BUY'
    if d.close.iloc[-1] < a.iloc[-1] < b.iloc[-1] and a.iloc[-1] < a.iloc[-4]:
        return 'SELL'
    return 'NEUTRAL'

def calculate(m1: pd.DataFrame, *, now, bid=None, ask=None, quote_at=None, prior_events=None) -> dict:
    """Evaluate completed M1, M5, H1 and H4 with an anti-chase quote gate.

    M1 uses open timestamps; HTF resamples use right-aligned close timestamps.
    Both buy and sell zones appear regardless of trend; only aligned entries
    can become EARLY ENTRY CANDIDATE. No real-money authority.
    """
    now = pd.Timestamp(now).tz_convert('UTC')
    d = clean_m1(m1, now)
    m5, h1, h4 = (completed(d, m, now) for m in (5, 60, 240))
    if len(m5) < 55 or m5.index[-1] < now - pd.Timedelta(minutes=6):
        raise ValueError('M5 history incomplete or stale')
    if len(h1) and h1.index[-1] < now - pd.Timedelta(minutes=61): h1 = h1.iloc[:0]
    if len(h4) and h4.index[-1] < now - pd.Timedelta(minutes=241): h4 = h4.iloc[:0]
    h1_bias, h4_bias = _trend(h1), _trend(h4, short=10, long=20)
    bias = h1_bias if h1_bias in ('BUY', 'SELL') and h1_bias == h4_bias else 'WAIT'
    prev = m5.close.shift(1)
    tr = pd.concat([m5.high-m5.low, (m5.high-prev).abs(), (m5.low-prev).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    if not math.isfinite(atr) or atr <= 0: raise ValueError('ATR unavailable')
    closed_at = d.index[-1] + pd.Timedelta(minutes=1)
    if bid is None or ask is None or quote_at is None:
        quote_ok = False
    else:
        quote_at = pd.Timestamp(quote_at)
        if quote_at.tzinfo is None: raise ValueError('Quote timestamp must have timezone')
        qt = quote_at.tz_convert('UTC')
        quote_ok = (all(math.isfinite(float(v)) for v in (bid,ask)) and
                    0 < bid <= ask and -5 <= (now-qt).total_seconds() <= 30)
    spread = float(ask-bid) if quote_ok else None
    price = float((bid+ask)/2) if quote_ok else float(d.close.iloc[-1])
    # Pre-touch levels only: exclude any M5/H1 bar that includes the latest M1 event.
    prev5 = m5.loc[m5.index <= d.index[-1]]
    prevh = h1.loc[h1.index <= d.index[-1]]
    e20 = float(prev5.close.ewm(span=20,adjust=False).mean().iloc[-1])
    e50 = float(prev5.close.ewm(span=50,adjust=False).mean().iloc[-1])
    levels = [
        ('BUY','M5 SUPPORT',float(prev5.low.iloc[-20:].min())),
        ('SELL','M5 RESISTANCE',float(prev5.high.iloc[-20:].max())),
        ('BUY','M5 EMA20',e20),('SELL','M5 EMA20',e20),
        ('BUY','M5 EMA50',e50),('SELL','M5 EMA50',e50),
    ]
    if len(prevh)>=20:
        eh=float(prevh.close.ewm(span=20,adjust=False).mean().iloc[-1])
        levels += [('BUY','H1 EMA20',eh),('SELL','H1 EMA20',eh),
                   ('BUY','H1 SUPPORT',float(prevh.low.iloc[-12:].min())),
                   ('SELL','H1 RESISTANCE',float(prevh.high.iloc[-12:].max()))]
    width=max(.12*atr,2*spread if spread is not None else 0)
    last=d.iloc[-1]
    span=max(float(last.high-last.low),1e-9)
    wick_buy=float(min(last.open,last.close)-last.low)/span
    wick_sell=float(last.high-max(last.open,last.close))/span
    zones=[]
    recent=d.iloc[-6:-1]
    for side,name,level in levels:
        distance=abs(price-level)
        touched=float(last.low)<=level+width and float(last.high)>=level-width
        reclaim=(last.close>level and last.close>=last.open and wick_buy>=.30 if side=='BUY'
                 else last.close<level and last.close<=last.open and wick_sell>=.30)
        candidate=bool(touched and reclaim)
        past_rejects=[]
        for ts,bar in recent.iterrows():
            age=(closed_at-(ts+pd.Timedelta(minutes=1))).total_seconds()
            span_bar=max(float(bar.high-bar.low),1e-9)
            wick=(float(min(bar.open,bar.close)-bar.low)/span_bar if side=='BUY' else
                  float(bar.high-max(bar.open,bar.close))/span_bar)
            had_touch=float(bar.low)<=level+width and float(bar.high)>=level-width
            had_reclaim=(bar.close>level and bar.close>=bar.open if side=='BUY' else
                         bar.close<level and bar.close<=bar.open)
            if 0<=age<=300 and had_touch and had_reclaim and wick>=.30:
                past_rejects.append(ts)
        retest_event=past_rejects[-1] if past_rejects else None
        entry_price=float(ask if side=='BUY' else bid) if quote_ok else price
        chase=(entry_price-level)/atr if side=='BUY' else (level-entry_price)/atr
        if candidate:
            stage='EARLY REJECTION'
            entry=('EARLY ENTRY CANDIDATE' if quote_ok and bias==side and
                   (spread or 0)<=.20*atr and 0<=chase<=.60
                   else 'WAIT / CHECK BIAS, QUOTE, DISTANCE')
        elif retest_event is not None and touched:
            stage='RETEST AT WATCH ZONE'
            direction_ok=(last.close>last.open and last.close>level if side=='BUY' else
                          last.close<last.open and last.close<level)
            entry=('RETEST RECLAIM CANDIDATE' if quote_ok and bias==side and direction_ok and
                   (spread or 0)<=.20*atr and 0<=chase<=.60 else 'WAIT RETEST RECLAIM')
        elif retest_event is not None:
            stage='WAIT RETEST' if distance<=atr else 'MISSED / AVOID CHASE'
            entry='WAIT RETEST' if distance<=atr else 'NO ENTRY'
        elif touched:
            stage,entry='TOUCHED; WAIT REACTION','WAIT M1 RECLAIM'
        elif distance<=.35*atr:
            stage,entry='APPROACHING','WATCH'
        else:
            stage,entry='MONITOR','NO ENTRY'
        invalid=min(float(last.low),level-width) if side=='BUY' else max(float(last.high),level+width)
        zones.append(dict(side=side,name=name,price=round(level,3),
                          low=round(level-width,3),high=round(level+width,3),
                          distance_atr=round(distance/atr,3),stage=stage,entry=entry,
                          invalidation=round(invalid,3),
                          countertrend=bias not in (side,'WAIT')))
    selected=[]
    for side in ('BUY','SELL'):
        pool=sorted([x for x in zones if x['side']==side],key=lambda x:x['distance_atr'])
        structural=next((z for z in pool if 'SUPPORT' in z['name'] or 'RESISTANCE' in z['name']),None)
        ema=next((z for z in pool if 'EMA' in z['name']),None)
        chosen=[z for z in (structural,ema) if z is not None]
        chosen += [z for z in pool if z not in chosen][:max(0,3-len(chosen))]
        selected += chosen[:3]
    zones=selected
    event_history=advance_events(
        prior_events, d, m5, zones, now=now, atr=atr,
        bid=bid, ask=ask, quote_valid=quote_ok,
    )
    # A failed SELL/BUY rejection is an event-level veto, not just an EMA
    # label veto. Dynamic zones must not rebrand the same failed thesis.
    for z in zones:
        same=[e for e in event_history if e["side"]==z["side"]]
        if not same:
            continue
        last_event=same[-1]
        state=last_event["display_state"]
        if state not in {"REJECTION_INVALIDATED", "BREAKOUT_CONFIRMED",
                         "BREAKOUT_RISK", "DATA_GAP"}:
            continue
        failed_at=last_event.get("breakout_at") or last_event.get("invalidated_at") or last_event.get("checked_through")
        if (now-pd.Timestamp(failed_at)).total_seconds()<=15*60:
            z["stage"]=state
            z["entry"]="NO ENTRY — PRIOR REJECTION FAILED / BREAKOUT RISK"
    v4=evaluate_v4(d,prev5,h1_bias=h1_bias,h4_bias=h4_bias,
                   atr_m5=atr,now=now,quote_valid=quote_ok,bid=bid,ask=ask)
    for candidate in v4:
        same=[e for e in event_history if e["side"]==candidate["side"]]
        for prior in reversed(same):
            if prior["display_state"] not in {
                "REJECTION_INVALIDATED","BREAKOUT_CONFIRMED","BREAKOUT_RISK","DATA_GAP"}:
                continue
            failed_at=prior.get("breakout_at") or prior.get("invalidated_at") or prior.get("checked_through")
            if (now-pd.Timestamp(failed_at)).total_seconds()<=15*60:
                candidate["entry_status"]="BLOCKED_PREVIOUS_FAILED_REJECTION"
                candidate["reasons"].append("V3 same-side breakout/invalidated event cooldown")
            break
    return {'status':'RESEARCH_ONLY','bias':bias,'h1_bias':h1_bias,'h4_bias':h4_bias,
            'as_of':now.isoformat(),'last_closed_m1':closed_at.isoformat(),
            'last_closed_m5':m5.index[-1].isoformat(),'quote_valid':quote_ok,
            'price':round(price,3),'atr_m5':round(atr,3),'zones':zones,
            'rejection_events':event_history,'v4_setups':v4,
            'warning':'No tested accuracy/edge. Candidate only; manual decisions and independent risk controls.'}
