"""Snowball S7: XAU entry + EURUSD USD-direction proxy confirmation or divergence.
Research only. Cross-vendor observations are NOT a combined wallet or broker truth.
No LIVE authority, no Frozen V1 state changes, no future price or macro candles.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
import snowball_s5_fxcm_grid as eur
import snowball_s6_xau_grid as xau

OUT=Path("artifacts/snowball_s7");OUT.mkdir(parents=True,exist_ok=True)
FAMILIES=("SWEEP_RECLAIM","SWEEP_MSS","SQUEEZE_EXPAND","FAILED_BREAK","EMA50_DIP")
SIDES=(1,-1)
LOOKBACKS=(12,36)
MACRO=("ANY","EUR_ALIGNED","EUR_COUNTER")
RETURN_LOOKBACK=(3,12)  # 15m / 60m of fully completed EUR M5
VOLATILITY=("HIGH_ATR","LOW_ATR")
SESSIONS=("EUR_CORE_WIB","US_SESSION_WIB")
H4GATES=("H4_WITH","H4_AGAINST")
HOLDS=(60,120)
TARGETS=(1.5,2.5)
STOPS=1.5
LEVELS=(100,125,250,1000)
N=len(FAMILIES)*len(SIDES)*len(LOOKBACKS)*len(MACRO)*len(RETURN_LOOKBACK)*len(VOLATILITY)*len(SESSIONS)*len(H4GATES)*len(HOLDS)*len(TARGETS)
assert N==3840

def macro_data(m_xau,m_eur):
    # All bars are labelled with END timestamp. No asof future bar joins.
    e=m_eur.c.where(m_eur.n==5)
    spread={}
    for lag in RETURN_LOOKBACK:
        # Require all M5 EUR bars from prior lookback to be complete.
        full=e.notna().rolling(lag+1,min_periods=lag+1).sum()==lag+1
        returns=(e/e.shift(lag)-1).where(full)
        spread[lag]=returns.reindex(m_xau.index).to_numpy(float)
    # Ten trading days trailing ATR, lagged one complete bar, no future.
    past=m_xau.atr.shift().rolling(1200,min_periods=900).median()
    ratio=(m_xau.atr/past).to_numpy(float)
    return spread,ratio

def metric(net,stress,correct,mae,signals):
    n=len(net)
    return {"n":n,"signals":int(signals),
      "positive":int(np.count_nonzero(net>0)),
      "positive_stress":int(np.count_nonzero(stress>0)),
      "direction":int(correct.sum()),
      "net_R":float(net.sum()),"stress_net_R":float(stress.sum()),
      "gross_gain_R":float(net[net>0].sum()),
      "gross_loss_R":float(-net[net<0].sum()),
      "mae_R":float(mae.sum())}

def run(year):
    xa,p_x=xau.source(year)
    eu,p_e=eur.get_data(year)
    xm=eur.features(xa);em=eur.features(eu)
    macro,atr_ratio=macro_data(xm,em)
    mins=xm.index.asi8//60_000_000_000
    trend=xm.trend.to_numpy()
    hr=xm.hour_wib.to_numpy()
    sessions={"EUR_CORE_WIB":(hr>=14)&(hr<19),
              "US_SESSION_WIB":(hr>=19)|(hr<1)}
    results=[]
    for side in SIDES:
      for lookback in LOOKBACKS:
       for family in FAMILIES:
        sig=eur.family_signal(xm,side,lookback,family)
        event=np.flatnonzero(sig)
        for hold in HOLDS:
         for tp in TARGETS:
          a,p,stress,correct,mae,stages=xau.outcome(xa,xm,event,side,hold,STOPS,tp)
          where={int(i):j for j,i in enumerate(a)}
          for macro_mode in MACRO:
           for lag in RETURN_LOOKBACK:
            r=macro[lag]
            # EURUSD rising is a bullish USD proxy for XAU; caveat: EUR != DXY.
            aligned=side*r>.0001
            opposed=side*r<-.0001
            if macro_mode=="ANY":mcond=np.ones(len(xm),bool)
            elif macro_mode=="EUR_ALIGNED":mcond=aligned
            else:mcond=opposed
            for vol in VOLATILITY:
             vcond=(atr_ratio>=1.) if vol=="HIGH_ATR" else (atr_ratio<1.)
             vcond &= np.isfinite(atr_ratio)
             for sess,session in sessions.items():
              for h4mode in H4GATES:
               h4cond=(trend==side) if h4mode=="H4_WITH" else (trend==-side)
               signal_ix=np.flatnonzero(sig&mcond&vcond&session&h4cond)
               feasible=np.array([k for k in signal_ix if k in where],dtype=int)
               # Every configuration gets causal fixed horizon no overlapping entries.
               kept=eur.greedy(feasible,hold,mins)
               ix=np.array([where[int(k)] for k in kept],dtype=int)
               conf=(f"{family}|{'BUY' if side==1 else 'SELL'}|LB{lookback}|"
                     f"{macro_mode}|EUR{lag*5}m|{vol}|{sess}|{h4mode}|"
                     f"H{hold}|SL1.5|TP{tp:g}")
               bycash={}
               for cash in LEVELS:
                j=ix[stages[cash][ix]]
                bycash[str(cash)]=metric(p[j],stress[j],correct[j],mae[j],len(signal_ix))
               results.append({"config":conf,"family":family,
                 "direction":"BUY" if side==1 else "SELL",
                 "macro_gate":macro_mode,"return_lookback_minutes":lag*5,
                 "volatility":vol,"session":sess,"H4_gate":h4mode,
                 "lookback":lookback,"hold":hold,"TP_R":tp,
                 "stages":bycash})
    assert len(results)==N,(year,len(results),N)
    report={"year":year,"study":"SNOWBALL_S7_XAU_EUR_PROXY","n":N,
      "XAU_source":p_x,"EUR_source":p_e,"results":results,
      "research_only":True,"live_authority":False,
      "limitations":["Different vendors (Dukascopy-derived XAU and FXCM EUR), NOT a broker live basis",
        "EURUSD direction is a dollar proxy, not the full DXY or Treasury yield",
        "EUR as CONTEXT ONLY; no EUR trading, no shared EUR-XAU account, no native V1",
        "2019–2025 not fresh holdout; calendars FXCM partial 2023–25",
        "Only M5-complete EUR bars known at decision time, no future joins",
        "Four cash values are hypothetical minlot/risk/margin admission, not equity paths",
        "Stress changes costs on identical M1 stop/TP sequence rather than re-evaluating fill timing",
        "Close bid/ask M1 does not contain venue queue or broker spread execution",
        "No USD 10B simulation or original V1 ledger parity"]}
    f=OUT/f"s7_year_{year}.json"
    f.write_text(json.dumps(report,allow_nan=False))
    q=[x for x in results if x["stages"]["100"]["n"]>=30]
    top=sorted(q,key=lambda x:x["stages"]["100"]["stress_net_R"]/x["stages"]["100"]["n"],
               reverse=True)[:3]
    print("S7_YEAR",json.dumps({"year":year,"configs":N,
      "XAU_rows":p_x["rows"],"EUR_rows":p_e["bars"],
      "source_EUR_missing_weeks":p_e["missing_weeks"],
      "top_NOT_SELECTED":[{"name":x["config"],
        "n":x["stages"]["100"]["n"],"avg_stress_R":
          x["stages"]["100"]["stress_net_R"]/x["stages"]["100"]["n"]}
        for x in top]}),flush=True)

def summary(rows,cash,years,k):
    v=[rows[y][k]["stages"][str(cash)] for y in years]
    n=sum(x["n"] for x in v)
    profit=sum(x["gross_gain_R"] for x in v)
    loss=sum(x["gross_loss_R"] for x in v)
    return {"n":n,"mean_R":sum(x["net_R"] for x in v)/n if n else None,
       "mean_stress_R":sum(x["stress_net_R"] for x in v)/n if n else None,
       "pf":profit/loss if loss else None,
       "stress_positive_years":sum(x["stress_net_R"]>0 and x["n"]>=8 for x in v),
       "annual_n":[x["n"] for x in v]}

def aggregate(root):
    records={};inputs={}
    for y in range(2012,2026):
      a=list(Path(root).rglob(f"s7_year_{y}.json"))
      assert len(a)==1,(y,a)
      d=json.loads(a[0].read_text())
      assert d["year"]==y and d["n"]==N
      records[y]={r["config"]:r for r in d["results"]}
      inputs[y]={"XAU_rows":d["XAU_source"]["rows"],
                 "EUR_rows":d["EUR_source"]["bars"],
                 "missing_eur_weeks":d["EUR_source"]["missing_weeks"]}
    keys=set(records[2012])
    assert len(keys)==N and all(set(records[y])==keys for y in records)
    result={"study":"SNOWBALL_S7_XAU_EUR_PROXY_2012_2025",
      "models":N,"model_years":N*14,
      "macro_modes":list(MACRO),"asset_only_XAU_policies_probed":True,
      "EUR_trading":False,
      "train":"2012-2018","valid":"2019-2022","retrospective":"2023-2025",
      "cash":{},"data_quality":inputs,"candidates":[],
      "research_only":True,"live_authority":False,"native_v1_parity":False}
    for cash in LEVELS:
      presel=[];survived=[]
      for k in sorted(keys):
        train=summary(records,cash,range(2012,2019),k)
        if (train["n"]<80 or train["mean_stress_R"] is None or
           train["mean_stress_R"]<=.03 or train["pf"] is None or
           train["pf"]<=1.12 or train["stress_positive_years"]<5):continue
        val=summary(records,cash,range(2019,2023),k)
        retro=summary(records,cash,range(2023,2026),k)
        valid=(val["n"]>=50 and val["mean_stress_R"] is not None and
           val["mean_stress_R"]>.02 and val["pf"] is not None and
           val["pf"]>1.08 and val["stress_positive_years"]>=3)
        presel.append({"config":k,"train":train,"validation":val,
            "retrospective":retro,"validation_passed":bool(valid)})
        if valid:survived.append(k)
      presel.sort(key=lambda x:x["train"]["mean_stress_R"],reverse=True)
      result["cash"][str(cash)]={"train_qualified":len(presel),
        "validation_qualified":len(survived),
        "retrospective_positive":sum(x["validation_passed"] and
          x["retrospective"]["n"]>=30 and
          x["retrospective"]["mean_stress_R"] is not None and
          x["retrospective"]["mean_stress_R"]>0 and
          x["retrospective"]["stress_positive_years"]>=2 for x in presel),
        "top_training_diagnostic":presel[:15]}
    (OUT/"s7_aggregate.json").write_text(json.dumps(result,indent=2,allow_nan=False))
    print("S7_AGGREGATE",json.dumps({"study":result["study"],"models":N,
      "cash_status":{c:{k:v for k,v in q.items() if k!="top_training_diagnostic"}
          for c,q in result["cash"].items()},
      "EUR_not_traded":True,"native_v1_parity":False},allow_nan=False),flush=True)
    print("S7_BEST",json.dumps({c:q["top_training_diagnostic"][:3]
       for c,q in result["cash"].items()},allow_nan=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int);p.add_argument("--aggregate",action="store_true")
    p.add_argument("--root",default="/tmp/snowball_s7")
    p.add_argument("--selftest",action="store_true")
    args=p.parse_args()
    if args.selftest:
        eur.selftest()
        assert N==3840
        print("S7_SELFTEST",json.dumps({"configs":N,"crossfeed_causal":True}))
    elif args.aggregate:aggregate(args.root)
    elif args.year:run(args.year)
    else:p.error("specify action")
