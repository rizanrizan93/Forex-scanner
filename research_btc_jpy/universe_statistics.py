import pathlib,sys,json
import pandas as pd
import numpy as np
root=pathlib.Path(sys.argv[1]);symbol=sys.argv[2];r=root/f'results_{symbol}'
families={};eq=[];rawtops=[];counts={'configurations':0,'profitable':0,'inactive':0,'below_initial':0,'dd50_profitable':0,'target100k_any_trade_count':0,'target100k_min30trades':0,'target100k_dd50_min30trades':0,'DD90_or_worse':0}
for q in pd.read_csv(r/'ALL_CONFIGURATIONS.csv',chunksize=100000):
 e=q.full_equity;dd=q.full_floating_dd;tr=q.full_trades;eq.append(e.to_numpy());rawtops.append(q.nlargest(20,'full_equity'))
 counts['configurations']+=len(q);counts['profitable']+=int((e>100).sum());counts['inactive']+=int((tr==0).sum());counts['below_initial']+=int((e<100).sum());counts['dd50_profitable']+=int(((e>100)&(dd<50)).sum());counts['target100k_any_trade_count']+=int((e>=100000).sum());counts['target100k_min30trades']+=int(((e>=100000)&(tr>=30)).sum());counts['target100k_dd50_min30trades']+=int(((e>=100000)&(tr>=30)&(dd<50)).sum());counts['DD90_or_worse']+=int((dd>=90).sum())
 for name,g in q.groupby('family'):
  x=families.setdefault(name,{'family':name,'configurations':0,'profitable':0,'max_equity':-1e99,'max_equity_DD50':0,'inactive':0});x['configurations']+=len(g);x['profitable']+=int((g.full_equity>100).sum());x['inactive']+=int((g.full_trades==0).sum());x['max_equity']=max(x['max_equity'],float(g.full_equity.max()));v=g.loc[g.full_floating_dd<50,'full_equity'];x['max_equity_DD50']=max(x['max_equity_DD50'],float(v.max()) if len(v) else 0.)
tops=pd.concat(rawtops).nlargest(20,'full_equity');tops.to_csv(r/'ALL_TRADE_COUNTS_TOP20.csv',index=False);counts['best_any_trade_count_id']=int(tops.iloc[0].id);counts['best_any_trade_count_equity']=float(tops.iloc[0].full_equity);counts['best_any_trade_count_trades']=int(tops.iloc[0].full_trades)
values=np.concatenate(eq);counts['equity_quantiles']={str(p):float(np.quantile(values,p)) for p in [.01,.1,.5,.9,.95,.99,1.]};counts['profitable_fraction']=counts['profitable']/counts['configurations'];(r/'UNIVERSE_STATISTICS.json').write_text(json.dumps(counts,indent=2));pd.DataFrame(families.values()).sort_values('max_equity',ascending=False).to_csv(r/'FAMILY_STATISTICS.csv',index=False);print(counts)
