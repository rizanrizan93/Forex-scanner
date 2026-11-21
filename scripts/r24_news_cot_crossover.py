"""R24 W1/D1 side-specialist crossover on COMMON samples.
R23 news-only BUY and R20-style COT hybrid SELL are predeclared hypotheses,
not pooled historical headline accuracies. Preserve R20 as archival benchmark.
Latest-vintage sources, delayed-availability proxies, historical reuse.
No orders, zones, production changes or forward-validation claims.
"""
import json,itertools
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r17_macro_pilot import treasury_fallback,align
from r18_asymmetric_direction import fomc_fixed,side_metrics
from r20_cot_direction import cot
from r23_news_surprise import news
from r15_direction_tournament import score
O=Path("artifacts");O.mkdir(exist_ok=True)
LANES=["technical","news","cot_hybrid","news_cot","full"]
POLICIES={
 "technical":("technical","technical"),
 "news":("news","news"),
 "cot_hybrid":("cot_hybrid","cot_hybrid"),
 "news_cot":("news_cot","news_cot"),
 "full":("full","full"),
 "crossover_news_buy_cot_sell":("news","cot_hybrid"),
 "crossover_cot_buy_news_sell":("cot_hybrid","news"),
}
def evaluate(y,b,s):
    return {"raw_BUY":side_metrics(y,b,1),"raw_SELL":side_metrics(y,s,0),
        "conflicts":int((b&s).sum()),"resolved":score(y,b&~s,s&~b,np.ones(len(y),bool))}
def run(tf,nf,mf,cp):
    d,z,_,y,valid,times=load_tf(tf)
    px=features(z);px=px.drop(columns=[c for c in px if c.startswith("hour_")])
    macro=align(mf,times,d.index);n=align([nf],times,d.index);pos=align([cp],times,d.index)
    cot_time=pd.DatetimeIndex(pd.Series(cp.index,index=cp.index).reindex(times,method="ffill"))
    age=times-cot_time
    valid &= (times>=nf.index.min())&(times<=nf.index.max())&(age>=pd.Timedelta(0))&(age<=pd.Timedelta(days=21))
    valid &= px.notna().all(axis=1).to_numpy()&macro.notna().all(axis=1).to_numpy()&n.notna().all(axis=1).to_numpy()&pos.notna().all(axis=1).to_numpy()
    groups={"technical":px,"news":n,"cot_hybrid":pd.concat([px,macro,pos],axis=1),
        "news_cot":pd.concat([n,pos],axis=1),"full":pd.concat([px,macro,n,pos],axis=1)}
    assert set(groups)==set(LANES)
    mat={k:v.to_numpy(float) for k,v in groups.items()}
    mature=pd.Series(times,index=d.index).shift(-1)
    nmin=25 if tf=="1D" else 10
    fits=rules=0
    totals={k:[] for k in POLICIES};annual=[]
    # No evaluation-year labels in model selection. Candidate heads selected
    # only on preceding year. Entire policies chosen as research hypotheses
    # after viewing earlier R20/R23 aggregate results, so retrospective only.
    for yr in range(2018,2027):
        start=pd.Timestamp(f"{yr}-01-01",tz="UTC")
        vs=start-pd.DateOffset(years=1);end=start+pd.DateOffset(years=1)
        va=valid&(times>=vs)&(times<start)&(mature<start).to_numpy()
        te=valid&(times>=start)&(times<end)&(mature<end).to_numpy()
        if min(va.sum(),te.sum())<2*nmin:continue
        chosen={}
        for name,x in mat.items():
            best=[None,None]
            for years,C in itertools.product([3,6,10],[.01,.1,1]):
                tr=valid&(times>=vs-pd.DateOffset(years=years))&(mature<vs).to_numpy()
                if tr.sum()<(150 if tf=="1D" else 60) or len(np.unique(y[tr]))<2:continue
                model=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
                model.fit(x[tr],y[tr]);fits+=1
                pv=model.predict_proba(x[va])[:,1];pt=model.predict_proba(x[te])[:,1]
                for th in [.5,.52,.55,.58,.60,.65,.70]:
                    for side in (0,1):
                        rules+=1
                        v=pv>=th if side else (pv<.5 if th==.5 else pv<=1-th)
                        t=pt>=th if side else (pt<.5 if th==.5 else pt<=1-th)
                        m=side_metrics(y[va],v,side)
                        if m["n"]<nmin:continue
                        r=(m["lower95"],m["n"])
                        if best[side] is None or r>best[side][0]:
                            best[side]=(r,t,{"years":years,"C":C,"threshold":th,"validation":m})
            chosen[name]=best
        yy=y[te];row={"year":yr,"n":len(yy),"baseline_buy":float(yy.mean()),"policies":{}}
        for policy,(bk,sk) in POLICIES.items():
            qb=chosen[bk][1];qs=chosen[sk][0]
            b=qb[1] if qb is not None else np.zeros(te.sum(),bool)
            s=qs[1] if qs is not None else np.zeros(te.sum(),bool)
            totals[policy].append((yy,b,s))
            row["policies"][policy]={"buy_source":bk,"sell_source":sk,
                "buy_config":qb[2] if qb else None,"sell_config":qs[2] if qs else None,
                **evaluate(yy,b,s)}
        annual.append(row)
    aggregate={}
    for name,ls in totals.items():
        assert ls,(tf,name,"no folds")
        Y,B,S=[np.concatenate([a[i] for a in ls]) for i in range(3)]
        aggregate[name]=evaluate(Y,B,S)
    r={"tf":tf,"matched_n":len(Y),"baseline_buy":float(Y.mean()),"fits":fits,"rule_evals":rules,"aggregate":aggregate,"annual":annual,
       "limitations":["Calendar archive ends April 2026; all compared policies use identical restricted sample","R20-style hybrid retrained on matched sample, not original frozen model reproduction","All historical folds reused, not pristine or forward validation","Policies selected after inspecting prior R20 and R23 results; multiple-comparison risk","News actual/consensus third-party retrospective; FOMC/Treasury/COT lag proxies not proven exact historical availability","No DXY or entry zone or net profit claims"]}
    O.joinpath(f"r24-crossover-{tf}.json").write_text(json.dumps(r,indent=2))
    print(json.dumps({k:v for k,v in r.items() if k!="annual"}),flush=True)
if __name__=="__main__":
    nf,nm=news()
    mf,tm=treasury_fallback();assert len(mf)>=2
    fp,fm=fomc_fixed();mf.append(fp)
    cp,cm=cot()
    O.joinpath("r24-source-manifest.json").write_text(json.dumps({"news":nm,"treasury":tm,"fomc":fm,"cot":cm},indent=2))
    for tf in ["1D","1W"]:run(tf,nf,mf,cp)
