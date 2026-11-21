"""R20 research pilot: CFTC positioning + Treasury/FOMC, matched ablation.
Weekly report date refers to Tuesday positions, NOT release date.
Conservative availability: 14 calendar days after report date. Not exact PIT:
late-report disruptions and retrospective corrections still require separate audit.
Direction only; no live or entry development.
"""
import io,itertools,json,hashlib,zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from r17_macro_pilot import treasury_fallback,align,get
from r18_asymmetric_direction import fomc_fixed,side_metrics
from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r15_direction_tournament import score
from r10_million import wilson
O=Path("artifacts");O.mkdir(exist_ok=True)
def clean(s):return "".join(c for c in str(s).lower() if c.isalnum())
def cot():
    # CFTC legacy futures-only archive, gold COMEX market code 088691.
    def one(year):
        url=f"https://www.cftc.gov/files/dea/history/deacot{year}.zip"
        try:
            raw=get(url);z=zipfile.ZipFile(io.BytesIO(raw))
            names=[n for n in z.namelist() if n.lower().endswith((".txt",".csv"))]
            assert names, z.namelist()
            a=pd.read_csv(z.open(names[0]),encoding="latin1",low_memory=False)
            keys={clean(k):k for k in a.columns}
            def field(*names):
                for n in names:
                    if clean(n) in keys:return keys[clean(n)]
                raise KeyError((names,list(a.columns)[:20]))
            market=field("CFTC_Contract_Market_Code","CFTC Contract Market Code")
            mask=a[market].astype(str).str.strip().str.replace(r"\.0$","",regex=True).str.zfill(6)=="088691"
            a=a.loc[mask].copy()
            dt=field("As of Date in Form YYYY-MM-DD","As_of_Date_In_Form_YYYY-MM-DD","Report_Date_as_YYYY-MM-DD")
            b=pd.DataFrame({"date":pd.to_datetime(a[dt],errors="coerce",utc=True),
                  "oi":pd.to_numeric(a[field("Open Interest (All)","Open_Interest_All")],errors="coerce"),
                  "long":pd.to_numeric(a[field("Noncommercial Positions-Long (All)","NonComm_Positions_Long_All")],errors="coerce"),
                  "short":pd.to_numeric(a[field("Noncommercial Positions-Short (All)","NonComm_Positions_Short_All")],errors="coerce"),
                  "spread":pd.to_numeric(a[field("Noncommercial Positions-Spreading (All)","NonComm_Positions_Spreading_All")],errors="coerce")})
            b=b.dropna().set_index("date").sort_index()
            assert 20<=len(b)<=56,(year,len(b))
            return b,{"year":year,"url":url,"rows":len(b),"sha256":hashlib.sha256(raw).hexdigest()}
        except Exception as e:return None,{"year":year,"url":url,"error":repr(e)}
    with ThreadPoolExecutor(max_workers=4) as p:r=list(p.map(one,range(2010,2027)))
    meta=[m for _,m in r]
    valid=[v for v,_ in r if v is not None]
    O.joinpath("r20-cot-manifest.json").write_text(json.dumps(meta,indent=2))
    assert len(valid)>=15,meta
    a=pd.concat(valid).sort_index();a=a[~a.index.duplicated(keep="last")]
    assert set(range(2012,2027))<=set(a.index.year),meta
    assert a.index.max()>=pd.Timestamp("2026-09-01",tz="UTC"),str(a.index.max())
    assert (a.oi>0).all()
    f=pd.DataFrame(index=a.index)
    net=(a.long-a.short)/a.oi
    f["cot_net"]=net;f["cot_long"]=a.long/a.oi;f["cot_short"]=a.short/a.oi
    f["cot_spread"]=a.spread/a.oi
    for w in [1,2,4,8,13,26]:
        f[f"cot_change{w}"]=net.diff(w)
        f[f"cot_oi{w}"]=a.oi.pct_change(w)
    for w in [13,26,52]:
        lo=net.rolling(w).min();hi=net.rolling(w).max()
        f[f"cot_rank{w}"]=(net-lo)/(hi-lo).replace(0,np.nan)
    # Report dates cannot be treated as release dates. 14 days conservative proxy.
    f.index=f.index+pd.Timedelta(days=14)
    return f,{"files":meta,"n":len(a),"first_report":str(a.index.min()),"last_report":str(a.index.max()),"availability_proxy":"report date +14 calendar days; late publication still unverified"}

def side(y,mask,s):
    return side_metrics(y,mask,s)
def metrics(y,b,s):
    return score(y,b,s,np.ones(len(y),bool))
def run():
    parts,treasury=treasury_fallback()
    assert len(parts)>=2,"Missing Treasury"
    fp,fm=fomc_fixed();parts.append(fp)
    cp,cm=cot()
    O.joinpath("r20-manifest.json").write_text(json.dumps({"treasury":treasury,"fomc":fm,"cot":cm},indent=2))
    print(json.dumps({"cot":{k:v for k,v in cm.items() if k!="files"},"fomc":fm}),flush=True)
    results={}
    for tf in ["1h","4h","1D","1W"]:
        d,z,_,y,valid,times=load_tf(tf)
        px=features(z)
        if tf in ("1D","1W"):px=px.drop(columns=[c for c in px if c.startswith("hour_")])
        macro=align(parts,times,d.index)
        pos=align([cp],times,d.index)
        # Fail closed stale COT reports (release proxy already lagged).
        latest=pd.Series(cp.index,index=cp.index).reindex(times,method="ffill")
        age=times-pd.DatetimeIndex(latest)
        valid &= (age<=pd.Timedelta(days=21)) & (age>=pd.Timedelta(0))
        valid &= (times<=fp.index.max())
        valid &= px.notna().all(axis=1).to_numpy() & macro.notna().all(axis=1).to_numpy() & pos.notna().all(axis=1).to_numpy()
        groups={"technical":px,"macro":macro,"positioning":pos,
            "tech_macro":pd.concat([px,macro],axis=1),
            "tech_macro_cot":pd.concat([px,macro,pos],axis=1)}
        mature=pd.Series(times,index=d.index).shift(-1)
        nmin={"1h":80,"4h":40,"1D":25,"1W":10}[tf]
        mintrain={"1h":500,"4h":200,"1D":150,"1W":70}[tf]
        preds={k:[] for k in groups};annual={k:[] for k in groups}
        evals=0;fits=0
        for yr in (range(2022,2027) if tf in ("1h","4h") else range(2018,2027)):
            b=pd.Timestamp(f"{yr}-01-01",tz="UTC");vstart=b-pd.DateOffset(years=1);end=b+pd.DateOffset(years=1)
            va=valid&(times>=vstart)&(times<b)&(mature<b).to_numpy()
            te=valid&(times>=b)&(times<end)&(mature<end).to_numpy()
            if min(va.sum(),te.sum())<2*nmin:continue
            for key,g in groups.items():
                x=g.to_numpy(float);best=[None,None]
                for years,C in itertools.product([3,6,10],[.01,.1,1.]):
                    tr=valid&(times>=vstart-pd.DateOffset(years=years))&(mature<vstart).to_numpy()
                    if tr.sum()<mintrain or len(np.unique(y[tr]))<2:continue
                    model=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
                    model.fit(x[tr],y[tr]);fits+=1
                    pv=model.predict_proba(x[va])[:,1];pt=model.predict_proba(x[te])[:,1]
                    for cut in [.5,.52,.55,.58,.60,.65,.70]:
                        for s in [0,1]:
                            evals+=1
                            v=(pv>=cut if s else (pv<.5 if cut==.5 else pv<=1-cut))
                            t=(pt>=cut if s else (pt<.5 if cut==.5 else pt<=1-cut))
                            r=side(y[va],v,s)
                            if r["n"]<nmin:continue
                            rank=(r["lower95"],r["n"])
                            if best[s] is None or rank>best[s][0]:best[s]=(rank,t,{"years":years,"C":C,"cut":cut,"validation":r})
                buy=best[1][1] if best[1] else np.zeros(te.sum(),bool)
                sell=best[0][1] if best[0] else np.zeros(te.sum(),bool)
                bb=buy&~sell;ss=sell&~buy
                preds[key].append((y[te],bb,ss))
                annual[key].append({"year":yr,"buy_rule":best[1][2] if best[1] else None,"sell_rule":best[0][2] if best[0] else None,"conflicts":int((buy&sell).sum()),"evaluation":metrics(y[te],bb,ss)})
        agg={}
        for k,a in preds.items():
            assert a,(tf,k,"no folds")
            Y,B,S=[np.concatenate([r[i] for r in a]) for i in range(3)]
            agg[k]=metrics(Y,B,S)
        out={"evaluations_across_folds":evals,"model_fits":fits,"matched_n":len(Y),"base_buy":float(Y.mean()),"aggregate":agg,"annual":annual}
        results[tf]=out
        print(json.dumps({"tf":tf,**{k:v for k,v in out.items() if k!="annual"}}),flush=True)
    O.joinpath("r20-cot-direction.json").write_text(json.dumps({"results":results,"sources":{"treasury":treasury,"fomc":fm,"cot":cm},"limits":["CFTC report date plus 14 calendar days is a conservative availability proxy, not actual timestamp, delayed publication and revisions may still leak; provisional only","COT noncommercial futures-only gold positions are weekly aggregate, not live smart-money entries","Treasury/FOMC retrospective vintage delayed two weekdays","No CPI/NFP consensus or DXY","Annual historical folds previously reused, not untouched forward holdout","No entry or net P&L claims"]},indent=2))
if __name__=="__main__":run()
