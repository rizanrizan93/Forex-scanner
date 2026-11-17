"""Read only the hash-verified user archive. No external research code needed."""
from pathlib import Path
import sys,json,hashlib
import pandas as pd

ROOT=Path(sys.argv[1]).resolve()/'research_manual_r1/frozen-inputs/data'
MANIFEST=Path(__file__).resolve().parent/'source_manifest.json'

def bars(frame,minutes):
    return frame.resample(f'{minutes}min',label='right',closed='left').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()

def load_data():
    source={x['file']:x['sha256'] for x in json.loads(MANIFEST.read_text())};parts=[];provenance=[]
    for year in range(2019,2026):
        p=ROOT/f'xau-{year}.csv';digest=hashlib.sha256(p.read_bytes()).hexdigest()
        assert digest==source[p.name],f'Changed input {p.name}'
        d=pd.read_csv(p,parse_dates=['timestamp']).set_index('timestamp');d.index=pd.to_datetime(d.index,utc=True)
        assert not d.index.duplicated().any();keep=d.index.year==year
        if year==2019:keep|=d.index.year==2018
        d=d.loc[keep];parts.append(d);provenance.append({'file':p.name,'sha256':digest,'rows_used_with_warmup':len(d),'first':d.index[0].isoformat(),'last':d.index[-1].isoformat()})
    d=pd.concat(parts).sort_index()
    assert not d.index.duplicated().any() and not d.isna().any().any()
    assert not ((d.low>d[['open','close']].min(axis=1))|(d.high<d[['open','close']].max(axis=1))|(d.high<d.low)).any()
    return d,provenance
