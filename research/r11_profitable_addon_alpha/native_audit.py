"""Verify recovered source and required immutable inputs; never fabricate tapes."""
import argparse,hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
EXPECTED={
 'eur_2012_2026.csv':'710f10ed97e709f48e284e79511981e4e85638deca6958a668908d6f418285c5',
 'xau_2012_2026.csv':'defcbd64ab625156f7594f8a357591bc3d2fea2a0e8deb4c9144ae88e4e8fea7',
 'BTCUSD_M1.csv':'9257332636450a0c93d20c45757016ae359feb208d7b91ac82fac173a64f8c51'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def audit(input_root=None):
 manifest=json.loads((ROOT/'native_source_manifest.json').read_text())
 for p,digest in manifest['files'].items():
  assert sha(ROOT/'native_original'/p)==digest,p
 inputs={}
 for name,digest in EXPECTED.items():
  p=Path(input_root or '/tmp/r11_inputs_not_restored')/name
  inputs[name]=dict(required_sha256=digest,available=p.is_file(),
      actual_sha256=sha(p) if p.is_file() else None)
  inputs[name]['matched']=inputs[name]['actual_sha256']==digest
 inputs_matched=all(v['matched'] for v in inputs.values())
 blockers=[]
 if not inputs_matched:
  blockers.append('Exact 3-asset corrected CSV bytes are missing or mismatched in this environment')
 blockers.extend([
      'SEED_DATA base{Base}_symbol{sid}.bin signal tapes missing; generator recovered but tapes and parity not verified',
      'Original MACRO_DATA and XAU buyOk/sellOk vintage provenance uncertified',
      'Original full 1047-basket reference order/settlement/equity ledger missing',
      'FP Markets actual minlot/step/margin tiers/fees/capacity not certified'])
 result=dict(source_files_verified=len(manifest['files']),
    original_source_unchanged=True,target_framework='net8.0',input_audit=inputs,
    exact_price_input_bytes_matched=inputs_matched,
    signal_tape_generator_recovered=True,
    signal_tapes_present=False,macro_input_present=False,reference_basket_ledger_present=False,
    native_parity=False,can_run_exact_control=False,production_changes=False,
    blockers=blockers,
    commit_sha=os.getenv('GITHUB_SHA'),run_id=os.getenv('GITHUB_RUN_ID'))
 out=ROOT.parents[1]/'artifacts/r11/native_input_audit.json';out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text(json.dumps(result,indent=2)+'\n');print('R11_NATIVE_AUDIT',json.dumps(result),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--inputs');a=p.parse_args();audit(a.inputs)
