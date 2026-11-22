"""XAU ZQ1: test the actual frozen-dashboard 20-candle quartile geometry.
No production changes. Direction context is the pinned dashboard's five votes,
not its eight historical benchmarks. Fixed parameters, no test optimization.
"""
import argparse, glob, hashlib, json, math
from collections import defaultdict,Counter
from pathlib import Path
import numpy as np,pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from fx_scanner.frozen_direction_context import context,watch_zone

O=Path("artifacts");O.mkdir(exist_ok=True)
TFS={"H1":1,"H4":4,"D1":24,"W1":168}
TARGETS=["usd10","usd25","usd50","atr0.5"]
STATUS=["WIN_PROVEN","STOP","TIMEOUT","AMBIGUOUS","NO_TOUCH","GAP_INVALID"]
POLICIES=["quartile","atr_reference"]
PIN="272a50cb48278b3bc038d12db1b53d0702e89764"

def read_shards(pattern,expected):
    ps=sorted(glob.glob(pattern));assert len(ps)==expected,(pattern,len(ps))
    d=pd.concat([pd.read_csv(p,index_col=0,parse_dates=True) for p in ps]).sort_index()
    assert not d.index.has_duplicates and d.index.tz is not None
    d.index=d.index.tz_convert("UTC")
    a=d[["o","h","l","c"]].to_numpy(float)
    assert np.isfinite(a).all() and (a[:,2]>0).all()
    assert ((a[:,2]<=np.minimum(a[:,0],a[:,3]))&(a[:,1]>=np.maximum(a[:,0],a[:,3]))).all()
    return d,{Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ps}

def read_all():
    h1,m1=read_shards("/tmp/r10/r10-1h-*.csv",8)
    h4,m4=read_shards("/tmp/r10/r10-4h-*.csv",8)
    day,md=read_shards("/tmp/r98/daily-*.csv",15)
    # Same integer coverage thresholds as dashboard M1 aggregation.
    a=h1.loc[h1.minutes>=int(60*.83),["o","h","l","c"]]
    b=h4.loc[h4.minutes>=int(240*.83),["o","h","l","c"]]
    d=day.loc[day.n>=1200,["o","h","l","c"]]
    mon=d.index.floor("D")-pd.to_timedelta(d.index.dayofweek,unit="D")
    w=d.groupby(mon).agg(o=("o","first"),h=("h","max"),l=("l","min"),c=("c","last"),n=("c","size"))
    w=w.loc[w.n>=3,["o","h","l","c"]]
    return {"H1":a,"H4":b,"D1":d,"W1":w},h1.loc[h1.minutes>=50,["o","h","l","c"]],{**m1,**m4,**md}

def weights(span,n):
    alpha=2/(span+1);q=1-alpha
    w=alpha*q**np.arange(n-1,-1,-1,dtype=float);w[0]=q**(n-1);return w
def exact_votes(d,tf):
    # Exact 80-candle reset used by display context; exclude first 79 bars.
    # No future OHLC included even when computing vectorized features.
    arr=d[["o","h","l","c"]].to_numpy(float)
    out=pd.DataFrame(index=d.index,columns=["buy","sell","atr","lo","hi","prior5","side"],dtype=float)
    if len(d)<80:return out
    W=sliding_window_view(arr,80,axis=0)
    o,h,l,c=[W[:,i,:] for i in range(4)]
    tr=np.maximum(h[:,1:]-l[:,1:],np.maximum(np.abs(h[:,1:]-c[:,:-1]),np.abs(l[:,1:]-c[:,:-1])))
    atr=tr[:,-14:].mean(axis=1)
    e5=c@weights(5,80);e13=c@weights(13,80);prev=c[:,:-3]@weights(13,77)
    lo=l[:,-20:].min(1);hi=h[:,-20:].max(1)
    def sign(x,b):return np.where(x>b,1,np.where(x<-b,-1,0))
    hh=h[:,-5:].max(1);ph=h[:,-10:-5].max(1);ll=l[:,-5:].min(1);pl=l[:,-10:-5].min(1)
    struct=np.where((hh>ph)&(ll>pl),1,np.where((hh<ph)&(ll<pl),-1,0))
    votes=np.stack([sign(e5-e13,.10*atr),sign(e13-prev,.05*atr),sign(c[:,-1]-c[:,-4],.15*atr),struct,sign(c[:,-1]-(hi+lo)/2,.10*atr)],1)
    buy=(votes==1).sum(1);sell=(votes==-1).sum(1)
    side=np.where((buy>=4)&(sell<=1),1,np.where((sell>=4)&(buy<=1),-1,0))
    # Before-current-candle drift; independent pre-touch regime classification.
    prior=c[:,-2]-c[:,-7]
    out.iloc[79:]=np.column_stack([buy,sell,atr,lo,hi,prior,side])
    # Compare to exact pinned production helper, including geometry and prefix.
    idx=np.linspace(79,len(d)-1,min(32,len(d)-79),dtype=int)
    for i in idx:
        f=d.iloc[max(0,i-79):i+1].rename(columns={"o":"open","h":"high","l":"low","c":"close"}).copy()
        f.index+=pd.Timedelta(hours=TFS[tf])
        t=f.index[-1].to_pydatetime()
        r=context(f,tf,now=t,observed_at=t,market_fresh=False)
        v=out.iloc[i]
        assert r["buy"]==int(v.buy) and r["sell"]==int(v.sell) and np.isclose(r["atr"],v.atr,rtol=0,atol=1e-9),(tf,i,r,v.to_dict())
        z=watch_zone(f,r)
        if v.side:
            assert z and np.isclose(z["low"],v.lo if v.side==1 else v.hi-.25*(v.hi-v.lo)) and np.isclose(z["high"],v.lo+.25*(v.hi-v.lo) if v.side==1 else v.hi),(tf,i)
    return out

def eligible_gap(t0,t1,tf):
    dt=(t1-t0).total_seconds()/3600
    return 24<=dt<=96 if tf=="D1" else dt==TFS[tf]

def signed_path(path,side,edge,stop,target):
    # All comparisons in directional coordinates: favorable=up.
    edge*=side;stop*=side;target=edge+target
    touched=False;possible=False;entry_i=None
    for i,(o,h,l,c) in enumerate(path):
        if side==-1:o,h,l,c=-o,-l,-h,-c
        if not touched:
            if l>edge:continue
            # Opening gap beyond the distal boundary is not a valid touch/fill.
            if o<stop:return "GAP_INVALID"
            touched=True;entry_i=i
            hit=h>=target;breach=l<stop
            # If the open was outside the zone, its intrabar high can precede touch.
            prove=hit and (o<=edge or c>=target)
            if breach:return "AMBIGUOUS" if hit else "STOP"
            if prove:return "WIN_PROVEN"
            possible|=hit
        else:
            if o>=target:return "WIN_PROVEN"
            if o<stop:return "AMBIGUOUS" if possible else "STOP"
            hit=h>=target;breach=l<stop
            if hit and breach:return "AMBIGUOUS"
            if hit:return "WIN_PROVEN"
            if breach:return "AMBIGUOUS" if possible else "STOP"
    if not touched:return "NO_TOUCH"
    return "AMBIGUOUS" if possible else "TIMEOUT"

def h1_refinement(h1,tf,t,bar):
    if tf=="H1":return None
    q=h1.loc[(h1.index>=t)&(h1.index<t+pd.Timedelta(hours=TFS[tf]))]
    # Same observed OHLC AND sufficient actual constituent candles.
    # Do not use more permissive data to manufacture a result.
    required={"H4":4,"D1":20,"W1":95}[tf]
    if len(q)<required:return None
    if tf=="H4" and not q.index.equals(pd.date_range(t,periods=4,freq="h")):return None
    if tf in ("D1","W1"):
        # No missing internal sequence within each observed UTC trading day;
        # tolerate expected inter-day market closure. Missing-session days could
        # still exist, so D1/W1 refinement remains an OHLC-matched proxy.
        for _,g in q.groupby(q.index.floor("D")):
            if len(g)>1 and not (g.index.to_series().diff().dropna()==pd.Timedelta(hours=1)).all():return None
    got=np.array([q.o.iloc[0],q.h.max(),q.l.min(),q.c.iloc[-1]])
    if not np.allclose(got,bar,rtol=0,atol=1e-6):return None
    return q[["o","h","l","c"]].to_numpy(float)

def wilson(k,n):
    if not n:return None
    p=k/n;z=1.95996398454
    return float((p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n))
def rate(k,n):return float(k/n) if n else None
def summarize(rows):
    n=len(rows);counts=Counter(r["status"] for r in rows)
    wins=counts["WIN_PROVEN"];amb=counts["AMBIGUOUS"];touch=n-counts["NO_TOUCH"]-counts["GAP_INVALID"]
    return {"opportunities":n,"touches":touch,"touch_rate":rate(touch,n),"confirmed":wins,
      "ambiguous":amb,"stop":counts["STOP"],"timeout":counts["TIMEOUT"],"no_touch":counts["NO_TOUCH"],"gap_invalid":counts["GAP_INVALID"],
      "confirmed_per_touch_lower":rate(wins,touch),"possible_per_touch_upper":rate(wins+amb,touch),
      "confirmed_per_opportunity":rate(wins,n),"wilson_lower95_confirmed":wilson(wins,touch),
      "next_anchor_close_correct":rate(sum(r["next_close_correct"] for r in rows),n)}

def run(tf):
    data,h1,hashes=read_all();d=data[tf];v=exact_votes(d,tf)
    lower={"H1":None,"H4":"H1","D1":"H4","W1":"D1"}[tf]
    lowctx=None
    if lower:
        lowctx=exact_votes(data[lower],lower).side.dropna()
        lowctx.index+=pd.Timedelta(hours=TFS[lower])
    times=d.index+pd.Timedelta(hours=TFS[tf]);A=d[["o","h","l","c"]].to_numpy(float)
    records=[];coverage=defaultdict(Counter);counts=Counter()
    for i in range(79,len(d)-1):
        date=times[i];year=int(date.year)
        # Declare the decision year; future candle must mature inside that year.
        if year<2019 and tf in ("H1","H4"):continue
        if year<2012 or year>2026:continue
        y=coverage[str(year)];y["anchor_warm"]+=1
        if not eligible_gap(d.index[i],d.index[i+1],tf) or times[i+1].year!=year:
            y["excluded_gap_or_year_end"]+=1;continue
        y["eligible"]+=1
        r=v.iloc[i]
        if not np.isfinite(r.atr) or r.atr<=0 or not r.side or not r.hi>r.lo:
            y["neutral"]+=1;continue
        s=int(r.side);side="BUY" if s>0 else "SELL";y[side+"_bias"]+=1
        price=A[i,3];width=r.hi-r.lo
        edge=r.lo+.25*width if s==1 else r.hi-.25*width
        stop=r.lo if s==1 else r.hi
        if s*(price-edge)<=0:
            y[side+"_already_inside_or_beyond"]+=1;continue
        y[side+"_prospective"]+=1
        # Ex-ante trend classification, not retrospective claim of reversal.
        regime="continuation_context" if s*r.prior5>.1*r.atr else "reversal_context" if s*r.prior5<-.1*r.atr else "flat_context"
        timing="unavailable"
        if lowctx is not None:
            k=lowctx.index.searchsorted(date,side="right")-1
            if k>=0 and date-lowctx.index[k]<=pd.Timedelta(hours=TFS[lower]*1.5):
                t=float(lowctx.iloc[k]);timing="aligned" if t==s else "opposite" if t==-s else "neutral"
        # Baseline uses exact same anchor decisions and ex-ante price.
        # No tuning: zone 0.5–1.0 ATR from current close.
        variants={"quartile":(edge,stop),"atr_reference":(price-s*.5*r.atr,price-s*r.atr)}
        nextbar=A[i+1];p0=np.array([nextbar])
        fine=h1_refinement(h1,tf,d.index[i+1],nextbar)
        if fine is not None:y[side+"_matched_h1"]+=1
        # Secondary: allow one extra completed anchor candle (not max one-horizon hold).
        p2=None;f2=None
        if i+2<len(d) and eligible_gap(d.index[i+1],d.index[i+2],tf) and times[i+2].year==year:
            p2=np.array([nextbar,A[i+2]])
            q=h1_refinement(h1,tf,d.index[i+2],A[i+2])
            if fine is not None and q is not None:f2=np.concatenate([fine,q])
        for policy,(e,st) in variants.items():
            if e<=0 or st<=0 or s*(e-st)<=0:continue
            for target,delta in zip(TARGETS,[10.,25.,50.,.5*r.atr]):
                # Touch restricted to the FIRST anchor candle even for two-candle response.
                for resolution,path in [("anchor_1",p0),("h1_matched_1",fine),("anchor_2",p2),("h1_matched_2",f2)]:
                    if path is None:continue
                    first=fine if "h1" in resolution else p0
                    first_status=signed_path(first,s,e,st,delta)
                    status=first_status
                    if resolution.endswith("_2") and first_status not in ("NO_TOUCH","GAP_INVALID","WIN_PROVEN","STOP"):
                        status=signed_path(path,s,e,st,delta)
                    records.append({"year":year,"side":side,"regime":regime,"timing":timing,
                      "policy":policy,"target":target,"resolution":resolution,"status":status,
                      "next_close_correct":bool(s*(nextbar[3]-price)>0)})
    groups=defaultdict(list);annual=defaultdict(list);regimes=defaultdict(list);timings=defaultdict(list)
    for r in records:
        key=tuple(r[k] for k in ("policy","resolution","target","side"))
        groups[key].append(r);annual[(*key,r["year"])].append(r)
        regimes[(*key,r["regime"])].append(r);timings[(*key,r["timing"])].append(r)
    def table(g,extra=None):
        names=["policy","resolution","target","side"]+([extra] if extra else [])
        return [{**dict(zip(names,k)),**summarize(rows)} for k,rows in sorted(g.items())]
    result={"version":"ZQ1","tf":tf,"dashboard_pin":PIN,"status":"EXPLORATORY_COMPLETE",
       "scope":"H1/H4 2019–2026, D1/W1 2012–2026; 80-bar warmup; partial 2026. Same 20-candle quartile and 5 votes as pinned dashboard.",
       "source_sha256":hashes,"prefix_checks":32,"coverage":{k:dict(v) for k,v in coverage.items()},
       "all":table(groups),"annual":table(annual,"year"),"regime":table(regimes,"regime"),"lower_timeframe":table(timings,"timing"),
       "limitations":["Forecast context is dashboard 5-vote heuristic, NOT R28.1 benchmark model inference","Entry edge reference, not fill. Strict intrabar breach of distal edge is more conservative than dashboard closed-candle invalidation","Touch allowed first next eligible anchor candle only, target before end of first (primary) or second (secondary) anchor candle","H1 OHLC cannot prove general same-bar order; ambiguous separated, never assumed wins","H4/D1/W1 H1 matched refinement requires matching OHLC and coverage; not tick path","D1 gap 1–4 calendar days, W1 UTC Monday calendar, not broker sessions; no exact wall-clock holding time over closures","Continuation/reversal labels are ex-ante preceding five-candle drift, not proof of market regime change","No spreads/slippage/P&L or forward trial; repeated opportunities overlap and Wilson bounds descriptive only","No parameter fitting or selection, historical years previously inspected, no production changes"]}
    O.joinpath(f"zq1-{tf}.json").write_text(json.dumps(result,indent=2,allow_nan=False))
    primary=[x for x in result["all"] if x["resolution"] in ("anchor_1","h1_matched_1") and x["target"] in ("usd10","atr0.5")]
    recent=table({k:[r for r in rows if r["year"]>=2023] for k,rows in groups.items() if k[1] in ("anchor_1","h1_matched_1") and k[2] in ("usd10","atr0.5")})
    print(json.dumps({"tf":tf,"status":result["status"],"coverage":result["coverage"],"primary":primary,"2023_2026":recent},allow_nan=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--tf",choices=list(TFS),required=True);run(p.parse_args().tf)
