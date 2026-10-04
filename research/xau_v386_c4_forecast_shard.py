from __future__ import annotations
import argparse, json
from datetime import UTC, datetime
from pathlib import Path
from fx_scanner.research_xau_sd_liquidity_v345 import load_price_frame
from xau_v384_adaptive_c4_reforecast_cached import _arrays,_bar_cache,_forecast

def main():
 p=argparse.ArgumentParser(); p.add_argument("--year",type=int,required=True); p.add_argument("--month",type=int,required=True); p.add_argument("--csv",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
 price=load_price_frame(a.csv); arrays=_arrays(price); bars,completed,_=_bar_cache(price)
 cache={}; stats={"hits":0,"evaluations":0}; rows={}
 for t in completed["M15"]:
  u=t.astimezone(UTC)
  if u.year!=a.year or u.month!=a.month: continue
  f=_forecast(as_of=u,arrays=arrays,bars=bars,completed=completed,cache=cache,cache_stats=stats)
  rows[u.isoformat()]=f
 payload={"schema":"XAU_V386_C4_FORECAST_SHARD_V1","year":a.year,"month":a.month,"causal":True,"champion_selector":"V376_C4_NEXT_ZONE_PATH_FROZEN","execution_authority":False,"forecasts":rows,"cache_stats":stats}
 a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(payload,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
 print("V386_SHARD="+json.dumps({"month":a.month,"forecasts":len(rows),"stats":stats},sort_keys=True))
if __name__=="__main__": main()
