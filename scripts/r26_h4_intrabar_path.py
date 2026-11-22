"""R26 H4 path specialist: completed H1 subbars reveal intrabar sequence.
Same H4 close-to-next-close label as R25. No future subbars in features.
Compare H4 OHLC baseline vs H1 path vs hybrid, separately selected BUY/SELL.
Exploratory historical replay, not pristine holdout. No entry zones / orders.
"""
import itertools,json
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from r10_million import load,ohlc_indicators
from r14_multitimeframe_direction import load_tf
from r21_horizon_specialists import price_specialist
from r18_asymmetric_direction import side_metrics
from r15_direction_tournament import score
from r25_eight_specialists import gates
O=Path("artifacts");O.mkdir(exist_ok=True)
def path(d,h1):
    # H4 row indexed by open t. All four H1 bars [t,t+3h] have closed
    # at t+4h. Exactly matched opens; reject missing bars.
    arr=np.stack([h1[["o","h","l","c","minutes"]].reindex(d.index+pd.Timedelta(hours=j)).to_numpy(float) for j in range(4)],axis=1)
    o,h,l,c,mins=[arr[:,:,k] for k in range(5)]
    scale=(d.h-d.l).replace(0,np.nan).to_numpy(float)
    origin=d.o.to_numpy(float)
    f=pd.DataFrame(index=d.index)
    for j in range(4):
        f[f"s{j}_body"]=(c[:,j]-o[:,j])/scale
        f[f"s{j}_range"]=(h[:,j]-l[:,j])/scale
        f[f"s{j}_close"]=(c[:,j]-origin)/scale
        f[f"s{j}_upperwick"]=(h[:,j]-np.maximum(o[:,j],c[:,j]))/scale
        f[f"s{j}_lowerwick"]=(np.minimum(o[:,j],c[:,j])-l[:,j])/scale
    # H1 continuity/sequence, levels from preceding COMPLETED H4 candles.
    f["early_move"]=(c[:,1]-origin)/scale
    f["late_move"]=(c[:,3]-c[:,1])/scale
    f["late_reversal"]=f.early_move*f.late_move
    f["up_count"]=(c>o).sum(axis=1)/4
    f["max_high_hour"]=np.argmax(h,axis=1)/3
    f["min_low_hour"]=np.argmin(l,axis=1)/3
    f["close_location"]=(c[:,3]-np.min(l,axis=1))/scale
    for win in (3,5,12,20):
        hi=d.h.shift(1).rolling(win).max().to_numpy(float)
        lo=d.l.shift(1).rolling(win).min().to_numpy(float)
        hit_hi=h>hi[:,None];hit_lo=l<lo[:,None]
        f[f"sweep_high{win}"]=(hit_hi.any(axis=1)&(c[:,3]<hi)).astype(float)
        f[f"sweep_low{win}"]=(hit_lo.any(axis=1)&(c[:,3]>lo)).astype(float)
        f[f"early_high{win}"]=hit_hi[:,:2].any(axis=1).astype(float)
        f[f"early_low{win}"]=hit_lo[:,:2].any(axis=1).astype(float)
        f[f"late_high{win}"]=hit_hi[:,2:].any(axis=1).astype(float)
        f[f"late_low{win}"]=hit_lo[:,2:].any(axis=1).astype(float)
        f[f"close_high_dist{win}"]=(c[:,3]-hi)/scale
        f[f"close_low_dist{win}"]=(c[:,3]-lo)/scale
    # Require all four source subbars, minimum 50 minutes in each;
    # check reconstructed OHLC against original H4 aggregate.
    ok=np.isfinite(arr).all(axis=(1,2))&(mins>=50).all(axis=1)
    for actual,ref in [(o[:,0],d.o),(h.max(axis=1),d.h),(l.min(axis=1),d.l),(c[:,3],d.c)]:
        ok &= np.isclose(actual,ref.to_numpy(float),rtol=0,atol=1e-6)
    f.loc[~ok,:]=np.nan
    return f.replace([np.inf,-np.inf],np.nan),ok
def run():
    d,z,_,y,valid,times=load_tf("4h");h1=load("1h")
    p,sets=price_specialist(d,z,"4h")
    q,ok=path(d,h1)
    # Causal independent prefix audit: reconstruct with only H1 rows
    # whose closes are at/before the sampled H4 decision.
    loc=np.flatnonzero(ok&q.notna().all(axis=1).to_numpy())
    for i in loc[np.linspace(0,len(loc)-1,min(len(loc),16),dtype=int)]:
        r,k=path(d.iloc[:i+1],h1[h1.index+pd.Timedelta(hours=1)<=times[i]])
        assert k[-1] and np.allclose(r.iloc[-1],q.iloc[i],rtol=0,atol=1e-10,equal_nan=True)
    groups={"h4_structure":p,"h1_path":q,"hybrid":pd.concat([p,q],axis=1)}
    valid &= ok
    for a in groups.values():valid &= np.isfinite(a.to_numpy(float)).all(axis=1)
    gate=gates(d,z,times,"4h")
    # Prespecified sequence regimes, not tested on future outcomes.
    gate.update({"early_down_late_up":(q.early_move<0)&(q.late_move>0),
                 "early_up_late_down":(q.early_move>0)&(q.late_move<0),
                 "early_sweep_low5":(q.early_low5>0)&(q.sweep_low5>0),
                 "early_sweep_high5":(q.early_high5>0)&(q.sweep_high5>0)})
    gate={k:np.asarray(v,dtype=bool) for k,v in gate.items()}
    mature=pd.Series(times,index=d.index).shift(-1)
    policies=list(groups)+["independent_best"]
    totals={k:[] for k in policies};annual=[];fits=rules=0
    for yr in range(2023,2027):
        start=pd.Timestamp(f"{yr}-01-01",tz="UTC");vs=start-pd.DateOffset(years=2);end=start+pd.DateOffset(years=1)
        va=valid&(times>=vs)&(times<start)&(mature<start).to_numpy()
        te=valid&(times>=start)&(times<end)&(mature<end).to_numpy()
        if min(va.sum(),te.sum())<140:continue
        best={k:[None,None] for k in policies}
        for name,g in groups.items():
            a=g.to_numpy(float)
            for years,family in itertools.product([2,4,8],["ridge","logit","hgb"]):
                tr=valid&(times>=vs-pd.DateOffset(years=years))&(mature<vs).to_numpy()
                if tr.sum()<250 or len(np.unique(y[tr]))<2:continue
                for side in (0,1):
                    model=HistGradientBoostingClassifier(max_iter=60,max_depth=2,max_leaf_nodes=5,l2_regularization=15,random_state=26) if family=="hgb" else make_pipeline(StandardScaler(),LogisticRegression(C=.025 if family=="ridge" else .3,max_iter=500))
                    model.fit(a[tr],(y[tr]==side).astype(int));fits+=1
                    pv=model.predict_proba(a[va])[:,1];pt=model.predict_proba(a[te])[:,1]
                    for th in [.5,.52,.55,.58,.6,.65,.7,.75,.8]:
                        for gn,G in gate.items():
                            # Baseline must not use H1 path-specific filters.
                            if name=="h4_structure" and gn in ["early_down_late_up","early_up_late_down","early_sweep_low5","early_sweep_high5"]:continue
                            rules+=1
                            b=(pv>=th)&G[va];s=(pt>=th)&G[te]
                            m=side_metrics(y[va],b,side)
                            if m["n"]<max(70,int(.025*va.sum())):continue
                            rank=(m["lower95"],m["n"])
                            config={"group":name,"years":years,"model":family,"threshold":th,"gate":gn,"validation":m}
                            for key in (name,"independent_best"):
                                if best[key][side] is None or rank>best[key][side][0]:best[key][side]=(rank,s,config)
        row={"year":yr,"n":int(te.sum()),"base_buy":float(y[te].mean()),"policy":{}}
        for name in policies:
            B,S=best[name][1],best[name][0]
            b=B[1] if B else np.zeros(te.sum(),bool);s=S[1] if S else np.zeros(te.sum(),bool)
            totals[name].append((y[te],b&~s,s&~b))
            row["policy"][name]={"buy_config":B[2] if B else None,"sell_config":S[2] if S else None,"conflicts":int((b&s).sum()),"result":score(y[te],b&~s,s&~b,np.ones(te.sum(),bool))}
        annual.append(row)
    agg={}
    for k,ls in totals.items():
        assert ls,k
        Y,B,S=[np.concatenate([a[i] for a in ls]) for i in range(3)]
        agg[k]=score(Y,B,S,np.ones(len(Y),bool))
    out={"tf":"4h","matched_n":len(Y),"base_buy":float(Y.mean()),"prefix_audits":min(len(loc),16),"full_h4_rows":len(d),"coherent_subbar_rows":int(ok.sum()),"fits":fits,"rules":rules,"aggregate":agg,"annual":annual,"limitations":["H1 subbars from same original HistData M1-derived source; new path detail not independent asset data","Historical sample reused; strict subbar filtering changes coverage, no forward verification","No intraday FX proxy, yield or DXY","No entries, orders or profit claims"]}
    O.joinpath("r26-h4-path.json").write_text(json.dumps(out,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k!="annual"}),flush=True)
if __name__=="__main__":run()
