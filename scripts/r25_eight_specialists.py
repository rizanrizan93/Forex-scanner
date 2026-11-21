"""R25 eight side-specialists: independent feature/model/threshold/regime
selection on historical validation only. Fixed policy comparisons, conflicts WAIT.
Research-only; R20/R24 benchmarks unchanged. No zone development or broker actions.
"""
import argparse,itertools,json
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r21_horizon_specialists import price_specialist
from r17_macro_pilot import treasury_fallback,align
from r18_asymmetric_direction import fomc_fixed,side_metrics
from r20_cot_direction import cot
from r23_news_surprise import news
from r15_direction_tournament import score
O=Path("artifacts");O.mkdir(exist_ok=True)
def gates(d,z,times,tf):
    atr=z.atr14.replace(0,np.nan)
    ema=((z.ema8-z.ema21)/atr).to_numpy(float)
    rank=z.atr_rank.to_numpy(float)
    r={"all":np.ones(len(d),bool),
       "trend_up":ema>0,"trend_down":ema<0,
       "vol_high":rank>=.6,"vol_low":rank<=.4,
       "trend_up_highvol":(ema>0)&(rank>=.6),
       "trend_down_highvol":(ema<0)&(rank>=.6)}
    if tf in ("1h","4h"):
        lon=times.tz_convert("Europe/London").hour
        ny=times.tz_convert("America/New_York").hour
        tok=times.tz_convert("Asia/Tokyo").hour
        r.update({"london":(lon>=8)&(lon<16),"ny":(ny>=8)&(ny<16),"asia":(tok>=9)&(tok<15),
                  "london_open":(lon>=8)&(lon<11),"ny_open":(ny>=8)&(ny<11)})
    return r
def macro_sources():
    nf,nm=news();mf,tm=treasury_fallback();assert len(mf)>=2
    fp,fm=fomc_fixed();mf.append(fp);cp,cm=cot()
    O.joinpath("r25-source-manifest.json").write_text(json.dumps({"news":nm,"treasury":tm,"fomc":fm,"cot":cm},indent=2))
    return nf,mf,cp
def setup(tf,d,z,times,sources):
    base=gates(d,z,times,tf);extra=np.ones(len(d),bool)
    if tf in ("1h","4h"):
        f,sets=price_specialist(d,z,tf)
        groups={k:f[c] for k,c in sets.items()}
        groups["generic_price"]=features(z)
    else:
        nf,mf,cp=sources
        p=features(z);p=p.drop(columns=[c for c in p if c.startswith("hour_")])
        m=align(mf,times,d.index);n=align([nf],times,d.index);pos=align([cp],times,d.index)
        last=pd.DatetimeIndex(pd.Series(cp.index,index=cp.index).reindex(times,method="ffill"))
        age=times-last
        extra &= (times>=nf.index.min())&(times<=nf.index.max())&(age>=pd.Timedelta(0))&(age<=pd.Timedelta(days=21))
        groups={"technical":p,"technical_macro":pd.concat([p,m],axis=1),
                "news":n,"cot":pos,"macro":m,"cot_hybrid":pd.concat([p,m,pos],axis=1),
                "news_cot":pd.concat([n,pos],axis=1),"full":pd.concat([p,m,n,pos],axis=1)}
        base["news_hawkish"]=n.total_decay10.to_numpy()>0
        base["news_dovish"]=n.total_decay10.to_numpy()<0
        base["yields_up"]=m.DGS2_5.to_numpy()>0
        base["yields_down"]=m.DGS2_5.to_numpy()<0
        base["net_pos_increasing"]=pos.cot_change4.to_numpy()>0
        base["net_pos_decreasing"]=pos.cot_change4.to_numpy()<0
    return groups,base,extra
def summary(y,b,s):
    return {"raw_BUY":side_metrics(y,b,1),"raw_SELL":side_metrics(y,s,0),
      "conflicts":int((b&s).sum()),"resolved":score(y,b&~s,s&~b,np.ones(len(y),bool))}
def run(tf,sources=None):
    d,z,_,y,valid,times=load_tf(tf)
    groups,gate,extra=setup(tf,d,z,times,sources)
    valid &= extra
    mat={}
    for k,f in groups.items():
        a=f.to_numpy(float);mat[k]=a
        valid &= np.isfinite(a).all(axis=1)
    mature=pd.Series(times,index=d.index).shift(-1)
    # A two-year validation, minimum count per side and minimum coverage.
    # A fixed validation gate selected before evaluation, never optimized on test.
    minval={"1h":140,"4h":70,"1D":40,"1W":16}[tf]
    mintrain={"1h":500,"4h":250,"1D":120,"1W":55}[tf]
    cuts=[.5,.52,.55,.58,.60,.65,.7,.75,.8]
    variants=["ungated","regime_specialist"]
    totals={k:[] for k in variants};annual=[];fits=rules=0
    for year in (range(2023,2027) if tf in ("1h","4h") else range(2019,2027)):
        start=pd.Timestamp(f"{year}-01-01",tz="UTC");vs=start-pd.DateOffset(years=2);end=start+pd.DateOffset(years=1)
        va=valid&(times>=vs)&(times<start)&(mature<start).to_numpy()
        te=valid&(times>=start)&(times<end)&(mature<end).to_numpy()
        if min(va.sum(),te.sum())<2*minval:continue
        best={v:[None,None] for v in variants}
        for group,x in mat.items():
            for years,family in itertools.product([2,4,8],["ridge_logit","logit","hgb"]):
                tr=valid&(times>=vs-pd.DateOffset(years=years))&(mature<vs).to_numpy()
                if tr.sum()<mintrain or len(np.unique(y[tr]))<2:continue
                for side in (0,1):
                    # Separately fit the side event (1 = this side is correct).
                    target=(y==side).astype(int)
                    model=(HistGradientBoostingClassifier(max_iter=60,max_depth=2,max_leaf_nodes=5,l2_regularization=15,random_state=25)
                      if family=="hgb" else make_pipeline(StandardScaler(),LogisticRegression(C=.025 if family=="ridge_logit" else .3,max_iter=500)))
                    model.fit(x[tr],target[tr]);fits+=1
                    pv=model.predict_proba(x[va])[:,1];pt=model.predict_proba(x[te])[:,1]
                    for th in cuts:
                        for gname,G in gate.items():
                            rules+=1
                            v=(pv>=th)&G[va];t=(pt>=th)&G[te]
                            m=side_metrics(y[va],v,side)
                            if m["n"]<max(minval,int(.025*va.sum())):continue
                            # Conservative selection, not max raw percentage.
                            rank=(m["lower95"],m["n"])
                            config={"group":group,"years":years,"model":family,"threshold":th,"gate":gname,"validation":m}
                            for variant in (["ungated","regime_specialist"] if gname=="all" else ["regime_specialist"]):
                                cur=best[variant][side]
                                if cur is None or rank>cur[0]:
                                    best[variant][side]=(rank,t,config)
        yy=y[te];row={"year":year,"n":len(yy),"baseline_buy":float(yy.mean()),"policies":{}}
        for v in variants:
            B,S=best[v][1],best[v][0]
            b=B[1] if B is not None else np.zeros(len(yy),bool)
            s=S[1] if S is not None else np.zeros(len(yy),bool)
            totals[v].append((yy,b,s))
            row["policies"][v]={"BUY_config":B[2] if B else None,"SELL_config":S[2] if S else None,**summary(yy,b,s)}
        annual.append(row)
    agg={}
    for v,arr in totals.items():
        if not arr:raise ValueError(f"no eligible folds {tf}")
        Y,B,S=[np.concatenate([r[i] for r in arr]) for i in range(3)]
        agg[v]=summary(Y,B,S)
    report={"tf":tf,"n":len(Y),"base_buy":float(Y.mean()),"fits":fits,"rule_evaluations":rules,"aggregate":agg,"annual":annual,
      "limits":["All historical evaluation reused; not prospective validation","Per-side model selected independently but target events complementary","No new FX intraday data, no DXY; H1/H4 price only","D1/W1 retrospective news until April 2026 and macro/COT release lag proxies; not proven PIT","No claim 60/80 percent without observed results and adequate sample","No entry zones or P&L"]}
    O.joinpath(f"r25-eight-{tf}.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!="annual"}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--lane",choices=["1h","4h","macro"],required=True);a=p.parse_args().lane
    if a=="macro":
        src=macro_sources()
        for tf in ["1D","1W"]:run(tf,src)
    else:run(a)
