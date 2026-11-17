"""Exact balanced-direction benchmark at the already selected research entries."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from research.zone_rebound.exhaustion_r2 import label


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True,type=Path);p.add_argument('--ledger',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    d=pd.read_csv(a.input,usecols=['timestamp','open','high','low','close','spread']);d.index=pd.to_datetime(d.pop('timestamp'),utc=True);e=pd.read_csv(a.ledger);out=[]
    for (kind,side,scenario),q in e.groupby(['kind','side','selected_scenario']):
        up=label(d,q,random_side=np.ones(len(q),dtype=int))[scenario];down=label(d,q,random_side=-np.ones(len(q),dtype=int))[scenario]
        for year in [2025,2026]:
            m=q.year.to_numpy()==year;n=int(m.sum())
            out.append(dict(kind=kind,side=int(side),scenario=scenario,year=year,n=n,actual_rate=float(q.loc[m,scenario].mean()) if n else None,balanced_random_rate=float((.5*up[m]+.5*down[m]).mean()) if n else None))
    result={'method':'Expected success of 50/50 BUY/SELL at the exact same selected entry reference and times, same target/adverse/horizon. Does not select rules.','rows':out};a.out.write_text(json.dumps(result,indent=2));print(json.dumps([r for r in out if r['kind']=='CONFIRMED' and r['scenario']=='SMALL'],indent=2))

if __name__=='__main__':main()
