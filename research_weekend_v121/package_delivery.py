from pathlib import Path
import zipfile,json,hashlib,gzip,shutil
r=Path(__file__).resolve().parent;root=r.parent.parent;d=root/'delivery';f=root/'frozen';a=r/'analysis'
expected={f'{n}_{p}' for p in ['A','B'] for n in ['NORMAL','CONTROL','COST_15','COST_20','NEXT_M1','BTC_L2','BTC_L5','FULL_INDICATORS','LEGACY_7D']}
raw={p.name[:-8]:p for p in (r/'results').glob('*.json.gz')};assert set(raw)==expected,(set(raw),expected)
for p in raw.values():
 v=json.load(gzip.open(p))['Reports'][0];s=v['Summary'];assert not v['Open'] and s['OpenPositions']==0 and s['ErrorCount']==0 and not s['AccountingBlock'] and not s['Quarantined'] and s['TerminalForcedCloses']==0
 assert abs(100+sum(x['NetProfit'] for x in v['BrokerHistory'])-s['EndingBalance'])<1e-5
source_reference=json.loads((r/'analysis/RESEARCH_GIT_REFERENCE.json').read_text())
assert source_reference['baseline_unchanged']
entries={}
def add(path,name):entries[name]=Path(path)
add(r.parent/'portfolio_weekend/RIZAN_XAU_EUR_BTC_FROZEN_WEEKEND_V121.zip','frozen/RIZAN_XAU_EUR_BTC_FROZEN_WEEKEND_V121.zip')
for p in (root/'audited').iterdir():
 if p.is_file() and p.name not in ['RIZAN_XAU_EUR_BTC_FROZEN_WEEKEND_V121.zip','CI_NATIVE_REBUILD.algo','RizanXauEurBtcPortfolio_FROZEN_WEEKEND_V1_2_1.algo']:add(p,'original_actions_audit/'+p.name)
for p in a.iterdir():
 if p.is_file() and p.name not in ['PARTIAL_METRICS.json']:add(p,'analysis/'+p.name)
for p in raw.values():add(p,'replay/'+p.name)
for p in (r/'results').glob('*.log'):add(p,'execution_logs/'+p.name)
for p in (r/'results').glob('*.btc_signals.json'):add(p,'signal_inputs/'+p.name)
for p in r.iterdir():
 if p.is_file() and (p.suffix=='.py' and p.name not in ['run_batch_b.py','run_ablation.py','run_leverage.py'] or p.name in ['README.md','RUNNER_CHANGE.diff','NATIVE_BUILD.log']):add(p,'research_source/'+p.name)
for n in ['Replay.cs','ApiStubs.cs']:add(r/'work/replay'/n,'research_adapter/'+n)
add(r/'work/native/compile.log','native_rebuild/compiler.log')
for name in ['ANNUAL.csv','MONTHLY.csv','DIRECTION_CONTRIBUTIONS.csv','FILL_LEDGER.csv','WEEKEND_CHANGE.diff','FREEZE_MANIFEST.json','FROZEN_STATUS.json']:add(f/name,'baseline_exports/'+name)
for p in d.iterdir():
 if p.is_file() and p.suffix!='.zip' and p.name!='DELIVERY_SHA256.json':add(p,'deliverables/'+p.name)
manifest={n:dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size) for n,p in entries.items()}
manifest['research_reference']=source_reference
payload=json.dumps(manifest,indent=2).encode()
pkg=d/'RIZAN_WEEKEND_V121_AUDIT_STRESS_20261020.zip'
with zipfile.ZipFile(pkg,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for n,p in sorted(entries.items()):z.write(p,n)
 z.writestr('MEMBER_SHA256.json',payload)
with zipfile.ZipFile(pkg) as z:
 assert z.testzip() is None
 for n,h in manifest.items():
  if n=='research_reference':continue
  assert hashlib.sha256(z.read(n)).hexdigest()==h['sha256']
hashes={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in d.iterdir() if p.is_file() and p.name!='DELIVERY_SHA256.json'}
(d/'DELIVERY_SHA256.json').write_text(json.dumps(hashes,indent=2));print(json.dumps({'package':str(pkg),'files':len(entries),'raw_replay_cases':len(raw),'checksums':hashes},indent=2))
