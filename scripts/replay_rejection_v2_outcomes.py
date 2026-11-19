"""Audit historical price *after* V2 rejection signals; read-only, research only.

Results from reconstructed historical M1 and hypothetical bid/ask ($0.50 spread)
are ONLY entry proxies, NEVER verified live emitted signals or executable fills.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, UTC
from pathlib import Path
import argparse, hashlib, json
import numpy as np
import pandas as pd
from fx_scanner.rejection_v2_research import calculate

COST=0.50  # approximate round-trip spread, USD per ounce
COOLDOWN_MIN=60

def load_csv(path):
    d=pd.read_csv(path)
    if not {'timestamp','open','high','low','close'}.issubset(d):
        raise ValueError('CSV_MISSING_COLUMNS')
    s=d['timestamp'].astype(str)
    if not s.str.contains(r'(?:Z|[+-][0-9]{2}:[0-9]{2})$',regex=True).all():
        raise ValueError('UTC_OFFSET_REQUIRED')
    d.index=pd.to_datetime(d.pop('timestamp'),utc=True,errors='raise')
    return d

def load_public():
    from fx_scanner.manual_r3_feed import fetch_market
    p=fetch_market(now=datetime.now(UTC))
    return p['frame'], {'source':'CTRADER_MARKET_DATA_READ_ONLY',
                         'publication_at':str(p['as_of'])}

def future(d,i,side,horizon,target,adverse):
    """One-minute barrier order; simultaneous barrier touch is adverse first."""
    if i+horizon>=len(d):return None
    path=d.iloc[i+1:i+1+horizon]
    if len(path)!=horizon or path.index[0]!=d.index[i]+pd.Timedelta(minutes=1):
        return None
    if not (path.index.to_series().diff().iloc[1:]==pd.Timedelta(minutes=1)).all():
        return None
    entry=float(path.open.iloc[0])
    sg=1 if side=='BUY' else -1
    favorable=(path.high.to_numpy()-entry if sg==1 else entry-path.low.to_numpy())
    against=(entry-path.low.to_numpy() if sg==1 else path.high.to_numpy()-entry)
    fa=np.flatnonzero(favorable>=target+COST)
    aa=np.flatnonzero(against>=adverse)
    f=int(fa[0]) if len(fa) else horizon
    a=int(aa[0]) if len(aa) else horizon
    state='TARGET_FIRST' if f<a and f<horizon else (
        'ADVERSE_FIRST' if a<=f and a<horizon else 'NEITHER')
    return {'state':state,'net_end':float(sg*(float(path.close.iloc[-1])-entry)-COST),
            'mfe':float(max(0,favorable.max()-COST)),
            'mae':float(against.max()),
            'minutes_to_target':f+1 if f<horizon else None}

def wilson(w,n):
    if not n:return [None,None]
    z=1.96;p=w/n;factor=1+z*z/n
    c=(p+z*z/(2*n))/factor
    h=z*np.sqrt((p*(1-p)+z*z/(4*n))/n)/factor
    return [round(float((c-h)*100),2),round(float((c+h)*100),2)]

def stats(events):
    output={}
    for category in ['EARLY_ENTRY_PROXY','RETEST_ENTRY_PROXY','EARLY_WICK_ONLY','ZONE_TOUCH_BASELINE']:
        output[category]={}
        for side in ('BUY','SELL'):
            r=[v for v in events if v['category']==category and v['side']==side]
            n=len(r)
            if not n:
                output[category][side]={'n':0,'H1_direction_pct':None,'H4_direction_pct':None,
                    '3usd_before_3usd_H1_pct':None,'5usd_before_3usd_H1_pct':None,
                    '10usd_before_5usd_H4_pct':None,'wilson95_3usd_pct':[None,None]}
                continue
            n3=sum(e['x3']['state']=='TARGET_FIRST' for e in r)
            output[category][side]={'n':n,
                'H1_direction_pct':round(100*sum(e['x3']['net_end']>0 for e in r)/n,2),
                'H4_direction_pct':round(100*sum(e['x10']['net_end']>0 for e in r)/n,2),
                '3usd_before_3usd_H1_pct':round(100*n3/n,2),
                '5usd_before_3usd_H1_pct':round(100*sum(e['x5']['state']=='TARGET_FIRST' for e in r)/n,2),
                '10usd_before_5usd_H4_pct':round(100*sum(e['x10']['state']=='TARGET_FIRST' for e in r)/n,2),
                'wilson95_3usd_pct':wilson(n3,n),
                'median_mfe60_usd':round(float(np.median([e['x3']['mfe'] for e in r])),2),
                'median_mae60_usd':round(float(np.median([e['x3']['mae'] for e in r])),2)}
    return output

def replay(raw,provenance,limit=6000,start=6100):
    d=raw[['open','high','low','close']].copy()
    if not isinstance(d.index,pd.DatetimeIndex) or d.index.tz is None or d.index.has_duplicates or not d.index.is_monotonic_increasing:
        raise ValueError('BAD_TIMESTAMPS')
    for c in ('open','high','low','close'):
        d[c]=pd.to_numeric(d[c],errors='raise')
    if not np.isfinite(d.to_numpy()).all():
        raise ValueError('BAD_OHLC')
    digest=hashlib.sha256(d.to_csv(float_format='%.6f').encode()).hexdigest()
    end=min(len(d)-241,start+limit)
    if end<=start:
        return {'source':provenance,'input_rows':len(d),'normalized_sha256':digest,
                'evaluated_closes':0,'reason':'NOT_ENOUGH_HISTORY_FOR_H4_AND_FORWARD_LABEL',
                'results':stats([])}
    events=[];counts=Counter();last={}
    for i in range(start,end):
        now=d.index[i]+pd.Timedelta(minutes=1)
        row=d.iloc[i]
        # Every M1 close is examined: do not skip non-wick bars (retest and baseline).
        if row.high<=row.low:continue
        try:
            r=calculate(d.iloc[:i+1],now=now,
                        bid=float(row.close)-COST/2,ask=float(row.close)+COST/2,
                        quote_at=now)
        except (ValueError,TypeError,KeyError):
            counts['state_unavailable']+=1;continue
        counts['evaluated_closes']+=1
        for side in ('BUY','SELL'):
            z=[p for p in r['zones'] if p['side']==side]
            if any(p['entry']=='EARLY ENTRY CANDIDATE' for p in z):
                cat='EARLY_ENTRY_PROXY'
            elif any(p['entry']=='RETEST RECLAIM CANDIDATE' for p in z):
                cat='RETEST_ENTRY_PROXY'
            elif any(p['stage']=='EARLY REJECTION' for p in z):
                cat='EARLY_WICK_ONLY'
            elif any(p['stage']=='TOUCHED; WAIT REACTION' for p in z):
                cat='ZONE_TOUCH_BASELINE'
            else:continue
            counts['detected_'+cat+'_'+side]+=1
            if (cat,side) in last and (now-last[(cat,side)]).total_seconds()<COOLDOWN_MIN*60:
                counts['cooldown_skip']+=1;continue
            x3=future(d,i,side,60,3,3)
            x5=future(d,i,side,60,5,3)
            x10=future(d,i,side,240,10,5)
            if x3 is None or x5 is None or x10 is None:
                counts['censored_incomplete_future']+=1;continue
            events.append({'at_utc':now.isoformat(),'side':side,'category':cat,
                           'h1_bias':r['h1_bias'],'h4_bias':r['h4_bias'],
                           'x3':x3,'x5':x5,'x10':x10})
            last[(cat,side)]=now
    return {'contract':'RIZAN_REJECTION_V2_FUTURE_REVERSAL_REPLAY_V1',
            'source':provenance,'normalized_sha256':digest,'input_rows':len(d),
            'first_utc':d.index[0].isoformat(),'last_utc':d.index[-1].isoformat(),
            'screened_span':[d.index[start].isoformat(),d.index[end-1].isoformat()],
            'evaluated_closes':counts['evaluated_closes'],
            'spread_assumed_usd_oz':COST,'cooldown_minutes':COOLDOWN_MIN,
            'results':stats(events),'counters':dict(counts),'events':events,
            'limitations':['Hypothetical bid/ask only: no historical quote/spread verification',
                'One-minute same-bar barrier ambiguity counted against target',
                'Historical reconstructed signals, not archived scanner emissions',
                'Sample chosen for falsification, NOT pristine holdout',
                'No historical win-rate claim for LIVE or automatic deployment']}
    
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',choices=['public','csv'],required=True)
    p.add_argument('--csv',type=Path)
    p.add_argument('--limit',type=int,default=6000)
    p.add_argument('--start',type=int,default=6100)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.source=='public':
        d,prov=load_public()
    else:
        if a.csv is None:p.error('--csv is required')
        d=load_csv(a.csv)
        prov={'source':'USER_PROVIDED_HISTORICAL_XAUUSD_M1'}
        manifest=Path(str(a.csv)+'.provenance.json')
        if manifest.exists():
            prov=json.loads(manifest.read_text())
            actual=hashlib.sha256(a.csv.read_bytes()).hexdigest()
            if prov.get('sha256_csv')!=actual or prov.get('failed_periods'):
                raise ValueError('SOURCE_PROVENANCE_SHA_OR_FAILED_PERIODS')
    result=replay(d,prov,start=a.start,limit=a.limit)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print('REJECTION_REPLAY_SUMMARY',json.dumps({k:v for k,v in result.items() if k!='events'},allow_nan=False))
if __name__=='__main__':main()
