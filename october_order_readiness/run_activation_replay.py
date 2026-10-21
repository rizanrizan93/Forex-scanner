import collections,csv,datetime,hashlib,json,os,pathlib,subprocess
P=pathlib.Path;out=P('publish');(out/'cases').mkdir(parents=True,exist_ok=True)
manifest=json.loads(next(P('broker').rglob('BROKER_READ_ONLY_HISTORY.json')).read_text());assert manifest['status']=='BROKER_HISTORY_ACQUIRED';end=manifest['end_exclusive_utc']
for sym in ['XAUUSD','EURUSD','BTCUSD']:
 f=next(P('broker').rglob(sym+'_BROKER_M1.csv'));assert hashlib.sha256(f.read_bytes()).hexdigest()==manifest['data'][sym]['sha256']
 (out/(sym+'_BROKER_M1.csv')).write_bytes(f.read_bytes())
 # Source broker candles may legitimately omit no-tick minutes; require every weekday in replay range represented.
 rr=list(csv.DictReader(f.open()));days=collections.Counter(r['utc'][:10] for r in rr)
 d=datetime.date(2026,9,1);last=datetime.date.fromisoformat(end[:10])
 while d<last:
  assert d.weekday()>=5 or days[str(d)]>100,('MISSING_WEEKDAY',sym,str(d));d+=datetime.timedelta(days=1)
activation=json.loads(next(P('activation').rglob('BRIDGE_ACTIVATION_READONLY.json')).read_text());state={x['namespace']:x['state'] for x in activation['states']}
xfrom=state['RZXRC1']['EpochUtc'];efrom=state['RZEF245']['EpochUtc'];btcfrom=activation['services']['rizan-btc7d130.service']['markers']['Started']['first_utc'];assert btcfrom
settings={'data_end_exclusive_utc':end,'xau_checkpoint_epoch_utc':xfrom,'eur_checkpoint_epoch_utc':efrom,'btc_backend_first_retained_start_utc':btcfrom,'initial_balance':115.17,'activation_note':'Epoch is checkpoint initialization, not certified first cBot handshake. BTC date is backend start, not first terminal-ready timestamp. FX cases use current frozen source with BTC disabled before BTC backend; combined cases assume reliable handshake from backend start.','macro':'TECH_ALLOWED and STRICT_NO_MACRO are explicitly synthetic controls, not historical macro reconstruction.','spread':'XAU .26 and EUR .00001 fixed assumptions; BTC 5bp. Native historical ask/spread unavailable.','bridge':'Reliable scripted ACK 2 seconds, not real terminal connection history.','state':'Fresh simulated account at $115.17; historical native checkpoint chain/virtual EUR seed parity not certified.','broker_io':'Fake broker only; native order acceptance not asserted.'}
(out/'ACTIVATION_REPLAY_CONFIG.json').write_text(json.dumps(settings,indent=2));summary=[];ledger=[];gates=[];candidate_sets=[]
for window,start,control in [('FX_CHECKPOINT_EPOCHS',min(xfrom,efrom),True),('COMBINED_BTC_BACKEND',btcfrom,False)]:
 for macro in ['TECH_ALLOWED','STRICT_NO_MACRO']:
  for path in ['A','B']:
   name=f'{window}_{macro}_{path}';dest=out/'cases'/(name+'.json');env=os.environ.copy();env.update({'BTC_INPUT':str((out/'BTCUSD_BROKER_M1.csv').resolve()),'BTC_H1_INPUT':str((out/'BTC_H1.csv').resolve()),'AUDIT_START_UTC':start,'AUDIT_END_UTC':end,'AUDIT_XAU_FROM':xfrom,'AUDIT_EUR_FROM':efrom,'AUDIT_INITIAL':'115.17','RESEARCH_PATH':path,'RESEARCH_CASE':'STRICT_NO_MACRO' if macro=='STRICT_NO_MACRO' else name,'RESEARCH_BTC_LEVERAGE':'200','RESEARCH_CONTROL':'1' if control else '0'})
   with dest.with_suffix('.stdout.log').open('w') as so,dest.with_suffix('.stderr.log').open('w') as se:r=subprocess.run(['dotnet','october_order_readiness/bin/Release/net8.0/ActivationReplay.dll',str(out/'XAUUSD_BROKER_M1.csv'),str(out/'EURUSD_BROKER_M1.csv'),str(dest),'full','2026','2026'],env=env,stdout=so,stderr=se)
   if r.returncode:print('REPLAY_FAILURE',name,dest.with_suffix('.stderr.log').read_text()[-5000:],flush=True)
   assert r.returncode==0,(name,'FAILED')
   d=json.loads(dest.read_text())['Reports'][0];s=d['Summary'];hist=d['BrokerHistory'];opened=d['Open'];entries={}
   for p in hist+opened:
    key=p['SymbolName']+'|'+'|'.join(p['Label'].split('|')[:2]);v=entries.setdefault(key,{'symbol':p['SymbolName'],'basket_key':'|'.join(p['Label'].split('|')[:2]),'entry_utc':p['EntryTime'],'direction':'BUY' if p['TradeType']==0 else 'SELL','fills_or_batches':0});v['entry_utc']=min(v['entry_utc'],p['EntryTime']);v['fills_or_batches']+=1
   candidates=json.loads(P(str(dest)+'.raw_candidates.json').read_text());counter=collections.Counter(v['symbol'] for v in entries.values());raw=collections.Counter(v['symbol'] for v in candidates)
   residual=115.17+sum(p['NetProfit'] for p in hist)+sum(p.get('Commissions',0)+p.get('Swap',0) for p in opened)-s['EndingBalance'];assert abs(residual)<1e-6
   row={'case':name,'window':window,'start_utc':start,'end_exclusive_utc':end,'path':path,'macro':macro,'btc_enabled':not control,'raw_candidates':dict(raw),'accepted_baskets':dict(counter),'broker_requests':s['Orders'],'ending_balance':s['EndingBalance'],'open_positions_end':len(opened),'error_count':s['ErrorCount'],'quarantined':s['Quarantined'],'accounting_block':s['AccountingBlock'],'terminal_forced_closes':s['TerminalForcedCloses'],'cash_residual':residual,'gate_counts':dict(collections.Counter(g['Status'] for g in d.get('EntryAudit',[])))}
   assert s['ErrorCount']==0 and not s['Quarantined'] and not s['AccountingBlock'];summary.append(row)
   ledger.extend({'case':name,**v} for v in entries.values());gates.extend({'case':name,**v} for v in d.get('EntryAudit',[]));candidate_sets.append({'case':name,'candidates':candidates})
   print('ACTIVATION_CASE_RESULT',json.dumps(row),flush=True)
for name,data in [('ACTIVATION_ENTRY_SUMMARY.json',summary),('ACTIVATION_ENTRY_LEDGER.json',ledger),('ACTIVATION_GATE_AUDIT.json',gates),('ACTIVATION_RAW_CANDIDATES.json',candidate_sets)]: (out/name).write_text(json.dumps(data,indent=2))
print('ACTIVATION_ENTRY_LEDGER',json.dumps(ledger),flush=True);print('ACTIVATION_CANDIDATES',json.dumps(candidate_sets),flush=True)
