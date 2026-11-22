"""RIZAN Snowball S8: novel structural XAU intraday models, independent bid/ask risk-adjusted screen.
Research ONLY; neither original Frozen V1 nor broker / LIVE performance.
Uses verified pinned 3rd-party Dukascopy-derived XAU M1 via S6.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
import snowball_s5_fxcm_grid as base
import snowball_s6_xau_grid as gold

OUT=Path("artifacts/snowball_s8");OUT.mkdir(parents=True,exist_ok=True)
PATTERNS=("ASIA_LIQUIDITY_FAILURE","ASIA_RANGE_BREAK","PREV_DAY_LIQUIDITY_FAILURE",
 "PREV_DAY_BREAK_RETEST","DAILY_OPEN_REVERSION","ADR_EXTENSION_FADE",
 "LONDON_OPEN_RANGE","NY_OPEN_TRAP","M15_FRACTAL_RECLAIM",
 "ZSCORE_EXTREME_REENTRY","ZSCORE_TREND_EXPANSION","VOL_COMPRESS_EXPAND")
LOOKBACKS=(12,24,48)
SIDES=(1,-1)
REGIMES=("ANY","H4_WITH","H4_AGAINST")
SESSIONS=("ALL","LONDON_WIB","US_WIB")
HOLDS=(30,60,120)
STOPS=(1.0,1.5)
TPS=(1.5,2.5)
TIERS=(100,125,250,1000)
NUM=len(PATTERNS)*len(LOOKBACKS)*len(SIDES)*len(REGIMES)*len(SESSIONS)*len(HOLDS)*len(STOPS)*len(TPS)
assert NUM==7776

def state(m):
    idx=m.index
    assert idx.tz is not None
    local=idx.tz_convert("Asia/Jakarta")
    day=local.normalize()
    hour=local.hour+local.minute/60
    # All daily extremes are used only AFTER they have closed (prior-day shift).
    daily=m.groupby(day).agg(hi=("h","max"),lo=("l","min"),op=("o","first"))
    prev=daily.shift(1)
    x=pd.DataFrame(index=idx)
    x["prev_hi"]=prev.hi.reindex(day).to_numpy(float)
    x["prev_lo"]=prev.lo.reindex(day).to_numpy(float)
    x["op"]=daily.op.reindex(day).to_numpy(float)  # first of the day is already known
    x["prev_adr"]=daily.hi.sub(daily.lo).shift(1).rolling(10,min_periods=7).mean().reindex(day).to_numpy(float)
    x["curr_hi"]=m.h.groupby(day).cummax().to_numpy(float)
    x["curr_lo"]=m.l.groupby(day).cummin().to_numpy(float)
    x["since_open"]=m.c-x["op"]
    x["asia_hi"]=m.h.where((hour>=8)&(hour<13)).groupby(day).max().reindex(day).to_numpy(float)
    x["asia_lo"]=m.l.where((hour>=8)&(hour<13)).groupby(day).min().reindex(day).to_numpy(float)
    x["ld_hi"]=m.h.where((hour>=14)&(hour<=14.5)).groupby(day).max().reindex(day).to_numpy(float)
    x["ld_lo"]=m.l.where((hour>=14)&(hour<=14.5)).groupby(day).min().reindex(day).to_numpy(float)
    x["ny_hi"]=m.h.where((hour>=19)&(hour<=19.5)).groupby(day).max().reindex(day).to_numpy(float)
    x["ny_lo"]=m.l.where((hour>=19)&(hour<=19.5)).groupby(day).min().reindex(day).to_numpy(float)
    x["hour"]=hour
    # 15m close labelled right; only completed 3x5min bar sample admitted.
    m15=m.resample("15min",closed="right",label="right").agg(
      hi=("h","max"),lo=("l","min"),n=("c","count"))
    m15.loc[m15.n!=3,["hi","lo"]]=np.nan
    x["m15prev_hi"]=m15.hi.shift(1).rolling(8,min_periods=8).max().reindex(idx,method="ffill",tolerance=pd.Timedelta(minutes=15)).to_numpy(float)
    x["m15prev_lo"]=m15.lo.shift(1).rolling(8,min_periods=8).min().reindex(idx,method="ffill",tolerance=pd.Timedelta(minutes=15)).to_numpy(float)
    avg=m.c.rolling(48,min_periods=48).mean()
    dev=m.c.rolling(48,min_periods=48).std()
    x["z"]=(m.c-avg)/dev.replace(0,np.nan)
    x["atr_ref"]=m.atr.shift(1).rolling(1440,min_periods=700).median()
    x["vol_ratio"]=m.atr/x["atr_ref"]
    return x

def signals(m,x,side,look,pattern):
    h,l,c,o,a=m.h,m.l,m.c,m.o,m.atr
    bullish=(c>o)&((c-o)>.18*a)
    bearish=(c<o)&((o-c)>.18*a)
    good=bullish if side==1 else bearish
    pv=(x.prev_lo if side==1 else x.prev_hi)
    today=(x.curr_lo if side==1 else x.curr_hi)
    asia=(x.asia_lo if side==1 else x.asia_hi)
    ld=(x.ld_hi if side==1 else x.ld_lo)
    ny=(x.ny_hi if side==1 else x.ny_lo)
    candle_move=(c-c.shift())*side
    close_break=side*(c-pv)
    side_sweep=(l<pv-.08*a)&(c>pv) if side==1 else (h>pv+.08*a)&(c<pv)
    sweep_asia=(l<asia-.06*a)&(c>asia) if side==1 else (h>asia+.06*a)&(c<asia)
    range_break=(c>asia+.1*a) if side==1 else (c<asia-.1*a)
    prior_range_break=(c>x.prev_hi+.08*a) if side==1 else (c<x.prev_lo-.08*a)
    prev_break=(c.shift(1)>x.prev_hi.shift(1)) if side==1 else (c.shift(1)<x.prev_lo.shift(1))
    reenter=(c>x.prev_hi) if side==1 else (c<x.prev_lo)
    adr=x.prev_adr
    ext=(x.op-x.curr_lo) if side==1 else (x.curr_hi-x.op)
    opening=(x.op-c) if side==1 else (c-x.op)
    z=x.z
    z_reentry=((z.shift(1)<-1.8)&(z>-.9)) if side==1 else ((z.shift(1)>1.8)&(z<.9))
    z_expansion=((z>1.8)&(z>z.shift(1))) if side==1 else ((z< -1.8)&(z<z.shift(1)))
    chhi=h.shift().rolling(look,min_periods=look).max()
    chlo=l.shift().rolling(look,min_periods=look).min()
    contracting=(h.shift().rolling(look,min_periods=look).max()
               -l.shift().rolling(look,min_periods=look).min())<2.4*a
    if pattern=="ASIA_LIQUIDITY_FAILURE":
        result=sweep_asia&good&(x.hour>=13)
    elif pattern=="ASIA_RANGE_BREAK":
        result=range_break&good&(x.hour>=13)&(x.hour<=21)&(x.vol_ratio>=1)
    elif pattern=="PREV_DAY_LIQUIDITY_FAILURE":
        result=side_sweep&good
    elif pattern=="PREV_DAY_BREAK_RETEST":
        if side==1:result=prev_break.rolling(3,min_periods=1).max().gt(0)&(l<=x.prev_hi+.25*a)&reenter&good
        else:result=prev_break.rolling(3,min_periods=1).max().gt(0)&(h>=x.prev_lo-.25*a)&reenter&good
    elif pattern=="DAILY_OPEN_REVERSION":
        result=(opening>.75*a)&((c-x.op)*side>0)&good
    elif pattern=="ADR_EXTENSION_FADE":
        result=(ext>1.1*adr)&((c-o)*side>.3*a)&(candle_move>0)
    elif pattern=="LONDON_OPEN_RANGE":
        result=((c>ld+.1*a) if side==1 else (c<ld-.1*a))&good&(x.hour>14.5)&(x.hour<19)
    elif pattern=="NY_OPEN_TRAP":
        trap=(l<x.ny_lo-.10*a)&(c>x.ny_lo) if side==1 else (h>x.ny_hi+.10*a)&(c<x.ny_hi)
        result=trap&good&(x.hour>19.5)
    elif pattern=="M15_FRACTAL_RECLAIM":
        level=x.m15prev_lo if side==1 else x.m15prev_hi
        result=((l<level-.05*a)&(c>level) if side==1 else
                 (h>level+.05*a)&(c<level))&good
    elif pattern=="ZSCORE_EXTREME_REENTRY":
        result=z_reentry&good
    elif pattern=="ZSCORE_TREND_EXPANSION":
        result=z_expansion&good&(x.vol_ratio>=1.15)
    elif pattern=="VOL_COMPRESS_EXPAND":
        result=contracting&good&(x.vol_ratio>=1.15)&((c>chhi) if side==1 else (c<chlo))
    else:raise ValueError(pattern)
    return (result&m.n.eq(5)&m.c.notna()&m.atr.gt(0)).fillna(False).to_numpy(bool)

def metric(p,q,c,mae,opp):
    v=len(p)
    return {"n":v,"opportunities":int(opp),"net_R":float(p.sum()),
      "stress_R":float(q.sum()),"gain_R":float(p[p>0].sum()),
      "loss_R":float(-p[p<0].sum()),"stress_gain_R":float(q[q>0].sum()),
      "stress_loss_R":float(-q[q<0].sum()),
      "win":int(np.count_nonzero(p>0)),"correct":int(np.count_nonzero(c)),
      "mae_R":float(mae.sum())}

def execute(year):
    d,provenance=gold.source(year)
    m=base.features(d)
    x=state(m)
    minute=m.index.asi8//60_000_000_000
    trend=m.trend.to_numpy()
    hr=x.hour.to_numpy(float)
    sessions={"ALL":np.ones(len(m),bool),
      "LONDON_WIB":(hr>=14)&(hr<19),
      "US_WIB":(hr>=19)|(hr<1)}
    result=[]
    for side in SIDES:
      for look in LOOKBACKS:
       for family in PATTERNS:
        s=signals(m,x,side,look,family)
        events=np.flatnonzero(s)
        for hold in HOLDS:
         for stop in STOPS:
          for tp in TPS:
           e,returns,stress,correct,mae,tier=gold.outcome(d,m,events,side,hold,stop,tp)
           mapping={int(v):i for i,v in enumerate(e)}
           for gate in REGIMES:
            allowed=np.ones(len(m),bool) if gate=="ANY" else (
              trend==side if gate=="H4_WITH" else trend==-side)
            for sess,session_mask in sessions.items():
             raw=np.flatnonzero(s&allowed&session_mask)
             feasible=np.array([v for v in raw if v in mapping],dtype=int)
             clean=base.greedy(feasible,hold,minute)
             positions=np.array([mapping[int(v)] for v in clean],dtype=int)
             tiers={}
             for cash in TIERS:
              t=positions[tier[cash][positions]]
              tiers[str(cash)]=metric(returns[t],stress[t],correct[t],mae[t],len(raw))
             key=(f"{family}|{'BUY' if side==1 else 'SELL'}|L{look}|{gate}|"
                  f"{sess}|H{hold}|ATR{stop:g}|TP{tp:g}")
             result.append({"config":key,"family":family,"side":"BUY" if side==1 else "SELL",
               "look":look,"gate":gate,"session":sess,"hold":hold,
               "stop":stop,"target_R":tp,"tiers":tiers})
    assert len(result)==NUM,(year,len(result),NUM)
    output={"version":"SNOWBALL_S8_DIFFERENT_STRUCTURAL_FAMILIES","year":year,
      "source":provenance,"configs":NUM,"data":result,
      "research_only":True,"live_execution":False,"frozen_v1_parity":False,
      "limitations":["Third-party public Dukascopy-derived source; NOT exact frozen V1 price/ledger",
        "Daily/Asia/opening-range levels used only after their information cutoffs",
        "XAU bid/ask with nominal 1oz 1:200, 8% planned risk, 50% margin",
        "Stop-first ambiguous M1; fixed slippage/fee estimates, stress added after same fill path",
        "No continuous wallet, multiple concurrent basket risk, broker tick execution or market capacity",
        "No native V1 parity, no $10B verified, historical 2012-2025 folds not pristine future holdout"]}
    path=OUT/f"s8_xau_{year}.json";path.write_text(json.dumps(output,allow_nan=False))
    n=[v for v in result if v["tiers"]["100"]["n"]>=30]
    diagnostic=sorted(n,key=lambda y:y["tiers"]["100"]["stress_R"]/y["tiers"]["100"]["n"],reverse=True)[:3]
    print("S8_YEAR",json.dumps({"year":year,"models":NUM,"rows":provenance["rows"],
      "eligible_models_ge30":len(n),
      "top_single_year_DIAGNOSTIC":[{"config":a["config"],"n":a["tiers"]["100"]["n"],
         "mean_stress_R":a["tiers"]["100"]["stress_R"]/a["tiers"]["100"]["n"]}
         for a in diagnostic]}),flush=True)

def fold(rows,years,cash,k):
    samples=[rows[y][k]["tiers"][str(cash)] for y in years]
    n=sum(a["n"] for a in samples)
    val=sum(a["stress_R"] for a in samples)
    profit=sum(a["stress_gain_R"] for a in samples)
    loss=sum(a["stress_loss_R"] for a in samples)
    return {"n":n,"stress_avg_R":val/n if n else None,
      "stress_pf":profit/loss if loss else None,
      "positive_years":sum(a["n"]>=10 and a["stress_R"]>0 for a in samples),
      "yearly_n":[a["n"] for a in samples]}

def aggregate(root):
    panels={};qual={}
    for year in range(2012,2026):
        p=list(Path(root).rglob(f"s8_xau_{year}.json"))
        assert len(p)==1,(year,p)
        d=json.loads(p[0].read_text())
        assert d["year"]==year and d["configs"]==NUM
        panels[year]={r["config"]:r for r in d["data"]}
        qual[str(year)]={k:v for k,v in d["source"].items() if k!="monthly_sha256"}
    keys=set(panels[2012])
    assert len(keys)==NUM and all(set(panels[y])==keys for y in panels)
    output={"study":"SNOWBALL_S8_XAU_NEW_STRUCTURAL_ENTRIES_2012_2025",
       "number_models":NUM,"model_years":NUM*14,
       "training":"2012-2018","validation":"2019-2022","retrospective":"2023-2025",
       "stages":{},"source_annual":qual,"non_frozen_screen_only":True,
       "native_v1_wallet_replay":False,"target_10b_verified":False,"live_authority":False}
    for cash in TIERS:
        train=[];valid=[]
        for k in sorted(keys):
            t=fold(panels,range(2012,2019),cash,k)
            if (t["n"]<120 or t["stress_avg_R"] is None or t["stress_avg_R"]<=.03 or
                t["stress_pf"] is None or t["stress_pf"]<1.12 or
                t["positive_years"]<5):continue
            v=fold(panels,range(2019,2023),cash,k)
            retro=fold(panels,range(2023,2026),cash,k)
            good=(v["n"]>=70 and v["stress_avg_R"] is not None and
                  v["stress_avg_R"]>.01 and v["stress_pf"] is not None and
                  v["stress_pf"]>=1.08 and v["positive_years"]>=3)
            train.append({"config":k,"train":t,"validation":v,
               "retrospective":retro,"validation_pass":good})
            if good:valid.append(k)
        train.sort(key=lambda a:a["train"]["stress_avg_R"],reverse=True)
        output["stages"][str(cash)]={"train_qualified":len(train),
           "validation_qualified":len(valid),
           "retrospective_positive":sum(v["validation_pass"] and
             v["retrospective"]["n"]>=30 and
             v["retrospective"]["stress_avg_R"] is not None and
             v["retrospective"]["stress_avg_R"]>0 and
             v["retrospective"]["positive_years"]>=2 for v in train),
           "top_DIAGNOSTIC":train[:30]}
    (OUT/"s8_aggregate.json").write_text(json.dumps(output,indent=2,allow_nan=False))
    print("S8_AGGREGATE",json.dumps({"study":output["study"],"models":NUM,
        "model_years":NUM*14,"tiers":{t:{k:v for k,v in z.items() if k!="top_DIAGNOSTIC"}
         for t,z in output["stages"].items()},
         "native_wallet":False,"live_authority":False},allow_nan=False),flush=True)
    print("S8_BEST",json.dumps({t:z["top_DIAGNOSTIC"][:2] for t,z in output["stages"].items()}),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int)
    p.add_argument("--aggregate",action="store_true")
    p.add_argument("--root",default="/tmp/snowball_s8")
    p.add_argument("--selftest",action="store_true")
    a=p.parse_args()
    if a.selftest:
        assert NUM==7776
        base.selftest()
        idx=pd.date_range("2024-03-05",periods=576,freq="5min",tz="UTC")
        sample=pd.DataFrame({"o":np.ones(len(idx))*2000,
          "h":np.ones(len(idx))*2000.5,
          "l":np.ones(len(idx))*1999.5,
          "c":np.ones(len(idx))*2000,"n":np.ones(len(idx))*5,
          "atr":np.ones(len(idx))*2,
          "trend":np.ones(len(idx)),"hour_wib":idx.tz_convert("Asia/Jakarta").hour},index=idx)
        feat=state(sample)
        for f in PATTERNS:
            o=signals(sample,feat,1,12,f)
            assert len(o)==len(sample),f
        print("S8_SELFTEST_PASS",json.dumps({"models":NUM,"families":len(PATTERNS)}),flush=True)
    elif a.aggregate:aggregate(a.root)
    elif a.year in range(2012,2026):execute(a.year)
    else:p.error("year must be 2012–2025 or --aggregate/--selftest")
