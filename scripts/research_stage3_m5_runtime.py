from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

FX_PATHS={
 "EURUSD":"Forex-Majors/EURUSD/EURUSD_M5.csv",
 "GBPUSD":"Forex-Majors/GBPUSD/GBPUSD_M5.csv",
 "USDJPY":"Forex-Majors/USDJPY/USDJPY_M5.csv",
 "AUDUSD":"Forex-Majors/AUDUSD/AUDUSD_M5.csv",
 "USDCAD":"Forex-Main/USDCAD/USDCAD_M5.csv",
 "USDCHF":"Forex-Main/USDCHF/USDCHF_M5.csv",
}
RAW="https://raw.githubusercontent.com/simom1/XAUUSD-history/main/{path}"
STRATEGIES=["IMPULSE_RETEST_V2","DONCHIAN_20_LOWVOL","DONCHIAN_40_LOWVOL","FOUR_EMA_9_20_34_50_PULLBACK","ASIA_RANGE_LONDON_BREAKOUT"]
FINAL=pd.Timestamp("2023-01-01")
MAX_HOLD=192
BASE_COST_PIPS=1.2
STRESS_COST_PIPS=1.5


def pip_size(s): return 0.01 if s.endswith("JPY") else 0.0001

def load(path):
 d=pd.read_csv(RAW.format(path=path)); d.columns=[c.lower().strip() for c in d.columns]
 d["time"]=pd.to_datetime(d.time,errors="coerce",utc=True).dt.tz_convert(None)
 for c in ["open","high","low","close"]: d[c]=pd.to_numeric(d[c],errors="coerce")
 d=d.dropna(subset=["time","open","high","low","close"]).sort_values("time").drop_duplicates("time").reset_index(drop=True)
 pc=d.close.shift(1); tr=pd.concat([d.high-d.low,(d.high-pc).abs(),(d.low-pc).abs()],axis=1).max(axis=1)
 d["atr"]=tr.rolling(14,min_periods=14).mean()
 for p in [9,20,34,50]: d[f"ema{p}"]=d.close.ewm(span=p,adjust=False).mean()
 d["hi12"]=d.high.shift(1).rolling(12,min_periods=12).max(); d["lo12"]=d.low.shift(1).rolling(12,min_periods=12).min()
 d["hi20"]=d.high.shift(1).rolling(20,min_periods=20).max(); d["lo20"]=d.low.shift(1).rolling(20,min_periods=20).min()
 d["hi40"]=d.high.shift(1).rolling(40,min_periods=40).max(); d["lo40"]=d.low.shift(1).rolling(40,min_periods=40).min()
 d["atr_pct"]=d.atr/d.close.replace(0,np.nan); d["atr_q35"]=d.atr_pct.shift(1).rolling(3000,min_periods=1000).quantile(.35)
 d["body_atr"]=(d.close-d.open).abs()/d.atr.replace(0,np.nan); d["hour"]=d.time.dt.hour; d["date"]=d.time.dt.date
 return d

def cooldown(rows,b=24):
 out=[]; last=-10**9
 for r in sorted(rows,key=lambda z:z["i"]):
  if r["i"]-last<b: continue
  out.append(r); last=r["i"]
 return out

def impulse(df):
 rows=[]
 rng=(df.high-df.low).replace(0,np.nan); body=(df.close-df.open).abs()
 for direction in ["LONG","SHORT"]:
  if direction=="LONG": loc=(df.close-df.low)/rng; mask=(df.close>df.hi12)&(df.close>df.open)&(loc>=.75)&((df.high-df.low)>=1.2*df.atr)&(body>=.8*df.atr)
  else: loc=(df.high-df.close)/rng; mask=(df.close<df.lo12)&(df.close<df.open)&(loc>=.75)&((df.high-df.low)>=1.2*df.atr)&(body>=.8*df.atr)
  for j in np.flatnonzero(mask.fillna(False).to_numpy()):
   if j<1000 or j+1>=len(df): continue
   a=float(df.at[j,"atr"]); level=float(df.at[j,"hi12"] if direction=="LONG" else df.at[j,"lo12"]); ic=float(df.at[j,"close"])
   if not np.isfinite(a) or a<=0: continue
   for k in range(j+1,min(j+13,len(df))):
    r=df.iloc[k]
    if direction=="LONG": depth=(ic-r.low)/a; accepted=r.close>level; invalid=r.close<level-.25*a
    else: depth=(r.high-ic)/a; accepted=r.close<level; invalid=r.close>level+.25*a
    if invalid: break
    if accepted and .10<=depth<=1.25:
     stop=level-.35*a if direction=="LONG" else level+.35*a
     rows.append({"i":k,"d":direction,"atr":a,"stop":float(stop),"rr":1.5}); break
 return cooldown(rows,12)

def generic(df,strategy):
 lv=df.atr_pct.shift(1)<=df.atr_q35.shift(1)
 if strategy=="DONCHIAN_20_LOWVOL":
  lo=lv&(df.close>df.hi20)&(df.close>df.open)&(df.body_atr>=.3); sh=lv&(df.close<df.lo20)&(df.close<df.open)&(df.body_atr>=.3); sa=1.5; rr=2.0
 elif strategy=="DONCHIAN_40_LOWVOL":
  lo=lv&(df.close>df.hi40)&(df.close>df.open)&(df.body_atr>=.3); sh=lv&(df.close<df.lo40)&(df.close<df.open)&(df.body_atr>=.3); sa=1.5; rr=2.2
 elif strategy=="FOUR_EMA_9_20_34_50_PULLBACK":
  lo=(df.ema9>df.ema20)&(df.ema20>df.ema34)&(df.ema34>df.ema50)&(df.ema9>df.ema9.shift(5))&(df.low<=df.ema20+.1*df.atr)&(df.close>df.ema9)&(df.close>df.open)
  sh=(df.ema9<df.ema20)&(df.ema20<df.ema34)&(df.ema34<df.ema50)&(df.ema9<df.ema9.shift(5))&(df.high>=df.ema20-.1*df.atr)&(df.close<df.ema9)&(df.close<df.open); sa=1.4; rr=1.8
 else: raise ValueError(strategy)
 rows=[]
 for d,m in [("LONG",lo),("SHORT",sh)]:
  for i in np.flatnonzero(m.fillna(False).to_numpy()):
   if i<3100 or i+1>=len(df): continue
   rows.append({"i":int(i),"d":d,"atr":float(df.at[i,"atr"]),"stop_atr":sa,"rr":rr})
 return cooldown(rows)

def asia(df):
 rows=[]
 for _,g in df.groupby("date",sort=False):
  a=g[g.hour<6]; t=g[(g.hour>=6)&(g.hour<12)]
  if len(a)<60 or t.empty: continue
  hi=float(a.high.max()); lo=float(a.low.min())
  for idx,r in t.iterrows():
   if r.close>hi and r.close>r.open and r.body_atr>=.25: rows.append({"i":int(idx),"d":"LONG","atr":float(r.atr),"stop":lo,"rr":1.8}); break
   if r.close<lo and r.close<r.open and r.body_atr>=.25: rows.append({"i":int(idx),"d":"SHORT","atr":float(r.atr),"stop":hi,"rr":1.8}); break
 return cooldown(rows,1)

def simulate(df,symbol,strategy,r,cost_pips):
 i=r["i"]; e=i+1
 if e>=len(df): return None
 entry=float(df.at[e,"open"]); d=r["d"]; atr=float(r["atr"])
 if "stop" in r: stop=float(r["stop"]); risk=entry-stop if d=="LONG" else stop-entry
 else: risk=float(r["stop_atr"])*atr; stop=entry-risk if d=="LONG" else entry+risk
 if not np.isfinite(risk) or risk<=0 or risk/pip_size(symbol)<2: return None
 rr=float(r["rr"]); target=entry+rr*risk if d=="LONG" else entry-rr*risk
 last=min(len(df)-1,e+MAX_HOLD-1); gross=None; x=last
 for j in range(e,last+1):
  lo=float(df.at[j,"low"]); hi=float(df.at[j,"high"]); hs=lo<=stop if d=="LONG" else hi>=stop; ht=hi>=target if d=="LONG" else lo<=target
  if hs and ht: gross=-1.; x=j; break
  if hs: gross=-1.; x=j; break
  if ht: gross=rr; x=j; break
 if gross is None:
  px=float(df.at[x,"close"]); gross=(px-entry)/risk if d=="LONG" else (entry-px)/risk; gross=max(-1.,min(rr,gross))
 cr=cost_pips/(risk/pip_size(symbol)); return {"strategy":strategy,"symbol":symbol,"entry_at":df.at[e,"time"],"net_r":float(gross-cr),"gross_r":float(gross),"cost_r":float(cr)}

def metrics(g):
 if g.empty:return {"trades":0}
 win=g[g.net_r>0].net_r.sum(); loss=-g[g.net_r<0].net_r.sum(); eq=g.net_r.cumsum().to_numpy(); peak=np.maximum.accumulate(np.maximum(eq,0)); dd=peak-eq
 return {"trades":len(g),"avg_r":float(g.net_r.mean()),"net_r":float(g.net_r.sum()),"win_rate":float((g.net_r>0).mean()),"pf":float(win/loss) if loss>0 else None,"max_dd_r":float(dd.max())}

def boot(g,n=1000,seed=567):
 if len(g)<30:return {}
 a=g.net_r.to_numpy(); rng=np.random.default_rng(seed); m=np.array([rng.choice(a,size=len(a),replace=True).mean() for _ in range(n)])
 return {"p_positive":float((m>0).mean()),"p05":float(np.quantile(m,.05)),"p50":float(np.quantile(m,.5))}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--output",default="out/stage3_m5"); z=ap.parse_args(); out=Path(z.output); out.mkdir(parents=True,exist_ok=True)
 rows={BASE_COST_PIPS:[],STRESS_COST_PIPS:[]}; coverage={}
 for sym,path in FX_PATHS.items():
  df=load(path); coverage[sym]={"rows":len(df),"start":str(df.time.min()),"end":str(df.time.max())}
  recs={"IMPULSE_RETEST_V2":impulse(df),"DONCHIAN_20_LOWVOL":generic(df,"DONCHIAN_20_LOWVOL"),"DONCHIAN_40_LOWVOL":generic(df,"DONCHIAN_40_LOWVOL"),"FOUR_EMA_9_20_34_50_PULLBACK":generic(df,"FOUR_EMA_9_20_34_50_PULLBACK"),"ASIA_RANGE_LONDON_BREAKOUT":asia(df)}
  for cp in rows:
   for s,rs in recs.items():
    for r in rs:
     t=simulate(df,sym,s,r,cp)
     if t: rows[cp].append(t)
 result={"coverage":coverage,"cost_contract":{"base_cost_pips":BASE_COST_PIPS,"stress_cost_pips":STRESS_COST_PIPS},"results":{}}
 for cp,rr in rows.items():
  t=pd.DataFrame(rr); t.entry_at=pd.to_datetime(t.entry_at); hold=t[t.entry_at>=FINAL]
  ranking=[]
  for s in STRATEGIES:
   g=hold[hold.strategy==s].sort_values("entry_at").reset_index(drop=True); m=metrics(g); b=boot(g); pos=0; pairs={}
   for sym in FX_PATHS:
    pm=metrics(g[g.symbol==sym].sort_values("entry_at").reset_index(drop=True)); pairs[sym]=pm
    if pm.get("trades",0)>=30 and (pm.get("avg_r") or 0)>0: pos+=1
   ranking.append({"strategy":s,"positive_pairs":pos,"pair_metrics":pairs,**m,**b})
  result["results"][str(cp)]=sorted(ranking,key=lambda q:((q.get("avg_r") or -99),q.get("positive_pairs",0),q.get("p_positive",0)),reverse=True)
 (out/"summary.json").write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
 lines=["# Stage 3 M5 Runtime Validation","","Final holdout: 2023+; six FX majors; STOP_FIRST; costs in actual pips.",""]
 for cp in [BASE_COST_PIPS,STRESS_COST_PIPS]:
  lines += [f"## Cost {cp:.1f} pips","","|Rank|Strategy|Trades|Avg R|Net R|PF|Win %|Positive pairs|Bootstrap P+|","|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
  for k,r in enumerate(result["results"][str(cp)],1):
   pf="NA" if r.get("pf") is None else f"{r['pf']:.3f}"; lines.append(f"|{k}|{r['strategy']}|{r['trades']}|{r.get('avg_r',0):.4f}|{r.get('net_r',0):.1f}|{pf}|{100*r.get('win_rate',0):.1f}%|{r.get('positive_pairs',0)}/6|{100*r.get('p_positive',0):.1f}%|")
  lines.append("")
 (out/"report.md").write_text("\n".join(lines),encoding="utf-8"); print((out/"report.md").read_text())
if __name__=="__main__": main()
