"""Read-only rejection audit of the locked V6 grid; never changes selection."""
import json
from pathlib import Path
import numpy as np
from fx_scanner.volatility_reversal import SHAPE, config, CONTRACT
fields=('n','r_sum','r_sq','gain','loss','stress_sum','censored')
train={k:np.zeros(SHAPE,dtype=np.float64) for k in fields}
val={k:np.zeros(SHAPE,dtype=np.float64) for k in fields}
gt=np.zeros(SHAPE,dtype=np.int8);gv=gt.copy()
paths=sorted(Path('/tmp/volatility-shards').rglob('volatility-*.npz'))
assert len(paths)==10
for p in paths:
    year=int(p.stem.split('-')[-1])
    with np.load(p) as d:
        dest=train if year<=2021 else val
        for k in fields:dest[k]+=d[k]
        good=(d['n']>=15)&(d['r_sum']>0)
        if year<=2021:gt+=good
        else:gv+=good
    print('AUDIT_YEAR',year,flush=True)
n=np.maximum(val['n'],1)
mean=val['r_sum']/n
lcb=mean-1.96*np.sqrt(np.maximum(val['r_sq']/n-mean*mean,0)/n)
gates=[
('train_n_ge_180',train['n']>=180),
('validation_n_ge_60',val['n']>=60),
('train_net_positive',train['r_sum']>0),
('train_pf_ge_1_15',train['gain']>=1.15*train['loss']),
('validation_pf_ge_1_2',val['gain']>=1.2*val['loss']),
('validation_stress_positive',val['stress_sum']>0),
('validation_mean_lcb_positive',lcb>0),
('train_positive_years_ge_5',gt>=5),
('validation_positive_years_ge_3',gv>=3),
('train_censor_le_2pct',train['censored']/np.maximum(train['n']+train['censored'],1)<=.02),
('validation_censor_le_2pct',val['censored']/np.maximum(val['n']+val['censored'],1)<=.02)]
mask=np.ones(SHAPE,dtype=bool);counts=[]
for name,gate in gates:
    mask &= gate
    counts.append({'gate':name,'remaining_tuples':int(mask.sum()),'buy':int(mask[0].sum()),'sell':int(mask[1].sum())})
report={'contract':CONTRACT,'source_run':38386687428,'cumulative_gates':counts,
        'interpretation':'Parameter tuples are not independent strategies. Zero qualifying tuples is not proof all lose money.',
        'diagnostic_examples':[]}
def metrics(data,idx):
    nn=float(data['n'][idx]);rr=float(data['r_sum'][idx]);loss=float(data['loss'][idx]);gain=float(data['gain'][idx])
    cc=float(data['censored'][idx])
    return {'n':int(nn),'net_r_sum':rr,'mean_net_r':rr/max(nn,1),
            'profit_factor':gain/loss if loss else None,'mean_stress_r':float(data['stress_sum'][idx])/max(nn,1),
            'censored':int(cc),'censored_fraction':cc/max(nn+cc,1)}
# Descriptive runner-up only; cannot be promoted or called an out-of-sample winner.
for sid in range(2):
    enough=(train['n'][sid]>=180)&(val['n'][sid]>=60)
    possible=np.flatnonzero(enough.ravel())
    if len(possible):
        chosen=int(possible[np.argmax(lcb[sid].ravel()[possible])])
        idx=(sid,)+np.unravel_index(chosen,SHAPE[1:])
        report['diagnostic_examples'].append({'config':config(idx),'train':metrics(train,idx),
        'validation':metrics(val,idx),'validation_lcb_mean_r':float(lcb[idx]),
        'train_positive_years':int(gt[idx]),'validation_positive_years':int(gv[idx]),
        'failed_gates':[name for name,gate in gates if not gate[idx]],
        'status':'REJECTED_DESCRIPTIVE_EXAMPLE_NOT_VALIDATED'})
Path('audit').mkdir(exist_ok=True)
Path('audit/volatility_reversal_diagnostics.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
print('VOLATILITY_DIAGNOSTICS_JSON='+json.dumps(report,allow_nan=False),flush=True)
results=list(Path('/tmp/final-result').rglob('volatility_reversal_results.json'))
assert len(results)==1
r=json.loads(results[0].read_text());assert r['contract']==CONTRACT
assert r['status'] in {'RESEARCH_ONLY','VALIDATED_2026'}
Path('audit/volatility_reversal_results.json').write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
print('VOLATILITY_RESULT_JSON='+json.dumps(r,allow_nan=False),flush=True)

