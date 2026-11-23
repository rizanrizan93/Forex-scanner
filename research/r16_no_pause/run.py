"""Run both preregistered profiles through the compiled R15 native adapter."""
from pathlib import Path
import argparse, json, os, subprocess
def run(root):
    root=Path(root).resolve();out=root/'native_runs'; repo=root/'Forex-scanner/research/r16_no_pause'
    env=os.environ.copy();env.update(R15_GROWTH_GUARD='0',
        BTC_SIGNAL_CACHE=str(out/'cases/control.json.btc_signals.json'),
        BTC_INPUT=str(root/'native_inputs/BTCUSD_M1.csv'),
        SEED_DATA=str(root/'r16_seed_data'),MACRO_DATA=str(out/'macro_off_loader.json'),
        RESEARCH_CONFIGS=str(repo/'profiles.json'),RESEARCH_PATH='B',RESEARCH_COST='1')
    cmd=[str(root/'r15_indexed_runtime/indexed_runtime/NovemberReplay'),
        str(root/'native_inputs/xau_2012_2026.csv'),str(root/'native_inputs/eur_2012_2026.csv'),
        str(out/'cases/r16_quality.json'),'all','2019','2026']
    with (out/'r16.stdout.log').open('w') as stdout,(out/'r16.stderr.log').open('w') as stderr:
        code=subprocess.run(cmd,env=env,stdout=stdout,stderr=stderr).returncode
    (repo/'run_status.json').write_text(json.dumps({'exit_code':code,'complete':True,'extra_24h_guard':False})+'\n')
    if code:raise SystemExit(code)
    print('R16_NATIVE_COMPLETE',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);run(p.parse_args().root)
