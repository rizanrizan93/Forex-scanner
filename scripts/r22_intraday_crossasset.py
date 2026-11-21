"""R22 cross-asset directional ablation, OHLC + FX dollar proxies.
Data: Dukascopy H1 BID candles for EURUSD/USDJPY, monthly BI5.
Not DXY, not yields, no entry zones, no broker/production changes.
Use completed FX candles only, with one extra hour delay to avoid
assuming simultaneous close availability. Match samples for all lanes.
"""
import hashlib, itertools, json, lzma, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np,pandas as pd,requests
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from r14_multitimeframe_direction import load_tf
from r21_horizon_specialists import price_specialist
from r18_asymmetric_direction import side_metrics
from r15_direction_tournament import score
O=Path("artifacts");O.mkdir(exist_ok=True)
SYMS={"EURUSD":100000,"USDJPY":1000}
DT=np.dtype([("sec",">u4"),("o",">u4"),("c",">u4"),("l",">u4"),("h",">u4"),("v",">f4")])
def getmonth(job):
    sym,yr,mo=job
    url=f"https://datafeed.dukascopy.com/datafeed/{sym}/{yr}/{mo-1:02d}/BID_candles_hour_1.bi5"
    why=None
    for attempt in range(3):
        try:
            r=requests.get(url,timeout=(8,25),headers={"User-Agent":"research/1.0"});r.raise_for_status()
            raw=r.content;buf=lzma.decompress(raw)
            assert len(buf)%24==0
            a=np.frombuffer(buf,dtype=DT)
            assert len(a)>200
            start=pd.Timestamp(year=yr,month=mo,day=1,tz="UTC")
            end=start+pd.offsets.MonthBegin(1)
            ts=start+pd.to_timedelta(a["sec"].astype(np.int64),unit="s")
            assert (ts>=start).all() and (ts<end).all() and (ts.minute==0).all()
            assert not ts.duplicated().any()
            good=(a["o"]>0)&(a["l"]>0)&(a["h"]>=a["o"])&(a["h"]>=a["c"])&(a["l"]<=a["o"])&(a["l"]<=a["c"])&(a["v"]>0)
            step=pd.Series(a["c"][good].astype(float)/SYMS[sym],index=ts[good],name=sym)
            med=float(step.median())
            assert (0.75<med<1.8 if sym=="EURUSD" else 60<med<220),med
            assert len(step)>200
            return sym,step,{"symbol":sym,"month":f"{yr}-{mo:02d}","url":url,"n":len(step),"sha256":hashlib.sha256(raw).hexdigest()}
        except Exception as e:
            why=repr(e);time.sleep(attempt+.25)
    return sym,None,{"symbol":sym,"month":f"{yr}-{mo:02d}","url":url,"error":why}
def download():
    months=pd.period_range("2019-01","2026-10",freq="M")
    jobs=[(sym,m.year,m.month) for sym in SYMS for m in months]
    with ThreadPoolExecutor(max_workers=6) as p:rs=list(p.map(getmonth,jobs))
    manifest=[m for _,_,m in rs]
    O.joinpath("r22-fx-manifest.json").write_text(json.dumps(manifest,indent=2))
    fx={}
    for sym in SYMS:
        arr=[v for s,v,_ in rs if s==sym and v is not None]
        assert len(arr)>=.90*len(months),(sym,len(arr))
        c=pd.concat(arr).sort_index()
        c=c[~c.index.duplicated(keep="last")]
        assert c.index.year.min()==2019 and c.index.year.max()==2026
        fx[sym]=c
        print(json.dumps({"source":sym,"n":len(c),"months":len(arr),"first":str(c.index.min()),"last":str(c.index.max())}),flush=True)
    return fx
def xfeatures(fx,times,index):
    out=pd.DataFrame(index=index)
    # At decision timestamp, use FX bar opening 2h earlier (closed 1h earlier).
    anchor=times-pd.Timedelta(hours=2)
    for sym,c in fx.items():
        now=c.reindex(anchor).to_numpy(float)
        for lag in [1,2,4,8,12,24,48]:
            old=c.reindex(anchor-pd.Timedelta(hours=lag)).to_numpy(float)
            out[f"{sym}_ret{lag}"]=np.log(now/old)*(-1 if sym=="EURUSD" else 1)
    for lag in [1,2,4,8,12,24,48]:
        a=out[f"EURUSD_ret{lag}"];b=out[f"USDJPY_ret{lag}"]
        out[f"usd_mean{lag}"]=(a+b)/2
        out[f"usd_div{lag}"]=a-b
        out[f"usd_agreement{lag}"]=np.sign(a)+np.sign(b)
    return out.replace([np.inf,-np.inf],np.nan)
def run(tf,fx):
    d,z,_,y,valid,times=load_tf(tf)
    p,_=price_specialist(d,z,tf)
    x=xfeatures(fx,times,d.index)
    # Do not exclude weekends merely by demanding every 48h lag:
    # shorter and longer features evaluated on common exact-match sample.
    valid &= p.notna().all(axis=1).to_numpy() & x.notna().all(axis=1).to_numpy()
    groups={"price":p,"fx":x,"price_fx":pd.concat([p,x],axis=1)}
    mature=pd.Series(times,index=d.index).shift(-1)
    mi=50 if tf=="1h" else 25
    rows={k:[] for k in groups};preds={k:[] for k in groups};fits=rules=0
    for yr in range(2022,2027):
        b=pd.Timestamp(f"{yr}-01-01",tz="UTC");vs=b-pd.DateOffset(years=1);end=b+pd.DateOffset(years=1)
        va=valid&(times>=vs)&(times<b)&(mature<b).to_numpy()
        te=valid&(times>=b)&(times<end)&(mature<end).to_numpy()
        if min(va.sum(),te.sum())<2*mi:continue
        for name,g in groups.items():
            a=g.to_numpy(float);chosen=[None,None]
            for years,C in itertools.product([2,4,8],[.01,.1,1]):
                tr=valid&(times>=vs-pd.DateOffset(years=years))&(mature<vs).to_numpy()
                if tr.sum()<200 or len(np.unique(y[tr]))<2:continue
                mod=make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500))
                mod.fit(a[tr],y[tr]);fits+=1
                pv=mod.predict_proba(a[va])[:,1];pt=mod.predict_proba(a[te])[:,1]
                for th in [.5,.52,.55,.58,.6,.65,.7]:
                    for side in (0,1):
                        rules+=1
                        v=pv>=th if side else (pv<.5 if th==.5 else pv<=1-th)
                        t=pt>=th if side else (pt<.5 if th==.5 else pt<=1-th)
                        m=side_metrics(y[va],v,side)
                        if m["n"]<mi:continue
                        rank=(m["lower95"],m["n"])
                        if chosen[side] is None or rank>chosen[side][0]:chosen[side]=(rank,t,{"years":years,"C":C,"threshold":th,"validation":m})
            buy=chosen[1][1] if chosen[1] else np.zeros(te.sum(),bool)
            sell=chosen[0][1] if chosen[0] else np.zeros(te.sum(),bool)
            B=buy&~sell;S=sell&~buy
            rows[name].append({"year":yr,"buy_rule":chosen[1][2] if chosen[1] else None,"sell_rule":chosen[0][2] if chosen[0] else None,"conflicts":int((buy&sell).sum()),"metrics":score(y[te],B,S,np.ones(te.sum(),bool))})
            preds[name].append((y[te],B,S))
    agg={}
    for name,ls in preds.items():
        assert ls,(tf,name,"no qualified folds")
        yy,b,s=[np.concatenate([r[i] for r in ls]) for i in range(3)]
        agg[name]=score(yy,b,s,np.ones(len(yy),bool))
    out={"tf":tf,"matched_n":len(yy),"base_buy":float(yy.mean()),"fits":fits,"rule_evals":rules,"aggregate":agg,"annual":rows,
         "limits":["EURUSD/USDJPY directional proxy only; not DXY","FX bar close delayed 1h, exact timestamp joins without forward fill","Sample excludes missing 48h lag or other invalid data, not equivalent to full-market coverage","Historical evaluation reused, not forward validation","No CPI/NFP consensus or intraday yield"]}
    O.joinpath(f"r22-crossasset-{tf}.json").write_text(json.dumps(out,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k!="annual"}),flush=True)
if __name__=="__main__":
    fx=download()
    for tf in ["1h","4h"]:run(tf,fx)
