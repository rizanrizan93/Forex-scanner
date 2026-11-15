import sys,pathlib,json,numpy as np,pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'research_r1'))
from analyze import prepared,metrics,bootstrap,initial_of
from signals_r2 import make_id
OUT=ROOT/'r2_results'
def periods(t):
 out=[]
 for key,g in t.groupby('candidate'):
  for label,mask,months in [('TRAIN',g.year<=2021,36),('VALIDATION',(g.year>=2022)&(g.year<=2023),24),('TEST',g.year>=2024,27)]:out.append({'candidate':key,'period':label,**metrics(g[mask],10000.,months)})
 return pd.DataFrame(out)
def main():
 t=prepared(pd.read_csv(OUT/'GRID/trades.csv.gz'));cfg=json.loads((OUT/'GRID/configs.json').read_text());cm={make_id(c):c for c in cfg};p=periods(t);p.to_csv(OUT/'grid_period_metrics.csv',index=False)
 train=p[p.period=='TRAIN'].set_index('candidate');val=p[p.period=='VALIDATION'].set_index('candidate');comb=train.join(val,lsuffix='_train',rsuffix='_val');comb['eligible']=(comb.trades_train>=60)&(comb.trades_val>=30)&(comb.net_profit_train>0)&(comb.net_profit_val>0)&(comb.profit_factor_train>1)&(comb.profit_factor_val>1)&(comb.floating_equity_dd_val<=.30)
 comb['family']=[cm[k]['family'] for k in comb.index];comb.to_csv(OUT/'selection_train_validation.csv');rank=comb[comb.eligible].sort_values('return_over_dd_val',ascending=False)
 # Cap multiple nearly identical variants by selecting one per family.
 winners=rank.drop_duplicates('family').head(5).index.tolist();(OUT/'validated_selected.json').write_text(json.dumps([cm[k] for k in winners],indent=2))
 # One diagnostic leader per family chosen using TRAINING only, even if gate fails.
 leaders=[]
 for family,g in comb.groupby('family'):
  q=g[g.trades_train>=60].sort_values(['return_over_dd_train','expectancy_usd_train'],ascending=False)
  if len(q):leaders.append(q.index[0])
 # Retain the best profitable-but-sparse discovery configuration as a labelled diagnostic.
 sparse=comb[(comb.net_profit_train>0)&(comb.trades_train<60)].sort_values('return_over_dd_train',ascending=False)
 if len(sparse):leaders.append(sparse.index[0])
 (OUT/'diagnostic_leaders.json').write_text(json.dumps([cm[k] for k in leaders],indent=2))
 selected=list(dict.fromkeys(winners+leaders));p[p.candidate.isin(selected)].to_csv(OUT/'selected_period_metrics.csv',index=False)
 annual=[]
 for key,g in t[t.candidate.isin(selected)].groupby('candidate'):
  for year in range(2019,2027):
   q=g[g.year==year];annual.append({'candidate':key,'year':str(year)+(' YTD_MARCH' if year==2026 else ''),**metrics(q,initial_of(q),3 if year==2026 else 12)})
 pd.DataFrame(annual).to_csv(OUT/'selected_yearly_continuous.csv',index=False)
 (OUT/'selected_ids.json').write_text(json.dumps(selected,indent=2))
 print('Discovery/validation eligible',len(rank),'of',len(comb));print(rank[['family','net_profit_train','profit_factor_train','net_profit_val','profit_factor_val','floating_equity_dd_val']].head(15).to_string());print('Frozen selected IDs',winners)
if __name__=='__main__':main()
