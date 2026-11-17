"""Independent scalar audit of primary rebound labels against source M1 bars."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd


def verify(input_path,ledger_path):
    d=pd.read_csv(input_path,usecols=['timestamp','high','low']);t=pd.to_datetime(d.pop('timestamp'),utc=True).array.asi8
    e=pd.read_csv(ledger_path);sample=e.sample(min(300,len(e)),random_state=1711)
    counts={}
    for r in sample.to_dict('records'):
        at=pd.Timestamp(r['touch']).value;i=int(np.searchsorted(t,at));assert t[i]==at
        side=1 if r['side']=='BUY' else -1;target=r['atr_h1']*.25;end=at+60*60_000_000_000
        j=int(np.searchsorted(t,end));result='TIMEOUT'
        if j>=len(t) or t[j]!=end or any(t[k]-t[k-1]!=60_000_000_000 for k in range(i+1,j+1)):
            result='DATA_GAP'
        else:
            for k in range(i,j):
                hi=float(d.high.iloc[k]);lo=float(d.low.iloc[k]);ref=r['entry_reference']
                adverse=ref-lo if side==1 else hi-ref
                favorable=hi-ref if side==1 else ref-lo
                if adverse>=target:result='ADVERSE';break
                if k>i and favorable>=target:result='BOUNCE';break
        assert result==r['outcome_0_25'],(r['touch'],r['zone'],result,r['outcome_0_25'])
        counts[result]=counts.get(result,0)+1
    return {'independent_scalar_samples':len(sample),'all_primary_outcomes_match':True,'sample_outcomes':counts,'random_seed':1711}

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--input',type=Path,required=True);a.add_argument('--ledger',type=Path,required=True);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
    p=verify(args.input,args.ledger);args.out.write_text(json.dumps(p,indent=2));print(json.dumps(p))
