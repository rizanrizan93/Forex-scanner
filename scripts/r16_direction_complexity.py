"""R16 direction-only, simple-to-complex walk-forward tournament.
Research only. No entry zones, SL/TP, trading or production writes.
Reported OOS folds are historically re-used, NOT untouched holdout.
Training targets must mature strictly before validation/test decision boundary.
"""
import argparse,json,itertools
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from sklearn.naive_bayes import GaussianNB
from r10_million import ohlc_indicators,load,wilson
from r102_calibrated import context
from r14_multitimeframe_direction import load_tf
from r15_direction_tournament import score
OUT=Path("artifacts");OUT.mkdir(exist_ok=True)
TF={"1h":"H1","4h":"H4","1D":"D1","1W":"W1"}
# Simple momentum/reversal hypotheses, explicit sign and abstention thresholds.
def features(z):
    a=z.atr14.replace(0,np.nan)
    c=z.c
    f=pd.DataFrame(index=z.index)
    f["ema"]=((z.ema8-z.ema21)/a)
    f["rsi"]=(z.rsi14-50)/15
    f["di"]=z.di/25
    f["momentum3"]=z.roc3*c/(a*3)
    f["momentum8"]=z.roc8*c/(a*6)
    f["macd"]=z.macdh/a*4
    f["body"]=z.body
    f["clv"]=z.clv
    f["sweep"]=z.sweep5
    f["position"]=(z.discount-.5)*2
    f["breakout"]=z.break8
    f["efficiency"]=z.eff3
    f["atr_rank"]=z.atr_rank
    f["adx"]=z.adx14/25
    f["range"]=z.rangeratio
    f["vol"]=z.bbwidth
    for k in ["d1_mom","d1_trend","w1_mom","w1_trend"]:
        if k in z:f[k]=z[k]*100
    f["weekday_sin"]=np.sin(2*np.pi*z.index.dayofweek/7)
    f["weekday_cos"]=np.cos(2*np.pi*z.index.dayofweek/7)
    f["hour_sin"]=np.sin(2*np.pi*z.index.hour/24)
    f["hour_cos"]=np.cos(2*np.pi*z.index.hour/24)
    return f.replace([np.inf,-np.inf],np.nan)
def blocks(f,tf):
    b={"trend":["ema","momentum3","momentum8","di","macd"],
       "reversal":["rsi","position","sweep","clv","body","adx"],
       "compact":["ema","rsi","clv","adx","atr_rank","momentum3","sweep"],
       "full":list(f.columns)}
    if tf in ("1D","1W"):
        b["full"]=[k for k in b["full"] if not k.startswith("hour_")]
    return b
def factory(name):
    if name=="logit_strong":return make_pipeline(StandardScaler(),LogisticRegression(C=.03,max_iter=600))
    if name=="logit":return make_pipeline(StandardScaler(),LogisticRegression(C=.3,max_iter=600))
    if name=="lda":return make_pipeline(StandardScaler(),LinearDiscriminantAnalysis(solver="lsqr",shrinkage="auto"))
    if name=="nb":return GaussianNB(var_smoothing=1e-5)
    if name=="tree":return DecisionTreeClassifier(max_depth=3,min_samples_leaf=30,random_state=42)
    if name=="extra":return ExtraTreesClassifier(n_estimators=60,max_depth=5,min_samples_leaf=20,random_state=42,n_jobs=2)
    if name=="hgb":return HistGradientBoostingClassifier(max_iter=80,max_depth=3,max_leaf_nodes=7,l2_regularization=10,random_state=42)
    raise ValueError(name)
SIMPLE=["ema","rsi","di","momentum3","momentum8","macd","body","clv","sweep","position","breakout","efficiency"]
ML=["logit_strong","logit","lda","nb","tree","extra","hgb"]
CUT=[.5,.52,.55,.58,.60,.65]
def masks(p,cut):
    return p>=cut, (p<.5 if cut==.5 else p<=1-cut)
def stats(y,p,cut):
    b,s=masks(p,cut)
    return score(y,b,s,np.ones(len(y),bool))
def signed(v,orientation,threshold):
    q=orientation*v
    return np.where(q>threshold,1,np.where(q< -threshold,0,.5))
def measured(y,p,cut):
    return stats(y,p,cut)
def rank(m,nmin):
    a,b=m["BUY"],m["SELL"]
    if min(a["n"],b["n"])<nmin:return -1.
    return float(min(a["wilson_lower95"],b["wilson_lower95"]))
def audit(d,z,f,valid,tf):
    h1=load("1h") if tf in ("1h","4h") else None
    eligible=np.flatnonzero(valid)
    loc=eligible[np.linspace(0,len(eligible)-1,min(12,len(eligible)),dtype=int)]
    fails=[]
    for i in loc:
        q=ohlc_indicators(d.iloc[:i+1])
        if h1 is not None:
            hours=1 if tf=="1h" else 4
            t=d.index[i]+pd.Timedelta(hours=hours)
            context(q,h1.loc[h1.index+pd.Timedelta(hours=1)<=t],hours)
        g=features(q)
        aa=f.iloc[i].to_numpy(float);bb=g.iloc[-1].reindex(f.columns).to_numpy(float)
        if not np.allclose(aa,bb,rtol=1e-8,atol=1e-8,equal_nan=True):
            fails.append(str(d.index[i]))
    return dict(checks=len(loc),failures=fails,passed=not fails)
def emit(masks_or_p,y):
    y=np.asarray(y)
    return score(y,masks_or_p==1,masks_or_p==0,np.ones(len(y),bool))
def run(tf):
    d,z,_,y,valid,times=load_tf(tf)
    f=features(z)
    valid &= f.notna().all(axis=1).to_numpy()
    proof=audit(d,z,f,valid,tf)
    if not proof["passed"]:raise RuntimeError("prefix causal audit failed "+str(proof))
    # Label maturity is the NEXT candle's close; purge cross-boundary samples.
    mature=pd.Series(times,index=d.index).shift(-1)
    signal=times
    X=f.to_numpy(float)
    names={c:i for i,c in enumerate(f.columns)}
    groups=blocks(f,tf)
    testyears=range(2022,2027) if tf in ("1h","4h") else range(2019,2027)
    nmin={"1h":60,"4h":30,"1D":20,"1W":8}[tf]
    trainmin={"1h":250,"4h":150,"1D":120,"1W":80}[tf]
    records=[];predictions={"simple":[],"complex":[],"ensemble":[]}
    counts={"simple":0,"complex":0,"ensemble":0,"model_fits":0}
    for yr in testyears:
        tz=signal.tz
        val_start=pd.Timestamp(year=yr-1,month=1,day=1,tz=tz)
        test_start=pd.Timestamp(year=yr,month=1,day=1,tz=tz)
        test_end=pd.Timestamp(year=yr+1,month=1,day=1,tz=tz)
        before_val=np.asarray(mature<val_start)
        before_test=np.asarray(mature<test_start)
        v=valid & (signal>=val_start)&(signal<test_start)&before_test
        t=valid & (signal>=test_start)&(signal<test_end)&np.asarray(mature<test_end)
        if v.sum()<nmin*2 or t.sum()<nmin*2:continue
        # Families chosen only on immediately prior calendar validation year.
        simple=[];complex_=[];ensemble=[]
        for col,ori,th in itertools.product(SIMPLE,[-1,1],[0.,.1,.3,.55]):
            arr=X[:,names[col]]
            p=signed(arr,ori,th);m=stats(y[v],p[v],.75)
            counts["simple"]+=1
            q=rank(m,nmin)
            if q>=0:simple.append((q,m["coverage"],f"{col}:{ori}:{th}",p[t],.75,m))
        for years in [2,4,8]:
            tr=valid & (signal>=val_start-pd.DateOffset(years=years)) & before_val
            if tr.sum()<trainmin or len(np.unique(y[tr]))<2:continue
            for group,cols in groups.items():
                xp=X[:,[names[k] for k in cols]]
                members=[]
                for model in ML:
                    # Narrow trees and larger samples protect small W1 data.
                    try:
                        e=factory(model).fit(xp[tr],y[tr])
                        pv=e.predict_proba(xp[v])[:,1];pt=e.predict_proba(xp[t])[:,1]
                    except (ValueError,np.linalg.LinAlgError):
                        continue
                    counts["model_fits"]+=1
                    members.append((pv,pt))
                    for cut in CUT:
                        m=stats(y[v],pv,cut);counts["complex"]+=1
                        q=rank(m,nmin)
                        if q>=0:complex_.append((q,m["coverage"],f"{model}:{group}:{years}y",pt,cut,m))
                if len(members)>=3:
                    pv=np.mean([x[0] for x in members],axis=0)
                    pt=np.mean([x[1] for x in members],axis=0)
                    for cut in CUT:
                        m=stats(y[v],pv,cut);counts["ensemble"]+=1
                        q=rank(m,nmin)
                        if q>=0:ensemble.append((q,m["coverage"],f"mean_ensemble:{group}:{years}y",pt,cut,m))
        row={"year":yr,"evaluation_bars":int(t.sum()),"validation_bars":int(v.sum()),
             "baseline_buy":round(float(y[t].mean()),5),
             "persistence":round(float(((z.c>z.o).to_numpy()[t]==y[t]).mean()),5),
             "results":{}}
        for family,pool in [("simple",simple),("complex",complex_),("ensemble",ensemble)]:
            if not pool:
                # No qualifying rule means WAIT, not substitute evaluation winner.
                pred=np.full(int(t.sum()),-1,dtype=int)
                row["results"][family]={"selected":None,"evaluation":emit(pred,y[t])}
            else:
                q,cov,key,p,cut,m=max(pool,key=lambda a:(a[0],a[1],a[2],-a[4]))
                buy,sell=masks(p,cut);pred=np.where(buy,1,np.where(sell,0,-1))
                row["results"][family]={"selected":key,"threshold":cut,"validation":m,
                      "evaluation":emit(pred,y[t])}
            predictions[family].append((y[t],pred))
        records.append(row)
        print(json.dumps({"stage":"walk_forward_fold","tf":TF[tf],**row}),flush=True)
    assert records,"no complete folds"
    aggregate={}
    for family,pp in predictions.items():
        yy=np.concatenate([a for a,b in pp]);pr=np.concatenate([b for a,b in pp])
        aggregate[family]=emit(pr,yy)
    result={"version":"R16","timeframe":TF[tf],"audit":proof,
        "counts":counts,"folds":records,"aggregate":aggregate,
        "definition":"predict next completed bar CLOSE-to-CLOSE direction; abstain WAIT",
        "source":"R10 2019-26 H1/H4; R9.8 2012-26 daily/W1",
        "selection":"each annual test fold uses earlier train and immediately preceding validation; purge immature labels",
        "limitations":["Repeated historical evaluation, not untouched forward holdout",
            "Counts are candidate rule evaluations across folds, not unique strategy count",
            "Simple vs complex vs ensemble are compared descriptively; do not choose a winner on these test outcomes and claim independent validation",
            "No actual macro data, order flow, or trading outcome in this version",
            "W1 sample sizes are necessarily small"],
        "live_permission":False,"zones_deferred":True}
    OUT.joinpath(f"r16-direction-{tf}.json").write_text(json.dumps(result,indent=2))
    print(json.dumps({"stage":"complete","tf":TF[tf],"counts":counts,"aggregate":aggregate}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--tf",choices=list(TF),required=True)
    run(p.parse_args().tf)
