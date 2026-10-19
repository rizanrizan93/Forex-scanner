import pathlib,sys,json
import pandas as pd
import numpy as np
root=pathlib.Path(sys.argv[1]);symbol=sys.argv[2];r=root/'raw_validation';v=pd.read_csv(r/'RAW_TOP20_STRESS.csv');rows=[];maxerr=0
for p in sorted(r.glob('raw_*_ledger.csv')):
 if len(p.name.split('_'))!=3:continue # This checker compares BASE only; all-case checker handles stress.
 cid=int(p.name.split('_')[1]);q=pd.read_csv(p);b=v[(v.id==cid)&(v['case']=='BASE')].iloc[0]
 if q.empty:continue
 gross=q.side*(q.exit_price-q.entry_average)*q.quantity
 if symbol=='USDJPY':gross=gross/q.exit_price
 net=gross-q.entry_commission-q.exit_commission-q.financing
 err=max(float(np.abs(net-q.net_pnl).max()),float(np.abs(100+q.net_pnl.cumsum()-q.balance).max()),abs(float(q.balance.iloc[-1])-float(b.equity)));maxerr=max(maxerr,err)
 assert err<max(1e-6,abs(b.equity)*1e-9),(cid,err)
 rows.append({'id':cid,'cash_error':err,'trades':len(q)})
json.dump({'independent_cash_reconciliation':True,'max_error':maxerr,'checks':rows},open(r/'RAW_CASH_RECONCILIATION.json','w'),indent=2)
print('RAW_CASH_RECONCILIATION_PASS',symbol,len(rows),maxerr)
