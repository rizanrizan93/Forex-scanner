"""Scalar first-passage oracle for frozen R2 exhaustion research samples."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
MIN=60_000_000_000
BUDGETS={'STRICT':(.25,.25),'MODERATE':(.25,.5),'SMALL':(.1,.5),'WIDE':(.25,1.)}


def scalar(d,t,row,scenario,delay=0,cost=0.):
    i=int(row['i'])+delay;side=int(row['side']);a=float(row['atr_h1'])
    if i+60>=len(t) or any(t[k]-t[k-1]!=MIN for k in range(i+1,i+61)):return False
    ref=float(row['reference']) if not delay else float(d.open.iloc[i]);ref+=side*cost
    reward,adverse=BUDGETS[scenario]
    for j in range(i,i+60):
        hi=float(d.high.iloc[j]);lo=float(d.low.iloc[j]);fav=hi-ref if side==1 else ref-lo;bad=ref-lo if side==1 else hi-ref
        if bad>=adverse*a:return False
        if not (j==i and row['kind']=='AREA' and delay==0) and fav>=reward*a:return True
    return False


def verify(input_path,ledger_path):
    d=pd.read_csv(input_path,usecols=['timestamp','open','high','low','spread']);t=pd.to_datetime(d.pop('timestamp'),utc=True).array.asi8;e=pd.read_csv(ledger_path);n=0
    for _,q in e.groupby(['kind','side','selected_scenario']):
        for row in q.sample(min(25,len(q)),random_state=1711).to_dict('records'):
            scenario=row['selected_scenario'];i=int(row['i']);assert int(row['time_ns'])==int(t[i])
            expected=lambda name:row[name] in [True,1,'True']
            assert scalar(d,t,row,scenario)==expected(scenario),(row['time_ns'],scenario,'raw')
            assert scalar(d,t,row,scenario,delay=1)==expected('delay_1m_success'),(row['time_ns'],scenario,'delay')
            assert scalar(d,t,row,scenario,cost=float(d.spread.iloc[i]))==expected('spread_proxy_success'),(row['time_ns'],scenario,'spread')
            n+=1
    return {'samples':n,'scalar_comparisons':3*n,'raw_delay_and_spread_labels_match':True,'random_seed':1711}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True,type=Path);p.add_argument('--ledger',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();out=verify(a.input,a.ledger);a.out.write_text(json.dumps(out,indent=2));print(json.dumps(out))
