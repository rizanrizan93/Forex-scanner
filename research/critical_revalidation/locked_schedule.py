"""Controlled quote/cost diagnostic. Locked B order times/volumes/exits; no compounding, margin gate or stop re-evaluation. NOT a tradable replay."""
from pathlib import Path
import json,os,urllib.request,hashlib
import numpy as np,pandas as pd,pyarrow.parquet as pq
r=Path(__file__).resolve().parent;old=Path('/tmp/previous');out=r/'locked_schedule';out.mkdir(exist_ok=True)
b=json.load(open(old/'replay_results/B_MODEL_2S_ARCHIVED_FLAGS.json'));original_trades=b['Ledger'];excluded=[p for p in original_trades if pd.Timestamp(p['ExitTime'])<pd.Timestamp(p['EntryTime'])+pd.Timedelta(seconds=8)];tr=[p for p in original_trades if pd.Timestamp(p['ExitTime'])>=pd.Timestamp(p['EntryTime'])+pd.Timedelta(seconds=8)];queries={};lookup={}
for i,p in enumerate(tr):
 symbol=p['SymbolName'];at=pd.Timestamp(p['EntryTime'])-pd.Timedelta(seconds=2);exit=pd.Timestamp(p['ExitTime'])
 for delay in [0,2,5,10]:
  t=at+pd.Timedelta(seconds=delay);queries.setdefault((symbol,t.strftime('%Y-%m')),[]).append((i,'entry',delay,int(t.value//1000000)))
 queries.setdefault((symbol,exit.strftime('%Y-%m')),[]).append((i,'exit',0,int(exit.value//1000000)))
checks={v['file']:v['sha256']for v in json.load(open(old/'data_audit/data_quality.json'))['files']}
provenance=[]
for (sym,ym),qs in sorted(queries.items(),key=lambda a:(a[0][1],a[0][0])):
 name=f'{sym}_{ym}.parquet';p=out/name;url=f'https://huggingface.co/datasets/Henrik404/dukascopy-ticks/resolve/main/data/{sym}/{name}?download=true'
 for attempt in range(3):
  try:
   with urllib.request.urlopen(url,timeout=120)as response,p.open('wb')as f:
    while buf:=response.read(1048576):f.write(buf)
   assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==checks[name];break
  except Exception:
   if attempt==2:raise
 d=pq.read_table(p,columns=['timestamp','bid','ask']).to_pandas();p.unlink();d['timestamp']=pd.to_datetime(d.timestamp,utc=True)
 # Use recovered ticks only in missing strict interval, retaining original equal-time order.
 patch=r/'gap_repair/XAUUSD_gap_patch.parquet'
 if sym=='XAUUSD'and ym=='2025-10'and patch.exists():
  a=pq.read_table(patch,columns=['timestamp','bid','ask']).to_pandas();a['timestamp']=pd.to_datetime(a.timestamp,utc=True);d=pd.concat([d,a]).sort_values('timestamp',kind='stable')
 ts=d.timestamp.astype('datetime64[ns, UTC]').astype('int64').to_numpy()//1000000;scale=1000 if sym=='XAUUSD' else 100000
 for i,kind,delay,t in qs:
  j=np.searchsorted(ts,t,side='right')-1;assert j>=0
  lookup[(i,kind,delay)]={'bid':float(d.bid.iloc[j]/scale),'ask':float(d.ask.iloc[j]/scale),'quote_utc':str(pd.Timestamp(int(ts[j]),unit='ms',tz='UTC')),'staleness_ms':t-int(ts[j])}
 provenance.append({'file':name,'sha256':checks[name],'queries':len(qs)});print('LOCKED_QUOTES',name,len(qs),flush=True)
rows=[];summaries=[]
for delay in [0,2,5,10]:
 for cost in [1,1.5,2]:
  pnl=0;gain=loss=0
  for i,p in enumerate(tr):
   e=lookup[i,'entry',delay];x=lookup[i,'exit',0];side=1 if p['TradeType']==0 else-1;vol=p['VolumeInUnits'];slip=(.05 if p['SymbolName']=='XAUUSD' else .00001)*cost;fee=(.03 if p['SymbolName']=='XAUUSD' else .00003)*cost
   entry=(e['ask']if side==1 else e['bid'])+side*slip;exit=(x['bid']if side==1 else x['ask'])-side*slip;net=side*vol*(exit-entry)-2*vol*fee;pnl+=net;gain+=max(0,net);loss+=max(0,-net)
   rows.append({'delay':delay,'cost':cost,'label':p['Label'],'symbol':p['SymbolName'],'volume':vol,'entry':entry,'exit':exit,'net':net,'entry_quote_utc':e['quote_utc'],'exit_quote_utc':x['quote_utc'],'entry_staleness_ms':e['staleness_ms'],'exit_staleness_ms':x['staleness_ms']})
  summaries.append({'delay':delay,'cost':cost,'fixed_volume_total_pnl':pnl,'arithmetic_100_plus_pnl_NOT_feasible_equity':100+pnl,'position_profit_factor':gain/loss if loss else None,'positions':len(tr)})
pd.DataFrame(rows).to_csv(out/'LOCKED_QUOTES_AND_PNL.csv',index=False);json.dump({'status':'DIAGNOSTIC_COUNTERFACTUAL_NOT_EXECUTABLE','schedule':'B old audited fills minus 2s for entry request; exits fixed to B observed exit timestamp','volume':'B actual volumes frozen; may violate $100 margin under counterfactual losses','entry_delay_only':'ACK scheduling held fixed inside B request time; not a complete ACK intervention','sl_tp':'not reevaluated; isolates execution prices/cost only','common_ordering_filter':'All delay/cost cases use same retained positions: exit >= request+10s, including request=old B fill-2s. Faster exits/rejected fills excluded from EVERY case to avoid entry-after-exit.','excluded_short_or_rejected_positions':len(excluded),'original_positions':len(original_trades),'summaries':summaries,'source_files':provenance},open(out/'LOCKED_SCHEDULE_RESULTS.json','w'),indent=2)
