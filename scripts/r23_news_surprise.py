"""R23 pilot: archived actual minus consensus for D1/W1.
Public third-party research archive; NOT verified point-in-time consensus.
Only explicitly nonapproximate release dates. Two-day availability buffer.
Never use revised FRED actual as actual surprises. No raw redistribution.
No zones, production or broker actions.
"""
import hashlib,itertools,json
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from r17_macro_pilot import get,treasury_fallback,align
from r18_asymmetric_direction import fomc_fixed,side_metrics
from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r15_direction_tournament import score
O=Path("artifacts");O.mkdir(exist_ok=True)
URL="https://raw.githubusercontent.com/superpilot69/fred-us-macro-open-data/main/data/fred-us-macro-events.json"
GROUPS={"CPIAUCNS":"inflation","CPILFENS":"inflation","PPIACO":"inflation","PCEPI":"inflation","PCEPILFE":"inflation","PAYEMS":"labor","UNRATE":"labor","ICSA":"labor","CES0500000003":"labor","JTSJOL":"labor","RSAFS":"growth","GDPC1":"growth"}
def news():
    raw=get(URL);data=json.loads(raw);events=data["events"]
    rows=[];rejected={}
    for e in events:
        m=e.get("metadata") or {};s=m.get("seriesId")
        if s not in GROUPS:continue
        k=m.get("consensus") or {}
        try:
            assert m.get("releaseDateApproximate") is False
            assert k.get("sourceId")=="investing-economic-calendar"
            assert k.get("sourceUrl")
            a=float(k["actual"]);b=float(k["forecast"])
            assert np.isfinite(a) and np.isfinite(b)
            t=pd.Timestamp(e["createdAt"])
            assert t.tzinfo is not None
            t=t.tz_convert("UTC")
            assert pd.Timestamp(m["releaseDate"]).date()==t.date()
            assert pd.Timestamp(m["observationDate"]).date()<=t.date()
            assert pd.Timestamp("2008-01-01",tz="UTC")<=t<=pd.Timestamp("2026-04-26",tz="UTC")
            # Do not use metadata.value: may be revised FRED historical value.
            rows.append({"series":s,"group":GROUPS[s],"time":t,"obs":str(m["observationDate"]),"surprise":a-b})
        except (AssertionError,ValueError,KeyError,TypeError):
            rejected[s]=rejected.get(s,0)+1
    a=pd.DataFrame(rows)
    assert len(a)>=500,("insufficient exact-date consensus archive",len(a),rejected)
    a=a.sort_values("time")
    # Ambiguous duplicate release/series discarded rather than select retrospectively.
    a=a[~a.duplicated(["series","time","obs"],keep=False)]
    a=a[~a.duplicated(["series","time"],keep=False)].copy()
    counts=a.groupby("series").size().to_dict()
    assert counts.get("PAYEMS",0)>=80 and counts.get("CPIAUCNS",0)>=60,counts
    # Prior releases only; normalize per event type, with clipping after scaling.
    a["scale"]=a.groupby("series")["surprise"].transform(lambda v:v.shift(1).rolling(36,min_periods=12).std())
    a["z"]=(a.surprise/a.scale.replace(0,np.nan)).clip(-5,5)
    a=a.dropna(subset=["z"])
    a["hawk"]=a.z*np.where(a.series.isin(["UNRATE","ICSA"]),-1,1)
    # Conservative next two UTC calendar days; excludes event-spike prediction.
    a["available"]=a.time.dt.floor("D")+pd.Timedelta(days=3)
    idx=pd.date_range(a.available.min(),a.available.max(),freq="D")
    f=pd.DataFrame(index=idx)
    for group in ["inflation","labor","growth"]:
        q=a[a.group==group].groupby("available").hawk.mean().reindex(idx,fill_value=0)
        for d in [1,3,5,10,20,40]:
            f[f"{group}_decay{d}"]=q.ewm(halflife=d,adjust=False).mean()
    for d in [1,3,5,10,20,40]:
        f[f"total_decay{d}"]=f[[f"{g}_decay{d}" for g in ["inflation","labor","growth"]]].mean(axis=1)
    meta={"url":URL,"sha256":hashlib.sha256(raw).hexdigest(),"raw_rows":len(events),"qualified_rows":len(a),"series_counts":counts,"rejected":rejected,"first":str(a.time.min()),"last":str(a.time.max()),"available_through":str(idx.max()),"limitations":["retrospective third-party archive, consensus snapshot/first-print not independently verified","release time standard assumed by archive, use later UTC date only","no missing forecasts imputed, missing release coverage still possible","data ends April 2026; no extrapolation"]}
    O.joinpath("r23-news-manifest.json").write_text(json.dumps(meta,indent=2))
    print(json.dumps({"news":meta}),flush=True)
    return f,meta
def run(tf,nf,parts):
    d,z,_,y,valid,times=load_tf(tf)
    p=features(z);p=p.drop(columns=[c for c in p if c.startswith("hour_")])
    macro=align(parts,times,d.index);n=align([nf],times,d.index)
    valid &= (times>=nf.index.min())&(times<=nf.index.max())
    valid &= p.notna().all(axis=1).to_numpy() & macro.notna().all(axis=1).to_numpy() & n.notna().all(axis=1).to_numpy()
    groups={"technical":p,"macro":macro,"news":n,"technical_macro":pd.concat([p,macro],axis=1),"full":pd.concat([p,macro,n],axis=1)}
    mature=pd.Series(times,index=d.index).shift(-1)
    nmin=25 if tf=="1D" else 8
    acc={k:[] for k in groups};annual={k:[] for k in groups};fits=rules=0
    for yr in range(2018,2027):
        b=pd.Timestamp(f"{yr}-01-01",tz="UTC");vs=b-pd.DateOffset(years=1);end=b+pd.DateOffset(years=1)
        va=valid&(times>=vs)&(times<b)&(mature<b).to_numpy()
        te=valid&(times>=b)&(times<end)&(mature<end).to_numpy()
        if min(va.sum(),te.sum())<2*nmin:continue
        for key,g in groups.items():
            x=g.to_numpy(float);chosen=[None,None]
            for years,C in itertools.product([3,6,10],[.01,.1,1]):
                tr=valid&(times>=vs-pd.DateOffset(years=years))&(mature<vs).to_numpy()
                if tr.sum()<(150 if tf=="1D" else 60) or len(np.unique(y[tr]))<2:continue
                model=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
                model.fit(x[tr],y[tr]);fits+=1
                pv=model.predict_proba(x[va])[:,1];pt=model.predict_proba(x[te])[:,1]
                for th in [.5,.52,.55,.58,.6,.65,.7]:
                    for side in (0,1):
                        rules+=1
                        v=pv>=th if side else (pv<.5 if th==.5 else pv<=1-th)
                        t=pt>=th if side else (pt<.5 if th==.5 else pt<=1-th)
                        m=side_metrics(y[va],v,side)
                        if m["n"]<nmin:continue
                        rank=(m["lower95"],m["n"])
                        if chosen[side] is None or rank>chosen[side][0]:
                            chosen[side]=(rank,t,{"years":years,"C":C,"cut":th,"validation":m})
            buy=chosen[1][1] if chosen[1] else np.zeros(te.sum(),bool)
            sell=chosen[0][1] if chosen[0] else np.zeros(te.sum(),bool)
            B=buy&~sell;S=sell&~buy
            acc[key].append((y[te],B,S))
            annual[key].append({"year":yr,"conflicts":int((buy&sell).sum()),"buy_rule":chosen[1][2] if chosen[1] else None,"sell_rule":chosen[0][2] if chosen[0] else None,"metrics":score(y[te],B,S,np.ones(te.sum(),bool))})
    out={}
    for k,ls in acc.items():
        assert ls,(tf,k)
        Y,B,S=[np.concatenate([r[i] for r in ls]) for i in range(3)]
        out[k]=score(Y,B,S,np.ones(len(Y),bool))
    r={"tf":tf,"matched_n":len(Y),"base_buy":float(Y.mean()),"fits":fits,"rules":rules,"aggregate":out,"annual":annual,"limitations":["Exploratory third-party source retrospective coverage; not exact point-in-time or forward validation","No news after archive cutoff","R20 W1 preserved, no COT in R23 matched ablation","Actual minus consensus only; no pre-release prediction"]}
    O.joinpath(f"r23-news-{tf}.json").write_text(json.dumps(r,indent=2))
    print(json.dumps({k:v for k,v in r.items() if k!="annual"}),flush=True)
if __name__=="__main__":
    nf,nm=news()
    parts,tm=treasury_fallback();assert len(parts)>=2
    fp,fm=fomc_fixed();parts.append(fp)
    O.joinpath("r23-all-manifest.json").write_text(json.dumps({"news":nm,"treasury":tm,"fomc":fm},indent=2))
    for tf in ["1D","1W"]:run(tf,nf,parts)
