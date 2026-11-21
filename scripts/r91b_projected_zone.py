"""R9.1b: causal projected pullback zones, first touch and M1 confirmation.
Development only; not a live signal or a prospective notification receipt.
"""
from itertools import product
from pathlib import Path
import hashlib,json,os,sys
import numpy as np
import pandas as pd
import r91_early_warning as base

# Zone, regime, minimum trailing range, session, expiry minutes, confirmation.
CONFIGS=list(product(("SWING","EQ50","OTE62","FVG"),("ANY","TREND"),(0.,10.,20.),base.SESSIONS,(15,30,45),("REJECT","MSS3")))
MIN_LEAD=5
LATENCY=1
CONF_WINDOW=5
MAX_EXPIRY=45
EXTRA=("early","no_touch","no_confirm","eta_n","eta_abs_error","lead_sum")
KEYS=base.KEYS+EXTRA

def run_year():
    year=int(os.environ["XAU_V193_YEAR"])
    p=Path(os.environ["XAU_V193_PRICE_CSV"])
    prov=json.loads(Path(os.environ["XAU_V193_PRICE_PROVENANCE"]).read_text())
    assert hashlib.sha256(p.read_bytes()).hexdigest()==prov["normalized_csv_sha256"]
    d=pd.read_csv(p,parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    d.index=pd.to_datetime(d.index,utc=True).as_unit("ns")
    assert d.index.is_unique
    d=d[d.index.year<=2024]
    m=d.resample("5min",label="right",closed="left").agg(open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),n=("close","size"))
    m.loc[m.n!=5,["open","high","low","close"]]=np.nan
    o,h,l,c=(m[q] for q in ("open","high","low","close"))
    hh=h.rolling(12).max(); ll=l.rolling(12).min(); rg=hh-ll
    atr=(h-l).rolling(12).mean()
    speed=c.diff().abs().rolling(3).mean()/5
    # Most recent completed three-bar FVG, only as-of warning, age <=60m.
    bull_fvg=((l+h.shift(2))/2).where(l>h.shift(2)).ffill(limit=12)
    bear_fvg=((h+l.shift(2))/2).where(h<l.shift(2)).ffill(limit=12)
    valid=(m.index.year==year)&(m.index+pd.Timedelta(minutes=MAX_EXPIRY+CONF_WINDOW+61)<pd.Timestamp(f"{year+1}-01-01",tz="UTC"))&rg.notna()&atr.notna()&speed.notna()
    idx=m.index[valid]; t=d.index.asi8; ts=idx.asi8//base.NS
    pos=np.searchsorted(t,idx.asi8)
    hi=d.high.to_numpy(); lo=d.low.to_numpy(); op=d.open.to_numpy(); cl=d.close.to_numpy()
    now=c.loc[idx].to_numpy(); vol=rg.loc[idx].to_numpy()
    sp=speed.loc[idx].to_numpy()
    # Future observations used only as replay outcomes, never as alert filters.
    # A missing minute invalidates the outcome, not the warning.
    offsets=np.arange(MAX_EXPIRY+CONF_WINDOW+1)
    q=np.minimum(pos[:,None]+offsets,len(t)-1)
    contiguous=t[q]==idx.asi8[:,None]+offsets*base.NS
    complete=np.logical_and.accumulate(contiguous,axis=1)
    hour=idx.tz_convert("Asia/Jakarta").hour
    lon=idx.tz_convert("Europe/London").hour; ny=idx.tz_convert("America/New_York").hour
    sess={"ALL":np.ones(len(idx),bool),"ASIA":(hour>=8)&(hour<13),"LONDON":(lon>=8)&(lon<12),"NY_OPEN":(ny>=8)&(ny<11)}
    results={}
    for side in (1,-1):
        zones={"SWING":ll if side==1 else hh,
               "EQ50":hh-rg*.5 if side==1 else ll+rg*.5,
               "OTE62":hh-rg*.618 if side==1 else ll+rg*.618,
               "FVG":bull_fvg if side==1 else bear_fvg}
        trend=(side*(c-c.shift(6))>0).loc[idx].to_numpy()
        cache={}
        for name,z in zones.items():
            zone=z.loc[idx].to_numpy()
            dist=side*(now-zone)
            eta=dist/np.maximum(sp,.001)
            eligible=np.isfinite(zone)&(dist>=.5)&(eta>=MIN_LEAD+LATENCY)&(eta<=MAX_EXPIRY)
            # A zone is a fixed price determined at the warning, not fitted after touch.
            touch=((lo[q]<=zone[:,None]) if side==1 else (hi[q]>=zone[:,None]))&complete
            touch=touch[:,:MAX_EXPIRY]
            first=np.where(touch.any(axis=1),touch.argmax(axis=1),MAX_EXPIRY)
            for conf in ("REJECT","MSS3"):
                enter=np.full(len(idx),-1,dtype=int)
                for k in range(CONF_WINDOW):
                    off=first+k
                    rows=np.flatnonzero((first<MAX_EXPIRY)&(enter<0)&(off<MAX_EXPIRY+CONF_WINDOW))
                    p0=pos[rows]+off[rows]
                    safe=(p0>=3)&(p0+1<len(t))&complete[rows,np.minimum(off[rows]+1,MAX_EXPIRY+CONF_WINDOW)]
                    rows=rows[safe];p0=p0[safe]
                    reject=(side*(cl[p0]-zone[rows])>0)&(side*(cl[p0]-op[p0])>0)
                    if conf=="MSS3":
                        lim=(hi[p0[:,None]-np.arange(1,4)].max(axis=1) if side==1 else lo[p0[:,None]-np.arange(1,4)].min(axis=1))
                        reject &= (side*(cl[p0]-lim)>0)&(t[p0]-t[p0-3]==3*base.NS)
                    enter[rows[reject]]=off[rows[reject]]+1
                # only eligible rows can become actual outcomes; entry at following open
                ids=np.flatnonzero(eligible&(first>=MIN_LEAD+LATENCY)&(first<MAX_EXPIRY)&(enter>=0))
                entries=idx[ids]+pd.to_timedelta(enter[ids],unit="min")
                unique,inv=np.unique(entries.asi8,return_inverse=True)
                paths=base.eval_paths(d,pd.to_datetime(unique,utc=True))[side]
                cache[name,conf]=(eligible,first,enter,eta,ids,inv,paths)
        stats=[]
        for name,regime,minimum,session,expiry,conf in CONFIGS:
            eligible,first,enter,eta,ids,inv,paths=cache[name,conf]
            warning=np.flatnonzero(eligible&(vol>=minimum)&sess[session]&(eta<=expiry)&(trend if regime=="TREND" else True))
            keep=[];last=-10**15
            for i in warning:
                if ts[i]>=last+expiry+CONF_WINDOW+60:
                    keep.append(i);last=ts[i]
            k=np.asarray(keep,dtype=int)
            early=(first[k]<MIN_LEAD+LATENCY)
            no_touch=(first[k]>=expiry)&complete[k,expiry-1]
            touched=(first[k]>=MIN_LEAD+LATENCY)&(first[k]<expiry)
            no_confirm=touched&(enter[k]<0)&complete[k,np.minimum(first[k]+CONF_WINDOW,MAX_EXPIRY+CONF_WINDOW)]
            cancel=int((early|no_touch|no_confirm).sum())
            sel=k[touched&(enter[k]>=0)]
            ii=np.searchsorted(ids,sel)
            assert np.array_equal(ids[ii],sel)
            a=inv[ii]; good=paths["good"][a]; ix=a[good]; sk=sel[good]
            rec=dict(alerts=len(k),cancel=cancel,censored=len(k)-cancel-len(ix),confirmed=len(ix),
                     early=int(early.sum()),no_touch=int(no_touch.sum()),no_confirm=int(no_confirm.sum()),
                     eta_n=int(touched.sum()),eta_abs_error=float(np.abs(first[k[touched]]-eta[k[touched]]).sum()),
                     lead_sum=float((enter[sk]-LATENCY).sum()))
            for item in base.KEYS[4:]:
                rec[item]=float(paths[item][ix].sum()) if item in ("net10","mae_sum") else int(paths[item][ix].sum())
            stats.append(rec)
        results[str(side)]=stats
    out=dict(year=year,rows_m1=int((d.index.year==year).sum()),months=sorted(set(d.index[d.index.year==year].month.tolist())),decisions=len(idx),source=prov,configs=len(CONFIGS),stats=results)
    path=Path(f"artifacts/r91b-{year}.json");path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(out,allow_nan=False))
    print("R91B_YEAR",year,out["rows_m1"],len(idx),len(CONFIGS),flush=True)

def aggregate():
    root=Path(os.environ["R91_ROOT"])
    data={y:json.loads(next(root.rglob(f"r91b-{y}.json")).read_text()) for y in base.YEARS}
    assert all(d["configs"]==len(CONFIGS) for d in data.values())
    def merge(rows):
        return {k:sum(r[k] for r in rows) for k in KEYS}
    folds=[]
    for y in range(2022,2025):
        for side in ("1","-1"):
            best=None; qualified=0
            for j,c in enumerate(CONFIGS):
                rows=[data[t]["stats"][side][j] for t in range(y-3,y)]
                m=merge(rows)
                if m["confirmed"]<100 or sum(q["confirmed"]>=15 for q in rows)<2 or m["net10"]<=0:continue
                if m["censored"]>m["alerts"]*.1:continue
                qualified+=1
                score=(base.wilson(m["win10"],m["confirmed"]),base.wilson(m["win10"],m["alerts"]),m["confirmed"],-j)
                if best is None or score>best[0]:best=score,j,m
            rec=dict(year=y,side=side,qualified=qualified,status="WAIT")
            if best:
                _,j,m=best
                rec.update(status="DEV",config=CONFIGS[j],inner=m,outer=data[y]["stats"][side][j])
            folds.append(rec)
    totals={s:merge([f["outer"] for f in folds if f["side"]==s and "outer" in f]) for s in ("1","-1")}
    out=dict(contract="R91B_CAUSAL_PROJECTED_ZONE",configs_per_side=len(CONFIGS),annual_evaluations=len(CONFIGS)*2*len(base.YEARS),folds=folds,totals=totals,data=[{k:v for k,v in z.items() if k!="stats"} for z in data.values()],min_received_lead_minutes=MIN_LEAD,latency_assumed_minutes=LATENCY,actual_receipt_verified=False,actual_macro_filter_used=False,untouched_holdout=False,authority_to_trade=False,cost=base.COST,sl=base.SL)
    p=Path("artifacts/r91b-results.json");p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(out,indent=2,allow_nan=False))
    print("R91B_TOTALS",json.dumps(totals),flush=True)

if __name__=="__main__":
    aggregate() if sys.argv[-1]=="aggregate" else run_year()
