"""R9.1 independent BUY/SELL advance warnings, fixed lead, real M1 paths.
No live permission, retrospective price archive, no observed receipt timestamp.
"""
from itertools import product
from pathlib import Path
import hashlib,json,os,sys
import numpy as np
import pandas as pd
YEARS=list(range(2019,2025))
LEADS=(5,10,15,30)
LATENCY=1
TP=(10.,20.,30.,50.)
COST=.5
SL=10.
FAMILIES=("trend","reversal","sweep","breakout","compression","wick")
RANGES=(0.,5.,10.,15.,20.,30.)
SESSIONS=("ALL","ASIA","LONDON","NY_OPEN")
CONF=("NONE","MOM3","MSS5")
CONFIGS=list(product(FAMILIES,RANGES,SESSIONS,LEADS,CONF))
NS=60_000_000_000
KEYS=("alerts","cancel","censored","confirmed","win10","win20","win30","win50","stop10","net10","mae_sum","tie10")
def eval_paths(d,at):
    t=d.index.asi8
    j=np.searchsorted(t,at.asi8)
    out={}
    jj=np.minimum(j,len(t)-1); end=np.minimum(j+59,len(t)-1)
    breaks=np.r_[0,np.cumsum(np.diff(t)!=NS)]
    good=(j+59<len(t))&(t[jj]==at.asi8)&(t[end]==at.asi8+59*NS)&(breaks[end]==breaks[jj])
    # Confirmation uses completed minutes only; none of their prices are from entry time.
    a=np.maximum(j-5,0); b=np.maximum(j-1,0); c=np.maximum(j-3,0)
    past=(j>=5)&(j<len(t))&(t[b]==at.asi8-NS)&(t[a]==at.asi8-5*NS)&(breaks[a]==breaks[b])
    close=d.close.to_numpy(); high=d.high.to_numpy(); low=d.low.to_numpy(); op=d.open.to_numpy()
    for side in (1,-1):
        early=side*(close[b]-close[c])>0
        levels=(high[a[:,None]+np.arange(4)].max(axis=1) if side==1 else low[a[:,None]+np.arange(4)].min(axis=1))
        mss=side*(close[b]-levels)>0
        v={"NONE":np.ones(len(j),bool),"MOM3":past&early,"MSS5":past&mss,"good":good,"past":past}
        for name in ("win10","win20","win30","win50","stop10","tie10"):v[name]=np.zeros(len(j),bool)
        for name in ("net10","mae_sum"):v[name]=np.zeros(len(j))
        ids=np.flatnonzero(good)
        for k in range(0,len(ids),5000):
            ix=ids[k:k+5000]; p=j[ix]; entry=op[p]
            q=p[:,None]+np.arange(60)[None,:]
            f=high[q]-entry[:,None] if side==1 else entry[:,None]-low[q]
            adv=entry[:,None]-low[q] if side==1 else high[q]-entry[:,None]
            sl=adv>=SL-COST
            sf=np.where(sl.any(axis=1),sl.argmax(axis=1),60)
            for target in TP:
                hit=f>=target+COST
                tf=np.where(hit.any(axis=1),hit.argmax(axis=1),60)
                win=tf<sf
                v[f"win{int(target)}"][ix]=win
                if target==10:
                    loss=(sf<=tf)&(sf<60)
                    v["stop10"][ix]=loss; v["tie10"][ix]=(tf==sf)&(tf<60)
                    v["net10"][ix]=np.where(win,10.,np.where(loss,-10.,side*(close[p+59]-entry)-COST))
                    exit_at=np.minimum(np.minimum(sf,tf),59)
                    v["mae_sum"][ix]=np.maximum(0,np.where(np.arange(60)[None,:]<=exit_at[:,None],adv,-np.inf).max(axis=1))
        out[side]=v
    return out

def run_year():
    year=int(os.environ["XAU_V193_YEAR"])
    p=Path(os.environ["XAU_V193_PRICE_CSV"]); prov=json.loads(Path(os.environ["XAU_V193_PRICE_PROVENANCE"]).read_text())
    assert hashlib.sha256(p.read_bytes()).hexdigest()==prov["normalized_csv_sha256"]
    d=pd.read_csv(p,parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    d.index=pd.to_datetime(d.index,utc=True).as_unit("ns")
    assert not d.index.has_duplicates
    d=d[d.index.year<=2024]; assert len(d)>100000
    m=d.resample("5min",label="right",closed="left").agg(open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),n=("close","size"))
    m.loc[m.n!=5,["open","high","low","close"]]=np.nan
    o,h,l,c=(m[q] for q in ("open","high","low","close"))
    r60=h.rolling(12).max()-l.rolling(12).min()
    r15=h.rolling(3).max()-l.rolling(3).min()
    tr=h-l; atr=tr.rolling(12).mean()
    mom=c-c.shift(3); body=c-o
    ph=h.shift().rolling(12).max(); pl=l.shift().rolling(12).min()
    quiet=r15.shift()<=.30*r60.shift()
    mask=(m.index.year==year)&(m.index+pd.Timedelta(minutes=max(LEADS)+LATENCY+60)<=pd.Timestamp(f"{year+1}-01-01",tz="UTC"))&r60.notna()&ph.notna()
    idx=m.index[mask]
    ts=idx.asi8//NS
    hour=idx.tz_convert("Asia/Jakarta").hour; ny=idx.tz_convert("America/New_York").hour; lon=idx.tz_convert("Europe/London").hour
    session={"ALL":np.ones(len(idx),bool),"ASIA":(hour>=8)&(hour<13),"LONDON":(lon>=8)&(lon<12),"NY_OPEN":(ny>=8)&(ny<11)}
    vol=r60.loc[idx].to_numpy()
    rule={}
    for side in (1,-1):
        sweep=((l<pl)&(c>pl)&(body>0)) if side==1 else ((h>ph)&(c<ph)&(body<0))
        br=(c>ph) if side==1 else (c<pl)
        wick=(np.minimum(o,c)-l) if side==1 else (h-np.maximum(o,c))
        rule[side]={
          "trend":(side*mom>=atr)&(side*body>0),
          "reversal":(side*mom.shift()<=-1.5*atr)&(side*body>=.5*atr),
          "sweep":sweep,
          "breakout":br&(side*body>=.5*atr),
          "compression":quiet&br,
          "wick":(wick>=atr)&(side*body>0)}
        rule[side]={k:v.loc[idx].fillna(False).to_numpy() for k,v in rule[side].items()}
    paths={lead:eval_paths(d,idx+pd.Timedelta(minutes=lead+LATENCY)) for lead in LEADS}
    result={}
    for side in (1,-1):
        stats=[]
        for family,r,sess,lead,conf in CONFIGS:
            warning=np.flatnonzero(rule[side][family]&(vol>=r)&session[sess])
            # Suppress repeated warning for same side throughout its entire entry+exit window,
            # including cancellations. No future-price filtering of alert selection.
            keep=[]; last=-10**15
            for i in warning:
                if ts[i]>=last+lead+LATENCY+60:
                    keep.append(i);last=ts[i]
            k=np.asarray(keep,dtype=int); q=paths[lead][side]
            # If confirmation requires unavailable preceding minutes classify as censored.
            known=(np.ones(len(k),bool) if conf=="NONE" else q["past"][k])
            ok=known&q[conf][k]
            confirm_idx=k[ok&q["good"][k]]
            cancel=int((known&~q[conf][k]).sum())
            censored=len(k)-cancel-len(confirm_idx)
            record=dict(alerts=len(k),cancel=cancel,censored=censored,confirmed=len(confirm_idx))
            for item in KEYS[4:]:
                record[item]=float(q[item][confirm_idx].sum()) if item in ("net10","mae_sum") else int(q[item][confirm_idx].sum())
            stats.append(record)
        result[str(side)]=stats
    out={"year":year,"rows_m1":int((d.index.year==year).sum()),"months":sorted({int(v) for v in d.index[d.index.year==year].month}),"decisions":len(idx),"source":prov,"configs":len(CONFIGS),"stats":result}
    path=Path(f"artifacts/r91-{year}.json");path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(out,allow_nan=False))
    print("R91_YEAR",year,out["rows_m1"],out["months"],len(idx),len(CONFIGS),flush=True)
def merge(records):
    return {k:sum(r[k] for r in records) for k in KEYS}
def wilson(k,n):
    if n==0:return 0.
    z=1.645;p=k/n
    return (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
def aggregate():
    root=Path(os.environ["R91_ROOT"])
    data={y:json.loads(next(root.rglob(f"r91-{y}.json")).read_text()) for y in YEARS}
    assert all(d["configs"]==len(CONFIGS) for d in data.values())
    folds=[]
    for y in range(2022,2025):
        for side in ("1","-1"):
            prior=list(range(y-3,y))
            for lead in (*LEADS,"ALL"):
                best=None; qualified=0
                for j,c in enumerate(CONFIGS):
                    if lead!="ALL" and c[3]!=lead:continue
                    rows=[data[t]["stats"][side][j] for t in prior]
                    m=merge(rows)
                    if m["confirmed"]<100 or sum(q["confirmed"]>=15 for q in rows)<2 or m["net10"]<=0:continue
                    if m["censored"]>m["alerts"]*.10:continue
                    qualified+=1
                    score=(wilson(m["win10"],m["confirmed"]),wilson(m["win10"],m["alerts"]),m["confirmed"],-j)
                    if best is None or score>best[0]:best=(score,j,m)
                rec={"year":y,"side":side,"lead_group":lead,"qualified":qualified,"status":"WAIT"}
                if best:
                    _,j,m=best
                    rec.update(status="DEV",config=CONFIGS[j],inner=m,outer=data[y]["stats"][side][j])
                folds.append(rec)
    totals={}
    for lead in (*LEADS,"ALL"):
        totals[str(lead)]={s:merge([f["outer"] for f in folds if f["side"]==s and f["lead_group"]==lead and "outer" in f]) for s in ("1","-1")}
    out={"contract":"R91_EARLY_WARNING_M5_M1_FIXED_LEAD","years":YEARS,"evaluation_years":[2022,2023,2024],"configs_per_side":len(CONFIGS),"annual_evaluations":len(CONFIGS)*2*len(YEARS),"folds":folds,"totals_by_lead":totals,"data":[{k:v for k,v in z.items() if k!="stats"} for z in data.values()],"latency_assumed_minutes":LATENCY,"live_delivery_verified":False,"cost":COST,"sl":SL,"same_minute_exit":"STOP_FIRST","actual_macro_filter_used":False,"side_models_separately_scored_not_joint_portfolio":True,"untouched_holdout":False,"authority_to_trade":False}
    p=Path("artifacts/r91-results.json");p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(out,indent=2,allow_nan=False))
    print("R91_TOTALS",json.dumps(totals),flush=True)
if __name__=="__main__":
    aggregate() if sys.argv[-1]=="aggregate" else run_year()
