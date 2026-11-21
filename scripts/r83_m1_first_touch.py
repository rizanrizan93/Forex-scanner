"""R8.3: M5 event/next-M1 entry, 60-minute first-touch research. Pre-2025 only."""
import json,os,hashlib,sys
from pathlib import Path
from itertools import product
import numpy as np
import pandas as pd
COST=.5
TP=10.0
SL=10.0
WINDOW=60
YEARS=list(range(2016,2025))
LOOKBACK=(6,12,24,48)
STRENGTH=(.6,1.,1.5)
VOL=(0.,3.,5.,7.)
CLOCK=("ALL","ASIA","LONDON","NY","NY_OPEN")
FAMILIES=("SWEEP","FAILED_BREAKOUT","BREAKOUT","EXHAUSTION","COMPRESSION")
CONFIGS=list(product(FAMILIES,LOOKBACK,STRENGTH,VOL,CLOCK))
# Actual M1 bid proxy, assumed total cost. Both barriers in one minute -> SL.
def paths(d,decision):
    t=d.index.asi8
    step=60_000_000_000
    j=np.searchsorted(t,decision.asi8)
    last=j+WINDOW-1
    jj=np.minimum(j,len(t)-1); ll=np.minimum(last,len(t)-1)
    continuity=np.r_[0,np.cumsum(np.diff(t)!=step)]
    good=(j<len(t))&(last<len(t))&(t[jj]==decision.asi8)&(t[ll]==decision.asi8+(WINDOW-1)*step)&(continuity[ll]==continuity[jj])
    # no gap across the entry and all 60 future bars
    ids=np.flatnonzero(good); js=j[ids]
    ix=js[:,None]+np.arange(WINDOW)[None,:]
    entry=d.open.to_numpy()[js]; hi=d.high.to_numpy()[ix]; lo=d.low.to_numpy()[ix]; cl=d.close.to_numpy()[js+WINDOW-1]
    records={}
    for side in (1,-1):
        favorable=hi-entry[:,None] if side==1 else entry[:,None]-lo
        adverse=entry[:,None]-lo if side==1 else hi-entry[:,None]
        hit=favorable>=TP+COST
        stop=adverse>=SL-COST
        tfirst=np.where(hit.any(axis=1),hit.argmax(axis=1),WINDOW)
        sfirst=np.where(stop.any(axis=1),stop.argmax(axis=1),WINDOW)
        win=tfirst<sfirst
        lose=(sfirst<=tfirst)&(sfirst<WINDOW)
        out=np.where(win,TP,np.where(lose,-SL,side*(cl-entry)-COST))
        # Conservative upper estimate of adverse excursion up to exit minute;
        # intraminute sequence not known, hence includes whole exit minute.
        exitminute=np.minimum(np.minimum(tfirst,sfirst),WINDOW-1)
        mae=np.maximum(0,np.where(np.arange(WINDOW)[None,:]<=exitminute[:,None],adverse,-np.inf).max(axis=1))
        records[side]={"win":win,"lose":lose,"touch":(favorable>=TP).any(axis=1),"net":out,"mae":mae,"tie":(tfirst==sfirst)&(tfirst<WINDOW)}
    return ids,records
def summary(index,side,records,decision):
    # Retain first chronological signal; block subsequent entries for 60 full minutes,
    # regardless of actual exit time. Independent buy/sell policy, no overlapping trades.
    selected=[]; last=-10**20
    sec=decision.asi8//1_000_000_000
    for i in index:
        if sec[i]>=last+3600:
            selected.append(i); last=sec[i]
    selected=np.array(selected,dtype=int)
    out={}
    for s,name in [(1,"buy"),(-1,"sell")]:
        jj=selected[side[selected]==s]
        r=records[s]
        out[name]={"n":len(jj),"win":int(r["win"][jj].sum()),"stop":int(r["lose"][jj].sum()),"touch":int(r["touch"][jj].sum()),"net":float(r["net"][jj].sum()),"mae_sum":float(r["mae"][jj].sum()),"ties":int(r["tie"][jj].sum())}
    return out
def year_run():
    year=int(os.environ["XAU_V193_YEAR"]); assert year in YEARS
    source=Path(os.environ["XAU_V193_PRICE_CSV"]); prov=json.loads(Path(os.environ["XAU_V193_PRICE_PROVENANCE"]).read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest()==prov["normalized_csv_sha256"]
    d=pd.read_csv(source,parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    d.index=pd.to_datetime(d.index,utc=True)
    assert not d.index.duplicated().any()
    d=d[d.index.year<=2024].copy()
    assert np.isfinite(d[["open","high","low","close"]].to_numpy()).all()
    d=d[d.index.dayofweek!=5]
    m=d.resample("5min",label="right",closed="left").agg(open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),n=("close","size"))
    # Keep explicit incomplete placeholders to reject gaps in rolling windows.
    m.loc[m.n!=5,["open","high","low","close"]]=np.nan
    o,h,l,c=(m[k] for k in ("open","high","low","close"))
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(12,min_periods=12).mean().where(m.n.rolling(12,min_periods=12).min()==5)
    hour_range=h.rolling(12).max()-l.rolling(12).min()
    baseline_range=hour_range.shift(12).rolling(72,min_periods=72).median()
    denom=atr.replace(0,np.nan)
    body=(c-o)/denom
    trend=(c-c.shift(3))/denom
    elig=(m.index.year==year)&(m.index+pd.Timedelta(hours=1)<=pd.Timestamp(f"{year+1}-01-01",tz="UTC"))&atr.notna()&c.notna()
    cand=m.index[elig]
    good,records=paths(d,cand)
    idx=cand[good]
    clock=idx.tz_convert("Asia/Jakarta").hour
    ny=idx.tz_convert("America/New_York")
    lon=idx.tz_convert("Europe/London")
    masks={"ALL":np.ones(len(idx),bool),"ASIA":(clock>=8)&(clock<13),"LONDON":(lon.hour>=8)&(lon.hour<12),"NY":(ny.hour>=8)&(ny.hour<16),"NY_OPEN":(ny.hour>=8)&(ny.hour<11)}
    all_results=[]
    for family,k,strength,vol,session in CONFIGS:
        priorh=h.shift().rolling(k).max(); priorl=l.shift().rolling(k).min()
        up=(c>priorh)&(body>=strength)
        down=(c<priorl)&(body<=-strength)
        if family=="SWEEP":
            buy=(l<priorl)&(c>priorl)&(body>=strength)
            sell=(h>priorh)&(c<priorh)&(body<=-strength)
        elif family=="FAILED_BREAKOUT":
            buy=(c.shift()<priorl.shift())&(c>priorl.shift())&(body>=strength)
            sell=(c.shift()>priorh.shift())&(c<priorh.shift())&(body<=-strength)
        elif family=="BREAKOUT":
            buy=up;sell=down
        elif family=="EXHAUSTION":
            buy=(trend.shift()<=-2*strength)&(body>=strength)&(l<=l.shift())
            sell=(trend.shift()>=2*strength)&(body<=-strength)&(h>=h.shift())
        else:
            quiet=(hour_range.shift()<=.75*baseline_range)
            buy=quiet&up;sell=quiet&down
        b=buy.reindex(idx).fillna(False).to_numpy();s=sell.reindex(idx).fillna(False).to_numpy()
        active=masks[session]&(hour_range.reindex(idx).to_numpy()>=vol)&(b^s)
        side=np.where(b,1,-1)
        row=summary(np.flatnonzero(active),side,records,idx)
        all_results.append(row)
    dest=Path(f"artifacts/r83-year-{year}.json");dest.parent.mkdir(exist_ok=True)
    doc={"year":year,"source":prov,"actual_year_m1_rows":int((d.index.year==year).sum()),"months":sorted(set(d.index[d.index.year==year].month.astype(int))),"eligible_decisions":len(idx),"config_count":len(CONFIGS),"config_stats":all_results}
    dest.write_text(json.dumps(doc,allow_nan=False))
    print("R83_YEAR",year,doc["actual_year_m1_rows"],doc["months"],len(idx),len(CONFIGS),flush=True)
def combine(rows):
    return {s:{k:sum(q[s][k] for q in rows) for k in ("n","win","stop","touch","net","mae_sum","ties")} for s in ("buy","sell")}
def wilson(k,n):
    if n==0:return 0
    z=1.645;p=k/n
    return (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
def aggregate():
    base=Path(os.environ["R83_ROOT"])
    docs={y:json.loads(next(base.rglob(f"r83-year-{y}.json")).read_text()) for y in YEARS}
    assert all(x["config_count"]==len(CONFIGS) for x in docs.values())
    folds=[]
    for y in range(2020,2025):
        # Three prior years; no outer-year outcomes used to select. Require
        # each side >=60 in aggregate and >=8 in at least two prior years.
        prior=list(range(y-3,y)); best=None; qualified=0
        for j,c in enumerate(CONFIGS):
            stats=[docs[z]["config_stats"][j] for z in prior]
            met=combine(stats)
            if not all(met[s]["n"]>=60 and sum(q[s]["n"]>=8 for q in stats)>=2 for s in ("buy","sell")):continue
            if sum(met[s]["net"] for s in ("buy","sell"))<=0:continue
            qualified+=1
            val=min(wilson(met[s]["win"],met[s]["n"]) for s in ("buy","sell"))
            rank=(val,sum(met[s]["n"] for s in ("buy","sell")),-j)
            if best is None or rank>best[0]:best=(rank,j,met)
        if best is None:
            folds.append({"year":y,"status":"WAIT","eligible_configs":qualified});continue
        _,j,met=best
        folds.append({"year":y,"status":"DEV","eligible_configs":qualified,"selected":CONFIGS[j],"inner":met,"outer":docs[y]["config_stats"][j]})
    totals=combine([q["outer"] for q in folds if "outer" in q])
    # Total opportunity baseline across price-path eligible decisions, ungated:
    # report only evaluated policy counts, not naive direction guessing.
    result={"contract":"R83_M1_PATH_PRE2025_RESEARCH","years":YEARS,"folds":folds,"totals":totals,"unique_configs":len(CONFIGS),"annual_config_scores":len(CONFIGS)*len(YEARS),"outer_selection_config_scores":len(CONFIGS)*5,"data":[{k:v for k,v in d.items() if k!="config_stats"} for d in docs.values()],"cost_assumed":COST,"net_tp":TP,"net_sl":SL,"minutes":WINDOW,"same_minute_tie":"STOP_FIRST","untouched_holdout":False,"native_ask_bid":False,"execution_authority":False}
    p=Path("artifacts/r83-results.json");p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(result,indent=2,allow_nan=False))
    print("R83_RESULT",json.dumps({"totals":totals,"folds":folds,"unique_configs":len(CONFIGS)}),flush=True)
if __name__=="__main__":
    if sys.argv[-1]=="aggregate":aggregate()
    else:year_run()
