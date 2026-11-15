import sys,pathlib,json,numpy as np,pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'research_r1'))
from analyze import prepared,metrics,initial_of
from select_r2 import key
OUT=ROOT/'r2_results'
def block_test(t,n=20000,block=20):
 if len(t)<30:return {'trades':len(t),'status':'INSUFFICIENT_TRADES_FOR_INFERENCE','ci95_low_usd':None,'ci95_high_usd':None,'raw_p':None,'bonferroni504_p':None}
 dates=pd.bdate_range('2024-01-01','2026-03-31');daily=t.groupby('day').agg(pnl=('net_profit','sum'),n=('net_profit','size')).reindex(dates.strftime('%Y-%m-%d'),fill_value=0).to_numpy();rng=np.random.default_rng(125);stats=[]
 for _ in range(n):
  starts=rng.integers(len(daily),size=int(np.ceil(len(daily)/block)));ix=((starts[:,None]+np.arange(block))%len(daily)).ravel()[:len(daily)];z=daily[ix].sum(axis=0)
  if z[1]:stats.append(z[0]/z[1])
 a=np.asarray(stats);obs=t.net_profit.mean();p=float((np.sum(a-obs>=obs)+1)/(len(a)+1))
 return {'trades':len(t),'status':'BOOTSTRAP_DESCRIPTIVE_RETROSPECTIVE_TEST','ci95_low_usd':float(np.quantile(a,.025)),'ci95_high_usd':float(np.quantile(a,.975)),'raw_p':p,'bonferroni504_p':min(1.,p*504),'block_trading_days':block,'replicates':len(a)}
def main():
 cfg=json.loads((OUT/'review_configs.json').read_text());ids=[key(c) for c in cfg];parts=[]
 for name in ['GRID','ABLATION','ML']:
  t=pd.read_csv(OUT/name/'trades.csv.gz');parts.append(t[t.candidate.isin(ids)].copy())
 base=prepared(pd.concat(parts,ignore_index=True));base.to_csv(OUT/'review_base_trades.csv.gz',index=False)
 tests=[]
 for k,g in base[base.year>=2024].groupby('candidate'):tests.append({'candidate':k,**block_test(g)})
 pd.DataFrame(tests).to_csv(OUT/'review_block_bootstrap.csv',index=False)
 rows=[]
 for scenario in ['REVIEW_STRESS15','REVIEW_STRESS20','REVIEW_ANNUAL','REVIEW_CONTINUOUS','REVIEW_COMPOUND']:
  t=prepared(pd.read_csv(OUT/scenario/'trades.csv.gz'))
  for k in ids:
   g=t[t.candidate==k]
   if scenario=='REVIEW_ANNUAL':
    for year in range(2019,2027):rows.append({'scenario':scenario,'candidate':k,'period':str(year)+(' YTD_MARCH' if year==2026 else ''),**metrics(g[g.year==year],10000.,3 if year==2026 else 12)})
   elif scenario in ['REVIEW_CONTINUOUS','REVIEW_COMPOUND']:rows.append({'scenario':scenario,'candidate':k,'period':'2019_MARCH2026',**metrics(g,10000.,87)})
   else:
    for label,mask,months in [('TRAIN',g.year<=2021,36),('VALIDATION',(g.year>=2022)&(g.year<=2023),24),('TEST',g.year>=2024,27)]:rows.append({'scenario':scenario,'candidate':k,'period':label,**metrics(g[mask],10000.,months)})
 pd.DataFrame(rows).to_csv(OUT/'review_robustness_metrics.csv',index=False)
 # Walk-forward reselect using only preceding three annual-reset results among frozen watchlist.
 ann=pd.DataFrame(rows);ann=ann[ann.scenario=='REVIEW_ANNUAL'].copy();ann['year']=ann.period.str[:4].astype(int);wf=[]
 for year in range(2022,2027):
  past=ann[(ann.year>=year-3)&(ann.year<year)].groupby('candidate').agg(profit=('net_profit','sum'),trades=('trades','sum'))
  q=past[(past.profit>0)&(past.trades>=20)]
  if len(q):
   winner=q.profit.idxmax();test=ann[(ann.year==year)&(ann.candidate==winner)].iloc[0];wf.append({'year':year,'chosen':winner,'training_profit':float(q.loc[winner,'profit']),'test_profit':float(test.net_profit),'test_trades':int(test.trades)})
  else:wf.append({'year':year,'chosen':'NO_TRADE','training_profit':0,'test_profit':0,'test_trades':0})
 pd.DataFrame(wf).to_csv(OUT/'watchlist_walk_forward_exploratory.csv',index=False)
 # Paired macro-gate ablation with entry/news/volatility settings held fixed.
 m=pd.read_csv(OUT/'all_period_metrics.csv');cfgs=json.loads((OUT/'ABLATION/configs.json').read_text());lookup={key(c):c for c in cfgs};a=m[m.experiment_group=='ABLATION'].copy();a['pair']=[k.rsplit('_MAC',1)[0]+'_NEWS'+lookup[k]['news']+'_VOL'+str(lookup[k]['vol_veto']) for k in a.candidate];a['macro']=[lookup[k]['macro'] for k in a.candidate]
 paired=a.pivot(index=['pair','period'],columns='macro',values=['net_profit','expectancy_usd','trades','profit_factor']);paired.to_csv(OUT/'yield_gate_paired_ablation.csv')
 print('Robustness reports written')
if __name__=='__main__':main()
