"""Create immutable pointwise-filtered addon tapes; no portfolio PnL is read."""
from pathlib import Path
import argparse, hashlib, json, shutil
import numpy as np
import pandas as pd

DT=np.dtype([('t','<i8'),('idx','<i4'),('symbol','<i4'),('side','<i4'),
             ('trend','<i4'),('atr','<f8'),('anchor','<f8')])
assert DT.itemsize == 40
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def gates(a,q):
    quotes=q.reindex(a['t'])
    valid=quotes.notna().all(axis=1).to_numpy()
    spread=quotes['spread'].to_numpy()
    flag=np.where(a['side']>0,quotes.buy_ok.to_numpy(),quotes.sell_ok.to_numpy())
    return valid & (a['trend']==7) & (flag==1) & (spread>=0) & (spread<=.15*a['atr'])
def run(root):
    root=Path(root).resolve(); target=root/'r16_seed_data';target.mkdir(exist_ok=True)
    repo=root/'Forex-scanner/research/r16_no_pause'
    source=root/'native_tapes/data/base13_symbol1.bin'
    a=np.fromfile(source,dtype=DT)
    parts=[]
    for c in pd.read_csv(root/'native_inputs/xau_2012_2026.csv',
                         usecols=['timestamp','spread','buy_ok','sell_ok'],chunksize=250000):
        t=pd.to_datetime(c.pop('timestamp'),utc=True).astype('int64')//60000000000
        c.index=t;parts.append(c.loc[c.index.isin(a['t'])])
    q=pd.concat(parts).sort_index();assert q.index.is_unique
    mask=gates(a,q);hours=(a['t']//60)%24
    checks={}
    for date in ['2020-01-01','2023-01-01','2026-01-01']:
        cut=int(pd.Timestamp(date,tz='UTC').value//60000000000)
        before=a['t']<=cut
        checks[date]=bool(np.array_equal(mask[before],gates(a[before],q[q.index<=cut])))
    assert all(checks.values()),'Prefix filter mismatch'
    seed=root/'native_tapes/data/base3_symbol0.bin';shutil.copyfile(seed,target/seed.name)
    assert sha(seed)==sha(target/seed.name)
    template=json.loads((root/'native_runs/addon_r3.json').read_text())[0]
    profiles=[];counts={}
    for base,name,select in [(101,'r16_quality_all',mask),
                              (102,'r16_quality_asia',mask&(hours>=1)&(hours<5))]:
        p=json.loads(json.dumps(template));p['Id']=name;p['Addon']['Base']=base;p['Addon']['Trend']=0
        profiles.append(p);out=target/f'base{base}_symbol1.bin';a[select].tofile(out)
        research_period=(a['t']>=int(pd.Timestamp('2019-01-01',tz='UTC').value//60000000000))&(a['t']<=int(pd.Timestamp('2026-11-13 03:00',tz='UTC').value//60000000000))
        counts[name]={'all_years_signals':int(select.sum()),'research_period_signals':int((select&research_period).sum()),'sha256':sha(out)}
    manifest={'source_signals':len(a),'trend7_signals':int((a['trend']==7).sum()),
              'exact_quote_matches':int(np.isin(a['t'],q.index).sum()),'prefix_checks':checks,
              'signal_source_sha256':sha(source),'seed_sha256':sha(seed),
              'runtime_sha256':sha(root/'r15_indexed_runtime/indexed_runtime/NovemberReplay'),
              'quote_columns_read':['timestamp','spread','buy_ok','sell_ok'],
              'extra_24h_guard':False,'candidates':counts}
    (repo/'profiles.json').write_text(json.dumps(profiles,indent=2)+'\n')
    (repo/'filter_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);run(p.parse_args().root)
