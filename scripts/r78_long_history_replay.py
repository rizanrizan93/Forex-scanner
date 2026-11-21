"""R7.8 pre-2025 long-history price-only intraday research, not execution."""
from pathlib import Path
import os,json,hashlib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

YEARS=list(range(2012,2025))
OUTER=list(range(2018,2025))
COST=.5
THRESHOLDS=(.50,.53,.56,.60,.65)
SPEC=(("LOGIT",3),("LOGIT",8),("TREE",3),("TREE",8))
def read_prices(root):
    frames=[]; sources=[]
    for year in YEARS:
        fs=list(Path(root).rglob(f"xauusd-h1-bid-{year}-01-01-*.csv"))
        assert len(fs)==1,(year,len(fs))
        p=fs[0]; m=json.loads(p.with_name("source.json").read_text())
        raw=p.read_bytes(); assert hashlib.sha256(raw).hexdigest()==m["sha256"]
        d=pd.read_csv(p)
        d["time"]=pd.to_datetime(d.timestamp,unit="ms",utc=True)
        d=d.loc[d.time.dt.year==year,["time","open","high","low","close"]]
        assert len(d)==m["rows"] and d.time.is_monotonic_increasing and not d.time.duplicated().any()
        frames.append(d);sources.append(m)
    d=pd.concat(frames).set_index("time").sort_index()
    assert not d.index.duplicated().any()
    return d,sources

def features(d,h):
    c=d.close;o=d.open;hi=d.high;lo=d.low
    atr=pd.concat([hi-lo,(hi-c.shift()).abs(),(lo-c.shift()).abs()],axis=1).max(axis=1).ewm(span=28,min_periods=28,adjust=False).mean()
    den=atr.replace(0,np.nan)
    f=pd.DataFrame(index=d.index)
    for k in (1,2,3,4,6,12,24,48,120):
        f[f"mom{k}"]=(c-c.shift(k))/den
    for k in (12,24,72):
        ema=c.ewm(span=k,adjust=False,min_periods=k).mean()
        f[f"ema{k}"]=(c-ema)/den
    for k in (6,24,72):
        upper=hi.shift().rolling(k).max(); lower=lo.shift().rolling(k).min()
        f[f"upper{k}"]=(c-upper)/den; f[f"lower{k}"]=(c-lower)/den
        f[f"sweep{k}"]=((lo<lower)&(c>lower)).astype(float)-((hi>upper)&(c<upper)).astype(float)
        f[f"position{k}"]=(c-lower)/(upper-lower).replace(0,np.nan)
    f["body"]=(c-o)/den
    f["upperwick"]=(hi-pd.concat([c,o],axis=1).max(axis=1))/den
    f["lowerwick"]=(pd.concat([c,o],axis=1).min(axis=1)-lo)/den
    f["atr_ratio"]=atr/atr.rolling(120,min_periods=120).median()
    f["range"]=(hi-lo)/den
    f["rv12"]=c.pct_change().rolling(12).std()*100
    f["rv48"]=c.pct_change().rolling(48).std()*100
    decision=d.index+pd.Timedelta(hours=1)
    wib=decision.tz_convert("Asia/Jakarta");lon=decision.tz_convert("Europe/London");ny=decision.tz_convert("America/New_York")
    for name,t in (("wib",wib),("lon",lon),("ny",ny)):
        f[name+"_sin"]=np.sin(2*np.pi*t.hour/24);f[name+"_cos"]=np.cos(2*np.pi*t.hour/24)
    f["day_sin"]=np.sin(2*np.pi*wib.dayofweek/7);f["day_cos"]=np.cos(2*np.pi*wib.dayofweek/7)
    # outcome: OPEN next hourly bar to CLOSE of h-th next hour; no weekend/gap bridging
    target=c.shift(-h)-o.shift(-1)
    end=pd.Series(d.index,index=d.index).shift(-h)
    complete=end.eq(pd.Series(d.index,index=d.index)+pd.Timedelta(hours=h))
    f=f.replace([np.inf,-np.inf],np.nan)
    valid=complete & f.notna().all(axis=1) & target.notna()
    return f[valid].clip(-20,20),target[valid].to_numpy(),decision[valid.to_numpy()]

def masks(time,h):
    hour=time.tz_convert("Asia/Jakarta").hour
    result={f"WIB{n:02d}":np.asarray(hour==n) for n in range(24)}
    if h==1:
        result.update({"ALL":np.ones(len(time),bool),"ASIA":(hour>=8)&(hour<13),"LONDON_WIB":(hour>=14)&(hour<19),"NY_WIB":(hour>=19)&(hour<24)})
    else:
        for phase in range(4):result[f"PHASE{phase}"]=np.asarray(hour%4==phase)
    return result

def metrics(p,move,mask,th):
    side=np.where(p>=th,1,np.where(p<=1-th,-1,0))
    if th==.5:side=np.where(p>=.5,1,-1)
    side=np.where(mask,side,0)
    b=side==1;s=side==-1; n=b|s
    win=side*move>COST
    return {"buy":int(b.sum()),"sell":int(s.sum()),"buy_correct":int((b&win).sum()),"sell_correct":int((s&win).sum()),"n":int(n.sum()),"correct":int((n&win).sum()),"opportunities":int(mask.sum()),"mean_move":float((side[n]*move[n]-COST).mean()) if n.any() else None}
def lower(k,n):
    if not n:return 0.
    z=1.645;p=k/n
    return (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
def rank(m,h):
    minside=30 if h==1 else 25
    if min(m["buy"],m["sell"])<minside or m["mean_move"] is None or m["mean_move"]<=0:return None
    return min(lower(m["buy_correct"],m["buy"]),lower(m["sell_correct"],m["sell"]))
def model(kind):
    if kind=="LOGIT":return make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=200))
    return HistGradientBoostingClassifier(max_iter=65,max_leaf_nodes=9,min_samples_leaf=100,l2_regularization=5,random_state=78)
def replay(d,h):
    x,y,t=features(d,h)
    arr=x.to_numpy();yr=np.asarray(t.year);out=[]
    target=(y>0).astype(int)
    for year in OUTER:
        # select on preceding calendar year, train to end of year before validation
        valyear=year-1
        v=(yr==valyear)&(t+pd.Timedelta(hours=h)<pd.Timestamp(f"{year}-01-01",tz="UTC"))
        e=(yr==year)&(t+pd.Timedelta(hours=h)<pd.Timestamp(f"{year+1}-01-01",tz="UTC"))
        valmask=masks(t[v],h); emask=masks(t[e],h)
        best=None;diagnostic=None;count=0
        for kind,lookback in SPEC:
            tr=(yr>=max(2012,valyear-lookback))&(t+pd.Timedelta(hours=h)<pd.Timestamp(f"{valyear}-01-01",tz="UTC"))
            if tr.sum()<2000:continue
            m=model(kind);m.fit(arr[tr],target[tr]);p=m.predict_proba(arr[v])[:,1]
            for clock,mask in valmask.items():
                for th in THRESHOLDS:
                    q=metrics(p,y[v],mask,th);count+=1
                    score=rank(q,h)
                    if score is None:continue
                    z=(score,q["n"],-th)
                    if best is None or z>best[0]:best=(z,kind,lookback,clock,th,q)
        if best is None:
            out.append({"year":year,"status":"WAIT","configs":count});continue
        _,kind,lookback,clock,th,vstats=best
        tr=(yr>=max(2012,year-lookback))&(t+pd.Timedelta(hours=h)<pd.Timestamp(f"{year}-01-01",tz="UTC"))
        # Refit same locked model family on preceding years only.
        m=model(kind);m.fit(arr[tr],target[tr]);p=m.predict_proba(arr[e])[:,1]
        stats=metrics(p,y[e],emask[clock],th)
        row={"year":year,"status":"DEV","configs":count,"model":kind,"lookback_years":lookback,"clock":clock,"threshold":th,"inner":vstats,"outer":stats}
        out.append(row);print("R78_FOLD",h,json.dumps(row),flush=True)
    totals={k:sum(q.get("outer",{}).get(k,0) for q in out) for k in ("buy","sell","buy_correct","sell_correct","n","correct","opportunities")}
    return {"horizon_hours":h,"rows":len(x),"folds":out,"totals":totals,"configs":sum(q["configs"] for q in out)}
def run():
    d,source=read_prices(os.environ["R78_ROOT"])
    result={"contract":"R78_LONG_HOURLY_PRICE_ONLY_RESEARCH","years":YEARS,"outer_years":OUTER,"source":source,"historical_macro_used":False,"cost_assumed_usd_oz":COST,"fresh_untouched_holdout":False,"live_authority":False,"results":[replay(d,4),replay(d,1)]}
    p=Path("artifacts/r78-long-history-results.json");p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(result,indent=2,allow_nan=False));print("R78_TOTALS",json.dumps([{"h":r["horizon_hours"],"totals":r["totals"],"configs":r["configs"]} for r in result["results"]]),flush=True)
if __name__=="__main__":run()
