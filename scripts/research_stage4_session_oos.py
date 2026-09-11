from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from research_stage2_m15_walkforward import FX_PATHS, RAW, features

TRAIN_END=pd.Timestamp("2021-01-01")
VALID_START=pd.Timestamp("2021-01-01")
FINAL_START=pd.Timestamp("2023-01-01")
BASE_COST=1.2
STRESS_COST=1.5
MAX_HOLD=64

@dataclass(frozen=True)
class Variant:
    name:str
    asia_end:int
    trade_start:int
    trade_end:int
    rr:float
    body_atr:float
    filter_name:str

VARIANTS=[]
for asia_end,ts,te in [(5,6,10),(6,6,10),(6,7,11),(6,7,12),(7,7,12),(7,8,12)]:
 for rr in [1.2,1.5,1.8,2.0,2.5]:
  for body in [.15,.25,.40]:
   for filt in ["NONE","TREND","RANGE_COMPACT"]:
    VARIANTS.append(Variant(f"AE{asia_end}_T{ts}{te}_R{rr}_B{body}_{filt}",asia_end,ts,te,rr,body,filt))

def pip_size(s): return .01 if s.endswith("JPY") else .0001

def load(path):
 d=pd.read_csv(RAW.format(path=path)); d.columns=[c.lower().strip() for c in d.columns]
 d["time"]=pd.to_datetime(d.time,errors="coerce",utc=True).dt.tz_convert(None)
 for c in ["open","high","low","close"]: d[c]=pd.to_numeric(d[c],errors="coerce")
 d=d.dropna(subset=["time","open","high","low","close"]).sort_values("time").drop_duplicates("time").reset_index(drop=True)
 d=features(d); d["ema200"]=d.close.ewm(span=200,adjust=False).mean(); d["date"]=d.time.dt.date; d["hour"]=d.time.dt.hour
 return d

def records(df,v):
 rows=[]
 for _,g in df.groupby("date",sort=False):
  a=g[g.hour<v.asia_end]; t=g[(g.hour>=v.trade_start)&(g.hour<v.trade_end)]
  if len(a)<max(12,v.asia_end*3) or t.empty: continue
  hi=float(a.high.max()); lo=float(a.low.min()); width=hi-lo
  if width<=0: continue
  atr0=float(a.atr.iloc[-1]) if np.isfinite(a.atr.iloc[-1]) else np.nan
  if not np.isfinite(atr0) or atr0<=0: continue
  compact=width/atr0 <= 5.0
  for idx,r in t.iterrows():
   long_ok=r.close>hi and r.close>r.open and r.body_atr>=v.body_atr
   short_ok=r.close<lo and r.close<r.open and r.body_atr>=v.body_atr
   if v.filter_name=="TREND":
    long_ok=long_ok and r.ema50>r.ema200
    short_ok=short_ok and r.ema50<r.ema200
   elif v.filter_name=="RANGE_COMPACT":
    long_ok=long_ok and compact; short_ok=short_ok and compact
   if long_ok: rows.append({"i":int(idx),"d":"LONG","stop":lo}); break
   if short_ok: rows.append({"i":int(idx),"d":"SHORT","stop":hi}); break
 return rows

def simulate(df,sym,v,r,cost):
 i=r["i"]; e=i+1
 if e>=len(df): return None
 entry=float(df.at[e,"open"]); stop=float(r["stop"]); d=r["d"]
 risk=entry-stop if d=="LONG" else stop-entry
 if risk<=0 or risk/pip_size(sym)<2:return None
 target=entry+v.rr*risk if d=="LONG" else entry-v.rr*risk
 last=min(len(df)-1,e+MAX_HOLD-1); gross=None; x=last
 for j in range(e,last+1):
  lo=float(df.at[j,"low"]); hi=float(df.at[j,"high"]); hs=lo<=stop if d=="LONG" else hi>=stop; ht=hi>=target if d=="LONG" else lo<=target
  if hs and ht: gross=-1.;x=j;break
  if hs:gross=-1.;x=j;break
  if ht:gross=v.rr;x=j;break
 if gross is None:
  px=float(df.at[x,"close"]);gross=(px-entry)/risk if d=="LONG" else (entry-px)/risk;gross=max(-1.,min(v.rr,gross))
 cr=cost/(risk/pip_size(sym));return {"entry_at":df.at[e,"time"],"net_r":float(gross-cr)}

def metric(rows):
 if not rows:return {"n":0,"avg":-999.,"pf":0.,"net":0.}
 a=np.array([r["net_r"] for r in rows]);p=a[a>0].sum();l=-a[a<0].sum();return {"n":len(a),"avg":float(a.mean()),"pf":float(p/l) if l>0 else 99.,"net":float(a.sum()),"win":float((a>0).mean())}

def choose(cands):
 # Must be positive in both train and validation; favor validation expectancy then breadth/stability.
 ok=[r for r in cands if r["train"]["n"]>=150 and r["valid"]["n"]>=60 and r["train"]["avg"]>0 and r["valid"]["avg"]>0 and r["train"]["pf"]>1 and r["valid"]["pf"]>1]
 if not ok:return None
 for r in ok:
  r["select_score"]=min(r["train"]["avg"],r["valid"]["avg"])+.25*min(r["train"]["pf"]-1,r["valid"]["pf"]-1)
 return max(ok,key=lambda r:r["select_score"])

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--output",default="out/stage4_session");z=ap.parse_args();out=Path(z.output);out.mkdir(parents=True,exist_ok=True)
 data={s:load(p) for s,p in FX_PATHS.items()}; coverage={s:{"rows":len(d),"start":str(d.time.min()),"end":str(d.time.max())} for s,d in data.items()}
 # Precompute each variant's per-pair trades at base cost.
 cache={}
 global_candidates=[]
 for v in VARIANTS:
  train=[];valid=[]
  for sym,df in data.items():
   rs=records(df,v); key=(sym,v.name); cache[key]=rs
   for r in rs:
    t=simulate(df,sym,v,r,BASE_COST)
    if not t:continue
    if t["entry_at"]<TRAIN_END:train.append(t)
    elif VALID_START<=t["entry_at"]<FINAL_START:valid.append(t)
  global_candidates.append({"variant":v.name,"train":metric(train),"valid":metric(valid)})
 global_pick=choose(global_candidates)

 pair_picks={}
 for sym,df in data.items():
  cand=[]
  for v in VARIANTS:
   tr=[];va=[]
   for r in cache[(sym,v.name)]:
    t=simulate(df,sym,v,r,BASE_COST)
    if not t:continue
    if t["entry_at"]<TRAIN_END:tr.append(t)
    elif VALID_START<=t["entry_at"]<FINAL_START:va.append(t)
   cand.append({"variant":v.name,"train":metric(tr),"valid":metric(va)})
  pair_picks[sym]=choose(cand)

 def eval_pick(sym,vname,cost):
  v=next(v for v in VARIANTS if v.name==vname);df=data[sym]; rows=[]
  for r in cache[(sym,vname)]:
   t=simulate(df,sym,v,r,cost)
   if t and t["entry_at"]>=FINAL_START:rows.append(t)
  return metric(rows)

 final_global={};
 if global_pick:
  vn=global_pick["variant"]
  final_global={"variant":vn,"selected_on":{"train":global_pick["train"],"valid":global_pick["valid"]},"base_by_pair":{},"stress_by_pair":{}}
  agg_b=[];agg_s=[]
  for sym in data:
   mb=eval_pick(sym,vn,BASE_COST);ms=eval_pick(sym,vn,STRESS_COST);final_global["base_by_pair"][sym]=mb;final_global["stress_by_pair"][sym]=ms
   # Reconstruct aggregate final rows for exact metric.
   v=next(v for v in VARIANTS if v.name==vn);df=data[sym]
   for r in cache[(sym,vn)]:
    tb=simulate(df,sym,v,r,BASE_COST);ts=simulate(df,sym,v,r,STRESS_COST)
    if tb and tb["entry_at"]>=FINAL_START:agg_b.append(tb)
    if ts and ts["entry_at"]>=FINAL_START:agg_s.append(ts)
  final_global["base"]=metric(agg_b);final_global["stress"]=metric(agg_s)

 final_pairs={}
 for sym,pick in pair_picks.items():
  if not pick: final_pairs[sym]={"selected":None};continue
  vn=pick["variant"]; final_pairs[sym]={"selected":vn,"train":pick["train"],"valid":pick["valid"],"final_base":eval_pick(sym,vn,BASE_COST),"final_stress":eval_pick(sym,vn,STRESS_COST)}

 payload={"methodology":{"variant_count":len(VARIANTS),"train":"before 2021","validation":"2021-2022","untouched_final":"2023+","base_cost_pips":BASE_COST,"stress_cost_pips":STRESS_COST,"selection":"requires positive train and validation before final is examined"},"coverage":coverage,"global_pick":final_global,"pair_picks":final_pairs}
 (out/"summary.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")
 lines=["# Stage 4 Session Breakout Frozen-OOS Validation","",f"Variants tested pre-OOS: {len(VARIANTS)}",""]
 if final_global:
  lines += ["## Global frozen variant",f"- variant: **{final_global['variant']}**",f"- train: {final_global['selected_on']['train']}",f"- validation 2021-22: {final_global['selected_on']['valid']}",f"- FINAL 2023+ base: **{final_global['base']}**",f"- FINAL 2023+ stress: **{final_global['stress']}**",""]
 else: lines += ["## Global frozen variant","No variant met positive train + positive validation gate.",""]
 lines += ["## Pair-specific frozen variants",""]
 for sym,r in final_pairs.items(): lines.append(f"- **{sym}**: {r}")
 (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8");print((out/"report.md").read_text())
if __name__=="__main__":main()
