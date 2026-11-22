"""R28 research only: alternative HistData FX source, causal relative strength.
Prespecified scope 2019-2025 complete calendar years; evaluation 2023-2025.
No change to locks, production, broker, zones. Historical folds are reused.
"""
import argparse, hashlib, json
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r18_asymmetric_direction import side_metrics
from r25_eight_specialists import macro_sources,setup
O=Path("artifacts");O.mkdir(exist_ok=True)
SYMS=["EURUSD","USDJPY"]
YEARS=range(2019,2026)
def acquire(sym,yr):
    from histdata_fetcher import fetch_data
    from fx_scanner.research_xau_histdata_download_v193 import _normalize_frame
    result=fetch_data(pair=sym,start_date=date(yr,1,1),end_date=date(yr,12,31),timeframe="1min",output_format=None,max_workers=1)
    d=_normalize_frame(result.data).set_index("timestamp")
    assert d.close.gt(0).all()
    assert (.75<d.close.median()<1.8 if sym=="EURUSD" else 60<d.close.median()<220)
    g=d.close.resample("1h",label="right",closed="left").agg(["last","count"])
    g=g[g["count"]>=50]["last"].dropna()
    # Full annual source: >= 5000 qualifying hourly bars and all 12 source months.
    assert len(g)>=5000 and d.index.tz_convert("Etc/GMT+5").month.nunique()==12,(sym,yr,len(g))
    p=O/f"r28-fx-{sym}-{yr}.csv";g.rename("close").to_csv(p)
    m={"symbol":sym,"year":yr,"n":len(g),"first":str(g.index.min()),"last":str(g.index.max()),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"source":"HistData M1 fixed EST -> UTC hourly close","provider_commit":"4a3c11b67f97758f6e3f77a3e5905b6aa87367b8","failed_periods":str(result.failed_periods)}
    O.joinpath(f"r28-fx-{sym}-{yr}.json").write_text(json.dumps(m,indent=2));print(json.dumps(m),flush=True)
def loadfx():
    out={}
    for sym in SYMS:
        parts=[]
        for yr in YEARS:
            p=Path(f"/tmp/r28fx/r28-fx-{sym}-{yr}.csv")
            m=json.loads(p.with_suffix(".json").read_text())
            assert hashlib.sha256(p.read_bytes()).hexdigest()==m["sha256"]
            parts.append(pd.read_csv(p,index_col=0,parse_dates=True).close)
        a=pd.concat(parts).sort_index()
        assert a.index.tz is not None
        out[sym]=a[~a.index.duplicated()]
    return out
def cross(fx,d,times,tf):
    out=pd.DataFrame(index=d.index)
    anchor=times-pd.Timedelta(hours=1)
    tol=pd.Timedelta(hours=2 if tf in ("1h","4h") else 75)
    for sym,c in fx.items():
        # Compute features at actually available FX bar closes, no future fill.
        r=np.log(c)*(-1 if sym=="EURUSD" else 1)
        base=pd.DataFrame({f"{sym}_r{k}":r.diff(k) for k in (1,4,12,24,72,120)})
        base[f"{sym}_vol24"]=r.diff().rolling(24).std()
        base[f"{sym}_trend"]=r-r.ewm(span=48,adjust=False).mean()
        base[f"{sym}_age"]=base.index
        f=base.reindex(anchor,method="ffill",tolerance=tol)
        age=anchor-pd.DatetimeIndex(f.pop(f"{sym}_age"))
        assert ((age>=pd.Timedelta(0))|pd.isna(age)).all()
        for col in f:out[col]=f[col].to_numpy()
    for k in (1,4,12,24,72,120):
        a=out[f"EURUSD_r{k}"];b=out[f"USDJPY_r{k}"]
        out[f"usd_proxy{k}"]=(a+b)/2;out[f"divergence{k}"]=a-b
    xret=np.log(d.c).diff()
    dollar=out["usd_proxy24"].diff()
    beta=xret.rolling(64,min_periods=48).cov(dollar)/dollar.rolling(64,min_periods=48).var()
    out["rolling_beta64"]=beta
    out["gold_fx_residual"]=xret-beta.shift(1)*dollar
    out["gold_fx_corr64"]=xret.rolling(64,min_periods=48).corr(dollar)
    return out.replace([np.inf,-np.inf],np.nan)
def metrics(y,b,s,total):
    B,S=b&~s,s&~b
    return {"BUY":side_metrics(y,B,1),"SELL":side_metrics(y,S,0),"conflicts":int((b&s).sum()),"matched_coverage":float((B|S).mean()) if len(y) else None,"market_coverage":float((B|S).sum()/total) if total else None,"raw_BUY":side_metrics(y,b,1),"raw_SELL":side_metrics(y,s,0)}
def run(tf,fx,sources=None):
    d,z,_,y,eligible,times=load_tf(tf)
    p=features(z);f=cross(fx,d,times,tf)
    # Fixed source scope; excludes 2026 before looking at performance.
    eligible &= (times.year>=2019)&(times.year<=2025)
    groups={"price":p,"fx":f,"price_fx":pd.concat([p,f],axis=1)}
    if sources is not None:
        g,_,extra=setup(tf,d,z,times,sources)
        groups["prior_macro"]=g["full"]
        groups["macro_fx"]=pd.concat([g["full"],f],axis=1)
    valid=eligible.copy()
    if sources is not None:valid &= extra
    for a in groups.values():valid &= np.isfinite(a.to_numpy(float)).all(axis=1)
    mature=pd.Series(times,index=d.index).shift(-1)
    minval={"1h":100,"4h":40,"1D":25,"1W":12}[tf]
    mintrain={"1h":500,"4h":250,"1D":120,"1W":50}[tf]
    annual=[];pred={k:[] for k in groups};fits=0;rules=0
    for yr in (2023,2024,2025):
        start=pd.Timestamp(f"{yr}-01-01",tz="UTC");vs=start-pd.DateOffset(years=1);end=start+pd.DateOffset(years=1)
        base=eligible&(times>=start)&(times<end)&(mature<end).to_numpy()
        tr=valid&(times<vs)&(mature<vs).to_numpy()
        va=valid&(times>=vs)&(times<start)&(mature<start).to_numpy()
        te=valid&base
        # Prespecified coverage gate: reject incomplete matched test year.
        # Macro sources have an extra eligibility restriction; same gate still applies.
        ratio=float(te.sum()/max(1,base.sum()))
        if ratio<.80 or tr.sum()<mintrain or va.sum()<2*minval:
            annual.append({"year":yr,"status":"REJECT_DATA","matched":int(te.sum()),"market":int(base.sum()),"ratio":ratio});continue
        row={"year":yr,"status":"EVALUATED","matched":int(te.sum()),"market":int(base.sum()),"ratio":ratio,"base_buy":float(y[te].mean()),"policies":{}}
        for name,a in groups.items():
            x=a.to_numpy(float);chosen=[None,None]
            for side in (0,1):
                target=(y==side).astype(int)
                for C in (.025,.3):
                    mod=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
                    mod.fit(x[tr],target[tr]);fits+=1
                    pv=mod.predict_proba(x[va])[:,1];pt=mod.predict_proba(x[te])[:,1]
                    for threshold in (.50,.53,.56,.60,.65,.70,.75,.80):
                        rules+=1
                        m=side_metrics(y[va],pv>=threshold,side)
                        if m["n"]<minval:continue
                        rank=(m["lower95"],m["n"])
                        if chosen[side] is None or rank>chosen[side][0]:chosen[side]=(rank,pt>=threshold,{"C":C,"threshold":threshold,"validation":m})
            b=chosen[1][1] if chosen[1] else np.zeros(te.sum(),bool)
            s=chosen[0][1] if chosen[0] else np.zeros(te.sum(),bool)
            row["policies"][name]={"BUY_config":chosen[1][2] if chosen[1] else None,"SELL_config":chosen[0][2] if chosen[0] else None,**metrics(y[te],b,s,int(base.sum()))}
            pred[name].append((y[te],b,s,int(base.sum())))
        annual.append(row)
    aggregate={}
    for name,arr in pred.items():
        if arr:
            yy,b,s=[np.concatenate([r[i] for r in arr]) for i in range(3)]
            aggregate[name]=metrics(yy,b,s,sum(r[3] for r in arr))
    report={"tf":tf,"status":"EXPLORATORY_COMPLETE" if aggregate else "NO_VALID_FOLDS","fits":fits,"rules":rules,"aggregate":aggregate,"annual":annual,"market_scope":"2019-2025, evaluation 2023-2025","limits":["Not DXY or intraday yield; FX pair proxy only","One hour delay plus bounded backward join","Annual 80% matched-data gate predeclared","Historical folds reused, no forward validation","No entry zone or LIVE permission"]}
    O.joinpath(f"r28-{tf}-{'macro' if sources else 'fx'}.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!="annual"}),flush=True)
if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--acquire",nargs=2);a.add_argument("--tf",choices=["1h","4h","1D","1W"]);a.add_argument("--macro",action="store_true");args=a.parse_args()
    if args.acquire:acquire(args.acquire[0],int(args.acquire[1]))
    else:run(args.tf,loadfx(),macro_sources() if args.macro else None)
