"""Exploratory stability grid added after initial negative friction results.
Not a fresh confirmatory OOS search. Targets remain training-selected.
"""
import pathlib,json,pandas as pd
import sys
from replay import run
from analyze import metrics,prepared
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'results'
configs=[tuple(x) for x in json.loads((OUT/'selected_configs.json').read_text())];rows=[]
ids=[f'{setup}_{session}_R{r}' for session,setup,r in configs]
for scale in [1.,1.6,7/3]:
 for hold in [60,120,300]:
  name=f'SENS_STOP{scale:.4f}_HOLD{hold}'
  if scale==1. and hold==120:path=OUT/'BASE_PERIODS'
  elif '--summarize-only' in sys.argv:path=OUT/name
  else:path=run(configs=configs,mode='PERIODS',stop_scale=scale,holding_minutes=hold,outname=name)
  t=prepared(pd.read_csv(path/'trades.csv.gz'))
  t=t[t.candidate.isin(ids)]
  for key,g in t.groupby('candidate'):
   for label,mask,months in [('TRAIN',g.year<=2021,36),('VALIDATION',(g.year>=2022)&(g.year<=2023),24),('OOS',g.year>=2024,27)]:
    rows.append({'candidate':key,'stop_scale':scale,'holding_minutes':hold,'period':label,**metrics(g[mask],10000.,months)})
  pd.DataFrame(rows).to_csv(OUT/'parameter_sensitivity.csv',index=False)
