"""Run guard-on only after disabled-copy ledger equality, against exact local inputs."""
from pathlib import Path
import argparse,json,os,subprocess,time
from compare_replays import read,compare

def run(root):
 root=Path(root).resolve();out=root/'native_runs';cases=out/'cases'
 off=cases/'r15_variant_off_Y2020_B_cost1.json.gz'
 while not off.exists():time.sleep(2)
 check=compare(read(cases/'r15_control_Y2020_B_cost1.json.gz'),read(off))
 (out/'guard_off_equality.json').write_text(json.dumps(check,indent=2)+'\n')
 assert check['all_ledger_streams_equal'],'Guard-off copy changed original order/cash/equity ledgers'
 p=json.loads((out/'continuous.json').read_text())[0];p['Id']='r15_continuous_guard4_24h'
 cfg=out/'continuous_guard.json';cfg.write_text(json.dumps([p]))
 env=os.environ.copy();env.update(R15_GROWTH_GUARD='1',BTC_SIGNAL_CACHE=str(cases/'control.json.btc_signals.json'),BTC_INPUT=str(root/'native_inputs/BTCUSD_M1.csv'),SEED_DATA=str(root/'native_tapes/data'),MACRO_DATA=str(out/'macro_off_loader.json'),RESEARCH_CONFIGS=str(cfg),RESEARCH_PATH='B')
 cmd=[str(root/'r15_guard_runtime/guard_runtime/NovemberReplay'),str(root/'native_inputs/xau_2012_2026.csv'),str(root/'native_inputs/eur_2012_2026.csv'),str(cases/'continuous_guard.json'),'all','2019','2026']
 with (out/'continuous_guard.stdout.log').open('w') as stdout,(out/'continuous_guard.stderr.log').open('w') as stderr:
  result=subprocess.run(cmd,env=env,stdout=stdout,stderr=stderr)
 (out/'guard_process_status.json').write_text(json.dumps({'exit_code':result.returncode,'complete':True,'command':cmd},indent=2)+'\n')
 if result.returncode:raise SystemExit(result.returncode)
 print('NATIVE_GUARD_COMPLETE',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();run(a.root)
