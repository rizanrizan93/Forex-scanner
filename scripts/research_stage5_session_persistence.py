from __future__ import annotations

import argparse,json
from pathlib import Path
import pandas as pd

import research_stage3_m5_runtime as m5
import research_stage4_session_oos as m15

COSTS=[1.2,1.5]
YEARS=[2022,2023,2024,2025,2026]
FIXED=m15.Variant("FIXED_AE6_T6_12_R1.8_B0.25_NONE",6,6,12,1.8,.25,"NONE")

def metric(vals):
 if not vals:return {"n":0,"avg":None,"net":0,"pf":None,"win":None}
 a=[x["net_r"] for x in vals];pos=sum(x for x in a if x>0);neg=-sum(x for x in a if x<0)
 return {"n":len(a),"avg":sum(a)/len(a),"net":sum(a),"pf":pos/neg if neg>0 else None,"win":sum(x>0 for x in a)/len(a)}

def eval_m5():
 out={}
 for sym,path in m5.FX_PATHS.items():
  df=m5.load(path);rs=m5.asia(df);out[sym]={}
  for c in COSTS:
   ts=[]
   for r in rs:
    t=m5.simulate(df,sym,"ASIA_RANGE_LONDON_BREAKOUT",r,c)
    if t:ts.append(t)
   out[sym][str(c)]={str(y):metric([t for t in ts if pd.Timestamp(t["entry_at"]).year==y]) for y in YEARS}
 return out

def eval_m15():
 out={}
 for sym,path in m15.FX_PATHS.items():
  df=m15.load(path);rs=m15.records(df,FIXED);out[sym]={}
  for c in COSTS:
   ts=[]
   for r in rs:
    t=m15.simulate(df,sym,FIXED,r,c)
    if t:ts.append(t)
   out[sym][str(c)]={str(y):metric([t for t in ts if pd.Timestamp(t["entry_at"]).year==y]) for y in YEARS}
 return out

def stability(rows):
 vals=[v for v in rows.values() if v["n"]>=30 and v["avg"] is not None]
 return {"eligible_years":len(vals),"positive_years":sum(v["avg"]>0 for v in vals),"mean_year_avg_r":sum(v["avg"] for v in vals)/len(vals) if vals else None,"worst_year_avg_r":min((v["avg"] for v in vals),default=None)}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--output",default="out/stage5_persistence");z=ap.parse_args();out=Path(z.output);out.mkdir(parents=True,exist_ok=True)
 data={"m5":eval_m5(),"m15":eval_m15()};rank=[]
 for tf in ["m5","m15"]:
  for sym,r in data[tf].items():
   s=stability(r["1.2"]);ss=stability(r["1.5"])
   rank.append({"timeframe":tf.upper(),"symbol":sym,"base":s,"stress":ss})
 rank.sort(key=lambda r:((r["stress"]["positive_years"] if r["stress"]["positive_years"] is not None else -1),(r["stress"]["mean_year_avg_r"] if r["stress"]["mean_year_avg_r"] is not None else -99)),reverse=True)
 payload={"rule":"Asian range 00:00-05:45 UTC; first close breakout 06:00-11:45; body>=0.25 ATR; opposite-range stop; 1.8R target; next-bar entry; STOP_FIRST","data":data,"ranking":rank}
 (out/"summary.json").write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
 lines=["# Session Breakout Persistence", "", "Fixed rules. No parameter tuning.", "", "|Rank|TF|Pair|Base +years/eligible|Base mean yr R|Stress +years/eligible|Stress mean yr R|Stress worst yr R|", "|---:|---|---|---:|---:|---:|---:|---:|"]
 for i,r in enumerate(rank,1):
  b=r["base"];s=r["stress"]
  lines.append(f"|{i}|{r['timeframe']}|{r['symbol']}|{b['positive_years']}/{b['eligible_years']}|{(b['mean_year_avg_r'] or 0):.4f}|{s['positive_years']}/{s['eligible_years']}|{(s['mean_year_avg_r'] or 0):.4f}|{(s['worst_year_avg_r'] or 0):.4f}|")
 (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8");print((out/"report.md").read_text())
if __name__=="__main__":main()
