"""Display-only directional context, not inference from R28.1 locked benchmarks."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
import math
import pandas as pd
from .manual_reversal_map import frame

TFS={"H1":60,"H4":240,"D1":1440,"W1":10080}
MAX_AGE={"H1":4200,"H4":15000,"D1":3*86400,"W1":8*86400}
CONTRACT="RIZAN_XAU_DIRECTION_CONTEXT_V1"
MIN_BARS=20

def session_closed(now):
    t=now.astimezone(ZoneInfo("America/New_York"))
    return t.weekday()==5 or (t.weekday()==4 and t.hour>=17) or (t.weekday()==6 and t.hour<18)

def build_context_packet(native, *, now):
    bars={}
    for tf,minutes in TFS.items():
        try:
            f=frame(native.get(tf,[]),tf,now).tail(80)
            bars[tf]=[{"timestamp":r.timestamp.isoformat(),"open":float(r.open),"high":float(r.high),"low":float(r.low),"close":float(r.close)} for r in f.itertuples()]
        except (ValueError,TypeError,KeyError,OverflowError):
            bars[tf]=[]
    return {"contract":CONTRACT,"symbol":"XAUUSD","source":"CTRADER_MARKET_DATA_READ_ONLY","as_of":now.isoformat(),"execution_authority":False,"execution_influence":False,"bars":bars}

def read_context_packet(packet, now):
    if not isinstance(packet,dict) or packet.get("contract")!=CONTRACT or packet.get("symbol")!="XAUUSD" or packet.get("source")!="CTRADER_MARKET_DATA_READ_ONLY" or packet.get("execution_authority") is not False or packet.get("execution_influence") is not False:
        raise ValueError("DIRECTION_CONTEXT_CONTRACT")
    at=pd.Timestamp(packet["as_of"])
    if at.tzinfo is None or not 0<=(pd.Timestamp(now)-at).total_seconds():raise ValueError("DIRECTION_CONTEXT_TIME")
    result={}
    for tf,minutes in TFS.items():
        rows=packet.get("bars",{}).get(tf,[])
        if not isinstance(rows,list) or len(rows)>80:continue
        try:
            f=frame(rows,tf,at)
            if f.empty:continue
            if len(f)!=len(rows):continue
            f=f.set_index("timestamp")
            f.index+=pd.Timedelta(minutes=minutes)
            result[tf]=f
        except (ValueError,TypeError,KeyError,OverflowError):continue
    return result,at

def context(bars,tf,*,now,observed_at,market_fresh):
    """Five transparent directional votes; no calibrated probabilities."""
    base={"tf":tf,"bias":"WAIT DATA","forecast":"WAIT","last_bias":None,"buy":None,"sell":None,"closed_at":None,"checks":[],"reason":"Riwayat minimal 20 candle tertutup belum tersedia.","fresh":False,"execution_authority":False}
    if bars is None or len(bars)<MIN_BARS:return base
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:return base
    now=pd.Timestamp(now);at=pd.Timestamp(observed_at)
    if now.tzinfo is None or at.tzinfo is None:return base
    f=bars.loc[bars.index<=at].tail(80)
    if len(f)<MIN_BARS or f.index[-1]>now:return base
    if not f[["open","high","low","close"]].map(lambda v: math.isfinite(float(v))).all().all():return base
    c,o,h,l=[f[k] for k in ("close","open","high","low")]
    if not ((l>0)&(l<=o)&(l<=c)&(h>=o)&(h>=c)).all():return base
    atr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1).rolling(14).mean().iloc[-1]
    if not math.isfinite(atr) or atr<=0:return base
    def sign(x,band=0):return 1 if x>band else -1 if x<-band else 0
    e5=c.ewm(span=5,adjust=False).mean();e13=c.ewm(span=13,adjust=False).mean()
    a=float(atr)
    struct=1 if h.iloc[-5:].max()>h.iloc[-10:-5].max() and l.iloc[-5:].min()>l.iloc[-10:-5].min() else -1 if h.iloc[-5:].max()<h.iloc[-10:-5].max() and l.iloc[-5:].min()<l.iloc[-10:-5].min() else 0
    # No forming bar or forward target enters the scoring.
    votes={"EMA5 vs EMA13":sign(e5.iloc[-1]-e13.iloc[-1],.10*a),
           "Slope EMA13 (3 candle)":sign(e13.iloc[-1]-e13.iloc[-4],.05*a),
           "Momentum 3 candle":sign(c.iloc[-1]-c.iloc[-4],.15*a),
           "Struktur HH/HL vs LH/LL":struct,
           "Close vs equilibrium 20":sign(c.iloc[-1]-(h.tail(20).max()+l.tail(20).min())/2,.10*a)}
    buy=sum(v==1 for v in votes.values());sell=sum(v==-1 for v in votes.values())
    last="BUY" if buy>=4 and sell<=1 else "SELL" if sell>=4 and buy<=1 else "NETRAL"
    age=(now-f.index[-1]).total_seconds();pub=(now-at).total_seconds()
    # A decision for the NEXT completed candle must expire at that candle\u0027s close.
    # Without this guard, a missing H1 update could keep an old SELL/BUY active
    # for up to 70 minutes after the predicted candle already closed.
    target_close=f.index[-1]+pd.Timedelta(minutes=TFS[tf])
    fresh=bool(market_fresh and not session_closed(now.to_pydatetime()) and 0<=age<=MAX_AGE[tf] and 0<=pub<=600 and now<target_close)
    reason=("Konteks searah; hipotesis close berikutnya, bukan output model frozen." if last!="NETRAL" else "Bukti struktur/momentum belum selaras.")
    if not fresh:reason="Pasar tutup, candle target telah berakhir, atau data kedaluwarsa; arah terakhir hanya referensi historis."
    return {**base,"bias":last if fresh else "WAIT DATA","forecast":last if fresh and last!="NETRAL" else "WAIT","last_bias":last,"buy":buy,"sell":sell,"closed_at":f.index[-1].isoformat(),"fresh":fresh,"reason":reason,"checks":[{"Faktor":k,"Arah":"BUY" if v==1 else "SELL" if v==-1 else "NETRAL"} for k,v in votes.items()],"last_close":float(c.iloc[-1]),"atr":a}


def next_candle_prediction(report, tf, *, now):
    """Read-only UI contract: only a current, unexpired technical hypothesis.

    Benchmark accuracy locks are not live prediction models. The target is
    the next completed candle CLOSE compared with the latest closed CLOSE.
    """
    base={"headline":"WAIT DATA","target_at":None,"kind":"UNAVAILABLE"}
    if tf not in TFS or not report.get("fresh"):
        return base
    if report.get("forecast") not in ("BUY","SELL"):
        return {**base,"headline":"WAIT · NETRAL","kind":"TECHNICAL_RESEARCH"}
    try:
        closed=pd.Timestamp(report["closed_at"]);current=pd.Timestamp(now)
        if closed.tzinfo is None or current.tzinfo is None:
            return base
        target=closed+pd.Timedelta(minutes=TFS[tf])
        if not closed<=current<target:
            return base
    except (TypeError,ValueError,KeyError,OverflowError):
        return base
    return {"headline":report["forecast"],"target_at":target.isoformat(),"kind":"TECHNICAL_RESEARCH"}

def horizon_side(reports, tf):
    """Independent directional hypothesis for selected horizon only."""
    report=reports.get(tf,{})
    side=report.get("forecast")
    return side if report.get("fresh") and side in ("BUY","SELL") else "WAIT"

def horizon_plan(reports, tf):
    """Adjacent lower timeframe contextualizes, never vetoes the anchor."""
    lower={"W1":"D1","D1":"H4","H4":"H1","H1":None}[tf]
    anchor=horizon_side(reports,tf)
    timing=horizon_side(reports,lower) if lower else None
    result={"anchor":tf,"side":anchor,"timing_tf":lower,"timing_side":timing,
            "setup":"WAIT","phase":"WAIT_DATA_OR_NEUTRAL","execution_authority":False}
    if anchor=="WAIT":return result
    result["setup"]="BUY THE DIP" if anchor=="BUY" else "SELL ON REBOUND"
    if lower is None:
        result["phase"]="WAIT_LOCAL_CONFIRMATION"
    elif timing=="WAIT":
        result["phase"]="TIMING_UNAVAILABLE_OR_NEUTRAL"
    elif timing!=anchor:
        result["phase"]="POTENTIAL_PULLBACK" if anchor=="BUY" else "POTENTIAL_REBOUND"
    else:
        result["phase"]="ALIGNED_CONTINUATION"
    return result


def watch_zone(bars, report):
    """Independent per-timeframe range geometry, not a validated rebound model.
    Historical zones are display-only and cannot be promoted to active zones.
    All values use the exact closed candle used by the directional context.
    """
    if bars is None or not report.get("closed_at"):
        return None
    side=report.get("last_bias")
    if side not in ("BUY","SELL"):
        return None
    try:
        at=pd.Timestamp(report["closed_at"])
        f=bars.loc[bars.index<=at].tail(20)
        if len(f)!=20 or f.index[-1]!=at or f.index.has_duplicates or not f.index.is_monotonic_increasing:
            return None
        if not f[["open","high","low","close"]].map(lambda v:math.isfinite(float(v))).all().all():
            return None
        if not ((f.low>0)&(f.low<=f.open)&(f.low<=f.close)&(f.high>=f.open)&(f.high>=f.close)).all():
            return None
        lo=float(f.low.min());hi=float(f.high.max());price=float(f.close.iloc[-1])
        if not hi>lo:return None
        width=hi-lo
        zl,zh=(lo,lo+width*.25) if side=="BUY" else (hi-width*.25,hi)
        active=bool(report.get("fresh") and report.get("forecast")==side)
        return {"side":side,"tf":report.get("tf"),"label":"Buy the dip" if side=="BUY" else "Sell on rebound",
                "low":zl,"high":zh,"invalidation":lo if side=="BUY" else hi,
                "reference_close":price,"closed_at":at.isoformat(),
                "distance":max(zl-price,price-zh,0.),
                "position":"DI ZONA" if zl<=price<=zh else "DI ATAS ZONA" if price>zh else "DI BAWAH ZONA",
                "active":active,"state":"PANTAU" if active else "HISTORIS",
                "probability":None,"execution_authority":False}
    except (ValueError,TypeError,KeyError,OverflowError):
        return None
