"""R32 causal XAUUSD source-TF liquidity sweep -> M5 retest/MSS/FVG replay.

Frozen R25/R11/R29.2/R18/R27/R24 are NOT reproduced here: all direction
votes are clearly marked new proxy challengers, never production forecasts.
Bars are from the same audited Dukascopy BID M5 source (2012--2026),
resampled with no future current-TF bar leakage. No orders/keys/VPS.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd

TF_MIN={"H1":60,"H4":240,"D1":1440,"W1":10080}
TF_FREQ={"H1":"1h","H4":"4h","D1":"1D","W1":"W-MON"}
MIN_COUNT={"H1":9,"H4":35,"D1":180,"W1":700}
RETEST_M5={"H1":180,"H4":720,"D1":2016,"W1":5040}
SWEEP_LOOKBACK=(4,8,16)
WICK_ZONE=(.25,.50,.75)
METHODS=("REJECTION","MSS","FVG")
TARGET_R=(.75,1.,1.5,2.)
HOLD_M5=(24,96,288)
COST=.70
N_OUT=len(TARGET_R)*len(HOLD_M5)
CONTRACT="RIZAN_R32_SOURCE_TF_LIQUIDITY_SWEEP_M5_V1"


def load(year,dir="/tmp/r32"):
    p=Path(dir)/f"r32-m5-{year}.csv.gz"
    if not p.is_file():raise FileNotFoundError(f"R32_M5_SHARD_MISSING:{year}")
    raw=p.read_bytes()
    d=pd.read_csv(p,index_col=0,parse_dates=True)
    if not {"o","h","l","c"}.issubset(d):
        raise ValueError("R32_SOURCE_M5_COLUMNS_MISSING")
    if d.index.tz is None or d.index.has_duplicates or not d.index.is_monotonic_increasing:
        raise ValueError("R32_SOURCE_M5_TIMESTAMP_INVALID")
    if not (d.index.year==year).all() or (d.index.dayofweek>=5).any():
        raise ValueError("R32_SOURCE_M5_YEAR_OR_WEEKEND_INVALID")
    if not np.isfinite(d[["o","h","l","c"]].to_numpy(float)).all():
        raise ValueError("R32_SOURCE_M5_PRICE_INVALID")
    return d,hashlib.sha256(raw).hexdigest()


def source_tf(m5,tf):
    n=TF_MIN[tf]//5
    freq=TF_FREQ[tf]
    q=m5.resample(freq,label="left",closed="left").agg(
        o=("o","first"),h=("h","max"),l=("l","min"),
        c=("c","last"),count=("c","size"))
    q=q.loc[q["count"]>=MIN_COUNT[tf]].drop(columns="count").dropna()
    close_at=q.index+pd.Timedelta(minutes=TF_MIN[tf])
    # A partially observed end-of-year bar must never appear "closed".
    fully_closed=close_at<=m5.index[-1]+pd.Timedelta(minutes=5)
    q=q.loc[fully_closed].copy()
    q["closed_at"]=close_at[fully_closed]
    return q


def indicators(q):
    c=q.c.astype(float)
    e={n:c.ewm(span=n,adjust=False).mean().to_numpy() for n in (8,21,34,55)}
    m={n:(c-c.shift(n)).to_numpy() for n in (3,5,8,13)}
    delta=c.diff()
    up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    dn=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rsi=(100-100/(1+up/dn.replace(0,np.nan))).fillna(50).to_numpy()
    h,l=q.h.to_numpy(float),q.l.to_numpy(float)
    tr=pd.concat([q.h-q.l,(q.h-q.c.shift(1)).abs(),
                  (q.l-q.c.shift(1)).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False).mean().to_numpy(float)
    return e,m,rsi,atr


def confirm_m5(o,h,l,c,start,end,side,low,high,method):
    """First touch, then closed-M5 confirmation; never use current OHLC
    before it closes. Reject gaps instead of padding broker holidays.
    """
    touched_at=None
    for j in range(start,end):
        if side==1 and c[j]<low:
            return None
        if side==-1 and c[j]>high:
            return None
        if touched_at is None:
            if l[j]<=high and h[j]>=low:touched_at=j
            else:continue
        if j>touched_at+18:return None
        if method=="REJECTION":
            valid=(c[j]>high and c[j]>o[j] if side==1
                   else c[j]<low and c[j]<o[j])
        elif method=="MSS":
            if j<4:continue
            valid=(c[j]>max(h[j-3:j]) and c[j]>o[j] if side==1
                   else c[j]<min(l[j-3:j]) and c[j]<o[j])
        else:
            if j<2:continue
            valid=(l[j]>h[j-2] and c[j]>o[j] if side==1
                   else h[j]<l[j-2] and c[j]<o[j])
        if valid:return j
    return None


def make_events(m5,tf,year):
    q=source_tf(m5,tf)
    if len(q)<65:return pd.DataFrame()
    e,m,rsi,atr=indicators(q)
    src=q[["o","h","l","c"]].to_numpy(float)
    so,sh,sl,sc=src.T
    m5_data=m5[["o","h","l","c"]].to_numpy(float)
    mo,mh,ml,mc=m5_data.T
    times=m5.index.asi8
    closed=q.closed_at.array.asi8
    last_time=times[-1]
    rows=[]
    for lb in SWEEP_LOOKBACK:
        previous_hi=q.h.shift(1).rolling(lb).max().to_numpy()
        previous_lo=q.l.shift(1).rolling(lb).min().to_numpy()
        for i in range(max(56,lb+3),len(q)):
            a=atr[i]
            if not np.isfinite(a) or a<=0:continue
            span=max(sh[i]-sl[i],1e-9)
            sides=[]
            if sl[i]<previous_lo[i] and sc[i]>previous_lo[i]:
                sides.append((1,float(previous_lo[i]),(previous_lo[i]-sl[i])/a,
                              (min(so[i],sc[i])-sl[i])/span))
            if sh[i]>previous_hi[i] and sc[i]<previous_hi[i]:
                sides.append((-1,float(previous_hi[i]),(sh[i]-previous_hi[i])/a,
                              (sh[i]-max(so[i],sc[i]))/span))
            if not sides:continue
            first=int(np.searchsorted(times,closed[i],side="left"))
            if first>=len(times)-300:continue
            # Do not take a signal on a stale/partial source-TF candle.
            if first>0 and times[first]<closed[i]:raise RuntimeError("R32_FUTURE_SOURCE_BAR")
            expiry=min(len(times)-300,first+RETEST_M5[tf])
            if expiry<=first:continue
            for side,level,depth,wick in sides:
                if not .04<=depth<=4.0 or wick<.12:continue
                wick_range=level-sl[i] if side==1 else sh[i]-level
                if wick_range<=0:continue
                for width in WICK_ZONE:
                    low=float(sl[i]) if side==1 else float(sh[i]-width*wick_range)
                    high=float(sl[i]+width*wick_range) if side==1 else float(sh[i])
                    if high<=low:continue
                    for method in METHODS:
                        confirmed=confirm_m5(mo,mh,ml,mc,first,expiry,
                                             side,low,high,method)
                        if confirmed is None or confirmed+1>=len(times):continue
                        # A forward gap cannot be represented as the next M5
                        # fill price without broker session and spread evidence.
                        if times[confirmed+1]-times[confirmed]>10*60*10**9:continue
                        if confirmed+1>=len(times)-289:continue
                        confirm_closed=times[confirmed]+5*60*10**9
                        latest=int(np.searchsorted(closed,confirm_closed,side="right")-1)
                        if latest<i or latest<55:continue
                        if not np.isfinite(rsi[latest]):continue
                        entry=float(mo[confirmed+1])
                        # Reference stop outside distal zone plus fixed cushion.
                        stop=float(sl[i]-.05*a if side==1 else sh[i]+.05*a)
                        risk=(entry-stop)*side
                        if not .02*a<=risk<=3.2*a:continue
                        vals={
                            "tf":tf,"year":year,"side":side,"lookback":lb,
                            "zone_fraction":width,"confirmation":method,
                            "sweep_depth_atr":float(depth),"wick_fraction":float(wick),
                            "risk_atr":risk/a,"hour_wib":int((m5.index[confirmed].hour+7)%24),
                            "formation_at":q.closed_at.iloc[i].isoformat(),
                            "confirmation_at":(m5.index[confirmed]+pd.Timedelta(minutes=5)).isoformat(),
                            "entry_at":m5.index[confirmed+1].isoformat(),
                            "entry_index":confirmed+1,"entry":entry,"stop":stop,"risk":risk,
                            "latest_closed_tf_at":q.closed_at.iloc[latest].isoformat(),
                            "rsi":float(rsi[latest]),
                            "direction_close":float(sc[latest]),
                            "m5_confirmation_distance":float((mc[confirmed]-level)*side/a),
                        }
                        for period in (8,21,34,55):
                            vals[f"ema_{period}"]=float(e[period][latest])
                        for period in (3,5,8,13):
                            vals[f"mom_{period}"]=float(m[period][latest])
                        rows.append(vals)
    return pd.DataFrame(rows)


def outcomes(m5,events):
    if events.empty:return events
    arr=m5[["o","h","l","c"]].to_numpy(float)
    op,high,low,close=arr.T
    ticks=m5.index.asi8
    for k in range(N_OUT):
        events[f"pnl_{k}"]=np.nan
        events[f"exit_at_{k}"]=""
    for i,e in events.iterrows():
        start=int(e.entry_index);entry=float(e.entry)
        stop=float(e.stop);side=int(e.side);risk=float(e.risk)
        for k,(hold,rr) in enumerate((hold,rr)
                for hold in HOLD_M5 for rr in TARGET_R):
            end=start+hold
            if end>=len(arr):continue
            # End-of-horizon candle close is known; no forward-bar entry.
            if np.any(np.diff(ticks[start:end+1])>15*60*10**9):
                continue
            target=entry+side*rr*risk
            exit_price=float(close[end-1])
            exit_idx=end-1
            for j in range(start,end):
                stop_hit=low[j]<=stop if side==1 else high[j]>=stop
                tp_hit=high[j]>=target if side==1 else low[j]<=target
                if stop_hit:
                    exit_idx=j;exit_price=stop;break
                if tp_hit:
                    exit_idx=j;exit_price=target;break
            events.at[i,f"pnl_{k}"]=float((exit_price-entry)*side-COST)
            events.at[i,f"exit_at_{k}"]=(m5.index[exit_idx]+pd.Timedelta(minutes=5)).isoformat()
    return events


def run(year,path):
    path=Path(path)
    if not path.is_file():raise FileNotFoundError("R32_SOURCE_CSV_REQUIRED")
    m5=pd.read_csv(path,index_col=0,parse_dates=True)
    if m5.index.tz is None or m5.index.has_duplicates:
        raise ValueError("R32_M5_INDEX_NOT_VALID")
    if (m5.index.dayofweek>=5).any() or (m5.index.year!=year).any():
        raise ValueError("R32_YEAR_WEEKEND_NOT_VERIFIED")
    out=Path("artifacts/r32");out.mkdir(parents=True,exist_ok=True)
    per_tf={}
    for tf in TF_MIN:
        ev=make_events(m5,tf,year)
        if not ev.empty:
            ev=outcomes(m5,ev)
        per_tf[tf]=ev
        target=out/f"r32-events-{tf}-{year}.csv.gz"
        if ev.empty:
            # Explicit empty, never fabricate candidate labels.
            pd.DataFrame(columns=["tf","year","side","entry_at"]).to_csv(
                target,index=False,compression="gzip")
        else:
            ev.to_csv(target,index=False,compression="gzip")
        print(json.dumps({"stage":"R32_EVENTS","year":year,"tf":tf,
                          "candidate_retest_signals":len(ev),
                          "complete_1R_24M5":int(ev["pnl_1"].notna().sum()) if len(ev) else 0}),flush=True)
    receipt={
        "contract":CONTRACT,"year":year,
        "source":"R32_VERIFIED_DUKASCOPY_XAUUSD_M5_BID",
        "source_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows_source_m5":len(m5),
        "counts":{tf:len(df) for tf,df in per_tf.items()},
        "next_M5_open_entry":True,
        "direction_model_type":"CAUSAL_SAME_SOURCE_TF_PROXY_NOT_FROZEN_PARITY",
        "candle_closed_before_direction_and_entry":True,
        "pnl_scenario_cost_usd_oz":COST,
        "pnl_censored_at_weekend_gap_or_missing_future":True,
        "research_only":True,"execution_authority":False,
        "execution_influence":False
    }
    (out/f"r32-events-receipt-{year}.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--year",type=int,required=True)
    ap.add_argument("--source",required=True)
    a=ap.parse_args()
    run(a.year,a.source)
