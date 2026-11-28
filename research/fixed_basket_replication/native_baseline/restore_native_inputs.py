"""Offline restoration from four user archives, exact original Nov13 procedure.

Does not fetch a replacement dataset. SHA mismatch raises, never silently edits
prices to force parity. Original corrected price/flag vintage remains uncertified.
"""
from pathlib import Path
import argparse,gzip,hashlib,json,shutil,zipfile
import numpy as np
import pandas as pd
from native_audit import EXPECTED

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def restore(archive_root,out):
    ar=Path(archive_root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    work=out/'raw';work.mkdir(exist_ok=True)
    settlement=ar/'RIZAN_REPLAY_SETTLEMENT_2016_2026_20261017.zip'
    november=ar/'RIZAN_NOVEMBER_REPLAY_AND_ENTRY_AUDIT_20261113.zip'
    with zipfile.ZipFile(settlement) as z:
        for name in ('xau_2012_2026.csv','eur_2012_2026.csv'):
            with z.open('inputs/'+name) as src,(work/name).open('wb') as dest:shutil.copyfileobj(src,dest)
    chunks=[]
    for i in (1,2):
        with zipfile.ZipFile(ar/f'RIZAN_BTC_RAW_20261113_PART_{i}.zip') as z:
            chunks.append(z.read(f'BTCUSD_M1.csv.gz.part{i}'))
    packed=b''.join(chunks);del chunks
    assert hashlib.sha256(packed).hexdigest()=='cb2742468de731d3ac785e0ad2bd96d3f419bbbc8cbef1ec7eaefb083b7fd6b4'
    (work/'BTCUSD_M1.csv').write_bytes(gzip.decompress(packed));del packed
    assert sha(work/'BTCUSD_M1.csv')=='c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'
    audit={}
    with zipfile.ZipFile(november) as z:
        newbtc=pd.read_csv(z.open('november_research/data/BTCUSD_BITSTAMP_EXTENSION.csv'))
        newbtc.timestamp=pd.to_datetime(newbtc.timestamp,utc=True)
        for symbol,name in (('XAUUSD','xau_2012_2026.csv'),('EURUSD','eur_2012_2026.csv'),('BTCUSD','BTCUSD_M1.csv')):
            old=pd.read_csv(work/name);old.timestamp=pd.to_datetime(old.timestamp,utc=True)
            if symbol=='BTCUSD':extension=newbtc[newbtc.timestamp>old.timestamp.iloc[-1]]
            else:
                new=pd.read_csv(z.open(f'november_research/data/broker/{symbol}_M1.csv'))
                new.timestamp=pd.to_datetime(new.timestamp,utc=True)
                original=old.timestamp.copy()
                corrected=original.dt.tz_localize(None).dt.tz_localize('Europe/London',ambiguous='raise',nonexistent='raise').dt.tz_convert('UTC')
                assert corrected.is_unique and corrected.is_monotonic_increasing
                if symbol=='XAUUSD':
                    ix=np.searchsorted(original.astype('int64'),corrected.astype('int64'),side='right')-1
                    valid=ix>=0;ix=np.maximum(ix,0)
                    for col in ('spread','roll','buy_ok','sell_ok'):
                        values=old[col].to_numpy()[ix].copy();values[~valid]=.26 if col=='spread' else 0;old[col]=values
                old.timestamp=corrected;extension=new[new.timestamp>corrected.iloc[-1]].copy()
                if symbol=='XAUUSD':
                    last=corrected.iloc[-1]
                    days=pd.date_range(last.normalize()-pd.Timedelta(days=2),extension.timestamp.iloc[-1].normalize()+pd.Timedelta(days=2),freq='D').tz_convert('America/New_York').normalize().unique()
                    rolltimes=[];weights=[]
                    for day in days:
                        at=day+pd.Timedelta(hours=17)
                        if day.dayofweek<5 and at>last:rolltimes.append(at.value);weights.append(3 if day.dayofweek==2 else 1)
                    counts=np.cumsum(weights);i=np.searchsorted(rolltimes,extension.timestamp.astype('int64'),side='right')
                    extension['roll']=int(old['roll'].iloc[-1])+np.where(i>0,counts[np.maximum(i-1,0)],0)
                    extension['spread']=.26;extension['buy_ok']=0;extension['sell_ok']=0
            joined=pd.concat([old,extension[list(old.columns)]],ignore_index=True)
            assert joined.timestamp.is_unique and joined.timestamp.is_monotonic_increasing
            dest=out/name;joined.to_csv(dest,index=False)
            digest=sha(dest)
            audit[symbol]=dict(rows=len(joined),bytes=dest.stat().st_size,sha256=digest,expected=EXPECTED[name],matched=digest==EXPECTED[name],first=str(joined.timestamp.iloc[0]),last=str(joined.timestamp.iloc[-1]))
            (out/'restoration_audit.json').write_text(json.dumps(audit,indent=2)+'\n')
            print('RESTORED_INPUT',symbol,json.dumps(audit[symbol]),flush=True)
            assert digest==EXPECTED[name],f'{symbol} exact bytes differ; do not use as native parity input'
            del old,joined;import gc;gc.collect()
    return audit
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archives',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();restore(a.archives,a.output)
