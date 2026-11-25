"""Manual Precision R13: read-only structural watch, not a validated strategy."""
from __future__ import annotations
import math
import pandas as pd

def watch(row, model, market, *, now):
    """Use only unexpired matching-TF bias, validated zones and closed broker M1.
    Output is descriptive research telemetry; never authorize order execution.
    """
    result={"state":"WAIT_DATA","reason":"Market feed unavailable",
            "steps":[False]*4,"level":None,"sweep_at":None,"mss_at":None,
            "retest_at":None,"entry_reference":None,"probability":None,
            "execution_authority":False}
    def stop(state, reason):
        return {**result,"state":state,"reason":reason}
    try:
        now=pd.Timestamp(now).tz_convert("UTC")
        if (row.get("tf") not in ("H1","H4") or model.get("tf")!=row.get("tf")
            or model.get("status")!="ACTIVE_SHADOW" or model.get("execution_authority") is not False
            or row.get("execution_authority") is not False
            or row.get("direction") not in ("BUY","SELL")
            or model.get("direction")!=row.get("direction")):
            return stop("WAIT_DIRECTION","Bias matching timeframe not active")
        issued=pd.Timestamp(model["issued"]).tz_convert("UTC")
        target=pd.Timestamp(model["target"]).tz_convert("UTC")
        if not issued<=now<target:
            return stop("WAIT_DIRECTION","Forecast expired or not yet issued")
        if row.get("state")!="WATCH_ZONE" or not row.get("zones"):
            return stop("WAIT_ZONE","No validated zone")
        if not isinstance(market,dict):return result
        at=pd.Timestamp(market["as_of"]).tz_convert("UTC")
        qt=pd.Timestamp(market["quote_as_of"]).tz_convert("UTC")
        bid,ask=float(market["bid"]),float(market["ask"])
        if not (0<=(now-at).total_seconds()<=90 and
                0<=(now-qt).total_seconds()<=30 and math.isfinite(bid+ask) and 0<bid<=ask):
            return stop("WAIT_DATA","Publication or quote stale")
        f=market["frame"]
        if not isinstance(f,pd.DataFrame) or f.empty or f.index.tz is None or f.index.has_duplicates or not f.index.is_monotonic_increasing:
            return stop("WAIT_DATA","Invalid M1 history")
        f=f.loc[f.index+pd.Timedelta(minutes=1)<=min(now,at),["open","high","low","close"]]
        if len(f)<60 or not 0<=(now-f.index[-1]-pd.Timedelta(minutes=1)).total_seconds()<=120:
            return stop("WAIT_DATA","Closed M1 history stale/incomplete")
        # Do not bridge a market/data gap in the confirmation sequence.
        recent=f.tail(360)
        breaks=recent.index.to_series().diff().ne(pd.Timedelta(minutes=1))
        recent=recent.iloc[max(i for i,v in enumerate(breaks) if v):]
        if len(recent)<60:return stop("WAIT_DATA","Contiguous M1 history insufficient")
        side=1 if row["direction"]=="BUY" else -1
        price=ask if side==1 else bid
        z=row["zones"][0]
        if z.get("tf")!=row["tf"] or z.get("direction")!=row["direction"] or z.get("execution_authority") is not False:
            return stop("WAIT_ZONE","Zone provenance mismatch")
        lo,hi,inv=map(float,(z["low"],z["high"],z["invalidation"]))
        if not all(map(math.isfinite,(lo,hi,inv))) or not 0<lo<hi or not (inv<lo if side==1 else inv>hi):
            return stop("WAIT_ZONE","Invalid zone geometry")
        start=max(issued,pd.Timestamp(z["formed_at"]).tz_convert("UTC"))
        if recent.index[0]>start:
            return stop("WAIT_DATA","Confirmation history since issue incomplete")
        q=recent.loc[recent.index>=start]
        distance=max(lo-price,price-hi,0.)
        result.update(distance=distance,zone_low=lo,zone_high=hi,invalidation=inv,
                      quote_reference=price,valid_until=target.isoformat())
        if (bid<=inv if side==1 else ask>=inv) or (len(q) and ((q.low<=inv).any() if side==1 else (q.high>=inv).any())):
            return stop("INVALIDATED","Structural invalidation touched after issue")
        touches=q[(q.low<=hi)&(q.high>=lo)]
        if touches.empty:
            return stop("APPROACH" if distance<=5 else "WATCH_ZONE","Waiting for zone touch; $5 proximity only, not ETA")
        result["steps"][0]=True
        touch=touches.index[0]
        # A sweep must reclaim a prior five-minute extreme with a closed M1.
        ph=recent.high.shift().rolling(5).max()
        pl=recent.low.shift().rolling(5).min()
        sweep=((recent.low<pl)&(recent.close>pl)) if side==1 else ((recent.high>ph)&(recent.close<ph))
        sweeps=recent.index[sweep & (recent.index>=touch) & (recent.low<=hi) & (recent.high>=lo)]
        if len(sweeps)==0:return stop("WAIT_SWEEP","Zone touched; waiting for closed liquidity reclaim")
        sw=sweeps[-1];result["steps"][1]=True;result["sweep_at"]=(sw+pd.Timedelta(minutes=1)).isoformat()
        # Closed M5 only, require break of prior three M5 bars and body displacement.
        m=recent.resample("5min",label="left",closed="left").agg(open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),n=("close","size"))
        m=m[(m.n==5)&(m.index+pd.Timedelta(minutes=5)<=min(now,at))]
        level=m.high.shift().rolling(3).max() if side==1 else m.low.shift().rolling(3).min()
        body=(m.close-m.open)*side
        ref=(m.close-m.open).abs().shift().rolling(6).median()
        ok=(body>0)&(body>=1.25*ref)&((m.close>level) if side==1 else (m.close<level))
        candidates=m.index[ok & (m.index>=sw+pd.Timedelta(minutes=1))]
        if len(candidates)==0:return stop("WAIT_MSS","Sweep observed; waiting for closed M5 displacement/BOS")
        ms=candidates[0];closed=ms+pd.Timedelta(minutes=5);lv=float(level.loc[ms])
        result["steps"][2]=True;result["mss_at"]=closed.isoformat();result["level"]=lv
        post=recent.loc[recent.index>=closed]
        retest=post[(post.low<=lv)&(post.high>=lv)&((post.close>lv)&(post.close>post.open) if side==1 else (post.close<lv)&(post.close<post.open))]
        if retest.empty:return stop("WAIT_RETEST","M5 structure break observed; waiting for closed M1 retest")
        rt=retest.index[-1]+pd.Timedelta(minutes=1);result["steps"][3]=True;result["retest_at"]=rt.isoformat()
        if (now-rt).total_seconds()>300:return stop("RETEST_EXPIRED","Retest older than five minutes")
        if (price-lv)*side<0 or abs(price-lv)>2:return stop("PRICE_MOVED","Quote outside research retest tolerance")
        return stop("SHADOW_PATTERN","Sequence observed; profitability not validated; not an entry recommendation")
    except (KeyError,TypeError,ValueError,OverflowError,AttributeError,IndexError):
        return stop("WAIT_DATA","Incomplete or invalid research input")

def render_precision(st,row,model,market,*,now):
    out=watch(row,model,market,now=now)
    with st.container(border=True):
        st.markdown("**Manual Precision R13 · SHADOW**")
        st.caption("Research only · not a trade signal · historical profitability not validated.")
        st.write(out["state"]+" · "+out["reason"])
        for passed,label in zip(out["steps"],("Zone touch","M1 liquidity sweep/reclaim","M5 displacement/BOS","M1 retest")):
            st.write(("✓ " if passed else "○ ")+label)
        if out.get("distance") is not None:
            st.caption(f"Jarak zona: ${out['distance']:.2f} · proximity alert: $5, bukan estimasi waktu")
        if out.get("level") is not None:
            st.caption(f"Level struktur M5: {out['level']:.2f} · bukan harga order")
        if out.get("retest_at"):
            st.caption("Retest tertutup: "+out["retest_at"])
        st.caption("Target riset $10/$20/$30/$50 · peluang dan expectancy belum terkalibrasi; tanpa rekomendasi SL/TP.")
