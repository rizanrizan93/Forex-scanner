"""Restore original generator's paths; verify inputs before producing signal tapes.

This prepares data only. It never replays or trades, and never certifies macro
vintage or reference ledger parity. Original generator file remains untouched.
"""
from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research/r11_profitable_addon_alpha'))
from native_audit import EXPECTED,sha
SOURCE=ROOT/'research/r11_profitable_addon_alpha/recovered_seed_tape_generator.py'
SOURCE_SHA='0d44530099752a067bde94fd14e54589d95fe9f7eef9352279fad95d8fe00fc4'
BOOTSTRAP="w=Path(__file__).resolve().parent.parent;r=w/'annual_seed_search';out=r/'data';out.mkdir(exist_ok=True)\nproto=json.load(open(r/'PROTOCOL.json'));assert math.prod(len(v) for v in proto['grid'].values())==4478976"
READ="w/'november_research/data/corrected'/name"
def source_code():
    assert sha(SOURCE)==SOURCE_SHA,'Generator bytes changed'
    source=SOURCE.read_text();assert source.count(BOOTSTRAP)==1 and source.count(READ)==1
    source=source.replace(BOOTSTRAP,"w=input_root;r=output_root;out=r/'data';out.mkdir(parents=True,exist_ok=True)").replace(READ,'input_root/name')
    compile(source,str(SOURCE),'exec')
    return source

def prepare(inputs,output):
    inputs=Path(inputs).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    checked={name:sha(inputs/name) for name in EXPECTED}
    assert checked==EXPECTED,'Exact corrected input mismatch; stop'
    namespace={'__file__':str(SOURCE),'input_root':inputs,'output_root':output}
    exec(compile(source_code(),str(SOURCE),'exec'),namespace)
    files={p.name:{'sha256':sha(p),'bytes':p.stat().st_size,'records':p.stat().st_size//40} for p in (output/'data').glob('base*_symbol*.bin')}
    assert len(files)==108 and all(p['bytes']%40==0 for p in files.values())
    receipt=dict(generator_sha256=SOURCE_SHA,input_sha256=checked,signal_tapes=files,
        algorithm_changed=False,path_bootstrap_only_adapted=True,native_parity=False,
        original_tape_hash_reference_available=False,macro_vintage_certified=False,
        reference_ledger_verified=False,production_changes=False)
    (output/'TAPE_RECOVERY.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('R12_TAPES_PREPARED',json.dumps({'files':len(files),'records':sum(x['records'] for x in files.values()),'native_parity':False}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs');p.add_argument('--output');p.add_argument('--selftest',action='store_true');a=p.parse_args()
    if a.selftest:source_code();print('R12_GENERATOR_PATH_ADAPTATION_PASS')
    elif a.inputs and a.output:prepare(a.inputs,a.output)
    else:p.error('Supply --inputs and --output')
