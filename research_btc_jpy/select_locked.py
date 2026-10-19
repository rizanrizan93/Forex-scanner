import pathlib,sys,json,hashlib
import pandas as pd
root=pathlib.Path(sys.argv[1]);symbol=sys.argv[2];r=root/f'results_{symbol}';v=pd.read_csv(r/'M1_VALIDATION.csv');b=v[v['case']=='BASE'].copy();tr=v[v['case']=='TRAIN_2019_2022'].set_index('id')
groups={}
def add(q,label):
 for cid in q.head(20).id.astype(int):groups.setdefault(cid,[]).append(label)
add(b[b.trades>=30].sort_values('equity',ascending=False),'GLOBAL_MARCH_FULL_TOP20')
add(b[(b.trades>=30)&(b.floating_dd<50)].sort_values('equity',ascending=False),'GLOBAL_MARCH_DD50_TOP20')
t=tr[(tr.trades>=20)&(tr.floating_dd<50)].sort_values('equity',ascending=False);add(t.reset_index(),'GLOBAL_TRAIN_ONLY_TOP20')
cols=['id','tf_minutes','family','lookback','threshold_index','trend_filter','session_utc','side','stop_atr','tp_R','hold_bars','risk','margin_fraction','add_stages','breakeven_R']
q=b[b.id.isin(groups)].copy();q['selection_criteria']=q.id.map(lambda i:'+'.join(groups[int(i)]));q['march_equity']=q.equity;q['march_trades']=q.trades
q[cols+['selection_criteria','march_equity','march_trades']].to_csv(r/'LOCKED_SELECTION.csv',index=False)
proof={'selection_period_end':'2026-03-31T23:59:00Z','selection_data_used':'Only directM1 MarchBASE and2019-2022TRAIN metrics','April_October_results_used':False,'configuration_count':len(q),'csv_sha256':hashlib.sha256((r/'LOCKED_SELECTION.csv').read_bytes()).hexdigest(),'criteria':groups}
(r/'LOCKED_SELECTION_PROOF.json').write_text(json.dumps(proof,indent=2))
leaders={}
for label,cond,key in [('FULL',b.trades>=30,'equity'),('DD50',(b.trades>=30)&(b.floating_dd<50),'equity')]:
 s=b[cond].sort_values(key,ascending=False)
 if len(s):leaders[label]=int(s.iloc[0].id)
if len(t):leaders['TRAIN']=int(t.index[0])
(r/'MARCH_LEADERS.json').write_text(json.dumps(leaders,indent=2))
print('FROZEN_SELECTION',symbol,len(q),leaders)
