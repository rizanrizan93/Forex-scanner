"""RIZAN R8 research-only, fixed R6 event x USD index proxy conditional replay.

Causal under EXPLICIT ASSUMED macro feed lag, never historical first_seen verified.
Fixed original R6 choices, no optimizer, no trading or live integrations.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

COST_USD_OZ=0.50
ASSUMED_DELAY_MINUTES=(1,5,15)
MAX_QUOTE_AGE_MINUTES=5
PROXY_ID='DUKASCOPY_DOLLARIDXUSD_M1_NOT_ICE_DXY'
FIXED_POLICIES={60:dict(mode='SWEEP36',confirmation='RECLAIM_CLOSE',gate='H4_COUNTER',session='LONDON'),
                240:dict(mode='PREVIOUS_DAY',confirmation='RECLAIM_CLOSE',gate='NONE',session='ALL')}
COHORTS=('BASE_R6','DXY_AVAILABLE','DXY_15_AND_60_ALIGNED','DXY_15_AND_60_OPPOSED',
         'DXY_5M_ALIGNED','DXY_2_OF_3_ALIGNED','DXY_3_OF_3_ALIGNED')
EXECUTION_AUTHORITY=False
EXECUTION_INFLUENCE=False
MINUTE_NS=60_000_000_000

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def wilson(w:int,n:int)->float|None:
    if not n:return None
    z=1.9599639845;p=w/n;d=1+z*z/n
    return (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/d

def load_verified(xau_csv:Path,xau_manifest:Path,usd_csv:Path,usd_manifest:Path,year:int):
    xp=json.loads(xau_manifest.read_text());up=json.loads(usd_manifest.read_text())
    if xp.get('year')!=year or xp.get('source')!='HISTDATA_XAUUSD_M1' or xp.get('failed_periods'):
        raise ValueError('XAU_SOURCE_PROVENANCE_FAILED')
    if xp.get('normalized_csv_sha256')!=sha(xau_csv):raise ValueError('XAU_SHA_MISMATCH')
    allowed={('DOLLARIDXUSD','R8_USD_ORIGINAL_BI5_M1_V1'),
             ('RECONSTRUCTED_DXY_6FX_HISTDATA','R8_RECONSTRUCTED_DXY_6FX_HISTDATA_V1')}
    if up.get('year')!=year or (up.get('instrument'),up.get('contract')) not in allowed:
        raise ValueError('USD_SOURCE_PROVENANCE_FAILED')
    if up.get('instrument')=='RECONSTRUCTED_DXY_6FX_HISTDATA':
        if len(up.get('component_sources',[]))!=6 or any(s.get('failed_periods') for s in up['component_sources']):
            raise ValueError('SIX_FX_PROVENANCE_INCOMPLETE')
    if up.get('csv_sha256')!=sha(usd_csv):raise ValueError('USD_SHA_MISMATCH')
    if 'HISTORICAL_FIRST_SEEN_UNKNOWN' not in up.get('availability_model',''):
        raise ValueError('USD_AVAILABILITY_MUST_BE_LABELLED_SCENARIO')
    return pd.read_csv(xau_csv),pd.read_csv(usd_csv),xp,up

def make_r6_events(xau,year,horizon):
    from research.zone_rebound.h1h4_direction_r1 import validate_m1,completed_bars
    from research.zone_rebound import xau_m5_mss_direction_r6 as r6
    m1=validate_m1(xau)
    p=FIXED_POLICIES[horizon]
    m5=completed_bars(m1,5)
    e=r6._decorations(m1,r6._events(m5,p['mode'],p['confirmation']))
    e=r6._gate(e,p['gate'],p['session'])
    e=r6._cooldown(e,horizon)
    if len(e):
        years=pd.to_datetime(e.entry_ns,utc=True).dt.year
        e=e.loc[years==year]
    return r6._attach_outcome(m1,e,horizon)

def macro_at_events(usd,events,delay_minutes=1,max_quote_age_minutes=5,source_contract='R8_USD_ORIGINAL_BI5_M1_V1'):
    """Observed M1 prices; explicit fixed assumed latency and actual bar-close quote age.

    Output is NEVER a claim of true historical first_seen_at.
    """
    from research.zone_rebound.xau_r7_macro_asof import normalize_quote_m1,_known_returns
    if delay_minutes<0 or max_quote_age_minutes<0:raise ValueError('INVALID_DELAY_OR_AGE')
    if events.entry_ns.duplicated().any():raise ValueError('DUPLICATE_EVENT')
    if events.empty:
        return pd.DataFrame(columns=['entry_ns','macro_ready','quote_age_minutes',
                'return_5m_pct','return_15m_pct','return_60m_pct'])
    if source_contract=='R8_USD_ORIGINAL_BI5_M1_V1':
        m=normalize_quote_m1(usd,PROXY_ID)
    elif source_contract=='R8_RECONSTRUCTED_DXY_6FX_HISTDATA_V1':
        if not {'timestamp','open','high','low','close'}.issubset(usd):raise ValueError('FX6_REQUIRED_COLUMNS')
        if not usd.timestamp.astype(str).str.endswith(('Z','+00:00')).all():raise ValueError('FX6_UTC_REQUIRED')
        stamps=pd.to_datetime(usd.timestamp,utc=True,errors='raise')
        if stamps.duplicated().any() or not stamps.is_monotonic_increasing:raise ValueError('FX6_BAD_TIMESTAMP')
        m=usd[['open','high','low','close']].astype('float64')
        if not np.isfinite(m.to_numpy()).all() or (m.low<=0).any():raise ValueError('FX6_BAD_PRICE')
        if (m.high < m[['open','close']].max(axis=1)).any() or (m.low>m[['open','close']].min(axis=1)).any():
            raise ValueError('FX6_BAD_PRICE_GEOMETRY')
        m.index=pd.DatetimeIndex(stamps)
    else:raise ValueError('UNKNOWN_MACRO_SOURCE')
    r=_known_returns(m)
    r['bar_close_ns']=m.index.asi8+MINUTE_NS
    r['assumed_available_ns']=r.bar_close_ns+delay_minutes*MINUTE_NS
    r=r.sort_values('assumed_available_ns').reset_index(drop=True)
    e=events[['entry_ns']].reset_index(drop=True).sort_values('entry_ns')
    joined=pd.merge_asof(e,r,left_on='entry_ns',right_on='assumed_available_ns',direction='backward')
    quote_age=(joined.entry_ns-joined.bar_close_ns)/MINUTE_NS
    available_age=(joined.entry_ns-joined.assumed_available_ns)/MINUTE_NS
    ready=(quote_age>=0)&(quote_age<=max_quote_age_minutes)&(available_age>=0)
    ready &= joined[[f'return_{i}m_pct' for i in (5,15,60)]].notna().all(axis=1)
    z=pd.DataFrame({'entry_ns':joined.entry_ns,'macro_ready':ready.fillna(False),
                    'quote_age_minutes':quote_age})
    for mnt in (5,15,60):
        col=f'return_{mnt}m_pct'
        z[col]=joined[col].where(ready)
    return z

def evaluate_events(events,macro,year,horizon,delay_minutes):
    """Only complete R6 future labels; outcomes signed price move BEFORE cost."""
    if events.empty:
        event_cols=['entry_ns','side','complete','delta']
        events=pd.DataFrame(columns=event_cols)
    q=events.iloc[0:0].copy() if events.empty else events.loc[events.complete].copy()
    if q.empty:q=q.assign(macro_ready=pd.Series(dtype=bool),quote_age_minutes=pd.Series(dtype=float))
    else:q=q.merge(macro,on='entry_ns',how='left',validate='one_to_one')
    for mnt in (5,15,60):
        col=f'return_{mnt}m_pct'
        if col not in q:q[col]=pd.Series(dtype=float)
    if 'macro_ready' not in q:q['macro_ready']=False
    q['macro_ready']=q['macro_ready'].fillna(False)
    x=q.side.to_numpy()[:,None]*q[[f'return_{m}m_pct' for m in (5,15,60)]].to_numpy(dtype=float)
    aligned=(x<0);opposed=(x>0)
    masks={
        'BASE_R6':np.ones(len(q),dtype=bool),
        'DXY_AVAILABLE':q.macro_ready.to_numpy(),
        'DXY_15_AND_60_ALIGNED':q.macro_ready.to_numpy()&aligned[:,1]&aligned[:,2],
        'DXY_15_AND_60_OPPOSED':q.macro_ready.to_numpy()&opposed[:,1]&opposed[:,2],
        'DXY_5M_ALIGNED':q.macro_ready.to_numpy()&aligned[:,0],
        'DXY_2_OF_3_ALIGNED':q.macro_ready.to_numpy()&(aligned.sum(axis=1)>=2),
        'DXY_3_OF_3_ALIGNED':q.macro_ready.to_numpy()&aligned.all(axis=1),
    }
    res=[]
    for side,name in ((1,'BUY'),(-1,'SELL')):
        for cohort,mask in masks.items():
            sel=q.loc[(q.side.to_numpy()==side)&mask]
            n=int(len(sel));win=int((sel.delta>COST_USD_OZ).sum())
            res.append({'year':year,'horizon':horizon,'side':name,'assumed_delay_min':delay_minutes,
                        'cohort':cohort,'n':n,'wins':win,'accuracy':win/n if n else None,
                        'wilson95_lower':wilson(win,n)})
    return res

def replay_one_year(xau_csv,xau_manifest,usd_csv,usd_manifest,year):
    xau,usd,xp,up=load_verified(*map(Path,(xau_csv,xau_manifest,usd_csv,usd_manifest)),year)
    rows=[];diag=[]
    for horizon in (60,240):
        events=make_r6_events(xau,year,horizon)
        diag.append({'horizon':horizon,'total_events':int(len(events)),
                     'full_future_path':int(events.complete.sum()),'invalid_future_path':int((~events.complete).sum())})
        valid=events.loc[events.complete]
        for delay in ASSUMED_DELAY_MINUTES:
            macro=macro_at_events(usd,valid,delay_minutes=delay,max_quote_age_minutes=MAX_QUOTE_AGE_MINUTES,source_contract=up['contract'])
            rows.extend(evaluate_events(events,macro,year,horizon,delay))
    return {'contract':'RIZAN_R8_HISTORICAL_CONDITIONAL_ABLATION_V1','year':year,
            'xau_sha256':xp['normalized_csv_sha256'],'usd_sha256':up['csv_sha256'],
            'usd_days_ok':up.get('days_ok'),'usd_missing_weekdays':up.get('missing_weekdays'),
            'macro_source_contract':up['contract'],'macro_instrument':up['instrument'],
            'availability_status':'HISTORICAL_FIRST_SEEN_UNVERIFIED_ASSUMED_LAG_SENSITIVITY_ONLY',
            'horizon_diagnostics':diag,'results':rows,'execution_authority':False,'execution_influence':False}

def aggregate(shards):
    data=[json.loads(Path(p).read_text()) for p in shards]
    if len(data)!=8 or set(x['year'] for x in data)!=set(range(2019,2027)):
        raise ValueError('EIGHT_YEAR_SHARDS_REQUIRED')
    if any(x['contract']!='RIZAN_R8_HISTORICAL_CONDITIONAL_ABLATION_V1' for x in data):
        raise ValueError('INVALID_SHARD_CONTRACT')
    source_ids={x.get('macro_source_contract') for x in data}
    if len(source_ids)!=1 or None in source_ids:raise ValueError('MIXED_OR_UNKNOWN_MACRO_SOURCE')
    rows=pd.DataFrame([r for shard in data for r in shard['results']])
    result=[]
    for (h,side,lag,cohort),g in rows.groupby(['horizon','side','assumed_delay_min','cohort'],sort=True):
        for period,years in (('train_2019_2023',range(2019,2024)),('validation_2024',[2024]),
                             ('reused_test_2025_2026',[2025,2026]),('all_2019_2026',range(2019,2027))):
            s=g[g.year.isin(years)];n=int(s.n.sum());w=int(s.wins.sum())
            result.append({'horizon':int(h),'side':side,'assumed_delay_min':int(lag),
                           'cohort':cohort,'split':period,'n':n,'wins':w,
                           'accuracy':w/n if n else None,'wilson95_lower':wilson(w,n)})
    return {'contract':'RIZAN_R8_HISTORICAL_CONDITIONAL_AGGREGATE_V1',
            'years':list(range(2019,2027)),'cost_scenario_usd_oz':COST_USD_OZ,
            'locked_R6_policies':FIXED_POLICIES,
            'macro_source_contract':next(iter(source_ids)),
            'first_seen_provenance':'UNVERIFIED_HISTORIC_VENDOR_AVAILABILITY; CANNOT CLAIM REAL POINT_IN_TIME',
            'evaluation_warning':'2025-2026 repeatedly inspected, NOT pristine project holdout. No calibration on it.',
            'execution_authority':False,'execution_influence':False,
            'per_year':json.loads(rows.to_json(orient='records')),'summary':result}

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--xau-csv',type=Path);a.add_argument('--xau-manifest',type=Path)
    a.add_argument('--usd-csv',type=Path);a.add_argument('--usd-manifest',type=Path)
    a.add_argument('--year',type=int);a.add_argument('--shards',nargs='*',type=Path)
    a.add_argument('--out',type=Path,required=True)
    x=a.parse_args()
    if x.shards is not None:report=aggregate(x.shards)
    else:
        if not (x.xau_csv and x.xau_manifest and x.usd_csv and x.usd_manifest and x.year):
            a.error('year and all 4 source paths are required')
        report=replay_one_year(x.xau_csv,x.xau_manifest,x.usd_csv,x.usd_manifest,x.year)
    x.out.parent.mkdir(parents=True,exist_ok=True)
    x.out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('R8_REPLAY',json.dumps({k:v for k,v in report.items() if k in ('contract','year','years','horizon_diagnostics')},default=str))
if __name__=='__main__':main()
