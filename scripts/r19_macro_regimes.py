"""R19 macro pressure regime research: test simple sign-confluence and FOMC persistence.
Predeclared candidate rules, per-side selection in previous two calendar years,
purged outcomes, conflict => WAIT. Retrospective source vintage, not live signal.
No zone/entry or order execution.
"""
import itertools,json
from pathlib import Path
import numpy as np,pandas as pd
from r17_macro_pilot import treasury_fallback,align
from r18_asymmetric_direction import fomc_fixed
from r14_multitimeframe_direction import load_tf
from r15_direction_tournament import score
from r10_million import wilson
O=Path("artifacts");O.mkdir(exist_ok=True)

def metrics(yy,b,s):
    return score(yy,b,s,np.ones(len(yy),bool))

def blocks_ci(y,mask,side,dates):
    # resample calendar months as blocks; descriptive uncertainty, not selection correction
    if np.sum(mask)<20:return None
    month=pd.DatetimeIndex(dates[mask]).strftime("%Y-%m")
    df=pd.DataFrame({"month":month,"correct":(y[mask]==side).astype(int)})
    sums=df.groupby("month").correct.agg(["sum","count"]).to_numpy(float)
    if len(sums)<6:return None
    gen=np.random.default_rng(901)
    ix=gen.integers(0,len(sums),size=(600,len(sums)))
    samples=sums[ix].sum(axis=1)
    return [float(k) for k in np.quantile(samples[:,0]/samples[:,1],[.025,.975])]

def build_signals(d,z,m):
    # All comparisons based on past-observed rates, already lagged by source functions.
    # Hawkish yield and positive FOMC 2Y shock are candidate bearish XAU pressure.
    arr=[]
    trend=np.sign((z.ema8-z.ema21).to_numpy(float))
    momentum=np.sign(z.roc3.to_numpy(float))
    for k in [1,3,5,10,20]:
        raw=[m[f"{s}_{k}"].to_numpy(float) for s in ("DGS2","DGS10","DFII10") if f"{s}_{k}" in m]
        if len(raw)<2:continue
        x2=m[f"DGS2_{k}"].to_numpy(float) if f"DGS2_{k}" in m else raw[0]
        real=m[f"DFII10_{k}"].to_numpy(float) if f"DFII10_{k}" in m else raw[-1]
        stack=np.stack(raw,axis=1)
        for bp in [.0,.025,.05,.1,.2]:
            # Strictly positive/negative readings; do not classify flat rates.
            vote_up=(stack>bp).sum(axis=1);vote_dn=(stack< -bp).sum(axis=1)
            for kind,pressure in [("2y",np.where(x2>bp,1,np.where(x2< -bp,-1,0))),
                                  ("real",np.where(real>bp,1,np.where(real< -bp,-1,0))),
                                  ("all_yields",np.where(vote_up==len(raw),1,np.where(vote_dn==len(raw),-1,0))),
                                  ("majority_yields",np.where(vote_up>len(raw)/2,1,np.where(vote_dn>len(raw)/2,-1,0)))]:
                for f in [0,3,10,20]:
                    if f:
                        name=f"fomc_decay_{f}"
                        if name not in m:continue
                        fs=np.sign(m[name].to_numpy(float))
                        press=np.where(fs==pressure,pressure,0)
                    else:press=pressure
                    for confirm,t in [("none",None),("ema",trend),("mom",momentum)]:
                        # Macro-fundamental forecast and inversion control as separate hypotheses.
                        for orientation in [-1,1]:
                            s=press*orientation
                            if t is not None:s=np.where(s==t,s,0)
                            key={"lookback":k,"threshold_yield_pp":bp,"pressure":kind,"FOMC_half_life_days":f,
                                 "technical_confirmation":confirm,"orientation":"inverse_yield" if orientation==-1 else "same_yield"}
                            arr.append((key,s==1,s==-1))
    # FOMC-only pressure (with optional price confirmation) and technical-only baselines.
    for f in [1,3,5,10,20,40]:
        name=f"fomc_decay_{f}"
        if name not in m:continue
        v=m[name].to_numpy(float)
        # Event change expressed in source units; use sign only, days since substantial shock encoded by decays.
        for cut in [0,.001,.005,.02]:
            q=np.where(v>cut,1,np.where(v< -cut,-1,0))
            for orientation in [-1,1]:
                for confirm,t in [("none",None),("ema",trend),("mom",momentum)]:
                    s=q*orientation
                    if t is not None:s=np.where(s==t,s,0)
                    arr.append(({"pressure":"FOMC_only","half_life":f,"source_threshold":cut,"confirmation":confirm,
                                 "orientation":orientation},s==1,s==-1))
    for kind,t in [("ema",trend),("momentum",momentum)]:
        for k in [-1,1]:
            arr.append(({"price_only":kind,"orientation":k},t*k==1,t*k==-1))
    return arr

def run():
    parts,meta=treasury_fallback()
    assert len(parts)>=2,"Missing Treasury sources"
    fp,fmeta=fomc_fixed() # fail closed: macro study requires actual FOMC observations
    parts.append(fp)
    O.joinpath("r19-manifest.json").write_text(json.dumps({"treasury":meta,"fomc":fmeta},indent=2))
    results={}
    for tf in ["1h","4h","1D","1W"]:
        d,z,_,y,valid,times=load_tf(tf)
        m=align(parts,times,d.index)
        valid &= m.notna().all(axis=1).to_numpy()
        valid &= np.isfinite(z.ema8.to_numpy()) & np.isfinite(z.ema21.to_numpy()) & np.isfinite(z.roc3.to_numpy())
        # Strictly exclude observations beyond last source's available timestamp, avoiding stale FOMC fill.
        valid &= (times<=fp.index.max())
        mature=pd.Series(times,index=d.index).shift(-1)
        candidates=build_signals(d,z,m)
        # Select separately per-side on past 2 years; counts per side and both-sided decisions.
        nmin={"1h":180,"4h":90,"1D":35,"1W":12}[tf]
        years=range(2022,2027) if tf in ("1h","4h") else range(2018,2027)
        yy=[];bb=[];ss=[];dd=[];annual=[];total=0
        for yr in years:
            start=pd.Timestamp(f"{yr}-01-01",tz="UTC")
            end=start+pd.DateOffset(years=1)
            begin=start-pd.DateOffset(years=2)
            tr=valid&(times>=begin)&(times<start)&(mature<start).to_numpy()
            te=valid&(times>=start)&(times<end)&(mature<end).to_numpy()
            if tr.sum()<2*nmin or te.sum()<20:continue
            # Selection uses exclusively historical matured outcomes.
            best=[None,None]
            for key,b,s in candidates:
                total+=2
                for side,mask in [(1,b),(0,s)]:
                    use=mask&tr;n=int(use.sum())
                    if n<nmin:continue
                    k=int((y[use]==side).sum())
                    q=(wilson(k,n),n)
                    if best[side] is None or q>best[side][0]:
                        best[side]=(q,key,mask[te],{"n":n,"correct":k,"accuracy":k/n})
            buy=best[1][2] if best[1] else np.zeros(te.sum(),bool)
            sell=best[0][2] if best[0] else np.zeros(te.sum(),bool)
            b=buy&~sell;s=sell&~buy
            annual.append({"year":yr,"buy_rule":best[1][1] if best[1] else None,"sell_rule":best[0][1] if best[0] else None,
                           "buy_validation":best[1][3] if best[1] else None,"sell_validation":best[0][3] if best[0] else None,
                           "conflicts":int((buy&sell).sum()),"base_buy":float(y[te].mean()),"evaluation":metrics(y[te],b,s)})
            yy.append(y[te]);bb.append(b);ss.append(s);dd.append(times[te])
        assert yy,tf
        Y=np.concatenate(yy);B=np.concatenate(bb);S=np.concatenate(ss)
        dates=pd.DatetimeIndex(np.concatenate([v.to_numpy() for v in dd]))
        out={"rules_unique":len(candidates),"evaluations_across_folds":total,"n":len(Y),"aggregate":metrics(Y,B,S),
             "buy_month_block_ci95":blocks_ci(Y,B,1,dates),"sell_month_block_ci95":blocks_ci(Y,S,0,dates),
             "always_buy":float(Y.mean()),"annual":annual}
        results[tf]=out
        print(json.dumps({"tf":tf,**{k:v for k,v in out.items() if k!="annual"}}),flush=True)
    O.joinpath("r19-macro-regimes.json").write_text(json.dumps({"results":results,"fomc_source":fmeta,
        "limitations":["Treasury and FOMC latest retrospective vintage, conservative 2 weekdays lag, not exact point in time",
           "Historical folds reused, no pristine holdout","Repeated rule selection; descriptive block CI not multiple testing adjusted",
           "No archived CPI/NFP consensus, DXY or true pre-news surprise forecasts","Direction only; no executable order or profitability claim"]},indent=2))
if __name__=="__main__":run()
