"""R28.1: official ECB daily USD basket context, matched samples.
New information, not replacement for missing true intraday FX. Research only.
"""
import argparse, hashlib, io, json, time
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np,pandas as pd,requests
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r18_asymmetric_direction import side_metrics
from r25_eight_specialists import macro_sources,setup
O=Path("artifacts");O.mkdir(exist_ok=True)
CURRENCIES=["USD","JPY","GBP","CAD","CHF","SEK"]
XML="https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
API="https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+GBP+CAD+CHF+SEK.EUR.SP00.A?startPeriod=2018-01-01&endPeriod=2025-12-31&format=csvdata"
def acquire():
    errors=[]
    for url in (XML,API):
        for attempt in range(3):
            try:
                r=requests.get(url,timeout=(10,60));r.raise_for_status()
                raw=r.content
                if url==XML:
                    rows=[]
                    for e in ET.fromstring(raw).iter():
                        if "time" not in e.attrib:continue
                        row={"date":e.attrib["time"]}
                        for c in e:
                            if c.attrib.get("currency") in CURRENCIES:row[c.attrib["currency"]]=float(c.attrib["rate"])
                        rows.append(row)
                    d=pd.DataFrame(rows).set_index("date")
                else:
                    t=pd.read_csv(io.BytesIO(raw))
                    d=t.pivot(index="TIME_PERIOD",columns="CURRENCY",values="OBS_VALUE")
                d.index=pd.to_datetime(d.index,utc=True)
                d=d.sort_index().loc["2018":"2025",CURRENCIES].astype(float)
                assert not d.index.duplicated().any()
                assert np.isfinite(d.to_numpy()).all() and d.gt(0).all().all()
                counts=d.groupby(d.index.year).size()
                assert set(counts.index)==set(range(2018,2026)) and counts.min()>=235,counts.to_dict()
                assert .75<d.USD.median()<1.8 and 100<d.JPY.median()<200
                p=O/"r281-ecb.csv";d.to_csv(p)
                m={"url":url,"data":"ECB daily reference rates per EUR","raw_sha256":hashlib.sha256(raw).hexdigest(),"csv_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"annual_rows":{str(k):int(v) for k,v in counts.items()},"availability":"next calendar day 00:00 UTC, conservative proxy","errors":errors,"pit":False}
                O.joinpath("r281-ecb.json").write_text(json.dumps(m,indent=2));print(json.dumps(m),flush=True);return
            except Exception as exc:
                errors.append({"url":url,"attempt":attempt+1,"error":repr(exc)});time.sleep(2**attempt)
    O.joinpath("r281-source-failure.json").write_text(json.dumps(errors,indent=2))
    raise RuntimeError("Both official ECB routes failed")
def loadfx():
    p=Path("/tmp/r281/r281-ecb.csv");m=json.loads(p.with_suffix(".json").read_text())
    assert hashlib.sha256(p.read_bytes()).hexdigest()==m["csv_sha256"]
    return pd.read_csv(p,index_col=0,parse_dates=True)
def source_features(fx):
    log=np.log(fx)
    # Dollar strength against EUR and the other five currencies; equal weights.
    x=pd.DataFrame({"EUR":-log.USD},index=fx.index)
    for c in CURRENCIES[1:]:x[c]=log[c]-log.USD
    basket=x.mean(axis=1)
    f=pd.DataFrame(index=x.index)
    for lag in (1,3,5,10,20):
        r=x.diff(lag)
        f[f"usd_basket_{lag}"]=basket.diff(lag)
        f[f"usd_breadth_{lag}"]=(r.gt(0).sum(axis=1)-r.lt(0).sum(axis=1))/6
        f[f"usd_dispersion_{lag}"]=r.std(axis=1)
        f[f"eur_jpy_div_{lag}"]=r.EUR-r.JPY
    f["usd_vol20"]=basket.diff().rolling(20).std()
    f["usd_trend"]=basket-basket.ewm(span=20,adjust=False).mean()
    f.index=f.index+pd.Timedelta(days=1)
    return f
def cross(fx,d,times,tf):
    f=source_features(fx)
    # Explicit prefix invariance on source features, never use future data.
    for i in np.linspace(30,len(fx)-1,16,dtype=int):
        a=source_features(fx.iloc[:i+1]).iloc[-1].to_numpy()
        assert np.allclose(a,f.iloc[i].to_numpy(),equal_nan=True,rtol=1e-10,atol=1e-10)
    f["available_at"]=f.index
    z=f.reindex(times,method="ffill",tolerance=pd.Timedelta(days=5))
    age=times-pd.DatetimeIndex(z.pop("available_at"))
    assert ((age>=pd.Timedelta(0))|pd.isna(age)).all()
    z.index=d.index
    return z
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
            aggregate[name]=metrics(yy,b,s,sum(r["market"] for r in annual))
    report={"tf":tf,"status":"EXPLORATORY_COMPLETE" if aggregate else "NO_VALID_FOLDS","fits":fits,"rules":rules,"aggregate":aggregate,"annual":annual,"market_scope":"2019-2025, evaluation 2023-2025","limits":["ECB daily reference basket, not DXY or intraday FX/yield","Availability next UTC day; bounded backward join, latest vintage not exact PIT","Annual 80% matched-data gate predeclared","Historical folds reused, no forward validation","No entry zone or LIVE permission"]}
    O.joinpath(f"r281-{tf}-{'macro' if sources else 'fx'}.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!="annual"}),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--acquire",action="store_true");p.add_argument("--tf",choices=["1h","4h","1D","1W"]);p.add_argument("--macro",action="store_true");a=p.parse_args()
    if a.acquire:acquire()
    else:run(a.tf,loadfx(),macro_sources() if a.macro else None)
