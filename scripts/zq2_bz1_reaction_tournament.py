"""ZQ2/BZ1 causal zone tournament: anchor-specific and independent BUY/SELL.
Only research. Entry next H1 open AFTER observed touch/confirmation.
No minute sequencing claims, no live models, no account access.
"""
import argparse, json, glob, gzip, hashlib, itertools
from pathlib import Path
from collections import Counter
import numpy as np,pandas as pd
from fx_scanner.btc_native_readonly import validate_seed,SEED_HASH
O=Path("artifacts");O.mkdir(exist_ok=True)
HOURS={"H1":1,"H4":4,"D1":24,"W1":168}
NAMES=["atr_025","atr_050","atr_075","ema8","ema21","last_mid","swing3","swing8","fvg8"]
GATES=["all","trend","countertrend","lower_opposite"]
CONF=["touch_close","reclaim","rejection"]
RANGES=[.25,.5]
# Candidate selection is validation-only. Test years cannot select candidates.
Z=1.95996398454
def lower95(k,n):
    if not n:return 0.
    p=k/n
    return float((p+Z*Z/(2*n)-Z*np.sqrt(p*(1-p)/n+Z*Z/(4*n*n)))/(1+Z*Z/n))
def read_hour(asset):
    if asset=="BTC":
        p=Path("frozen-btc/repairs/buy050_identity_20261108/bridge/BTC_SEED_PACKET.json.gz")
        if not p.exists():p=Path("repairs/buy050_identity_20261108/bridge/BTC_SEED_PACKET.json.gz")
        raw=p.read_bytes();a=pd.DataFrame(validate_seed(json.loads(gzip.decompress(raw))),columns=["at","o","h","l","c","minutes"])
        a.index=pd.to_datetime(a.pop("at"),unit="s",utc=True);a=a[a.minutes==60]
        source={"seed_hash":SEED_HASH,"gzip_sha256":hashlib.sha256(raw).hexdigest()}
    else:
        ps=sorted(glob.glob("/tmp/r10/r10-1h-*.csv"));assert len(ps)==8
        a=pd.concat([pd.read_csv(p,index_col=0,parse_dates=True) for p in ps]).sort_index()
        a.index=a.index.tz_convert("UTC");a=a[a.minutes>=50]
        source={Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ps}
    assert a.index.is_monotonic_increasing and a.index.is_unique
    a=a[["o","h","l","c"]].astype(float)
    assert np.isfinite(a).all().all() and (a.l>0).all() and (a.l<=a[["o","c"]].min(axis=1)).all() and (a.h>=a[["o","c"]].max(axis=1)).all()
    return a,source
def aggregate(a,asset,tf):
    if tf=="H1":return a.copy()
    h=HOURS[tf]
    b=a.resample(f"{h}h",origin=pd.Timestamp("1970-01-05",tz="UTC"),label="left",closed="left").agg(o=("o","first"),h=("h","max"),l=("l","min"),c=("c","last"),n=("c","count"))
    req=h if asset=="BTC" or tf=="H4" else 20 if tf=="D1" else 95
    b=b[b.n>=req]
    b=b[b.index+pd.Timedelta(hours=h)<=a.index[-1]+pd.Timedelta(hours=1)]
    return b[["o","h","l","c"]]
def feature(a):
    c,h,l,o=(a[k] for k in ["c","h","l","o"])
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(14).mean()
    e8=c.ewm(span=8,adjust=False).mean();e21=c.ewm(span=21,adjust=False).mean()
    s=np.sign(e8-e21)
    trend=np.where((s*(c-c.shift(3))>0)&(s*(e21-e21.shift(3))>0),s,0)
    return atr,e8,e21,pd.Series(trend,index=a.index)
def zones(a,s,atr,e8,e21):
    # signed coordinates: target up, near above far, current close above near.
    c=s*a.c;h=a.h if s==1 else -a.l;l=a.l if s==1 else -a.h
    f={"atr_025":c-.25*atr,"atr_050":c-.5*atr,"atr_075":c-.75*atr,
       "ema8":s*e8,"ema21":s*e21,"last_mid":(h+l)/2,
       "swing3":l.rolling(3).min(),"swing8":l.rolling(8).min()}
    # Most recent bullish signed fair-value gap, not invalidated since creation.
    fg=np.full(len(a),np.nan);H=h.to_numpy();L=l.to_numpy();C=c.to_numpy()
    for i in range(2,len(a)):
        for j in range(i,max(1,i-8),-1):
            if L[j]>H[j-2] and C[i]>L[j] and (L[j+1:i+1]>=H[j-2]).all():
                fg[i]=L[j];break
    f["fvg8"]=pd.Series(fg,index=a.index)
    return f

def path_valid(idx,asset,tf,wait,hold):
    # For shorter horizons, require fully contiguous H1 paths. For gold daily or
    # weekly, allow normal session breaks and weekend, but not large unexplained gaps.
    diff=np.diff(idx.asi8)//3_600_000_000_000
    ok=diff==1
    if asset=="XAU" and tf in ("D1","W1"):
        ok|=(diff>=1)&(diff<=3)
        ok|=(diff<=75)&(diff>3)&(idx[:-1].dayofweek==4)&(idx[1:].dayofweek<=1)
    bad=np.r_[0,np.cumsum(~ok)]
    return bad
def met(y,mask,nmarket):
    a=y[mask];n=len(a);ntr=int((a>=0).sum());w=int((a==1).sum());loss=int((a==0).sum());timeout=int((a==2).sum());amb=int((a==3).sum())
    # y encodes -1 no entry, -2 geometry ineligible, 0 stop, 1 target, 2 timeout, 3 both hit (loss).
    return {"opportunities":int(nmarket),"zone_eligible":int((a!=-2).sum()),"entries":ntr,"wins":w,"stop":loss,"timeout":timeout,"both_hit_loss":amb,
            "accuracy":float(w/ntr) if ntr else None,"lower95":lower95(w,ntr),"coverage":float(ntr/nmarket) if nmarket else None}
def measured(anchor,a,asset,tf):
    atr,e8,e21,tr=feature(anchor);times=anchor.index+pd.Timedelta(hours=HOURS[tf])
    # Trading-hour windows: D1/W1 XAU use 20/100 observed H1 bars, not exact wall-clock.
    span=HOURS[tf] if asset=="BTC" or tf in ("H1","H4") else 20 if tf=="D1" else 100
    wait=span;hold=span
    p=a.index.searchsorted(times,side="left");A=a.to_numpy(float)
    bad=path_valid(a.index,asset,tf,wait,hold)
    ok=(p+wait+hold<len(a))&(p>0)&(np.arange(len(anchor))>=79)&np.isfinite(atr.to_numpy())&(atr.to_numpy()>0)
    pp=p.clip(0,len(a)-1);qq=(p+wait+hold-1).clip(0,len(a)-1)
    ok &= (bad[qq]-bad[pp]==0)
    delay=(a.index[pp]-times).total_seconds()/3600
    ok &= (delay>=0)&(delay<= (72 if asset=="XAU" and tf in ("D1","W1") else 0))
    # Maturity before calendar split, fixed window irrespective of actual exit.
    mature=a.index[qq]+pd.Timedelta(hours=1)
    ok &= (times.year==mature.year)
    loc=np.flatnonzero(ok);assert len(loc)>50,(asset,tf,len(loc))
    p=p[loc];times=times[loc];mature=mature[loc]
    price=anchor.c.to_numpy()[loc];vol=atr.to_numpy()[loc];reg=tr.to_numpy()[loc]
    lower={"H4":"H1","D1":"H4","W1":"D1"}.get(tf)
    other=np.zeros(len(loc))
    if lower:
        l=aggregate(a,asset,lower);_,_,_,lt=feature(l);lt.index+=pd.Timedelta(hours=HOURS[lower])
        other=lt.reindex(times,method="ffill",tolerance=pd.Timedelta(hours=HOURS[lower]*1.5)).fillna(0).to_numpy()
    # H1 future arrays only labels, never features/selection inputs.
    future=A[p[:,None]+np.arange(wait+hold)]
    configs={};results={}
    for s in (1,-1):
        v=zones(anchor,s,atr,e8,e21)
        # Prefix check on 12 anchors, independent of outcome values.
        for i in loc[np.linspace(0,len(loc)-1,12,dtype=int)]:
            x=anchor.iloc[:i+1];at,ee8,ee21,_=feature(x)
            check=zones(x,s,at,ee8,ee21)
            for name in NAMES:assert np.isclose(v[name].iloc[i],check[name].iloc[-1],equal_nan=True,atol=1e-8,rtol=0)
        if s==1:fo,fh,fl,fc=[future[:,:,j] for j in range(4)]
        else:fo,fh,fl,fc=-future[:,:,0],-future[:,:,2],-future[:,:,1],-future[:,:,3]
        cp=s*price
        masks={"all":np.ones(len(loc),bool),"trend":reg==s,"countertrend":reg==-s,"lower_opposite":other==-s}
        for name,width,conf in itertools.product(NAMES,RANGES,CONF):
            near=v[name].to_numpy()[loc];far=near-width*vol;stop=far-.1*vol
            valid=np.isfinite(near)&(near<cp)&(cp-near<=2*vol)&(s*near>0)&(s*far>0)
            outcome=np.full(len(loc),-2,dtype=np.int8);outcome[valid]=-1
            touched=(fl[:,:wait]<=near[:,None])&(fh[:,:wait]>=far[:,None])
            # Cancel if an observed candle penetrates invalidation before entry.
            broken=(fl[:,:wait]<stop[:,None]).cumsum(axis=1)>0
            good=touched&~broken
            if conf=="reclaim":good &= fc[:,:wait]>near[:,None]
            elif conf=="rejection":good &= (fc[:,:wait]>near[:,None])&(fc[:,:wait]>fo[:,:wait])&((np.minimum(fo[:,:wait],fc[:,:wait])-fl[:,:wait])>=.3*(fh[:,:wait]-fl[:,:wait]))
            found=good.any(axis=1)&valid;j=np.argmax(good,axis=1)
            ix=np.flatnonzero(found);en=j[ix]+1
            entry=fo[ix,en];risk=entry-stop[ix]
            # Avoid unrealistic TP by requiring at least 1R and fixed asset-scaled minimum.
            threshold=np.maximum(10.,risk) if asset=="XAU" else np.maximum(price[ix]*.0025,risk)
            gate=(risk>0)&(risk<=1.5*vol[ix])&(entry<=near[ix]+.5*vol[ix])
            ix=ix[gate];en=en[gate];entry=entry[gate];threshold=threshold[gate]
            if len(ix):
                ids=en[:,None]+np.arange(hold)
                up=fh[ix[:,None],ids]>= (entry+threshold)[:,None]
                dn=fl[ix[:,None],ids]<=stop[ix,None]
                event=up|dn;has=event.any(axis=1);k=event.argmax(axis=1);ii=np.arange(len(ix))
                code=np.full(len(ix),2,dtype=np.int8)
                code[has]=np.where(dn[ii[has],k[has]],np.where(up[ii[has],k[has]],3,0),1)
                outcome[ix]=code
            for g,G in masks.items():
                key=f"{s}:{name}:{width}:{conf}:{g}"
                configs[key]={"side":"BUY" if s==1 else "SELL","zone":name,"width_atr":width,"confirm":conf,"gate":g}
                results[key]=np.where(G,outcome,-2)
    return times,mature,configs,results,{"anchor_rows":len(anchor),"eligible":len(loc),"excluded_path_or_warmup":len(anchor)-len(loc),"wait_H1_bars":wait,"hold_H1_bars":hold}

def run(asset,tf):
    a,source=read_hour(asset);b=aggregate(a,asset,tf)
    times,mature,cfg,ys,data=measured(b,a,asset,tf)
    annual=[];samples={"BUY":[],"SELL":[]}
    minimum={"H1":100,"H4":50,"D1":25,"W1":10}[tf]
    floor={"H1":.015,"H4":.025,"D1":.03,"W1":.03}[tf]
    for year in range(2023,2027):
        start=pd.Timestamp(f"{year}-01-01",tz="UTC");end=start+pd.DateOffset(years=1)
        va=(times>=start-pd.DateOffset(years=2))&(mature<start)
        te=(times>=start)&(mature<end)
        if not te.any():continue
        row={"year":year,"market":int(te.sum()),"sides":{}}
        for side in ("BUY","SELL"):
            ranking=[]
            for k,c in cfg.items():
                if c["side"]!=side:continue
                m=met(ys[k],va,int(va.sum()))
                if m["entries"]>=minimum and m["coverage"]>=floor:
                    ranking.append((m["lower95"],m["entries"],k,m))
            if not ranking:
                row["sides"][side]={"status":"NO_VALID_CONFIG"};samples[side].append(np.full(te.sum(),-2));continue
            _,_,k,v=max(ranking)
            e=met(ys[k],te,int(te.sum()))
            row["sides"][side]={"config":cfg[k],"validation":v,"test":e}
            samples[side].append(ys[k][te])
        annual.append(row)
    aggregate_results={}
    for side,ls in samples.items():
        y=np.concatenate(ls);aggregate_results[side]=met(y,np.ones(len(y),bool),len(y))
        # Baseline uses closest ATR zone and reclaim, with identical outcome and folds.
    report={"asset":asset,"tf":tf,"version":"ZQ2_BZ1","source":source,"data":data,"candidate_configs":len(cfg),
      "annual":annual,"aggregate":aggregate_results,"target":"XAU max($10,1R); BTC max(0.25% of anchor price,1R); first stop before target, same-hour BOTH = loss",
      "limitations":["H1 source only, entry at next H1 open after closed H1 touch/reclaim/rejection, not M1 execution","D1/W1 XAU: H1-derived anchors, 20/100 observed trading-hour windows; not exact broker periods","H1/H4 gold reject noncontiguous H1 paths; sample conditional on complete future observation","Selection only prior two years, evaluation 2023–2026; previously researched sample, not pristine","No spreads/slippage/fees, no trading P&L, no deployment","Independent side candidates may conflict; metrics are side lane diagnostics, not executable policy","Repeated overlapping opportunities; uncertainty bounds descriptive"]}
    O.joinpath(f"zq2-{asset}-{tf}.json").write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({k:v for k,v in report.items() if k!="source"},allow_nan=False),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--asset",choices=["XAU","BTC"],required=True);p.add_argument("--tf",choices=list(HOURS),required=True);x=p.parse_args();run(x.asset,x.tf)
