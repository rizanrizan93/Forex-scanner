"""R9.4: hard D1 permission, causal daily features and matched ungated diagnostic.
Development only; not a live signal or a prospective notification receipt.
"""
from itertools import product
from pathlib import Path
import hashlib,json,os,sys
import numpy as np
import pandas as pd
import r91_early_warning as base

# Zone, regime, minimum trailing range, session, expiry minutes, confirmation.
CONFIGS=list(product(("SWING","H4_OTE","H4_EQ","FVG"),("ANY","PULLBACK"),(0.,10.,20.),base.SESSIONS,(15,30,45),("MSS3","SWEEP_DISP","SWEEP_MSS"),(10.,),(0.,10.),("TOWARD",),("D1_EMA","D1_RIDGE")))
MIN_LEAD=5
LATENCY=1
CONF_WINDOW=10
MAX_EXPIRY=45
EXTRA=("early","no_touch","no_confirm","eta_n","eta_abs_error","lead_sum","invalidated","room_cancel","dir60","mfe10")
KEYS=base.KEYS+EXTRA

def daily_permissions(d, decision_index):
    # Daily candles strictly prior to decision UTC day; no partial day is used.
    # Reject short/weekend source sessions for this independent proxy.
    dd=d.resample("1D",label="left",closed="left").agg(open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),n=("close","size"))
    dd=dd[(dd.n>=900)&(dd.index.dayofweek<5)].copy()
    close=dd.close
    f=pd.DataFrame({"range5":100*((dd.high-dd.low)/close).rolling(5).mean(),
                    "mom5":100*(close/close.shift(5)-1),
                    "mom21":100*(close/close.shift(21)-1),
                    "rv21":100*close.pct_change().rolling(21).std()}).to_numpy()
    e=close.ewm(span=20,adjust=False,min_periods=30).mean()
    ema=np.where((close>e)&(e>e.shift(5)),1,np.where((close<e)&(e<e.shift(5)),-1,0))
    # R7.2-style feature/penalty proxy; NOT the frozen R7.2 model.
    # Each fit uses feature rows strictly earlier than the decision feature.
    # The latest allowed target ends on the last fully closed day.
    y=np.log(dd.close.to_numpy()/dd.open.to_numpy())
    pred=np.full(len(dd),np.nan)
    for j in range(1,len(dd)):
        x=f[:j]; target=y[1:j+1]
        ok=np.isfinite(x).all(axis=1)&np.isfinite(target)
        if ok.sum()<75 or not np.isfinite(f[j]).all():continue
        x=x[ok]; target=target[ok]
        mu=x.mean(axis=0); sd=x.std(axis=0); sd=np.where(sd>1e-12,sd,1.)
        z=np.clip((x-mu)/sd,-4.,4.)
        ym=target.mean()
        beta=np.linalg.solve(z.T@z+500*np.eye(z.shape[1]),z.T@(target-ym))
        pred[j]=ym+np.clip((f[j]-mu)/sd,-4.,4.)@beta
    # Session date, never relying on knowing whether current day will be complete.
    j=dd.index.searchsorted(decision_index.floor("D"),side="left")-1
    jj=np.maximum(j,0)
    age=(decision_index.floor("D").asi8-dd.index.asi8[jj])/86_400_000_000_000
    fresh=(j>=0)&(age<=4)&(decision_index.dayofweek<5)
    em=np.where(fresh,ema[jj],0)
    ri=np.where(fresh&np.isfinite(pred[jj]),np.sign(np.nan_to_num(pred[jj])),0)
    return {"D1_EMA":em,"D1_RIDGE":ri,"MATCH_EMA":em,"MATCH_RIDGE":ri}

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
    # A known opposing 4h swing is a reference pool, not guaranteed unobstructed room.
    h4=h.rolling(48).max(); l4=l.rolling(48).min()
    # Historical range capacity by NY clock hour of an observed, fully completed hour.
    # At M5 decision t this includes only hourly bars whose right edge <= t.
    hourbars=d.resample("1h",label="right",closed="left").agg(high=("high","max"),low=("low","min"),n=("close","size"))
    hourbars["range"]=(hourbars.high-hourbars.low).where(hourbars.n==60)
    # Match upcoming local start hour to completed bars with the same start-hour.
    # DST-aware; hourly observations unavailable until the right edge.
    local_start=(hourbars.index-pd.Timedelta(hours=1)).tz_convert("America/New_York").hour
    cap=np.full(len(m),np.nan)
    mh=m.index.tz_convert("America/New_York").hour
    for hour in range(24):
        history=hourbars.loc[(local_start==hour)&hourbars["range"].notna(),"range"]
        quant=history.rolling(30,min_periods=12).quantile(.75)
        cap[mh==hour]=quant.reindex(m.index[mh==hour],method="ffill").to_numpy()
    capacity=pd.Series(cap,index=m.index)
    # Most recent completed three-bar FVG, only as-of warning, age <=60m.
    bull_fvg=((l+h.shift(2))/2).where(l>h.shift(2)).ffill(limit=12)
    bear_fvg=((h+l.shift(2))/2).where(h<l.shift(2)).ffill(limit=12)
    valid=(m.index.year==year)&(m.index+pd.Timedelta(minutes=MAX_EXPIRY+CONF_WINDOW+61)<pd.Timestamp(f"{year+1}-01-01",tz="UTC"))&rg.notna()&atr.notna()&speed.notna()
    idx=m.index[valid]; t=d.index.asi8; ts=idx.asi8//base.NS
    daily=daily_permissions(d,idx)
    pos=np.searchsorted(t,idx.asi8)
    hi=d.high.to_numpy(); lo=d.low.to_numpy(); op=d.open.to_numpy(); cl=d.close.to_numpy()
    now=c.loc[idx].to_numpy(); vol=rg.loc[idx].to_numpy()
    sp=speed.loc[idx].to_numpy()
    cap=capacity.loc[idx].to_numpy()
    recent_move=(c-c.shift(3)).loc[idx].to_numpy()
    midtrend=(c-c.shift(48)).loc[idx].to_numpy()
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
               "H4_EQ":(h4+l4)*.5,
               "H4_OTE":h4-(h4-l4)*.618 if side==1 else l4+(h4-l4)*.618,
               "FVG":bull_fvg if side==1 else bear_fvg}
        trend=(side*(c-c.shift(6))>0).loc[idx].to_numpy()
        regimes={"ANY":np.ones(len(idx),bool),"TREND":trend,"PULLBACK":(side*midtrend>0)&(side*recent_move<0)}
        anchor=(h4 if side==1 else l4).loc[idx].to_numpy()
        buffer=np.maximum(1.,1.5*atr.loc[idx].to_numpy())
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
            # Price invalidation frozen at alert; conservative intrabar priority.
            invalid=((lo[q]<= (zone-buffer)[:,None]) if side==1 else (hi[q]>=(zone+buffer)[:,None]))&complete
            invalid_first=np.where(invalid.any(axis=1),invalid.argmax(axis=1),MAX_EXPIRY+CONF_WINDOW+1)
            room=side*(anchor-zone)
            for conf in ("MSS3","SWEEP_DISP","SWEEP_MSS"):
                enter=np.full(len(idx),-1,dtype=int)
                for k in range(CONF_WINDOW):
                    off=first+k
                    rows=np.flatnonzero((first<MAX_EXPIRY)&(enter<0)&(off<MAX_EXPIRY+CONF_WINDOW))
                    p0=pos[rows]+off[rows]
                    safe=(p0>=3)&(p0+1<len(t))&complete[rows,np.minimum(off[rows]+1,MAX_EXPIRY+CONF_WINDOW)]
                    rows=rows[safe];p0=p0[safe]
                    reject=(side*(cl[p0]-zone[rows])>0)&(side*(cl[p0]-op[p0])>0)&(invalid_first[rows]>off[rows])
                    if conf=="MSS3":
                        lim=(hi[p0[:,None]-np.arange(1,4)].max(axis=1) if side==1 else lo[p0[:,None]-np.arange(1,4)].min(axis=1))
                        reject &= (side*(cl[p0]-lim)>0)&(t[p0]-t[p0-3]==3*base.NS)
                    if conf.startswith("SWEEP"):
                        swept=(lo[p0]<zone[rows] if side==1 else hi[p0]>zone[rows])
                        # Require sweep at or since first touch, followed by directional close.
                        touchpos=pos[rows]+first[rows]
                        swept |= (lo[touchpos]<zone[rows] if side==1 else hi[touchpos]>zone[rows])
                        reject &= swept & (side*(cl[p0]-op[p0])>=np.maximum(.3,buffer[rows]*.25))
                        if conf=="SWEEP_MSS":
                            lim=(hi[p0[:,None]-np.arange(1,4)].max(axis=1) if side==1 else lo[p0[:,None]-np.arange(1,4)].min(axis=1))
                            reject &= (side*(cl[p0]-lim)>0)&(t[p0]-t[p0-3]==3*base.NS)
                    if conf=="M5_REJECT":
                        # Last minute of completed M5, with five contiguous minutes.
                        reject=(p0>=4)&((t[p0]//base.NS+1)%5==0)&(t[p0]-t[np.maximum(p0-4,0)]==4*base.NS)&(side*(cl[p0]-op[np.maximum(p0-4,0)])>0)&(side*(cl[p0]-zone[rows])>0)&(invalid_first[rows]>off[rows])
                    enter[rows[reject]]=off[rows[reject]]+1
                # only eligible rows can become actual outcomes; entry at following open
                ids=np.flatnonzero(eligible&(first>=MIN_LEAD+LATENCY)&(first<MAX_EXPIRY)&(enter>=0))
                entries=idx[ids]+pd.to_timedelta(enter[ids],unit="min")
                unique,inv=np.unique(entries.asi8,return_inverse=True)
                paths=base.eval_paths(d,pd.to_datetime(unique,utc=True))[side]
                # Confirmation-close headroom is available before next-minute order.
                confirmation_room=np.full(len(idx),-np.inf)
                confirmation_room[ids]=side*(anchor[ids]-cl[pos[ids]+enter[ids]-1])
                u=pd.to_datetime(unique,utc=True)
                jp=np.searchsorted(t,u.asi8)
                tail=np.minimum(jp+59,len(t)-1)
                jj=np.minimum(jp,len(t)-1)
                paths["dir60"]=(side*(cl[tail]-op[jj])>base.COST)&paths["good"]
                paths["mfe10"]=np.zeros(len(jp),dtype=bool)
                for k0 in range(0,len(jp),5000):
                    ks=np.arange(k0,min(k0+5000,len(jp)))
                    qq=np.minimum(jp[ks,None]+np.arange(60),len(t)-1)
                    favorable=(hi[qq]-op[jj[ks],None] if side==1 else op[jj[ks],None]-lo[qq])
                    paths["mfe10"][ks]=(favorable.max(axis=1)>=10.+base.COST)&paths["good"][ks]
                cache[name,conf]=(eligible,first,enter,eta,ids,inv,paths,invalid_first,room,confirmation_room)
        stats=[]
        for name,regime,minimum,session,expiry,conf,minroom,mincap,approach,gate in CONFIGS:
            eligible,first,enter,eta,ids,inv,paths,invalid_first,room,confirmation_room=cache[name,conf]
            # Directional speed is an independent pre-alert filter, not a future touch filter.
            toward=(side*recent_move<0)
            cap_ok=np.ones(len(idx),bool) if mincap==0 else (cap>=mincap)
            allowed=(daily[gate]==side) if gate.startswith("D1_") else (daily[gate]!=0)
            warning=np.flatnonzero(allowed&eligible&(vol>=minimum)&sess[session]&(eta<=expiry)&(room>=minroom)&regimes[regime]&cap_ok&(toward if approach=="TOWARD" else True))
            keep=[];last=-10**15
            for i in warning:
                if ts[i]>=last+expiry+CONF_WINDOW+60:
                    keep.append(i);last=ts[i]
            k=np.asarray(keep,dtype=int)
            early=(first[k]<MIN_LEAD+LATENCY)
            no_touch=(first[k]>=expiry)&complete[k,expiry-1]
            touched=(first[k]>=MIN_LEAD+LATENCY)&(first[k]<expiry)
            no_confirm=touched&(enter[k]<0)&complete[k,np.minimum(first[k]+CONF_WINDOW,MAX_EXPIRY+CONF_WINDOW)]
            invalidated=touched&(enter[k]<0)&(invalid_first[k]<first[k]+CONF_WINDOW)
            room_cancel=touched&(enter[k]>=0)&(confirmation_room[k]<minroom)
            cancel=int((early|no_touch|no_confirm|invalidated|room_cancel).sum())
            sel=k[touched&(enter[k]>=0)&(confirmation_room[k]>=minroom)]
            ii=np.searchsorted(ids,sel)
            assert np.array_equal(ids[ii],sel)
            a=inv[ii]; good=paths["good"][a]; ix=a[good]; sk=sel[good]
            rec=dict(alerts=len(k),cancel=cancel,censored=len(k)-cancel-len(ix),confirmed=len(ix),
                     early=int(early.sum()),no_touch=int(no_touch.sum()),no_confirm=int(no_confirm.sum()),
                     eta_n=int(touched.sum()),eta_abs_error=float(np.abs(first[k[touched]]-eta[k[touched]]).sum()),
                     lead_sum=float((enter[sk]-LATENCY).sum()),invalidated=int(invalidated.sum()),room_cancel=int(room_cancel.sum()),dir60=int(paths["dir60"][ix].sum()),mfe10=int(paths["mfe10"][ix].sum()))
            for item in base.KEYS[4:]:
                rec[item]=float(paths[item][ix].sum()) if item in ("net10","mae_sum") else int(paths[item][ix].sum())
            stats.append(rec)
        results[str(side)]=stats
    out=dict(year=year,rows_m1=int((d.index.year==year).sum()),months=sorted(set(d.index[d.index.year==year].month.tolist())),decisions=len(idx),source=prov,configs=len(CONFIGS),stats=results)
    path=Path(f"artifacts/r95-{year}.json");path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(out,allow_nan=False))
    print("R95_YEAR",year,out["rows_m1"],len(idx),len(CONFIGS),flush=True)

def aggregate():
    root=Path(os.environ["R91_ROOT"])
    data={y:json.loads(next(root.rglob(f"r95-{y}.json")).read_text()) for y in base.YEARS}
    assert all(d["configs"]==len(CONFIGS) for d in data.values())
    def merge(rows):
        return {k:sum(r[k] for r in rows) for k in KEYS}
    folds=[]
    for y in range(2022,2025):
        for side in ("1","-1"):
            best=None; qualified=0
            for j,c in enumerate(CONFIGS):
                if not c[-1].startswith("D1_"):continue
                rows=[data[t]["stats"][side][j] for t in range(y-3,y)]
                m=merge(rows)
                if m["confirmed"]<100 or sum(q["confirmed"]>=15 for q in rows)<2 or m["net10"]<=0:continue
                if m["censored"]>m["alerts"]*.1:continue
                qualified+=1
                score=(min(base.wilson(m["dir60"],m["confirmed"]),base.wilson(m["win10"],m["confirmed"])),base.wilson(m["dir60"],m["confirmed"]),base.wilson(m["win10"],m["alerts"]),m["confirmed"],-j)
                if best is None or score>best[0]:best=score,j,m
            rec=dict(year=y,side=side,qualified=qualified,status="WAIT")
            if best:
                _,j,m=best
                c=CONFIGS[j]
                rec.update(status="DEV",config=c,inner=m,outer=data[y]["stats"][side][j])
            folds.append(rec)
    totals={s:merge([f["outer"] for f in folds if f["side"]==s and "outer" in f]) for s in ("1","-1")}
    matched={s:merge([f["matched_ungated"] for f in folds if f["side"]==s and "matched_ungated" in f]) for s in ("1","-1")}
    out=dict(matched_ungated_totals=matched,contract="R95_D1_SWEEP_DISPLACEMENT",configs_per_side=len(CONFIGS),annual_evaluations=len(CONFIGS)*2*len(base.YEARS),folds=folds,totals=totals,data=[{k:v for k,v in z.items() if k!="stats"} for z in data.values()],min_received_lead_minutes=MIN_LEAD,latency_assumed_minutes=LATENCY,actual_receipt_verified=False,actual_macro_filter_used=False,actual_r73_filter_used=False,actual_r72_frozen_filter_used=False,daily_gate="strict prior UTC closed day EMA20 structural or expanding within-year price-only ridge proxy; neutral WAIT; no opposite entries; matched ungated diagnostics",capacity_model="75th percentile last 30 completed NY same-clock-hour ranges, minimum 12",selection="joint Wilson lower bounds direction and TP10",structural_room_reference="prior_completed_4h_extreme",invalidation="zone +/- max(1, 1.5*M5_ATR)",eta_model="distance / recent absolute speed heuristic",untouched_holdout=False,authority_to_trade=False,cost=base.COST,sl=base.SL)
    p=Path("artifacts/r95-results.json");p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(out,indent=2,allow_nan=False))
    print("R95_TOTALS",json.dumps(totals),flush=True)
    print("R95_FOLDS",json.dumps(folds),flush=True)

if __name__=="__main__":
    aggregate() if sys.argv[-1]=="aggregate" else run_year()
