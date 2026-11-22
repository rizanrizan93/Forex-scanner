"""BTC B1: eight independent direction heads; Bitstamp archived verified seed.
Research only, no broker, no entry zones, no execution. 24/7 UTC candles.
"""
import argparse,gzip,hashlib,itertools,json
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from fx_scanner.btc_native_readonly import validate_seed,SEED_HASH,SEED_END
O=Path("artifacts");O.mkdir(exist_ok=True)
SEED=Path("repairs/buy050_identity_20261108/bridge/BTC_SEED_PACKET.json.gz")
TF={"H1":1,"H4":4,"D1":24,"W1":168}
def load(tf):
    raw=SEED.read_bytes();pkt=json.loads(gzip.decompress(raw));rows=validate_seed(pkt)
    d=pd.DataFrame(rows,columns=["at","o","h","l","c","n"])
    d.index=pd.to_datetime(d.pop("at"),unit="s",utc=True)
    d=d[d.n==60].copy()
    # Weekly opens Monday 00:00 UTC; epoch anchored at Monday 1970-01-05.
    h=TF[tf];freq=f"{h}h";origin=pd.Timestamp("1970-01-05",tz="UTC")
    a=d.resample(freq,origin=origin,label="left",closed="left").agg(o=("o","first"),h=("h","max"),l=("l","min"),c=("c","last"),count=("n","count"))
    a=a[(a["count"]==h)&(a.index+pd.Timedelta(hours=h)<=pd.Timestamp(SEED_END,unit="s",tz="UTC"))].dropna()
    times=a.index+pd.Timedelta(hours=h)
    gaps=pd.Series(times,index=a.index).shift(-1)-pd.Series(times,index=a.index)
    y=(a.c.shift(-1)>a.c).to_numpy(int)
    valid=(gaps==pd.Timedelta(hours=h)).to_numpy()&(a.c.shift(-1).ne(a.c).to_numpy())
    return a,times,y,valid,{"seed_sha256":SEED_HASH,"gzip_sha256":hashlib.sha256(raw).hexdigest(),"source":"BITSTAMP_BTCUSD_M1 aggregated verified H1 seed (spot; not broker CFD)","seed_rows":len(rows),"through":str(pd.Timestamp(SEED_END,unit="s",tz="UTC"))}
def feats(d,times):
    pc=d.c.shift();tr=pd.concat([d.h-d.l,(d.h-pc).abs(),(d.l-pc).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean().replace(0,np.nan)
    ret=np.log(d.c).diff();o=pd.DataFrame(index=d.index)
    for k in (1,2,3,5,10,20):
        o[f"ret{k}"]=np.log(d.c/d.c.shift(k))
    for k in (8,21,48):
        o[f"ema{k}"]=(d.c-d.c.ewm(span=k,adjust=False,min_periods=k).mean())/atr
    o["atr_pct"]=atr/d.c;o["vol20"]=ret.rolling(20).std()
    o["body"]=(d.c-d.o)/atr;o["close_loc"]=(d.c-d.l)/(d.h-d.l).replace(0,np.nan)
    o["wick_top"]=(d.h-np.maximum(d.o,d.c))/atr;o["wick_bottom"]=(np.minimum(d.o,d.c)-d.l)/atr
    s=pd.DataFrame(index=d.index)
    for k in (5,10,20,40):
        hi=d.h.shift().rolling(k).max();lo=d.l.shift().rolling(k).min()
        s[f"dist_high{k}"]=(d.c-hi)/atr;s[f"dist_low{k}"]=(d.c-lo)/atr
        s[f"sweep_high{k}"]=((d.h>hi)&(d.c<hi)).astype(float)
        s[f"sweep_low{k}"]=((d.l<lo)&(d.c>lo)).astype(float)
        s[f"range_loc{k}"]=(d.c-lo)/(hi-lo).replace(0,np.nan)
    s["bull_fvg"]=(d.l-d.h.shift(2)).clip(lower=0)/atr
    s["bear_fvg"]=(d.l.shift(2)-d.h).clip(lower=0)/atr
    s["compression"]=(d.h-d.l).rolling(4).mean()/atr
    t=pd.DataFrame(index=d.index)
    t["weekend"]=(times.dayofweek>=5).astype(float)
    t["weekday_sin"]=np.sin(2*np.pi*times.dayofweek/7);t["weekday_cos"]=np.cos(2*np.pi*times.dayofweek/7)
    t["hour_sin"]=np.sin(2*np.pi*times.hour/24);t["hour_cos"]=np.cos(2*np.pi*times.hour/24)
    return {"price":o,"structure":pd.concat([o,s],axis=1),"structure_24x7":pd.concat([o,s,t],axis=1)}
def met(y,mask,side):
    n=int(mask.sum());k=int((y[mask]==side).sum())
    if not n:return {"n":0,"correct":0,"accuracy":None,"lower95":None}
    p=k/n;z=1.95996398454
    lo=(p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)
    return {"n":n,"correct":k,"accuracy":p,"lower95":float(lo)}
def summary(y,b,s):
    B=b&~s;S=s&~b
    return {"BUY":met(y,B,1),"SELL":met(y,S,0),"raw_BUY":met(y,b,1),"raw_SELL":met(y,s,0),"conflicts":int((b&s).sum()),"coverage":float((B|S).mean()),"base_buy":float(y.mean()),"eligible":len(y)}
def run(tf):
    d,times,y,valid,manifest=load(tf);groups=feats(d,times)
    for key in groups:
        for i in np.linspace(55,len(d)-1,16,dtype=int):
            v=feats(d.iloc[:i+1],times[:i+1])[key].iloc[-1].to_numpy()
            assert np.allclose(v,groups[key].iloc[i].to_numpy(),equal_nan=True,atol=1e-10,rtol=1e-10),(tf,key,i)
    for f in groups.values():valid &= np.isfinite(f.to_numpy()).all(axis=1)
    mature=pd.Series(times,index=d.index).shift(-1)
    mintrain={"H1":500,"H4":250,"D1":120,"W1":55}[tf];minval={"H1":100,"H4":40,"D1":25,"W1":12}[tf]
    pred={g:[] for g in groups};annual=[];fits=rules=0
    gates={"all":np.ones(len(d),bool)}
    if tf in ("H1","H4"):
        gates["weekend"]=times.dayofweek>=5;gates["weekday"]=times.dayofweek<5
        gates["asia_utc"]=(times.hour>=0)&(times.hour<8);gates["europe_utc"]=(times.hour>=8)&(times.hour<16);gates["us_utc"]=(times.hour>=16)
    for yr in range(2023,2027):
        start=pd.Timestamp(f"{yr}-01-01",tz="UTC");vs=start-pd.DateOffset(years=1);end=start+pd.DateOffset(years=1)
        va=valid&(times>=vs)&(times<start)&(mature<start).to_numpy()
        te=valid&(times>=start)&(times<end)&(mature<end).to_numpy()
        if min(va.sum(),te.sum())<2*minval:continue
        row={"year":yr,"eligible":int(te.sum()),"policies":{}}
        for name,f in groups.items():
            x=f.to_numpy(float);chosen=[None,None]
            for side,years,family in itertools.product((0,1),(2,4),("ridge","logit","hgb")):
                tr=valid&(times>=vs-pd.DateOffset(years=years))&(mature<vs).to_numpy()
                if tr.sum()<mintrain or len(np.unique(y[tr]))<2:continue
                model=HistGradientBoostingClassifier(max_iter=60,max_depth=2,max_leaf_nodes=5,l2_regularization=15,random_state=28) if family=="hgb" else make_pipeline(StandardScaler(),LogisticRegression(C=.025 if family=="ridge" else .3,max_iter=500))
                model.fit(x[tr],(y[tr]==side).astype(int));fits+=1
                pv=model.predict_proba(x[va])[:,1];pt=model.predict_proba(x[te])[:,1]
                for th,g in itertools.product((.5,.53,.56,.60,.65,.70,.75,.80),gates):
                    rules+=1
                    mask=(pv>=th)&gates[g][va];m=met(y[va],mask,side)
                    if m["n"]<minval:continue
                    rank=(m["lower95"],m["n"])
                    if chosen[side] is None or rank>chosen[side][0]:
                        chosen[side]=(rank,(pt>=th)&gates[g][te],{"years":years,"family":family,"threshold":th,"gate":g,"validation":m})
            b=chosen[1][1] if chosen[1] else np.zeros(te.sum(),bool);s=chosen[0][1] if chosen[0] else np.zeros(te.sum(),bool)
            yy=y[te];pred[name].append((yy,b,s));row["policies"][name]={"BUY_config":chosen[1][2] if chosen[1] else None,"SELL_config":chosen[0][2] if chosen[0] else None,**summary(yy,b,s)}
        annual.append(row)
    aggregate={}
    for name,arr in pred.items():
        if arr:aggregate[name]=summary(*[np.concatenate([r[i] for r in arr]) for i in range(3)])
    report={"version":"BTC B1","tf":tf,"source":manifest,"fits":fits,"rules":rules,"prefix_checks":48,"aggregate":aggregate,"annual":annual,"features":{k:list(v.columns) for k,v in groups.items()},"limits":["Spot Bitstamp not FP Markets CFD","Seed through Oct 2026, no current quote or future predictions","No funding/OI/ETF/macro in B1; next experiments need verified PIT","Historical exploratory replay only, not untouched forward evidence","Direction is not trading P&L; conflicts WAIT","No LIVE or zone execution"]}
    O.joinpath(f"btc-b1-{tf}.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ("annual","features")}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--tf",choices=list(TF),required=True);run(p.parse_args().tf)
