"""Post-search cost sensitivity only; original qualification remains unchanged."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import research_h4_d1_reversal as r
from fx_scanner.h4_d1_reversal import SHAPE,LOCAL_SHAPE,CONTRACT,config

def lock(folder,out):
 paths={}
 for p in folder.rglob('h4d1-*-s3.npz'):
  m=json.loads(p.with_suffix('.json').read_text());assert m['contract']==CONTRACT and m['source_index']==3;paths[m['year']]=p
 assert set(paths)==set(range(2016,2026))
 train={k:np.zeros(LOCAL_SHAPE,np.float64) for k in r.FIELDS};val={k:np.zeros(LOCAL_SHAPE,np.float64) for k in r.FIELDS}
 gt=np.zeros(LOCAL_SHAPE,np.int8);gv=gt.copy()
 for year,p in sorted(paths.items()):
  with np.load(p) as d:
   dest=train if year<=2021 else val
   for k in r.FIELDS:dest[k]+=d[k]
   good=(d['n']>=15)&(d['r_sum']>0)
   if year<=2021:gt+=good
   else:gv+=good
 mask=(train['n']>=180)&(val['n']>=60)&(train['r_sum']>0)&(train['gain']>=1.15*train['loss'])&(val['gain']>=1.2*val['loss'])
 candidates=[]
 for flat in np.flatnonzero(mask.ravel()):
  idx=np.unravel_index(int(flat),LOCAL_SHAPE);gi=(idx[0],3)+idx[2:]
  candidates.append({'index':int(np.ravel_multi_index(gi,SHAPE)),'config':config(gi),'train':r.summary({k:d[idx] for k,d in train.items()}),'validation':r.summary({k:d[idx] for k,d in val.items()}),'positive_train_years':int(gt[idx]),'positive_val_years':int(gv[idx]),'qualified':False,'status':'COST_SENSITIVITY_ONLY_NOT_PROMOTABLE'})
 assert len(candidates)==2
 result={'contract':CONTRACT,'source_run':38456814232,'configurations_evaluated':20_000_000,'selected_by_side':candidates,'status':'COST_SENSITIVITY_LOCKED','execution_authority':False,'execution_influence':False,'candidate_lock_sha256':hashlib.sha256(json.dumps(candidates,sort_keys=True).encode()).hexdigest(),'limitations':['Post-search diagnostic candidates from original grid; original gates remain unchanged.','2026 outcome withheld until diagnostic lock; prices cached, not pristine holdout.']}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n');print('H4_SENSITIVITY_LOCK_JSON='+json.dumps(result),flush=True)

def finish(locked,ledger,out):
 result=json.loads(locked.read_text());rows=json.loads(ledger.read_text())
 for c in result['selected_by_side']:
  c['test_2026']=r.ledger_metrics([x for x in rows if x['index']==c['index']]);c['test_2026']['trades_per_month']=c['test_2026']['n']/9;c['qualified']=False
 result['status']='RESEARCH_ONLY_COST_SENSITIVITY';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print('H4_SENSITIVITY_RESULT_JSON='+json.dumps(result),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--shards',type=Path);p.add_argument('--locked',type=Path);p.add_argument('--ledger',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.shards:lock(a.shards,a.output)
 else:finish(a.locked,a.ledger,a.output)
