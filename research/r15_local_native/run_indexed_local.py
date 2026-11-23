"""Only run indexed economic pilots after original/control full-ledger equality."""
from pathlib import Path
import argparse,json,os,subprocess,time
from compare_replays import compare,read

def run(root):
 root=Path(root).resolve();out=root/'native_runs';cases=out/'cases';checks={}
 for y in (2020,2026):
  p=cases/f'r15_indexed_control_Y{y}_B_cost1.json.gz'
  while not p.exists():time.sleep(2)
  checks[str(y)]=compare(read(cases/f'r15_control_Y{y}_B_cost1.json.gz'),read(p))
  assert checks[str(y)]['all_ledger_streams_equal'],f'Indexed history changed {y} orders/cash/equity'
 (out/'indexed_control_equality.json').write_text(json.dumps(checks,indent=2)+'\n')
 baseline=json.loads((out/'continuous.json').read_text())[0];baseline['Id']='r15_indexed_baseline'
 addon=json.loads((out/'addon_r3.json').read_text())[0];addon['Id']='r15_indexed_addon_r3'
 guard={**baseline,'Id':'r15_indexed_guard4_24h'}
 batches=[('indexed_baseline_addon',[baseline,addon],'0'),('indexed_guard',[guard],'1')]
 jobs=[]
 for name,profiles,enabled in batches:
  cfg=out/f'{name}_profiles.json';cfg.write_text(json.dumps(profiles))
  env=os.environ.copy();env.update(R15_GROWTH_GUARD=enabled,BTC_SIGNAL_CACHE=str(cases/'control.json.btc_signals.json'),BTC_INPUT=str(root/'native_inputs/BTCUSD_M1.csv'),SEED_DATA=str(root/'native_tapes/data'),MACRO_DATA=str(out/'macro_off_loader.json'),RESEARCH_CONFIGS=str(cfg),RESEARCH_PATH='B')
  cmd=[str(root/'r15_indexed_runtime/indexed_runtime/NovemberReplay'),str(root/'native_inputs/xau_2012_2026.csv'),str(root/'native_inputs/eur_2012_2026.csv'),str(cases/f'{name}.json'),'all','2019','2026']
  stdout=(out/f'{name}.stdout.log').open('w');stderr=(out/f'{name}.stderr.log').open('w')
  job=subprocess.Popen(cmd,env=env,stdout=stdout,stderr=stderr);jobs.append((name,job,stdout,stderr))
 for name,job,stdout,stderr in jobs:
  code=job.wait();stdout.close();stderr.close();(out/f'{name}_status.json').write_text(json.dumps({'exit_code':code,'complete':True})+'\n')
  if code:raise SystemExit(code)
 print('R15_INDEXED_ALL_COMPLETE',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();run(a.root)
