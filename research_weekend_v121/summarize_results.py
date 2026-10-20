from pathlib import Path
import gzip,json,csv,collections,datetime,math,zipfile
r=Path(__file__).resolve().parent;out=r/'analysis';out.mkdir(exist_ok=True)
def save(name,rows):
 if not rows:return
 with (out/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def groups(a):
 g=collections.defaultdict(list)
 for x in a['BrokerHistory']:g['|'.join(x['Label'].split('|')[:2])].append(x)
 return {k:dict(symbol=v[0]['SymbolName'],side=v[0]['TradeType'],units=sum(x['VolumeInUnits'] for x in v),net=sum(x['NetProfit'] for x in v),fills=v) for k,v in g.items()}
reports={};metrics=[]
for p in sorted((r/'results').glob('*.json.gz')):
 a=json.load(gzip.open(p))['Reports'][0];reports[p.name[:-8]]=a;s=a['Summary'];h=a['BrokerHistory'];g=groups(a);pnl=[v['net'] for v in g.values()];peak=100;dd=0
 for v in a['CashEvents']:peak=max(peak,v['Balance']);dd=max(dd,100*(peak-v['Balance'])/peak)
 net=sum(v['NetProfit'] for v in h);gross=sum(v['GrossProfit'] for v in h);fees=-sum(v['Commissions']+v['ExitCommission'] for v in h);fund=-sum(v['Swap'] for v in h);res=100+net-s['EndingBalance'];assert abs(res)<1e-5
 assert abs(dd-s['MaxClosedDDPct'])<1e-8
 violations=0;late_entries=0;btc_positions=0
 for v in h:
  if v['SymbolName']!='BTCUSD':continue
  btc_positions+=1;t0=datetime.datetime.fromisoformat(v['EntryTime'].replace('Z','+00:00'));t1=datetime.datetime.fromisoformat(v['ClosingTime'].replace('Z','+00:00'));monday=(t0-datetime.timedelta(days=t0.weekday())).replace(hour=0,minute=0,second=0,microsecond=0);cutoff=monday+datetime.timedelta(days=4,hours=21,minutes=30)
  violations+=int(t0.weekday()>4 or t1>cutoff+datetime.timedelta(seconds=5) or t1.weekday()>4)
  late_entries+=int(t0>cutoff-datetime.timedelta(minutes=30)+datetime.timedelta(seconds=5))
 if not p.name.startswith('LEGACY_7D'):assert violations==0,(p,violations)
 metrics.append(dict(case=p.name[:-8],weekend_or_flat_cutoff_violations=violations,entry_buffer_violations=late_entries,ending_balance=s['EndingBalance'],floating_dd_pct=s['MaxEquityDDPct'],balance_dd_pct=dd,pf=s['PF'],win_rate_pct=100*sum(v>0 for v in pnl)/len(pnl),baskets=s['Baskets'],xau=s['XauBaskets'],eur=s['EurBaskets'],btc=s['BtcBaskets'],btc_buy=s['BtcBuys'],btc_sell=s['BtcSells'],gross_pnl=gross,commission=fees,funding=fund,cash_residual=res,open_positions=s['OpenPositions'],errors=s['ErrorCount'],quarantine=s['Quarantined'],accounting_block=s['AccountingBlock'],terminal_forced_closes=s['TerminalForcedCloses'],spread_multiplier=s['SpreadStressMultiplier'],btc_leverage=s['BtcLeverage'],xau_eur_leverage=200,execution_delay=s['DelayPolicy'],dd56_pass=s['MaxEquityDDPct']<=56))
save('STRESS_CONTROL_METRICS.csv',metrics)
legacy_proof={}
oldzip=zipfile.ZipFile(r.parent/'portfolio_three/RIZAN_XAU_EUR_BTC_INTEGRATED_AUDIT_2019_2026.zip')
for path in ['A','B']:
 k='LEGACY_7D_'+path
 if k not in reports:continue
 prior=json.loads(gzip.decompress(oldzip.read('THREE_PATH_'+path+'_RAW_REPLAY.json.gz')))
 assert len(prior['BrokerHistory'])==len(reports[k]['BrokerHistory'])
 for old_fill,new_fill in zip(prior['BrokerHistory'],reports[k]['BrokerHistory']):assert old_fill=={key:new_fill[key] for key in old_fill},k+' legacy shared ledger mismatch'
 for v in ['EndingBalance','MaxEquityDDPct','MaxClosedDDPct','PF','Baskets']:assert abs(prior['Summary'][v]-reports[k]['Summary'][v])<1e-7
 legacy_proof[path]={'exact_legacy_shared_BrokerHistory_fields':True,'new_EntryTime_field_absent_in_legacy_archive':True,'metrics_match':True}
(out/'LEGACY_PARITY.json').write_text(json.dumps(legacy_proof,indent=2))
# Exact arithmetic decomposition in a declared sequential order, not a unique causal allocation.
# net = quantity * average net per unit. Quantity includes compounding, wallet/margin gates and layering.
decomp=[];matched_cutoff=[];sigrows=[]
for path in ['A','B']:
 for old,new in [('LEGACY_7D_'+path,'FULL_INDICATORS_'+path),('FULL_INDICATORS_'+path,'NORMAL_'+path)]:
  if old not in reports or new not in reports:continue
  og=groups(reports[old]);ng=groups(reports[new]);
  for sym in ['XAUUSD','EURUSD','BTCUSD']:
   keys0={k for k,v in og.items() if v['symbol']==sym};keys1={k for k,v in ng.items() if v['symbol']==sym};common=keys0&keys1;unit_effect=size_effect=0
   for k in common:
    a=og[k];b=ng[k];ar=a['net']/a['units'];br=b['net']/b['units'];unit_effect+=a['units']*(br-ar);size_effect+=(b['units']-a['units'])*br
    if sym=='BTCUSD' and old.startswith('LEGACY'):
     af=a['fills'][0];bf=b['fills'][0];t=datetime.datetime.fromisoformat(bf['ClosingTime'].replace('Z','+00:00'))
     if t.weekday()==4 and t.hour==21 and t.minute==30 and af['ClosingTime']>bf['ClosingTime']:
      matched_cutoff.append(dict(path=path,label=k,old_close=af['ClosingTime'],weekend_close=bf['ClosingTime'],old_units=a['units'],new_units=b['units'],old_pnl_per_btc=ar,weekend_pnl_per_btc=br,exit_effect_at_old_quantity=a['units']*(br-ar),exit_effect_at_new_quantity=b['units']*(br-ar)))
   removed=sum(og[k]['net'] for k in keys0-keys1);added=sum(ng[k]['net'] for k in keys1-keys0);delta=sum(ng[k]['net'] for k in keys1)-sum(og[k]['net'] for k in keys0);res=delta-(unit_effect+size_effect+added-removed);assert abs(res)<1e-5
   decomp.append(dict(path=path,from_case=old,to_case=new,symbol=sym,old_baskets=len(keys0),new_baskets=len(keys1),matched_baskets=len(common),removed_baskets=len(keys0-keys1),added_baskets=len(keys1-keys0),matched_per_unit_effect_at_old_quantity=unit_effect,matched_quantity_effect_at_new_unit_return=size_effect,removed_net_pnl=removed,added_net_pnl=added,delta_net_pnl=delta,identity_residual=res))
 # Input signal universe: split closure-only changes from changed indicators.
 def signals(name):
  p=r/'results'/(name+'.json.btc_signals.json')
  return json.loads(p.read_text()) if p.exists() else {}
 a=signals('FULL_INDICATORS_'+path);b=signals('NORMAL_'+path);end='2026-10-09T21:59:00Z';a={k:v for k,v in a.items() if '2019'<=k<end};b={k:v for k,v in b.items() if '2019'<=k<end};common=set(a)&set(b)
 sigrows.append(dict(path=path,full7d_indicator_signals=len(a),weekday_indicator_signals=len(b),common_timestamps=len(common),removed_timestamps=len(set(a)-set(b)),added_timestamps=len(set(b)-set(a)),common_changed_atr=sum(abs(a[k]['Atr']-b[k]['Atr'])>1e-12 for k in common),common_changed_side=sum(a[k]['Side']!=b[k]['Side'] for k in common)))
save('SEQUENTIAL_RESULT_DECOMPOSITION.csv',decomp);save('MATCHED_FRIDAY_EXIT_EFFECT.csv',matched_cutoff);save('INDICATOR_SIGNAL_CHANGES.csv',sigrows)
(r/'analysis/REPLAY_SUMMARIES.json').write_text(json.dumps({k:a['Summary'] for k,a in reports.items()},indent=2))
print(json.dumps(metrics,indent=2))
