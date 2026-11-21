"""RIZAN R14: FOUR INDEPENDENT DIRECTIONAL engines; research-only.
H1/H4 2019-26 R10 immutable source; D1/W1 2012-26 R9.8 daily source.
At a completed candle, forecast NEXT completed candle CLOSE-to-CLOSE direction.
No zone estimation, entries, take-profits, live pricing or broker order actions.
"""
import argparse, glob, json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss
from scipy.special import logit
from r10_million import load,ohlc_indicators,wilson
from r102_calibrated import prepare,context
warnings.filterwarnings('ignore',category=RuntimeWarning)
OUT=Path("artifacts");OUT.mkdir(exist_ok=True)
TF={"1h":"H1","4h":"H4","1D":"D1","1W":"W1"}
COLS=["clv","body","wick","b3","eff3","rsi7","rsi14",
      "roc3","roc8","macdh","adx7","adx14","adx21","di",
      "atr_pct","atr_rank","bbwidth","rangeratio","discount",
      "break8","sweep5"]
def load_d1():
    pp=sorted(glob.glob("/tmp/r98/daily-*.csv"))
    assert len(pp)>=12,("Missing R9.8 immutable daily shards",len(pp))
    d=pd.concat([pd.read_csv(p,index_col=0,parse_dates=True) for p in pp]).sort_index()
    d=d[~d.index.duplicated()]
    assert d.index.tz is not None and d.index.year.min()<=2012 and d.index.year.max()>=2026
    return d
def load_tf(tf):
    if tf in ("1h","4h"):
        d,z,x,y,valid=prepare(tf)
        cols=[c for c in COLS+["d1_mom","d1_trend","w1_mom","w1_trend"] if c in z]
        x=z[cols].copy()
    else:
        daily=load_d1()
        if tf=="1D":
            d=daily
        else:
            mon=daily.index.floor("D")-pd.to_timedelta(daily.index.dayofweek,unit="D")
            d=daily.groupby(mon).agg(o=("o","first"),h=("h","max"),l=("l","min"),
                  c=("c","last"),bars=("c","count"))
            d=d[d.bars>=3]
        z=ohlc_indicators(d)
        x=z[COLS].copy()
    # Every row represents OHLC of a candle that is CLOSED at decision_time.
    # Shifts below are OUTCOME LABELS ONLY, never predictors.
    oldclose=d.c.to_numpy(float);nextclose=d.c.shift(-1).to_numpy(float)
    times=d.index.to_series();gaps=(times.shift(-1)-times)
    if tf=="1D":good_gap=(gaps>=pd.Timedelta(days=1))&(gaps<=pd.Timedelta(days=4))
    elif tf=="1W":good_gap=(gaps==pd.Timedelta(days=7))
    else:good_gap=(gaps==pd.Timedelta(hours=1 if tf=="1h" else 4))
    y=(nextclose>oldclose).astype("int8")
    x["ema_gap_atr"]=(z.ema8-z.ema21)/z.atr14.replace(0,np.nan)
    x["macd_atr"]=z.macdh/z.atr14.replace(0,np.nan)
    x["hour_sin"]=np.sin(2*np.pi*z.index.hour/24)
    x["hour_cos"]=np.cos(2*np.pi*z.index.hour/24)
    if tf in ("1D","1W"):
        x=x.drop(columns=["hour_sin","hour_cos"])
    x=x.replace([np.inf,-np.inf],np.nan)
    valid=good_gap.fillna(False).to_numpy()&np.isfinite(oldclose)&np.isfinite(nextclose)&(oldclose!=nextclose)
    valid &= x.notna().all(axis=1).to_numpy()
    # Full period close must already have occurred before prediction.
    hour_delta={"1h":1,"4h":4,"1D":24,"1W":168}[tf]
    signal_times=d.index+pd.Timedelta(hours=hour_delta)
    assert (signal_times>d.index).all()
    return d,z,x,y,valid,signal_times
def split(tf,idx,valid):
    year=idx.year
    if tf in ("1h","4h"):
        train=valid & (year>=2019)&(year<=2022)
        cal=valid & (year==2023)&(idx.month<=6)
        val=valid & (year==2023)&(idx.month>=7)
        test=valid & (year>=2024)&(year<=2026)
        bounds=dict(train="2019-2022",cal="2023H1",selection="2023H2",evaluation="2024-2026")
    else:
        train=valid & (year>=2012)&(year<=2020)
        cal=valid & (year==2021)
        val=valid & (year==2022)
        test=valid & (year>=2023)&(year<=2026)
        bounds=dict(train="2012-2020",cal="2021",selection="2022",evaluation="2023-2026")
    minimum=20 if tf=="1W" else 100
    assert all(np.asarray(t).sum()>minimum for t in (train,cal,val,test)),{
        "tf":tf,"counts":[int(np.asarray(t).sum()) for t in (train,cal,val,test)]}
    return np.asarray(train),np.asarray(cal),np.asarray(val),np.asarray(test),bounds
def platt(a,y,b):
    m=LogisticRegression(C=.3,max_iter=1000)
    m.fit(logit(np.clip(a,1e-5,1-1e-5)).reshape(-1,1),y)
    return m.predict_proba(logit(np.clip(b,1e-5,1-1e-5)).reshape(-1,1))[:,1]
def met(y,p,cut):
    buy=(p>=cut);sell=(p<=1-cut)
    if cut==.5:sell=p<.5
    def each(mask,positive):
        n=int(mask.sum());k=int((y[mask]==positive).sum())
        return dict(n=n,correct=k,accuracy=round(k/n,6) if n else None,
                wilson_lower95=round(wilson(k,n),6) if n else None)
    return dict(BUY=each(buy,1),SELL=each(sell,0),
        WAIT=int((~(buy|sell)).sum()),coverage=round(float((buy|sell).mean()),6),
        brier=round(float(brier_score_loss(y,p)),6))
def models():
    for C in [.05,1.0]:
        yield (f"logit_C{C}",make_pipeline(StandardScaler(),LogisticRegression(C=C,max_iter=500)))
    for depth in [3,5]:
        yield (f"hgb_depth{depth}",HistGradientBoostingClassifier(max_iter=100,
            max_depth=depth,max_leaf_nodes=15,l2_regularization=5,
            learning_rate=.05,random_state=42))
def causal_test(tf,d,z,valid):
    if tf in ("1h","4h"):
        # The R10.3 independent prefix audit for 1h/4h is run 44907102788.
        return {"type":"R10.3 upstream independent prefix audit","status":"PASS",
                "reference_run":44907102788,
                "warning":"R14 adds only contemporaneous derived features; no new incomplete D1/W1 source"}
    # Recompute all independent raw D1/W1 indicators with only earlier completed candles.
    eligible=np.flatnonzero(valid)
    loc=eligible[np.linspace(0,len(eligible)-1,min(16,len(eligible)),dtype=int)]
    keys=["clv","body","b3","rsi14","roc8","macdh","adx14","di",
          "atr_pct","atr_rank","bbwidth","discount","break8","sweep5"]
    bad=[]
    for i in loc:
        before=ohlc_indicators(d.iloc[:i+1])
        for col in keys:
            a=float(z.iloc[i][col]);b=float(before.iloc[-1][col])
            if not np.isclose(a,b,atol=1e-9,rtol=1e-9,equal_nan=True):
                bad.append({"time":str(z.index[i]),"feature":col})
    return {"type":"recompute frozen-candle prefixes","checked_bars":len(loc),
            "status":"PASS" if not bad else "FAIL","errors":bad}
def run(tf):
    d,z,x,y,valid,decision_times=load_tf(tf)
    train,cal,val,test,bounds=split(tf,z.index,valid)
    causal=causal_test(tf,d,z,valid)
    if causal["status"]!="PASS":raise RuntimeError("PREFIX LEAKAGE "+json.dumps(causal))
    data=x.to_numpy(np.float32)
    rules=[];fitted=[]
    min_n={"1h":40,"4h":40,"1D":30,"1W":8}[tf]
    for label,m in models():
        m.fit(data[train],y[train])
        cp=m.predict_proba(data[cal])[:,1]
        vp=m.predict_proba(data[val])[:,1]
        tp=m.predict_proba(data[test])[:,1]
        for calibration in ("raw","platt"):
            v=vp if calibration=="raw" else platt(cp,y[cal],vp)
            t=tp if calibration=="raw" else platt(cp,y[cal],tp)
            for cut in [.50,.52,.55,.58,.60,.65]:
                r=met(y[val],v,cut)
                eligible=min(r["BUY"]["n"],r["SELL"]["n"])>=min_n
                # Selected SOLELY on 2022 (D1/W1) or 2023H2 (H1/H4).
                quality=min(r["BUY"]["wilson_lower95"] or 0,r["SELL"]["wilson_lower95"] or 0) if eligible else -1.
                rules.append(dict(model=label,calibration=calibration,cut=cut,validation=r,
                        quality=quality,evaluation=met(y[test],t,cut),eligible=eligible))
        fitted.append(label)
        print(json.dumps({"stage":"trained","tf":tf,"model":label}),flush=True)
    chosen=max(rules,key=lambda z:(z["quality"],z["validation"]["coverage"]))
    # Refit the selected family ONLY on the fixed train set, preserve calendar splits.
    label=chosen["model"]
    chosenmodel=next(m for l,m in models() if l==label)
    chosenmodel.fit(data[train],y[train])
    cp=chosenmodel.predict_proba(data[cal])[:,1]
    testprob=chosenmodel.predict_proba(data[test])[:,1]
    if chosen["calibration"]=="platt":testprob=platt(cp,y[cal],testprob)
    annual={}
    for year in sorted(set(z.index.year[test])):
        inyear=z.index.year[test]==year
        annual[str(year)]=met(y[test][inyear],testprob[inyear],chosen["cut"])
    e=chosen["evaluation"]
    min_eval=30 if tf=="1W" else 100
    success=bool(chosen["eligible"] and e["BUY"]["n"]>=min_eval and
         e["SELL"]["n"]>=min_eval and e["BUY"]["accuracy"]>=.60 and
         e["SELL"]["accuracy"]>=.60)
    baseline={
      "always_buy_accuracy":round(float(y[test].mean()),6),
      "always_sell_accuracy":round(float(1-y[test].mean()),6),
      "previous_candle_persistence":round(float(((d.c>d.o).to_numpy()[test]==y[test]).mean()),6)}
    # For direction-only engine, never render false entry/zone/SL/TP recommendations.
    summary={"version":"R14","model_type":"CLOSED-CANDLE DIRECTION ONLY","tf":TF[tf],
       "target":"next closed candle CLOSE-to-CLOSE BUY/SELL/WAIT",
       "data_source":"R10 M1->H1/H4 2019-2026" if tf in ("1h","4h") else "R9.8 M1->D1 2012-2026",
       "source_run":44901264975 if tf in ("1h","4h") else 44886465487,
       "candle_boundary":"signal only after completion of its own H1/H4/D1/W1 candle",
       "periods":bounds,"counts":{"train":int(train.sum()),"calibration":int(cal.sum()),
          "selection":int(val.sum()),"evaluation":int(test.sum())},
       "audit":causal,"models_trained":len(fitted),"candidate_rules":len(rules),
       "selection":{k:chosen[k] for k in ("model","calibration","cut","quality","validation")},
       "evaluation":e,"evaluation_annual":annual,"baseline":baseline,
       "target_60_both_directions_observed":success,
       "latest_dataset_candle_open":str(d.index[-1]),
       "latest_dataset_candle_closed":str(decision_times[-1]),
       "research_only":True,"no_zone_engine":True,"live_permission":False,
       "limitations":["No actual price stream at current time and no brokerage signal",
          "2023-2026 years previously inspected in earlier research, NOT pristine holdout",
          "Directional accuracy is not realized P&L, MFE, stop/target or tradable profit",
          "Sample selection across configs and multiple-testing bias still possible",
          "Model probabilities calibrated on older period and may drift",
          "No point-in-time DXY/yield/COT integration here",
          "Source data has gaps and aggregation thresholds; reject incomplete candles",
          "W1 calendar uses full Monday-Friday daily bars, not cTrader broker week",
          "Cost/spread/slippage not measured in direction-only model"]}
    p=OUT/f"r14-direction-{tf}.json";p.write_text(json.dumps(summary,indent=2))
    print(json.dumps({"stage":"direction_complete","tf":TF[tf],"n":summary["counts"],
        "models":len(fitted),"rules":len(rules),"selected":summary["selection"],
        "evaluation":e,"annual":annual,"baseline":baseline,
        "observed_pass":success}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--tf",choices=list(TF),required=True)
    run(p.parse_args().tf)
