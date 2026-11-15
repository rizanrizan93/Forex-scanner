"""Follow up the one positive test-period sensitivity case without promoting it."""
import pathlib,json,pandas as pd
from replay import run
from analyze import metrics,prepared,bootstrap
ROOT=pathlib.Path(__file__).resolve().parents[1];OUT=ROOT/'results'
configs=[('ASIA_FULL','TREND_FVG',3.)];key='TREND_FVG_ASIA_FULL_R3.0';rows=[]
for cost in ['STRESS15','STRESS20']:
 p=run(cost=cost,configs=configs,mode='PERIODS',stop_scale=7/3,holding_minutes=300,outname='EXPLORATORY_'+cost)
 t=prepared(pd.read_csv(p/'trades.csv.gz'))
 for label,mask,months in [('TRAIN',t.year<=2021,36),('VALIDATION',(t.year>=2022)&(t.year<=2023),24),('OOS',t.year>=2024,27)]:rows.append({'scenario':cost,'period':label,**metrics(t[mask],10000.,months)})
t=prepared(pd.read_csv(OUT/'SENS_STOP2.3333_HOLD300/trades.csv.gz'));t=t[t.candidate==key];b=bootstrap(t[t.year>=2024]);(OUT/'exploratory_candidate_bootstrap.json').write_text(json.dumps(b,indent=2))
p=run(configs=configs,mode='ANNUAL',stop_scale=7/3,holding_minutes=300,outname='EXPLORATORY_ANNUAL');t=prepared(pd.read_csv(p/'trades.csv.gz'))
for year in range(2019,2027):rows.append({'scenario':'BASE_ANNUAL','period':str(year)+(' YTD_MARCH' if year==2026 else ''),**metrics(t[t.year==year],10000.,3 if year==2026 else 12)})
pd.DataFrame(rows).to_csv(OUT/'exploratory_candidate_metrics.csv',index=False)
