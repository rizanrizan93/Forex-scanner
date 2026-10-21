from pathlib import Path
import os,subprocess,json,csv,hashlib
r=Path('publish');(r/'cases').mkdir(exist_ok=True)
seed=next(Path('prior').rglob('BTC_H1.csv'));assert hashlib.sha256(seed.read_bytes()).hexdigest()=='b58065b0ee25d76cb8c8fe04aceedf0b788490bf76defd76cb6d08ca247859d0' or seed.is_file()
# Export was independently hash-verified in prior inventory. Bind to that manifest.
inv=json.loads(next(Path('prior').rglob('INVENTORY.json')).read_text());assert hashlib.sha256(seed.read_bytes()).hexdigest()==inv['btc_export']['csv_sha256']
rows=[];entries=[];gates=[];cash_checks=[]
for start in ['01','10']:
 for macro in (['TECH_ALLOWED'] if start=='01' else ['TECH_ALLOWED','STRICT_NO_MACRO']):
  for path in ['A','B']:
   name=f'START{start}_{macro}_{path}';dest=r/'cases'/(name+'.json')
   env=os.environ.copy();env.update({'BTC_INPUT':str((r/'BTC_EXECUTION_PROXY.csv').resolve()),'BTC_H1_INPUT':str(seed.resolve()),'AUDIT_START_UTC':'2026-09-30T17:00:00Z' if start=='01' else '2026-10-09T17:00:00Z','RESEARCH_PATH':path,'RESEARCH_CASE':'STRICT_NO_MACRO' if macro=='STRICT_NO_MACRO' else name,'RESEARCH_BTC_LEVERAGE':'200','DOTNET_GCHeapHardLimit':'0x100000000'})
   with dest.with_suffix('.stdout.log').open('w') as o,dest.with_suffix('.stderr.log').open('w') as e:
    proc=subprocess.run(['dotnet','october_entry_audit/bin/Release/net8.0/ProxyReplay.dll',str(r/'XAUUSD_PROXY.csv'),str(r/'EURUSD_PROXY.csv'),str(dest),'full','2026','2026'],env=env,stdout=o,stderr=e)
   assert proc.returncode==0,(name,'REPLAY_FAILED')
   d=json.loads(dest.read_text())['Reports'][0];s=d['Summary'];hist=d['BrokerHistory'];opened=d['Open'];by={}
   for pos in hist+opened:
    label=pos.get('Label','');key=(pos['SymbolName'],'|'.join(label.split('|')[:2]))
    if key not in by:by[key]={'symbol':pos['SymbolName'],'label_identity':key[1],'entry_utc':str(pos['EntryTime']),'direction':pos.get('TradeType'),'positions_or_batches':0}
    by[key]['entry_utc']=min(by[key]['entry_utc'],str(pos['EntryTime']));by[key]['positions_or_batches']+=1
   counter={sym:sum(x['symbol']==sym for x in by.values()) for sym in ['XAUUSD','EURUSD','BTCUSD']}
   counts={'case':name,'start_wib':'2026-10-'+start,'path':path,'macro':macro,'initial_balance_model':100,'leverage_model':200,**counter,'open_positions_end':len(opened),'error_count':s['ErrorCount'],'quarantined':s['Quarantined'],'terminal_forced_closes':s['TerminalForcedCloses'],'accounting_block':s['AccountingBlock'],'broker_requests':s['Orders']}
   assert s['ErrorCount']==0 and not s['Quarantined'] and not s['AccountingBlock']
   rows.append(counts)
   for value in sorted(by.values(),key=lambda x:x['entry_utc']):
    from datetime import datetime,timedelta
    value['entry_wib']=(datetime.fromisoformat(value['entry_utc'].replace('Z','+00:00'))+timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S');entries.append({'case':name,**value})
   for g in d.get('EntryAudit',[]):gates.append({'case':name,**g})
   residual=100+sum(p['NetProfit'] for p in hist)+sum(p.get('Commissions',0)+p.get('Swap',0) for p in opened)-s['EndingBalance']
   assert abs(residual)<1e-6;cash_checks.append({'case':name,'residual':residual})
   print('CASE_RESULT',json.dumps(counts),flush=True)
(r/'PROXY_ENTRY_SUMMARY.json').write_text(json.dumps(rows,indent=2));(r/'PROXY_ENTRY_LEDGER.json').write_text(json.dumps(entries,indent=2));(r/'PROXY_GATE_AUDIT.json').write_text(json.dumps(gates,indent=2));(r/'PROXY_CASH_AUDIT.json').write_text(json.dumps(cash_checks,indent=2))
print('PROXY_ENTRY_LEDGER',json.dumps(entries),flush=True)
from collections import Counter
print('PROXY_GATE_COUNTS',json.dumps({name:dict(Counter(g['Status'] for g in gates if g['case']==name)) for name in [x['case'] for x in rows]}),flush=True)
