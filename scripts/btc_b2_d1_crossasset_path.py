"""BTC B2-D1: matched daily direction ablation, macro FX plus gold and intraday path.
Independent BUY/SELL heads. Prior-year selection; 2023-25 replay only.
"""
import sys,json,hashlib,glob,itertools
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from zq2_bz1_reaction_tournament import read_hour,aggregate,lower95
sys.path.insert(0,str(Path("frozen-btc/scripts").resolve()))
from btc_b1_direction import feats
O=Path("artifacts");O.mkdir(exist_ok=True)

def indicators(s,prefix):
    f=pd.DataFrame(index=s.index)
    for w in (1,3,5,10,20):f[prefix+str(w)]=np.log(s/s.shift(w))
    f[prefix+"vol20"]=np.log(s).diff().rolling(20).std()
    return f

def align(f,times,maxdays):
    return f.reindex(times,method="ffill",tolerance=pd.Timedelta(days=maxdays))

def inputs():
    a,source=read_hour("BTC");d=aggregate(a,"BTC","D1");times=d.index+pd.Timedelta(days=1)
    b=feats(d,times)["structure"]
    # Completed H1 history already within the D1 anchor. 24 subbars mandatory in source.
    H=np.stack([a.reindex(d.index+pd.Timedelta(hours=i)).to_numpy(float) for i in range(24)],axis=1)
    o,h,l,c=[H[:,:,i] for i in range(4)];atr=(d.h-d.l).rolling(14).mean().to_numpy()
    q=pd.DataFrame(index=d.index)
    for j in range(4):
        k=6*j;q["sixhour_ret"+str(j)]=np.log(c[:,k+5]/o[:,k])
        q["sixhour_range"+str(j)]=(h[:,k:k+6].max(1)-l[:,k:k+6].min(1))/atr
    q["high_hour"]=np.argmax(h,axis=1)/23;q["low_hour"]=np.argmin(l,axis=1)/23
    q["up_fraction"]=(c>o).mean(axis=1)
    q["late_reversal"]=(c[:,11]-o[:,0])*(c[:,23]-c[:,11])/atr**2
    q["hourly_vol"]=np.std(np.log(c[:,1:]/c[:,:-1]),axis=1)
    q["weekend"]=times.dayofweek>=5
    # ECB verified prior artifact; never use same-day reference fix before known timestamp.
    p=Path("/tmp/r281/r281-ecb.csv");manifest=json.loads(p.with_suffix(".json").read_text())
    assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest["csv_sha256"]
    fx=pd.read_csv(p,index_col=0,parse_dates=True);log=np.log(fx)
    usd=pd.DataFrame({"EUR":-log.USD},index=fx.index)
    for k in ("JPY","GBP","CAD","CHF","SEK"):usd[k]=log[k]-log.USD
    m=indicators(np.exp(usd.mean(axis=1)),"usd_")
    for w in (1,3,5,10):
        z=usd.diff(w);m["breadth"+str(w)]=(z.gt(0).sum(1)-z.lt(0).sum(1))/6;m["disp"+str(w)]=z.std(1)
    m.index+=pd.Timedelta(days=1)
    files=sorted(glob.glob("/tmp/r98/daily-*.csv"));assert len(files)==15
    gold=pd.concat([pd.read_csv(x,index_col=0,parse_dates=True) for x in files]).sort_index()
    assert gold.index.is_unique and gold.index.tz is not None
    g=indicators(gold.c,"gold_");g.index+=pd.Timedelta(days=1)
    # Align only completed previous daily OHLC. All values available no later than BTC decision.
    M=align(m,times,5);G=align(g,times,5);M.index=G.index=d.index
    macro=pd.concat([M,G],axis=1)
    # Prospective source-prefix audits for source-derived features.
    for k in np.linspace(40,len(usd)-1,16,dtype=int):
        check=indicators(np.exp(usd.iloc[:k+1].mean(1)),"usd_").iloc[-1]
        assert np.allclose(check,m.iloc[k][check.index],equal_nan=True)
    for k in np.linspace(40,len(gold)-1,16,dtype=int):
        z=indicators(gold.c.iloc[:k+1],"gold_").iloc[-1]
        assert np.allclose(z,g.iloc[k],equal_nan=True)
    for k in np.linspace(55,len(d)-1,16,dtype=int):
        z=feats(d.iloc[:k+1],times[:k+1])["structure"].iloc[-1]
        assert np.allclose(z,b.iloc[k],equal_nan=True)
    groups={"B1_structure":b,"intraday_path":pd.concat([b,q],axis=1),"macro_gold_fx":pd.concat([b,macro],axis=1),"combined":pd.concat([b,q,macro],axis=1)}
    groups={k:v.astype(float).replace([np.inf,-np.inf],np.nan) for k,v in groups.items()}
    future=d.c.shift(-1);mature=pd.Series(times,index=d.index).shift(-1)
    eligible=(times.year<=2025)&(times.year>=2019)&((mature-pd.Series(times,index=d.index))==pd.Timedelta(days=1)).to_numpy()&(future!=d.c).to_numpy()
    valid=eligible.copy()
    for f in groups.values():valid &= np.isfinite(f).all(1).to_numpy()
    return groups,(future>d.c).astype(int).to_numpy(),times,mature,eligible,valid,source
def metric(y,mask,side):
    n=int(mask.sum());k=int((y[mask]==side).sum())
    return {"n":n,"correct":k,"accuracy":k/n if n else None,"lower95":lower95(k,n) if n else None}
def score(y,b,s,market):
    B=b&~s;S=s&~b
    return {"BUY":metric(y,B,1),"SELL":metric(y,S,0),"conflicts":int((b&s).sum()),"coverage":float((B|S).sum()/market),"matched":len(y),"market":market}
def run():
    groups,y,times,mature,eligible,valid,source=inputs()
    records=[];samples={k:[] for k in groups};fits=rules=0
    for year in (2023,2024,2025):
        start=pd.Timestamp(f"{year}-01-01",tz="UTC");end=start+pd.DateOffset(years=1);vs=start-pd.DateOffset(years=1)
        tr=valid&(times<vs)&(mature<vs).to_numpy();va=valid&(times>=vs)&(times<start)&(mature<start).to_numpy()
        market=eligible&(times>=start)&(times<end)&(mature<end).to_numpy();te=valid&market
        if te.sum()<.8*market.sum() or tr.sum()<180 or va.sum()<100:
            records.append({"year":year,"status":"REJECT_DATA","market":int(market.sum()),"matched":int(te.sum())});continue
        row={"year":year,"market":int(market.sum()),"matched":int(te.sum()),"base_buy":float(y[te].mean()),"policies":{}}
        for name,f in groups.items():
            x=f.to_numpy();chosen={}
            for side in (0,1):
                best=None
                for family in ("ridge","logit","hgb"):
                    m=HistGradientBoostingClassifier(max_iter=60,max_depth=2,max_leaf_nodes=5,l2_regularization=15,random_state=28) if family=="hgb" else make_pipeline(StandardScaler(),LogisticRegression(C=.025 if family=="ridge" else .3,max_iter=500))
                    m.fit(x[tr],(y[tr]==side).astype(int));fits+=1
                    pv=m.predict_proba(x[va])[:,1];pt=m.predict_proba(x[te])[:,1]
                    for cut in (.5,.53,.56,.60,.65,.70,.75,.80):
                        rules+=1;z=metric(y[va],pv>=cut,side)
                        if z["n"]<25:continue
                        rank=(z["lower95"],z["n"])
                        if best is None or rank>best[0]:best=(rank,pt>=cut,{"family":family,"cut":cut,"validation":z})
                chosen[side]=best
            b=chosen[1][1] if chosen[1] else np.zeros(te.sum(),bool);s=chosen[0][1] if chosen[0] else np.zeros(te.sum(),bool)
            row["policies"][name]={"buy_config":chosen[1][2] if chosen[1] else None,"sell_config":chosen[0][2] if chosen[0] else None,**score(y[te],b,s,int(market.sum()))}
            samples[name].append((y[te],b,s))
        records.append(row)
    agg={}
    for k,arr in samples.items():
        if arr:agg[k]=score(*[np.concatenate([v[i] for v in arr]) for i in range(3)],sum(x["market"] for x in records))
    report={"version":"BTC B2 D1","source":source,"fits":fits,"rules":rules,"prefix_checks":48,"annual":records,"aggregate":agg,"limitations":["ECB USD proxy, not DXY; prior-day availability; not point-in-time vintage","Gold daily HistData, BTC spot Bitstamp, not broker CFD","Matched common rows, 2023-25 only, cannot compare B1 aggregate directly","No funding, OI, ETF data yet; historical research only"]}
    O.joinpath("btc-b2-d1.json").write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps(report,allow_nan=False),flush=True)
if __name__=="__main__":run()
