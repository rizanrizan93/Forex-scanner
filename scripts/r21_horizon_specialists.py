"""R21 horizon-specialist pilot, research only.
H1: session-conditioned return behavior and price pressure.
H4: objective SMC-inspired structure/sweep/displacement and context.
D1: lagged Treasury/FOMC macro pressure and technical confirmation.
W1 R20 held unchanged as research benchmark. No entry/zone/orders.
All history reused; no pristine holdout. No DXY/news consensus in this pilot.
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
from r17_macro_pilot import treasury_fallback,align
from r18_asymmetric_direction import fomc_fixed,side_metrics
from r15_direction_tournament import score
O=Path("artifacts");O.mkdir(exist_ok=True)
def price_specialist(d,z,tf):
    c=d.c.astype(float);h=d.h.astype(float);l=d.l.astype(float);o=d.o.astype(float)
    atr=z.atr14.replace(0,np.nan)
    f=pd.DataFrame(index=d.index)
    rng=(h-l).replace(0,np.nan)
    for n in [1,2,3,6,12,24]:
        f[f"ret{n}"]=np.log(c/c.shift(n))
    f["body_atr"]=(c-o)/atr
    f["clv"]=2*(c-l)/rng-1
    f["range_atr"]=rng/atr
    f["atr_rank"]=z.atr_rank
    f["ema_atr"]=(z.ema8-z.ema21)/atr
    if tf=="1h":
        # DST-sensitive local wall-clock hour. Boundaries are stylized trading
        # session proxies, not exchange open/close claims.
        times=d.index+pd.Timedelta(hours=1)
        lh=times.tz_convert("Europe/London").hour
        nh=times.tz_convert("America/New_York").hour
        ah=times.tz_convert("Asia/Tokyo").hour
        f["london_active"]=((lh>=8)&(lh<16)).astype(float)
        f["ny_active"]=((nh>=8)&(nh<16)).astype(float)
        f["asia_active"]=((ah>=9)&(ah<15)).astype(float)
        f["ny_open"]=((nh>=8)&(nh<11)).astype(float)
        f["london_open"]=((lh>=8)&(lh<11)).astype(float)
        f["hour_sin"]=np.sin(2*np.pi*times.hour/24)
        f["hour_cos"]=np.cos(2*np.pi*times.hour/24)
        for n in [3,6,12]:
            f[f"eff{n}"]=c.diff(n)/c.diff().abs().rolling(n).sum().replace(0,np.nan)
            f[f"range_rel{n}"]=rng/rng.rolling(n).median().replace(0,np.nan)
        sess=[k for k in f if k.endswith(("_active","_open"))]
        for k in sess:
            for u in ["body_atr","ema_atr","ret3","range_atr"]:
                f[k+"_"+u]=f[k]*f[u]
        sets={"intraday_price": [k for k in f if not any(k.startswith(x) for x in sess)],
              "session_interaction":list(f.columns),
              "session_pressure":[k for k in f if k.startswith(tuple(sess)) or k in ["ret1","ret3","ema_atr","range_atr","atr_rank"]]}
    else:
        # Only past completed bars define structure levels, never centered pivots.
        for n in [3,5,8,12,20,40]:
            ph=h.shift(1).rolling(n).max()
            pl=l.shift(1).rolling(n).min()
            width=(ph-pl).replace(0,np.nan)
            f[f"sweep_high{n}"]=((h>ph)&(c<ph)).astype(float)
            f[f"sweep_low{n}"]=((l<pl)&(c>pl)).astype(float)
            f[f"bos_up{n}"]=((c>ph)&((c-o)/atr>.35)).astype(float)
            f[f"bos_dn{n}"]=((c<pl)&((o-c)/atr>.35)).astype(float)
            f[f"position{n}"]=(c-pl)/width
            f[f"gap_hi{n}"]=(ph-c)/atr
            f[f"gap_lo{n}"]=(c-pl)/atr
        f["fvg_bull_atr"]=(l-h.shift(2)).clip(lower=0)/atr
        f["fvg_bear_atr"]=(l.shift(2)-h).clip(lower=0)/atr
        f["displacement"]=f.body_atr.abs()*f.clv
        for k in ["d1_mom","d1_trend","w1_mom","w1_trend"]:
            if k in z:f[k]=z[k]
        st=[k for k in f if k.startswith(("sweep_","bos_","position","gap_","fvg_"))]
        sets={"structure":st+["body_atr","ema_atr","clv","atr_rank"],
              "structure_context":list(f.columns),
              "compact_structure":[k for k in f if k.startswith(("sweep_","bos_","position")) and k.endswith(("5","12","20"))]+["body_atr","ema_atr","atr_rank"]}
    return f.replace([np.inf,-np.inf],np.nan),sets
def getsets(tf,d,z,times):
    if tf in ("1h","4h"):
        return (*price_specialist(d,z,tf),{"sources":"completed OHLC only; no intraday DXY or yield"})
    parts,meta=treasury_fallback()
    O.joinpath("r21-macro-manifest.json").write_text(json.dumps(meta,indent=2))
    assert len(parts)>=2,"Treasury data missing"
    fp,fm=fomc_fixed();parts.append(fp)
    m=align(parts,times,d.index)
    p=features(z);p=p.drop(columns=[k for k in p if k.startswith("hour_")])
    f=pd.concat([p,m],axis=1)
    for n in [3,5,10,20]:
        names=[k for k in [f"DGS2_{n}",f"DGS10_{n}",f"DFII10_{n}"] if k in m]
        f[f"yield_vote{n}"]=np.sign(m[names]).sum(axis=1)
        if f"DGS10_{n}" in m and f"DGS2_{n}" in m:f[f"curve_change{n}"]=m[f"DGS10_{n}"]-m[f"DGS2_{n}"]
        for k in ["fomc_decay_3","fomc_decay_10","fomc_decay_20"]:
            if k in m:f[f"{k}_confirm{n}"]=np.sign(m[k])*f[f"yield_vote{n}"]
    new=[k for k in f if k not in p.columns and k not in m.columns]
    sets={"daily_macro":list(m.columns)+new,
          "daily_hybrid":list(f.columns),
          "daily_technical":list(p.columns)}
    return f.replace([np.inf,-np.inf],np.nan),sets,{"treasury":meta,"fomc":fm,"limitation":"two-weekday lag, retrospective vintage; no actual consensus surprise"}
def run(tf):
    d,z,_,y,valid,times=load_tf(tf)
    f,sets,manifest=getsets(tf,d,z,times)
    valid &= f.notna().all(axis=1).to_numpy()
    # causal audit of H1/H4 specialist features from prefixes with upstream z prefix:
    # upstream R10.3 context separately audited; here newly derived feature invariance.
    if tf in ("1h","4h"):
        good=np.flatnonzero(valid)
        loc=good[np.linspace(0,len(good)-1,min(12,len(good)),dtype=int)]
        for i in loc:
            q,_=price_specialist(d.iloc[:i+1],z.iloc[:i+1],tf)
            assert np.allclose(q.iloc[-1].to_numpy(float),f.iloc[i].to_numpy(float),rtol=1e-8,atol=1e-8,equal_nan=True),str(d.index[i])
    mature=pd.Series(times,index=d.index).shift(-1)
    nmin={"1h":80,"4h":40,"1D":25}[tf]
    mini={"1h":600,"4h":250,"1D":150}[tf]
    cuts=[.5,.52,.55,.58,.6,.65,.7]
    fits=rules=0;rows=[];agg=[]
    for yr in (range(2022,2027) if tf in ("1h","4h") else range(2018,2027)):
        start=pd.Timestamp(f"{yr}-01-01",tz="UTC");vstart=start-pd.DateOffset(years=1);end=start+pd.DateOffset(years=1)
        va=valid&(times>=vstart)&(times<start)&(mature<start).to_numpy()
        te=valid&(times>=start)&(times<end)&(mature<end).to_numpy()
        if min(va.sum(),te.sum())<2*nmin:continue
        chosen=[None,None]
        for key,cols in sets.items():
            x=f[cols].to_numpy(float)
            for years,family in itertools.product([2,4,8],["logit_strong","logit","hgb"]):
                tr=valid&(times>=vstart-pd.DateOffset(years=years))&(mature<vstart).to_numpy()
                if tr.sum()<mini or len(np.unique(y[tr]))<2:continue
                model=(HistGradientBoostingClassifier(max_iter=70,max_depth=3,max_leaf_nodes=7,l2_regularization=10,random_state=42) if family=="hgb" else make_pipeline(StandardScaler(),LogisticRegression(C=.03 if family=="logit_strong" else .3,max_iter=500)))
                model.fit(x[tr],y[tr]);fits+=1
                pv=model.predict_proba(x[va])[:,1];pt=model.predict_proba(x[te])[:,1]
                for cut in cuts:
                    for side in [0,1]:
                        rules+=1
                        v=pv>=cut if side else (pv<.5 if cut==.5 else pv<=1-cut)
                        t=pt>=cut if side else (pt<.5 if cut==.5 else pt<=1-cut)
                        r=side_metrics(y[va],v,side)
                        if r["n"]<nmin:continue
                        rank=(r["lower95"],r["n"])
                        if chosen[side] is None or rank>chosen[side][0]:
                            chosen[side]=(rank,t,dict(group=key,years=years,model=family,threshold=cut,validation=r))
        b=chosen[1][1] if chosen[1] else np.zeros(te.sum(),bool)
        s=chosen[0][1] if chosen[0] else np.zeros(te.sum(),bool)
        rows.append({"year":yr,"buy":chosen[1][2] if chosen[1] else None,"sell":chosen[0][2] if chosen[0] else None,"conflicts":int((b&s).sum()),"evaluation":score(y[te],b&~s,s&~b,np.ones(te.sum(),bool))})
        agg.append((y[te],b&~s,s&~b))
    assert agg
    yy,b,s=[np.concatenate([a[i] for a in agg]) for i in range(3)]
    report={"tf":tf,"model_fits":fits,"rule_evaluations":rules,"eligible_n":len(yy),"baseline_buy":float(yy.mean()),"aggregate":score(yy,b,s,np.ones(len(yy),bool)),"annual":rows,"feature_groups":sets,"source":manifest,"limits":["All historical evaluation reused, not pristine holdout","Specialist methods are hypotheses, not trading systems","No DXY or news consensus features in this pilot","No entry zones or orders","H1/H4 feature prefix checks use already-computed causal upstream features, not full independent source rebuild"]}
    O.joinpath(f"r21-specialist-{tf}.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ("annual","source","feature_groups")}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--tf",required=True,choices=["1h","4h","1D"]);run(p.parse_args().tf)
