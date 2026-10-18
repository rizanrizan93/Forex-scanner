from pathlib import Path
import os,subprocess,json,hashlib
r=Path(__file__).resolve().parent;e=r/'engine'
env=os.environ.copy();env.pop('GH_TOKEN',None);env['RIZAN_PARALLEL_SCENARIOS']='1'
for mode in os.environ.get('RIZAN_REPLAY_MODES','control,patched').split(','):
 patch=r/'gap_repair/XAUUSD_gap_patch.parquet'
 if mode=='patched' and not patch.exists():continue
 if mode=='patched':env['RIZAN_GAP_PATCH']=str(patch)
 else:env.pop('RIZAN_GAP_PATCH',None)
 cmd=['python',str(e/'run_ticks.py'),'--target','unused','--key','unused','--hosts','unused','--audit',str(r/(mode+'_audit')),'--out',str(r/(mode+'_results'))]
 subprocess.run(cmd,env=env,check=True)
print('REVALIDATION_REPLAYS_DONE',flush=True)
