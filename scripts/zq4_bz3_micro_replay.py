"""ZQ4/BZ3 microstructure direction-first replay (research-only).
M5 closed signals, M1 entry at NEXT open; no look-ahead, no live authority.
Separate H1/H4/D1 contexts, no cross-timeframe voting veto. Risk controls
and costs are hypothetical. BTCUSDT spot is NOT BTCUSD FP Markets CFD.
"""
from __future__ import annotations
import argparse, hashlib, io, json, os, zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import requests

OUT=Path("artifacts");OUT.mkdir(exist_ok=True)
FAMILIES=("SWEEP_RECLAIM","SWEEP_MSS","FVG_RETEST","EMA20_RECLAIM")
LOOKBACKS=(12,24)
GATES=("ANY","ANCHOR","COUNTER","D1_SUPPORT")
SESSIONS=("ALL","ASIA","LONDON","NEW_YORK")
HORIZONS={"H1":60,"H4":240,"D1":480}
COST={"XAU":(1.,3.),"BTC":(5.,15.)}
Z=1.95996398454

def wilson(k,n):
    if not n:return None
    p=k/n
    return float((p+Z*Z/(2*n)-Z*np.sqrt(p*(1-p)/n+Z*Z/(4*n*n)))/(1+Z*Z/n))

def source_data(asset,year):
    if asset=="XAU":
        csv=Path(os.environ["XAU_V193_PRICE_CSV"])
        provenance=Path(os.environ["XAU_V193_PRICE_PROVENANCE"])
        p=json.loads(provenance.read_text())
        assert p["contract"]=="XAU_HISTDATA_M1_SHARD_V193_1" and p["source"]=="HISTDATA_XAUUSD_M1"
        assert int(p["year"])==year
        assert hashlib.sha256(csv.read_bytes()).hexdigest()==p["normalized_csv_sha256"]
        x=pd.read_csv(csv,parse_dates=["timestamp"]).set_index("timestamp")
        x.index=pd.to_datetime(x.index,utc=True)
        d=x[["open","high","low","close"]].rename(columns={"open":"o","high":"h","low":"l","close":"c"})
        prov={"provider":p["source"],"year":year,"sha256":p["normalized_csv_sha256"],
              "failed_periods":p["failed_periods"],"rows":p["rows"]}
    else:
        months=range(1,11) if year==2026 else range(1,13)
        # At least two full months of warmup for daily context.
        todo=[(year-1,11),(year-1,12)]+[(year,m) for m in months]
        session=requests.Session();pieces=[];sums={}
        for y,m in todo:
            name=f"BTCUSDT-1m-{y}-{m:02d}.zip"
            url=f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/{name}"
            data=session.get(url,timeout=(12,90));data.raise_for_status()
            body=data.content
            assert len(body)<20_000_000,(name,len(body))
            check=session.get(url+".CHECKSUM",timeout=(12,25));check.raise_for_status()
            expected=check.text.strip().split()[0].lower()
            actual=hashlib.sha256(body).hexdigest()
            assert expected==actual,(name,"CHECKSUM_FAIL")
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                members=[n for n in archive.namelist() if n.endswith(".csv")]
                assert len(members)==1,members
                a=pd.read_csv(archive.open(members[0]),header=None,
                              usecols=[0,1,2,3,4],low_memory=False)
            a.columns=["at","o","h","l","c"]
            a["at"]=pd.to_numeric(a["at"],errors="coerce")
            if a["at"].isna().sum():raise RuntimeError("Malformed archive "+name)
            # Binance SPOT switched milliseconds to microseconds on Jan 1 2025.
            mul=1000 if y>=2025 else 1
            assert ((a["at"].astype("int64")% (60000*mul))==0).all(),name
            t=pd.to_datetime(a.pop("at")/(1000*mul),unit="s",utc=True)
            a.index=t
            pieces.append(a.astype(float));sums[name]=actual
        d=pd.concat(pieces).sort_index()
        prov={"provider":"BINANCE_VISION_SPOT_BTCUSDT_M1","year":year,
              "source":"https://data.binance.vision/","checksum_zip_sha256":sums,
              "not_btcusd_cfd":True,"last_month":max(months)}
    assert d.index.is_monotonic_increasing and d.index.is_unique
    assert d.index.tz is not None
    v=d.to_numpy(float)
    assert np.isfinite(v).all() and (v[:,2]>0).all()
    assert (v[:,2]<=np.minimum(v[:,0],v[:,3])).all()
    assert (v[:,1]>=np.maximum(v[:,0],v[:,3])).all()
    assert (d.index.asi8%60_000_000_000==0).all()
    assert (d.index.year==year).sum()>100000,(asset,year,len(d))
    return d,prov

def anchors(d):
    out={}
    for tf,minutes in (("H1",60),("H4",240),("D1",1440)):
        b=d.resample(f"{minutes}min",label="right",closed="left").agg(
           o=("o","first"),h=("h","max"),l=("l","min"),c=("c","last"),n=("c","count"))
        minimum=minutes if os.environ.get("ZQ4_ASSET")=="BTC" else {60:50,240:200,1440:900}[minutes]
        b.loc[b.n<minimum,["o","h","l","c"]]=np.nan
        c=b.c;e8=c.ewm(span=8,adjust=False,min_periods=8).mean()
        e21=c.ewm(span=21,adjust=False,min_periods=21).mean()
        trend=np.sign(e8-e21)
        trend=np.where((trend*(c-e21)>0)&(trend*(e21-e21.shift(2))>0)&
                       (trend*(c-c.shift(3))>0),trend,0.)
        # Reject if last candle is partially missing; never backfill future.
        out[tf]=pd.Series(trend,index=b.index).where(b.c.notna(),0.)
    return out

def features(d):
    m=d.resample("5min",label="right",closed="left").agg(
       o=("o","first"),h=("h","max"),l=("l","min"),c=("c","last"),n=("c","count"))
    m.loc[m.n!=5,["o","h","l","c"]]=np.nan
    h,l,c,o=m.h,m.l,m.c,m.o
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(14,min_periods=14).mean()
    ema=c.ewm(span=20,adjust=False,min_periods=20).mean()
    return m,atr,ema

def candidate(m,atr,ema,side,lookback,family):
    o,h,l,c=m.o,m.h,m.l,m.c
    hi=h.shift(1).rolling(lookback,min_periods=lookback).max()
    lo=l.shift(1).rolling(lookback,min_periods=lookback).min()
    if side>0:
        sw=(l<lo-.05*atr)&(c>lo)&(c>o)
        mss=(c>h.shift(1).rolling(3).max())&((c-o)>.30*atr)
        fvg=(l.shift(1)>h.shift(3))
        mid=(l.shift(1)+h.shift(3))*.5
        gap=(fvg & (l<=l.shift(1)) & (c>mid)&(c>o))
        em=(l<=ema)&(c>ema)&(c>o)&((c-l)>.35*atr)
    else:
        sw=(h>hi+.05*atr)&(c<hi)&(c<o)
        mss=(c<l.shift(1).rolling(3).min())&((o-c)>.30*atr)
        fvg=(h.shift(1)<l.shift(3))
        mid=(h.shift(1)+l.shift(3))*.5
        gap=fvg&(h>=h.shift(1))&(c<mid)&(c<o)
        em=(h>=ema)&(c<ema)&(c<o)&((h-c)>.35*atr)
    if family=="SWEEP_RECLAIM":signal=sw
    elif family=="SWEEP_MSS":signal=(sw.shift(1).rolling(3).max()>0)&mss
    elif family=="FVG_RETEST":signal=gap
    else:signal=em
    return signal.fillna(False)&atr.notna()

def complete_paths(d,decision_times,horizon):
    t=d.index.asi8
    pos=np.searchsorted(t,decision_times.asi8)
    ids=np.clip(pos,0,len(t)-1)
    end=np.clip(pos+horizon-1,0,len(t)-1)
    bad=np.r_[0,np.cumsum(np.diff(t)!=60_000_000_000)]
    exact=(pos+horizon<=len(d))&(t[ids]==decision_times.asi8)&(
       t[end]==decision_times.asi8+(horizon-1)*60_000_000_000)&(
       bad[end]==bad[ids])
    return pos,exact

def measured(d,m,atr,decision,valid,side,horizon,asset):
    # Signals are based ONLY on completed M5 candles. Entry is next M1 open.
    indices=np.flatnonzero(valid)
    if not len(indices):return []
    # Prevent overlapping, cherry-picked entries of the same policy.
    keep=[];last=-10**18;dec=decision.asi8//60_000_000_000
    for i in indices:
        if dec[i]-last>=horizon:
            keep.append(i);last=dec[i]
    if not keep:return []
    ix=np.asarray(keep);times=decision[ix];p,ok=complete_paths(d,times,horizon)
    # Incomplete future outcomes are censored, never counted as failures or wins.
    # Purge boundary: a validation-year decision may not consume next year's prices.
    boundary=pd.Timestamp(f"{int(times.year[0])+1}-01-01",tz="UTC")
    ok &= (times+pd.Timedelta(minutes=horizon)<=boundary)
    q=np.flatnonzero(ok);records=[]
    for chunk in np.array_split(q,max(1,(len(q)+255)//256)):
        if not len(chunk):continue
        j=ix[chunk];a=p[chunk];ar=d[["o","h","l","c"]].to_numpy(float)
        entry=ar[a,0]
        vv=atr.iloc[j].to_numpy(float)
        invalid=(m.l.iloc[j].to_numpy(float)-.15*vv) if side==1 else (m.h.iloc[j].to_numpy(float)+.15*vv)
        risk=side*(entry-invalid)
        plausible=(risk>0)&(risk<3*vv)
        if not plausible.any():continue
        j=j[plausible];a=a[plausible];entry=entry[plausible]
        invalid=invalid[plausible];vv=vv[plausible]
        path=ar[a[:,None]+np.arange(horizon)[None,:]]
        low=path[:,:,2];high=path[:,:,1]
        stop=(low<=invalid[:,None]) if side==1 else (high>=invalid[:,None])
        stopped=stop.any(1);first=stop.argmax(1);r=np.arange(len(a))
        exit_open=path[r,first,0]
        filled=np.minimum(exit_open,invalid) if side==1 else np.maximum(exit_open,invalid)
        endp=path[:,-1,3]
        exitp=np.where(stopped,filled,endp)
        raw=side*(endp-entry)/entry*10000
        gross=side*(exitp-entry)/entry*10000
        base,stress=COST[asset]
        adv=np.maximum(0,np.max((entry[:,None]-low) if side==1 else (high-entry[:,None]),axis=1))/entry*10000
        fav=np.maximum(0,np.max((high-entry[:,None]) if side==1 else (entry[:,None]-low),axis=1))/entry*10000
        for k in range(len(a)):
            records.append({"decision":str(decision[j[k]]),"correct":bool(raw[k]>0),
                "net_win":bool(gross[k]>base),"stress_win":bool(gross[k]>stress),
                "gross_bp":float(gross[k]),"mae_bp":float(adv[k]),"mfe_bp":float(fav[k]),
                "stopped":bool(stopped[k]),"raw_bp":float(raw[k])})
    return records

def combine(rows,raw_opportunities,censored):
    n=len(rows);w=sum(r["correct"] for r in rows);net=sum(r["net_win"] for r in rows)
    return {"n":n,"correct":w,"accuracy":w/n if n else None,"direction_wilson_lower95":wilson(w,n),
      "net_positive":net,"net_hit_rate":net/n if n else None,
      "stress_hit_rate":sum(r["stress_win"] for r in rows)/n if n else None,
      "avg_stopaware_net_bp":sum(r["gross_bp"] for r in rows)/n-COST[os.environ["ZQ4_ASSET"]][0] if n else None,
      "avg_stopaware_stress_bp":sum(r["gross_bp"] for r in rows)/n-COST[os.environ["ZQ4_ASSET"]][1] if n else None,
      "mean_mae_bp":sum(r["mae_bp"] for r in rows)/n if n else None,
      "mean_mfe_bp":sum(r["mfe_bp"] for r in rows)/n if n else None,
      "stopped":sum(r["stopped"] for r in rows),
      "signals":raw_opportunities,"censored_or_skipped":censored,
      "coverage":n/max(1,int(os.environ["ZQ4_MARKET"]))}

def run(asset,year):
    os.environ["ZQ4_ASSET"]=asset
    data,source=source_data(asset,year)
    m,atr,ema=features(data);directions=anchors(data)
    arr=data.index
    horizons=["H1","H4","D1"] if asset=="XAU" else ["H1","H4"]
    decision=m.index
    yr=decision.year==year
    hour=decision.tz_convert("Asia/Jakarta").hour
    sess={"ALL":np.ones(len(m),bool),"ASIA":(hour>=8)&(hour<13),
          "LONDON":(hour>=14)&(hour<20),"NEW_YORK":(hour>=20)|(hour<2)}
    views={tf:directions[tf].reindex(decision,method="ffill",
          tolerance=pd.Timedelta(minutes={"H1":70,"H4":250,"D1":1700}[tf])).fillna(0.).to_numpy() for tf in directions}
    results=[];market=int((yr&m.c.notna()&atr.notna()).sum())
    os.environ["ZQ4_MARKET"]=str(market)
    cache={}
    for side in (1,-1):
        for lookback in LOOKBACKS:
            for family in FAMILIES:
                signals=candidate(m,atr,ema,side,lookback,family).to_numpy()
                for tf in horizons:
                    horizon=HORIZONS[tf]
                    for gate in GATES:
                        allow=(
                           np.ones(len(m),bool) if gate=="ANY" else
                           views[tf]*side>0 if gate=="ANCHOR" else
                           views[tf]*side<0 if gate=="COUNTER" else views["D1"]*side>0
                        )
                        for session,mask in sess.items():
                            key=f"{tf}|{side}|{lookback}|{family}|{gate}|{session}"
                            conditions=yr&signals&allow&mask
                            k=(side,lookback,family,tf,gate,session)
                            rows=measured(data,m,atr,decision,conditions,side,horizon,asset)
                            count=int(np.count_nonzero(conditions))
                            metrics=combine(rows,count,max(0,count-len(rows)))
                            results.append({"config":key,"tf":tf,"side":"BUY" if side>0 else "SELL",
                                 "family":family,"lookback":lookback,"gate":gate,"session":session,
                                 "horizon_minutes":horizon,"metrics":metrics})
    report={"version":"ZQ4_BZ3_M1_CAUSAL","asset":asset,"year":year,"data":source,
      "first":str(data.index.min()),"last":str(data.index.max()),
      "market_m5_candidates":market,"configs_evaluated":len(results),
      "rows":results,"execution_authority":False,"research_only":True,
      "limits":["XAU HistData is a secondary archive; BTC is Binance BTCUSDT spot, not broker BTCUSD",
       "M1 OHLC cannot prove order of two events within one minute; no TP optimization",
       "Signal at M5 close; entry next M1 open; excluded incomplete paths; stop first",
       "Costs base/stress are hypothetical fixed bp, no broker spread/slippage/funding",
       "H1/H4/D1 bias independently available only after completed anchor candles",
       "Historical development folds were used before; not a pristine forward test",
       "Per-config cooldown matches horizon to limit repeated overlapping entries",
       "No LIVE/cBot/order permission"]}
    p=OUT/f"zq4-{asset}-{year}.json";p.write_text(json.dumps(report,allow_nan=False))
    top=sorted([q for q in results if q["metrics"]["n"]>=40],key=lambda x:(x["metrics"]["direction_wilson_lower95"],x["metrics"]["n"]),reverse=True)[:8]
    print("ZQ4_YEAR",json.dumps({"asset":asset,"year":year,"market":market,"configs":len(results),
      "top_diagnostic_NOT_SELECTED":top,"source":{k:v for k,v in source.items() if "checksum" not in k}},allow_nan=False),flush=True)

def aggregate(asset,root):
    records={}
    for y in (2022,2023,2024,2025,2026):
        files=list(Path(root).rglob(f"zq4-{asset}-{y}.json"))
        if len(files)!=1:raise RuntimeError("Missing/duplicated replay shard "+asset+str(y))
        data=json.loads(files[0].read_text())
        assert data["asset"]==asset and data["year"]==y
        records[y]={r["config"]:r for r in data["rows"]}
    keys=set(records[2022])
    assert all(set(x)==keys for x in records.values())
    folds=[];selected={}
    for year in (2024,2025,2026):
        val=(year-2,year-1)
        for tf in (("H1","H4","D1") if asset=="XAU" else ("H1","H4")):
            for side in ("BUY","SELL"):
                qualifying=[]
                for k in keys:
                    rows=[records[z][k] for z in val]
                    if rows[0]["tf"]!=tf or rows[0]["side"]!=side:continue
                    m=[r["metrics"] for r in rows]
                    n=sum(t["n"] for t in m);good=sum(t["correct"] for t in m)
                    if n<60 or min(t["n"] for t in m)<15:continue
                    weighted=lambda x:sum(t[x]*t["n"] for t in m)/n
                    if weighted("avg_stopaware_stress_bp")<=0 or weighted("avg_stopaware_net_bp")<=0:continue
                    lower=wilson(good,n)
                    if lower<.5:continue
                    qualifying.append((lower,good/n,n,k))
                if qualifying:
                    lower,hit,n,k=max(qualifying)
                    rec={"year":year,"tf":tf,"side":side,"status":"VALIDATION_QUALIFIED",
                        "config":records[year][k]["config"],"validation_n":n,
                        "validation_direction":hit,"validation_lower95":lower,
                        "test":records[year][k]["metrics"]}
                else:
                    rec={"year":year,"tf":tf,"side":side,"status":"WAIT_NO_QUALIFIED_VALIDATION"}
                folds.append(rec)
    result={"version":"ZQ4_BZ3_M1_CAUSAL","asset":asset,"folds":folds,
            "target":"independent directional precision >= 80% AND net positive under cost stress; otherwise WAIT",
            "selection":"only prior two years; min 60 prior signals across both years, >=15 in each, positive net under cost stress, Wilson95 >.5",
            "scope":"2022-2023 development, purged by yearly shards; 2024-2026 exploratory evaluation",
            "research_only":True,"execution_authority":False}
    OUT.joinpath(f"zq4-{asset}-aggregate.json").write_text(json.dumps(result,indent=2,allow_nan=False))
    print("ZQ4_AGGREGATE",json.dumps(result,allow_nan=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--asset",choices=["XAU","BTC"],required=True)
    p.add_argument("--year",type=int,choices=range(2022,2027));p.add_argument("--aggregate",action="store_true")
    p.add_argument("--root",default="/tmp/zq4")
    z=p.parse_args()
    if z.aggregate:aggregate(z.asset,z.root)
    else:
        if z.year is None:raise SystemExit("--year required")
        run(z.asset,z.year)
