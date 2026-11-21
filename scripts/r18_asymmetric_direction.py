"""R18 independent directional permissions vs shared symmetric classifier.
Exploratory historical annual walk-forward only. No zone or orders.
Both heads have identical binary target class complements, but may select
different information, model windows, thresholds and regularization.
Conflicting permissions become WAIT. FOMC availability conservatively lagged.
"""
import io,itertools,json,hashlib
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from r17_macro_pilot import treasury_fallback,get,FOMC,date_column,align
from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r15_direction_tournament import score
from r10_million import wilson
O=Path("artifacts");O.mkdir(exist_ok=True)
def fomc_fixed():
    raw=get(FOMC);book=pd.ExcelFile(io.BytesIO(raw))
    sheet=next((s for s in book.sheet_names if "monetary" in s.lower() and "event" in s.lower()),None)
    if sheet is None:raise ValueError(str(book.sheet_names))
    a=book.parse(sheet);dc=date_column(a)
    col={str(c).strip().upper():c for c in a.columns}["UST2Y"]
    dates=pd.to_datetime(a[dc],errors="coerce",utc=True)
    e=pd.Series(pd.to_numeric(a[col],errors="coerce").to_numpy(),index=dates).dropna()
    e=e[e.index.notna()].sort_index();e=e[~e.index.duplicated(keep="last")]
    assert len(e)>50 and e.index.max().year>=2025
    e.index=pd.DatetimeIndex(e.index).tz_convert("UTC").normalize()+pd.offsets.BDay(2)
    e=e.groupby(level=0).sum()
    start=pd.Timestamp("2010-01-01",tz="UTC")
    end=e.index.max().tz_convert("UTC")+pd.Timedelta(days=90)
    idx=pd.date_range(start=start,end=end,freq="D")
    shocks=e.reindex(idx,fill_value=0.)
    f=pd.DataFrame(index=idx)
    for n in [1,3,5,10,20,40]:
        f[f"fomc_decay_{n}"]=shocks.ewm(halflife=n,adjust=False).mean()
    # Separate positive and negative event pressure, rather than assuming symmetric impact.
    for n in [3,10,20]:
        f[f"hawk_{n}"]=shocks.clip(lower=0).ewm(halflife=n,adjust=False).mean()
        f[f"dove_{n}"]=(-shocks.clip(upper=0)).ewm(halflife=n,adjust=False).mean()
    return f,{"sheet":sheet,"column":str(col),"n":len(e),"first_available":str(e.index.min()),"last_available":str(e.index.max()),"sha256":hashlib.sha256(raw).hexdigest(),"url":FOMC}
def side_metrics(y,mask,s):
    n=int(mask.sum());k=int((y[mask]==s).sum())
    return {"n":n,"correct":k,"accuracy":k/n if n else None,"lower95":wilson(k,n) if n else None}
def choose(curr,metric,key,mask,nmin):
    if metric["n"]<nmin:return curr
    rank=(metric["lower95"],metric["n"])
    if curr is None or rank>curr[0]:return (rank,key,mask)
    return curr
def run():
    parts,meta=treasury_fallback()
    assert len(parts)>=2,"Insufficient Treasury data"
    try:
        fp,fmeta=fomc_fixed();parts.append(fp)
    except Exception as e:fmeta={"error":repr(e)}
    manifest={"treasury":meta,"fomc":fmeta}
    O.joinpath("r18-source-manifest.json").write_text(json.dumps(manifest,indent=2))
    print(json.dumps({"fomc":fmeta}),flush=True)
    results={}
    for tf in ["1h","4h","1D","1W"]:
        d,z,_,y,valid,times=load_tf(tf)
        p=features(z)
        if tf in ("1D","1W"):p=p.drop(columns=[c for c in p if c.startswith("hour_")])
        m=align(parts,times,d.index)
        valid &= p.notna().all(axis=1).to_numpy() & m.notna().all(axis=1).to_numpy()
        groups={"technical":p,"macro":m,"hybrid":pd.concat([p,m],axis=1)}
        if "fomc_decay_1" in m:
            m0=m[[c for c in m if not c.startswith(("fomc_","hawk_","dove_"))]]
            groups["hybrid_no_fomc"]=pd.concat([p,m0],axis=1)
        mat={k:v.to_numpy(float) for k,v in groups.items()}
        mature=pd.Series(times,index=d.index).shift(-1)
        nmin={"1h":80,"4h":40,"1D":25,"1W":10}[tf]
        mintrain={"1h":500,"4h":200,"1D":150,"1W":70}[tf]
        cuts=[.50,.52,.55,.58,.60,.65,.70,.75]
        agg=[];rows=[];rules=0;fits=0
        for yr in (range(2022,2027) if tf in ("1h","4h") else range(2018,2027)):
            b=pd.Timestamp(f"{yr}-01-01",tz="UTC");vstart=b-pd.DateOffset(years=1);end=b+pd.DateOffset(years=1)
            va=valid&(times>=vstart)&(times<b)&(mature<b).to_numpy()
            te=valid&(times>=b)&(times<end)&(mature<end).to_numpy()
            if min(va.sum(),te.sum())<nmin*2:continue
            best=[None,None];shared=None
            for group,x in mat.items():
                for years,C in itertools.product([3,6,10],[.01,.1,1.]):
                    tr=valid&(times>=vstart-pd.DateOffset(years=years))&(mature<vstart).to_numpy()
                    if tr.sum()<mintrain or len(np.unique(y[tr]))<2:continue
                    mod=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
                    mod.fit(x[tr],y[tr]);fits+=1
                    pv=mod.predict_proba(x[va])[:,1];pt=mod.predict_proba(x[te])[:,1]
                    for cut in cuts:
                        vb=pv>=cut;vs=pv<.5 if cut==.5 else pv<=1-cut
                        tb=pt>=cut;ts=pt<.5 if cut==.5 else pt<=1-cut
                        key={"group":group,"years":years,"C":C,"cut":cut}
                        buy=side_metrics(y[va],vb,1);sell=side_metrics(y[va],vs,0)
                        best[1]=choose(best[1],buy,{**key,"validation":buy},tb,nmin)
                        best[0]=choose(best[0],sell,{**key,"validation":sell},ts,nmin)
                        rules+=2
                        if min(buy["n"],sell["n"])>=nmin:
                            q=(min(buy["lower95"],sell["lower95"]),buy["n"]+sell["n"])
                            if shared is None or q>shared[0]:shared=(q,key,tb,ts)
            buy=best[1][2] if best[1] else np.zeros(te.sum(),bool)
            sell=best[0][2] if best[0] else np.zeros(te.sum(),bool)
            conflicts=buy&sell
            sb=shared[2] if shared else np.zeros(te.sum(),bool)
            ss=shared[3] if shared else np.zeros(te.sum(),bool)
            yy=y[te]
            row={"year":yr,"n":int(te.sum()),"buy_rule":best[1][1] if best[1] else None,
                 "sell_rule":best[0][1] if best[0] else None,"conflicts":int(conflicts.sum()),
                 "independent_raw":{"BUY":side_metrics(yy,buy,1),"SELL":side_metrics(yy,sell,0)},
                 "independent_resolved":score(yy,buy&~sell,sell&~buy,np.ones(len(yy),bool)),
                 "shared_rule":shared[1] if shared else None,
                 "shared":score(yy,sb,ss,np.ones(len(yy),bool)),
                 "always_buy":float(yy.mean())}
            rows.append(row);agg.append((yy,buy,sell,sb,ss))
        assert agg,tf
        yy,b,s,sb,ss=[np.concatenate([r[i] for r in agg]) for i in range(5)]
        r={"n":len(yy),"rules_evaluated":rules,"fits":fits,"conflicts":int((b&s).sum()),
           "raw":{"BUY":side_metrics(yy,b,1),"SELL":side_metrics(yy,s,0)},
           "independent":score(yy,b&~s,s&~b,np.ones(len(yy),bool)),
           "shared":score(yy,sb,ss,np.ones(len(yy),bool)),"always_buy":float(yy.mean()),
           "annual":rows}
        results[tf]=r
        print(json.dumps({"tf":tf,**{k:v for k,v in r.items() if k!="annual"}}),flush=True)
    O.joinpath("r18-asymmetric.json").write_text(json.dumps({"results":results,"source_manifest":manifest,
        "limits":["Selection per side only on preceding year, training labels purged before validation; all historical evaluation reused",
        "FOMC proxy is event window 2Y yield change, delayed two weekdays; no exact PIT vintage or pre-release prediction",
        "No CPI/NFP surprise, DXY, or trade P&L; historical current Treasury vintage",
        "Independent heads are separately chosen rules for complementary binary event; cannot interpret outputs as jointly calibrated probabilities",
        "Conflicting signals become WAIT; raw head metrics are not combined executable decisions"]},indent=2))
if __name__=="__main__":run()
