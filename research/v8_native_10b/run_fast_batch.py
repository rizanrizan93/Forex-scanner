"""Load market inputs once per native worker; verify each receipt as it completes.
Requires indexed/diagnostic control parity, then validates locked P0 alone.
"""
import concurrent.futures,gzip,json,os,shutil,subprocess,time
from pathlib import Path
import run_v8 as r
r.DLL=r.ROOT/'build_diagnostics/NovemberReplay.dll'
FAST=r.ROOT/'diagnostic_runs';FAST.mkdir(exist_ok=True)
engine_map=r.DLL.parent/'engine_path.txt'
ECONOMIC_DLL=Path(engine_map.read_text().strip()) if engine_map.exists() else r.DLL
HASH=r.sha(ECONOMIC_DLL)
def record(row):
 row=r.verify(row);row['EngineBuildSHA256']=HASH
 dst=r.RUNS/f'{row["Profile"]["Id"]}_{row["Path"]}{row["Cost"]}'
 dst.mkdir(exist_ok=True);r.save(dst/'verified.json',row)
 s=row['Summary'];print('VERIFIED',row['Profile']['Id'],row['Path'],row['Cost'],s['EndingBalance'],s['MaxEquityDDPct'],flush=True)
 return row
def batch(profiles,label,path='B',cost=1):
 out=FAST/label;out.mkdir(exist_ok=True);conf=out/'profiles.json';r.save(conf,profiles)
 result=out/'results.json';metrics=Path(str(result)+'.metrics.json')
 env={k:v for k,v in os.environ.items() if not k.startswith(('RESEARCH_','R15_','BTC_SIGNAL_','BTC_FRIDAY_','BTC_SEVEN_','ADAPTIVE_GUARD','XAU_START_','RIZAN_REPLAY_'))}
 env.update(SEED_DATA=str(r.SEED),BTC_INPUT=str(r.INPUTS/'BTCUSD_M1.csv'),MACRO_DATA=str(r.ROOT/'macro_off.json'),RESEARCH_CONFIGS=str(conf),RESEARCH_PATH=path,RESEARCH_COST=str(cost),DOTNET_ROOT=str(r.DOTNET.parent))
 seen=set();rows=[]
 with (out/'stdout.log').open('w') as log:
  proc=subprocess.Popen([str(r.DOTNET),str(r.DLL),str(r.INPUTS/'xau_2012_2026.csv'),str(r.INPUTS/'eur_2012_2026.csv'),str(result),'research','2019','2026'],cwd=r.ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
  r.save(out/'execution.json',{'BuildSHA256':HASH,'Profiles':[p['Id'] for p in profiles],'Path':path,'Cost':cost,'StartedUnix':time.time()})
  while True:
   if metrics.exists():
    try:pending=json.loads(metrics.read_text())
    except json.JSONDecodeError:pending=[]
    for row in pending:
     key=row['Profile']['Id']
     if key not in seen:rows.append(record(row));seen.add(key)
   if proc.poll() is not None:break
   time.sleep(2)
  if proc.returncode:raise RuntimeError(f'{label} native exit {proc.returncode}')
  for row in json.loads(result.read_text()):
   if row['Profile']['Id'] not in seen:rows.append(record(row))
 return rows
def main():
 for f in ['fresh_xau_tape.json','fresh_eur_tape.json']:shutil.copyfile(r.OLD/'research10b'/f,FAST/f)
 controlfile=FAST/'V8_INDEXED_CONTROL_B1/verified.json'
 while not controlfile.exists():time.sleep(2)
 c=json.loads(controlfile.read_text());s=c['Summary']
 assert abs(s['EndingBalance']-1662133293.0811067)<.01 and abs(s['MaxEquityDDPct']-56.67209330213908)<1e-6 and s['Baskets']==1047 and s['Orders']==187560
 r.save(r.ROOT/'INDEXED_BASELINE_PARITY.json',{'passed':True,'BuildSHA256':HASH,'control':c})
 profiles=json.loads((r.ROOT/'v5/v7_priority_profiles.json').read_text())
 lock=profiles[1]
 if not (r.RUNS/'V7_LOCK_B1/verified.json').exists():batch([lock],'p0_lock')
 # Reverse the remainder so the legacy runner can execute the leading cases
 # concurrently and reuse verified receipts for cases already completed here.
 remaining=[p for p in profiles[2:] if not (r.RUNS/f'{p["Id"]}_B1/verified.json').exists()][::-1]
 chunks=[remaining]
 with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
  futures=[pool.submit(batch,chunk,f'priority_worker_{i}') for i,chunk in enumerate(chunks) if chunk]
  for f in concurrent.futures.as_completed(futures):f.result()
 r.save(r.ROOT/'FAST_BATCH_COMPLETE.json',{'BuildSHA256':HASH,'PriorityProfiles':len(profiles),'CompletedAtUnix':time.time()})
if __name__=='__main__':main()
