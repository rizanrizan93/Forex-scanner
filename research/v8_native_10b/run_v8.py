"""Isolated continuous native research. Never connects to a broker.
Controls gate challengers; every completed raw ledger is audited before ranking.
"""
import concurrent.futures,gzip,hashlib,json,math,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OLD=Path(os.environ.get('RIZAN_RESTORED_WORK','/workspace/scratch/5cedb7096ebe'))
INPUTS=Path(os.environ.get('RIZAN_INPUTS',str(OLD/'replay_recovery/inputs')))
SEED=Path(os.environ.get('RIZAN_SEED',str(OLD/'research10b/data')))
DOTNET=Path(os.environ.get('RIZAN_DOTNET',str(OLD/'research10b/runtime/dotnet')))
DLL=Path(os.environ.get('RIZAN_DLL',str(ROOT/'build/NovemberReplay.dll')))
RUNS=Path(os.environ.get('RIZAN_RUNS',str(ROOT/'runs')));RUNS.mkdir(exist_ok=True)
EXPECTED={'xau_2012_2026.csv':'defcbd64ab625156f7594f8a357591bc3d2fea2a0e8deb4c9144ae88e4e8fea7','eur_2012_2026.csv':'710f10ed97e709f48e284e79511981e4e85638deca6958a668908d6f418285c5','BTCUSD_M1.csv':'9257332636450a0c93d20c45757016ae359feb208d7b91ac82fac173a64f8c51'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,obj):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(obj,indent=2));t.replace(p)
def verify(r):
 s=r['Summary'];receipt=Path(r['File'])
 with gzip.open(receipt,'rt') as f: raw=json.load(f)
 residual=100+math.fsum(x['Pnl'] for x in raw['Ledger'])-s['EndingBalance']
 assert s['ErrorCount']==0 and not raw['Errors'] and s['OpenPositions']==0
 assert not s['Quarantined'] and not s['AccountingBlock'] and s['TotalContributions']==100
 assert abs(residual)<.05 and len(raw['Ledger'])==s['Baskets']
 assert not any(raw['BtcResearchStatus'].values()),raw['BtcResearchStatus']
 r.update(ReceiptSHA256=sha(receipt),LedgerResidualUSD=residual,Verified=True)
 return r
def run(profile,path='B',cost=1):
 name=f'{profile["Id"]}_{path}{cost}';out=RUNS/name
 if (out/'verified.json').exists():return json.loads((out/'verified.json').read_text())
 out.mkdir(exist_ok=True);cfg=out/'profiles.json';save(cfg,[profile]);result=out/'results.json'
 env={k:v for k,v in os.environ.items() if not k.startswith(('RESEARCH_','R15_','BTC_SIGNAL_','BTC_FRIDAY_','BTC_SEVEN_','ADAPTIVE_GUARD','XAU_START_','RIZAN_REPLAY_'))}
 env.update(SEED_DATA=str(SEED),BTC_INPUT=str(INPUTS/'BTCUSD_M1.csv'),MACRO_DATA=str(ROOT/'macro_off.json'),RESEARCH_CONFIGS=str(cfg),RESEARCH_PATH=path,RESEARCH_COST=str(cost),DOTNET_ROOT=str(DOTNET.parent))
 start=time.time();print('START',name,flush=True)
 with (out/'stdout.log').open('w') as f:
  subprocess.run([str(DOTNET),str(DLL),str(INPUTS/'xau_2012_2026.csv'),str(INPUTS/'eur_2012_2026.csv'),str(result),'research','2019','2026'],env=env,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
 r=verify(json.loads(result.read_text())[0]);r['WallSeconds']=time.time()-start
 save(out/'verified.json',r)
 s=r['Summary'];print('DONE',name,s['EndingBalance'],s['MaxEquityDDPct'],s['Baskets'],s['Orders'],flush=True)
 return r
def main():
 for k,v in EXPECTED.items():assert sha(INPUTS/k)==v,k
 for f in ['fresh_xau_tape.json','fresh_eur_tape.json']:shutil.copyfile(OLD/'research10b'/f,RUNS/f)
 (ROOT/'macro_off.json').write_text('[]')
 manifest={'SourceCommit':'26bf8396b6e703d650e703fca48d556252782f03','DatasetHashes':EXPECTED,'BuildSHA256':sha(DLL),'SourceFiles':{str(p.relative_to(ROOT/'native')):sha(p) for p in (ROOT/'native').rglob('*.cs') if 'obj' not in p.parts},'ProductionChanges':False}
 save(ROOT/'BUILD_AND_INPUT_MANIFEST.json',manifest)
 profiles=json.loads((ROOT/'v5/v7_priority_profiles.json').read_text());control=profiles[0]
 base=run(control);s=base['Summary']
 assert abs(s['EndingBalance']-1662133293.0811067)<.01 and abs(s['MaxEquityDDPct']-56.67209330213908)<1e-6 and s['Baskets']==1047 and s['Orders']==187560,'BASELINE_PARITY_FAILURE'
 save(ROOT/'BASELINE_PARITY.json',{'passed':True,'actual':base})
 rows=[base,run(profiles[1])];save(ROOT/'COMPLETED.json',rows)
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  jobs={pool.submit(run,p):p['Id'] for p in profiles[2:]}
  for f in concurrent.futures.as_completed(jobs):
   try:rows.append(f.result())
   except Exception as e:print('FAILED',jobs[f],repr(e),flush=True)
   save(ROOT/'COMPLETED.json',rows)
 eligible=sorted([r for r in rows[1:] if r['Summary']['MaxEquityDDPct']<60 and r['Summary']['EndingBalance']>s['EndingBalance']],key=lambda r:r['Summary']['EndingBalance'],reverse=True)[:3]
 byid={p['Id']:p for p in profiles}
 for path,cost in [('A',1),('A',2),('B',2)]:
  stress_control=run(control,path,cost);rows.append(stress_control);save(ROOT/'COMPLETED.json',rows)
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
   jobs=[pool.submit(run,byid[r['Profile']['Id']],path,cost) for r in eligible]
   for f in concurrent.futures.as_completed(jobs):rows.append(f.result());save(ROOT/'COMPLETED.json',rows)
 save(ROOT/'BATCH_COMPLETE.json',{'completed_native_replays':len(rows),'target_hit':[r['Profile']['Id'] for r in rows if r['Summary']['EndingBalance']>=1e10 and r['Summary']['MaxEquityDDPct']<60]})
if __name__=='__main__':main()
