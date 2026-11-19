"""Research-only watch zones, directional bias and early-entry timing.
Inputs are completed OHLC bars; no order execution or live claims.
"""
from dataclasses import dataclass
import math
import pandas as pd

@dataclass(frozen=True)
class WatchResult:
    bias: str
    bias_basis: str
    nearest_zone: str
    zone_price: float
    distance: float
    stage: str
    entry_style: str
    invalidation: float | None
    notes: str

def _clean(frame, minimum):
    needed={"timestamp","open","high","low","close"}
    if not needed.issubset(frame.columns) or len(frame)<minimum:
        raise ValueError("Need timestamp/open/high/low/close and at least %d closed bars" % minimum)
    d=frame.copy()
    d["timestamp"]=pd.to_datetime(d.timestamp,utc=True,errors="raise")
    if d.timestamp.isna().any() or d.timestamp.duplicated().any() or not d.timestamp.is_monotonic_increasing:
        raise ValueError("UTC timestamps must be unique and ascending")
    for col in ("open","high","low","close"):
        d[col]=pd.to_numeric(d[col],errors="raise")
        if not all(math.isfinite(float(v)) for v in d[col]):
            raise ValueError("Non-finite OHLC")
    if ((d.high<d.low)|(d.high<d[["open","close"]].max(axis=1))|(d.low>d[["open","close"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC")
    return d

def watch_zones(m5, h1=None, h4=None, atr_multiplier=0.35):
    """No lookahead: callers must supply only completed bars with aligned as-of timestamps.
    Bias is neutral unless both H1 and H4 agree on EMA20/50 + last-close direction.
    M5 watch uses EMA20/50 and previous 20-bar support/resistance (excluding current bar).
    """
    d=_clean(m5,55)
    now=d.timestamp.iloc[-1]
    def higher(frame):
        if frame is None: return None
        f=_clean(frame,55)
        if f.timestamp.iloc[-1]>now: raise ValueError("Higher timeframe candle timestamp exceeds M5 as-of")
        e20=f.close.ewm(span=20,adjust=False).mean().iloc[-1]
        e50=f.close.ewm(span=50,adjust=False).mean().iloc[-1]
        return "BUY" if f.close.iloc[-1]>e20>e50 else "SELL" if f.close.iloc[-1]<e20<e50 else "NEUTRAL"
    h1_dir,h4_dir=higher(h1),higher(h4)
    bias=h1_dir if h1_dir==h4_dir and h1_dir in ("BUY","SELL") else "NEUTRAL"
    basis="H1=%s | H4=%s (closed candles)" % (h1_dir or "N/A",h4_dir or "N/A")
    prev=d.iloc[:-1]
    close=float(d.close.iloc[-1])
    tr=pd.concat([d.high-d.low,(d.high-d.close.shift()).abs(),(d.low-d.close.shift()).abs()],axis=1).max(axis=1)
    atr=float(tr.rolling(14).mean().iloc[-1])
    if atr<=0: raise ValueError("ATR must be positive")
    candidates=[
      ("EMA20",float(prev.close.ewm(span=20,adjust=False).mean().iloc[-1])),
      ("EMA50",float(prev.close.ewm(span=50,adjust=False).mean().iloc[-1])),
      ("SUPPORT",float(prev.low.iloc[-20:].min())),
      ("RESISTANCE",float(prev.high.iloc[-20:].max())),
    ]
    if bias=="BUY": candidates=[c for c in candidates if c[0]!="RESISTANCE"]
    if bias=="SELL": candidates=[c for c in candidates if c[0]!="SUPPORT"]
    name,price=min(candidates,key=lambda c:abs(c[1]-close))
    distance=abs(close-price)
    last=d.iloc[-1]
    span=max(float(last.high-last.low),1e-9)
    lower=float(min(last.open,last.close)-last.low)/span
    upper=float(last.high-max(last.open,last.close))/span
    touch=float(last.low)<=price<=float(last.high)
    # Direction can be inferred from zone type in neutral HTF only as a *watch*, not confirmed bias.
    side="BUY" if name=="SUPPORT" or (name.startswith("EMA") and close>=price) else "SELL"
    if bias in ("BUY","SELL"): side=bias
    rejection=(lower>=0.35 and last.close>price and side=="BUY") or (upper>=0.35 and last.close<price and side=="SELL")
    # Early confirmation: current closed M5 bar rejects zone and closes in intended direction.
    momentum=(last.close>last.open if side=="BUY" else last.close<last.open)
    invalid=float(last.low if side=="BUY" else last.high)
    if touch and rejection and momentum:
        stage="EARLY REJECTION"
        entry="EARLY ENTRY CANDIDATE — manual check, no mandatory retest"
    elif touch:
        stage="ZONE TOUCHED — WAIT REACTION"
        entry="WAIT M1/M5 CLOSED-CANDLE REACTION"
    elif distance<=atr_multiplier*atr:
        stage="APPROACHING WATCH ZONE"
        entry="PREPARE; NO ENTRY YET"
    else:
        stage="MONITORING"
        entry="NO ENTRY"
    if bias!="NEUTRAL" and side!=bias:
        entry="COUNTERTREND — NO AUTOMATIC ENTRY"
    return WatchResult(bias,basis,name,price,distance,stage,entry,invalid if touch else None,
                       "Zone candidate only; no calibrated win rate. ATR14=%.3f; signal side=%s."%(atr,side))
