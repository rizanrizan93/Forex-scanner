import csv,datetime,hashlib,json,pathlib,zipfile
root=pathlib.Path('october_order_readiness/evidence');dest=pathlib.Path('research_reports/october-order-readiness-20261021');dest.mkdir(parents=True,exist_ok=True)
def get(z,suffix):return json.loads(z.read(next(n for n in z.namelist() if n.endswith('/'+suffix))))
z=zipfile.ZipFile(root/'ACTIVATION_REPLAY_EXTENDED.zip');tests=zipfile.ZipFile(root/'ORDERABILITY_TESTS.zip');broker=zipfile.ZipFile(root/'BROKER_READONLY.zip')
for name in ['ACTIVATION_ENTRY_SUMMARY.json','ACTIVATION_ENTRY_LEDGER.json','ACTIVATION_GATE_AUDIT.json','ACTIVATION_REPLAY_CONFIG.json','ACTIVATION_RAW_CANDIDATES.json','SOURCE_UNCHANGED.json','BTC_FRESH_SEED_MANIFEST.json','BRIDGE_ACTIVATION_READONLY.json']:
 (dest/name).write_text(json.dumps(get(z,name),indent=2))
n=next(n for n in z.namelist() if n.startswith('broker/') and n.endswith('BROKER_READ_ONLY_HISTORY.json'));(dest/'REPLAY_BROKER_INPUT_MANIFEST.json').write_bytes(z.read(n))
(dest/'BROKER_READ_ONLY_HISTORY.json').write_text(json.dumps(get(broker,'BROKER_READ_ONLY_HISTORY.json'),indent=2))
for name in ['ORDERABILITY_FIXTURES.json','PortfolioTests.json','WeekendTests.json','LeverageTests.json','SevenDayTests.json']:(dest/name).write_text(json.dumps(get(tests,name),indent=2))
raw=get(z,'ACTIVATION_RAW_CANDIDATES.json')[0]['candidates']
with (dest/'RAW_CANDIDATES.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['utc','wib','symbol','direction','Atr','Anchor','Distance','Fast','Slow','macro_eligibility_reconstructed']);w.writeheader()
 for r in raw:
  r=dict(r);r['wib']=datetime.datetime.fromisoformat(r['utc'].replace('Z','+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=7))).isoformat();w.writerow(r)
fields=['case','EntryTime','ClosingTime','SymbolName','Label','TradeType','VolumeInUnits','EntryPrice','ExitPrice','Commissions','ExitCommission','Swap','GrossProfit','NetProfit','Comment']
with (dest/'FILL_LEDGER.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
 for name in z.namelist():
  if '/cases/' not in name or not name.endswith('.json') or name.endswith(('.btc_signals.json','.raw_candidates.json')):continue
  d=json.loads(z.read(name));case=pathlib.Path(name).stem
  for r in d['Reports'][0]['BrokerHistory']:w.writerow({'case':case,**r})
source=next(n for n in z.namelist() if n.endswith('ACTIVATION_HARNESS.diff'));(dest/'ACTIVATION_HARNESS.diff').write_bytes(z.read(source))
checks=get(z,'SOURCE_UNCHANGED.json');summary=get(z,'ACTIVATION_ENTRY_SUMMARY.json');fixtures=get(tests,'ORDERABILITY_FIXTURES.json');reg={n:get(tests,n+'.json') for n in ['PortfolioTests','WeekendTests','LeverageTests','SevenDayTests']}
assert all(checks.values()) and len(summary)==12 and all(x['error_count']==0 and abs(x['cash_residual'])<1e-6 and not x['quarantined'] and not x['accounting_block'] for x in summary)
assert len(fixtures)==24 and all(x['passed'] for x in fixtures) and all(x['Pass'] for x in reg.values())
records=[{'name':n,'checks':v['Checks'],'pass':v['Pass']} for n,v in reg.items()];(dest/'VERIFICATION.json').write_text(json.dumps({'source_checks':len(checks),'source_all_match':True,'replay_cases':12,'all_replay_cases_pass':True,'all_cash_residual_abs_lt_1e_6':True,'orderability_fixture_cases':24,'all_fixtures_pass':True,'regression_suites':records,'regression_checks_total':sum(x['checks'] for x in records),'live_orders_sent_by_audit':0,'native_order_acceptance_proven':False},indent=2))
artifacts=[(39536869038,12318001900,'ACTIVATION_REPLAY_EXTENDED.zip'),(39535910719,12316729929,'ORDERABILITY_TESTS.zip'),(39535798577,12317199084,'BROKER_READONLY.zip')]
(dest/'ARTIFACT_PROVENANCE.json').write_text(json.dumps([{'run_id':run,'artifact_id':aid,'local_name':name,'bytes':(root/name).stat().st_size,'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),'url':f'https://github.com/rizanrizan93/Forex-scanner/actions/runs/{run}/artifacts/{aid}'} for run,aid,name in artifacts],indent=2))
print('VERIFIED',len(summary),'cases;',len(fixtures),'fixtures;',sum(x['checks'] for x in records),'regression checks')
