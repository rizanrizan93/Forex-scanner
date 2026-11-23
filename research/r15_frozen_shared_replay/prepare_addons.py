"""Recompute fixed R14 signal policies on original Frozen XAU price inputs."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/r13_million_frequency'))
import search as r13
EXPECTED='defcbd64ab625156f7594f8a357591bc3d2fea2a0e8deb4c9144ae88e4e8fea7'

def prepare(source,out):
    source=Path(source);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==EXPECTED
    pieces=[]
    for p in pd.read_csv(source,chunksize=500000):
        p=p[p.timestamp>='2018-01-01']
        if len(p):pieces.append(p)
    raw=pd.concat(pieces,ignore_index=True);del pieces
    raw.index=pd.to_datetime(raw.pop('timestamp'),utc=True)
    assert raw.index.is_unique and raw.index.is_monotonic_increasing
    d=pd.DataFrame({**{'b'+k:raw[v] for k,v in zip('ohlc',('open','high','low','close'))},
                    **{'a'+k:raw[v]+raw.spread for k,v in zip('ohlc',('open','high','low','close'))}})
    registry=json.loads((ROOT/'research/r14_sparse_addons/candidate_registry.json').read_text())
    frames={};audit=[]
    for cid in (1736543,27615):
        cfg=next(x['parameters'] for x in registry['candidates'] if x['id']==cid)
        tf=cfg['tf'];m=frames.setdefault(tf,r13.features(d,tf))
        ev=np.flatnonzero(r13.signals(m,tf,cfg['family'],cfg['look'],cfg['side']))
        minutes=m.index.asi8//60_000_000_000;dt=d.index.asi8//60_000_000_000
        pos=np.searchsorted(dt,minutes[ev]);safe=np.minimum(pos,len(dt)-1)
        exact=(pos<len(dt))&(dt[safe]==minutes[ev])&(m.index[ev].year>=2019)
        ev=ev[exact];pos=pos[exact];rows=[]
        for i,j in zip(ev,pos):
            atr=float(m.atr.iloc[i]);anchor=float(m.l.iloc[i]-.1*atr if cfg['side']==1 else m.h.iloc[i]+.1*atr)
            trend=int(m.trend.iloc[i]);hr=m.index[i].hour
            if cfg['regime']=='WITH' and trend!=cfg['side']:continue
            if cfg['regime']=='AGAINST' and trend!=-cfg['side']:continue
            if cfg['session']=='LONDON' and not 6<=hr<10:continue
            if cfg['session']=='US' and not 12<=hr<16:continue
            if cfg['session']=='ASIA' and not 1<=hr<6:continue
            low=atr<=m.volmed.iloc[i]
            if cfg['vol']=='LOW' and not low or cfg['vol']=='HIGH' and low:continue
            rows.append(dict(At=m.index[i].strftime('%Y-%m-%dT%H:%M:%SZ'),Candidate=cid,Side=cfg['side'],
                Atr=atr,Anchor=anchor,StopMult=cfg['stop'],TargetR=cfg['target'],Hold=cfg['hold'],
                MaxSpreadAtr=cfg['spread'],OriginalFlagAllowed=bool(raw.buy_ok.iloc[j] if cfg['side']==1 else raw.sell_ok.iloc[j])))
        p=out/f'candidate_{cid}.json';p.write_text(json.dumps(rows,separators=(',',':')))
        audit.append(dict(candidate=cid,parameters=cfg,raw_source_signal_points=len(rows),
            original_flag_allowed=sum(x['OriginalFlagAllowed'] for x in rows),
            first=rows[0]['At'] if rows else None,last=rows[-1]['At'] if rows else None,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    result=dict(source_sha256=EXPECTED,data_source_changed_from_R14_vendor=True,
        original_flags_preserved=True,macro_vintage_certified=False,candidates=audit)
    (out/'signals_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print('NATIVE_ADDON_TAPES',json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();prepare(a.source,a.output)
