"""Freeze winners and review cases using discovery/validation only."""
import sys,pathlib,json,numpy as np,pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'research_r1'))
from analyze import prepared,metrics
from signals_r2 import make_id
OUT=ROOT/'r2_results'
def key(c):return make_id(c)+c.get('suffix','')
def periods(t,configs):
 records=[]
 for c in configs:
  k=key(c);g=t[t.candidate==k]
  for label,mask,months in [('TRAIN',g.year<=2021,24 if c.get('prediction_key') else 36),('VALIDATION',(g.year>=2022)&(g.year<=2023),24),('TEST',g.year>=2024,27)]:
   records.append({'candidate':k,'period':label,**metrics(g[mask],10000.,months)})
 return pd.DataFrame(records)
def main():
 allmetrics=[];allconfigs=[];alllogs=[]
 for group in ['GRID','ABLATION','ML']:
  cfg=json.loads((OUT/group/'configs.json').read_text());t=prepared(pd.read_csv(OUT/group/'trades.csv.gz'));m=periods(t,cfg);m['experiment_group']=group;allmetrics.append(m);allconfigs+=cfg;alllogs.append(t)
 m=pd.concat(allmetrics,ignore_index=True);m.to_csv(OUT/'all_period_metrics.csv',index=False);cm={key(c):c for c in allconfigs};train=m[m.period=='TRAIN'].set_index('candidate');val=m[m.period=='VALIDATION'].set_index('candidate');rank=train.join(val,lsuffix='_train',rsuffix='_val')
 rank['min_train_required']=[40 if cm[k].get('prediction_key') else 60 for k in rank.index];rank['family']=[cm[k].get('prediction_key',cm[k]['family']) for k in rank.index]
 rank['eligible']=(rank.trades_train>=rank.min_train_required)&(rank.trades_val>=30)&(rank.net_profit_train>0)&(rank.net_profit_val>0)&(rank.profit_factor_train>1)&(rank.profit_factor_val>1)&(rank.floating_equity_dd_val<=.30)
 rank.sort_values('return_over_dd_val',ascending=False).to_csv(OUT/'final_train_validation_gates.csv')
 good=rank[rank.eligible].sort_values('return_over_dd_val',ascending=False).drop_duplicates('family').head(5).index.tolist()
 # Near misses are diagnostics, not an alternate approval gate.
 sparse=rank[(rank.net_profit_train>0)&(rank.net_profit_val>0)].sort_values('return_over_dd_val',ascending=False).drop_duplicates('family').index.tolist()
 larger=rank[(rank.trades_train>=20)&(rank.trades_val>=20)].sort_values('return_over_dd_val',ascending=False).drop_duplicates('family').index.tolist()
 diag=list(dict.fromkeys(sparse+larger))[:5]
 review=list(dict.fromkeys(good+diag))[:5]
 (OUT/'validated_final_configs.json').write_text(json.dumps([cm[k] for k in good],indent=2));(OUT/'review_configs.json').write_text(json.dumps([cm[k] for k in review],indent=2));(OUT/'all_configs.json').write_text(json.dumps(allconfigs,indent=2))
 m[m.candidate.isin(review)].to_csv(OUT/'review_period_metrics.csv',index=False)
 print('Total configurations',len(allconfigs),'eligible',int(rank.eligible.sum()),'unique family winners',len(good));print('Validated IDs',good);print('Review IDs (may fail gates)',review);print(rank.loc[review,['net_profit_train','profit_factor_train','trades_train','net_profit_val','profit_factor_val','trades_val','eligible']].to_string())
if __name__=='__main__':main()
