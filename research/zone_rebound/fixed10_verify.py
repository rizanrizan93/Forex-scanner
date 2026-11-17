"""Independent scalar barrier audit and same-entry direction counterfactual."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from research.zone_rebound.fixed10 import MIN,SCENARIOS,labels,mask,select_indices,metric


def scalar(d,row,horizon,adverse):
    i=int(row.i);t=d.index.asi8;side=int(row.side);reference=float(row.reference)
    if i+horizon>=len(d) or not np.all(np.diff(t[i:i+horizon+1])==MIN):return False
    for k in range(horizon):
        h=float(d.high.iloc[i+k]);l=float(d.low.iloc[i+k])
        bad=reference-l if side==1 else h-reference
        if bad>=adverse:return False
        if k:
            fav=h-reference if side==1 else reference-l
            if fav>=10:return True
    return False


def main():
    p=argparse.ArgumentParser();p.add_argument('--xau',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    e=pd.read_csv(args.out/'all_events.csv.gz');tr=pd.read_csv(args.out/'selected_ledger.csv.gz');summary=json.loads((args.out/'summary.json').read_text())
    d=pd.read_csv(args.xau,usecols=['timestamp','high','low']);d.index=pd.to_datetime(d.pop('timestamp'),utc=True)
    sample=e.sample(n=min(300,len(e)),random_state=1717);checks=0
    for row in sample.itertuples():
        for sc,(hz,a) in SCENARIOS.items():
            actual=scalar(d,row,hz,a);expected=getattr(row,sc)
            assert actual==expected,(row.time_ns,sc,actual,expected)
            checks+=1
    records=[]
    for model in summary['selected']:
        rule=model['rule'];sc=rule['scenario']
        if sc!='H240_A10':continue
        key=f"{rule['side']}_{sc}_{model['ablation']}";z=tr[(tr.model_id==key)&(tr.year==2025)].copy()
        z.side=-z.side;opposite=labels(d,z)[sc];original=tr.loc[(tr.model_id==key)&(tr.year==2025),sc].to_numpy()
        q=e[(e.family==rule['family'])&(e.tf==rule['tf'])&(e.side==rule['side'])].reset_index(drop=True)
        ids=select_indices(q,mask(q,rule['regime'],rule['phase'],'NONE'));ids=ids[q.year.to_numpy()[ids]==2025]
        records.append(dict(model_id=key,n=len(z),selected_rate=float(original.mean()) if len(z) else None,
                            balanced_same_entry_direction_rate=float((original.astype(float)+opposite.astype(float)).mean()/2) if len(z) else None,
                            same_zone_regime_session_without_macro_2025=metric(q,ids,sc)))
    result=dict(scalar_cases=len(sample),scalar_label_checks=checks,mismatches=0,controls=records,
                warning='Counterfactual direction uses the same area references and omits touch-bar favorable extremes. Removing macro changes prospective accepted entries; association, not a causal treatment effect.')
    (args.out/'verification.json').write_text(json.dumps(result,indent=2,allow_nan=False));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
