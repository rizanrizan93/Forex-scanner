"""R5: genuine DXY plus cash-yield inputs for zone replay; no FX substitution.

Point data schema is explicit about observation time AND availability time.
Intraday gates never substitute daily releases, bond prices or yield futures.
"""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd

MIN=60_000_000_000
MACROS=['NONE','DXY_ONLY','DXY_US10Y','DXY_BOTH_YIELDS','DXY_TURN_US10Y']
KINDS={'DXY':{'CASH_INDEX','INDEX_CFD'},'US10Y':{'CASH_YIELD','YIELD_INDEX'},'US2Y':{'CASH_YIELD','YIELD_INDEX'}}
SOURCES={'DXY':{'ICE_DXY','YAHOO_DXY_INDEX','CNBC_DXY','BROKER_DXY_CFD'},'US10Y':{'YAHOO_TNX_YIELD_INDEX','CNBC_TRADEWEB','TIMESTAMPED_CASH_YIELD'},'US2Y':{'CNBC_TRADEWEB','TIMESTAMPED_CASH_YIELD'}}
REQUIRED=['observed_at','available_at','value','series','unit','instrument_kind','source','frequency','time_basis']

def validate_points(frame,series):
    if series not in KINDS:raise ValueError('Unsupported series')
    if not set(REQUIRED)<=set(frame):raise ValueError('Missing timestamp/source/type/unit metadata')
    f=frame.copy()
    if f.empty:return f
    if set(f.series)!={series}:raise ValueError('Series mismatch; no EUR or synthetic-USD substitution')
    if not set(f.source)<=SOURCES[series]:raise ValueError('Unapproved source for this series')
    if not set(f.instrument_kind)<=KINDS[series]:raise ValueError('Cash index/yield required; futures rejected')
    if set(f.frequency)!={'INTRADAY'}:raise ValueError('Daily data is context, not an intraday trigger')
    unit='INDEX_POINTS' if series=='DXY' else 'PERCENT'
    if set(f.unit)!={unit}:raise ValueError('Explicit index-point/percent units required')
    for col in ['observed_at','available_at']:
        if not f[col].astype(str).str.contains(r'(?:Z|[+-]\d\d:\d\d)$',regex=True).all():raise ValueError('Timezone-aware timestamps required')
        f[col]=pd.to_datetime(f[col],utc=True)
    f['value']=pd.to_numeric(f.value,errors='raise')
    if not np.isfinite(f.value).all():raise ValueError('Nonfinite values')
    if series=='DXY' and not f.value.between(1,1000).all():raise ValueError('Invalid DXY level')
    if series!='DXY' and not f.value.between(-10,40).all():raise ValueError('Invalid yield percent; do not silently rescale')
    if (f.available_at<f.observed_at).any():raise ValueError('Availability predates observation')
    if not set(f.time_basis)<={'OBSERVED_INGEST','BAR_CLOSE_PLUS_60S_ASSUMED'}:raise ValueError('Unknown availability convention')
    f=f.sort_values(['available_at','observed_at'],kind='stable').reset_index(drop=True)
    if f.available_at.duplicated().any():raise ValueError('Conflicting publication timestamps')
    # A late old quote cannot overwrite a newer observation already received.
    obs=f.observed_at.array.asi8;f=f.loc[obs>=np.maximum.accumulate(obs)].reset_index(drop=True)
    return f

def normalize_yahoo(payload,series,*,fetched_at):
    """Cache closed 5m bars. Historical latency is assumed, never certified PIT."""
    expected={'DXY':'DX-Y.NYB','US10Y':'^TNX'}
    if series not in expected:raise ValueError('No Yahoo US2Y substitute is allowed')
    chart=payload.get('chart') or {};results=chart.get('result') or []
    if chart.get('error') or len(results)!=1:raise ValueError('Invalid Yahoo chart')
    q=results[0];meta=q.get('meta') or {}
    if meta.get('symbol')!=expected[series] or meta.get('dataGranularity')!='5m' or meta.get('instrumentType')!='INDEX':raise ValueError('Wrong symbol, frequency or instrument type')
    closes=((q.get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
    fetched=pd.Timestamp(fetched_at)
    if fetched.tzinfo is None:raise ValueError('Fetch time requires timezone')
    if meta.get('regularMarketTime') is not None:
        fetched=min(fetched,pd.Timestamp(int(meta['regularMarketTime']),unit='s',tz='UTC'))
    rows=[]
    for epoch,value in zip(q.get('timestamp') or [],closes):
        if value is None or int(epoch)%300:continue  # Exclude Yahoo's appended partial snapshot.
        end=pd.Timestamp(int(epoch),unit='s',tz='UTC')+pd.Timedelta(minutes=5)
        if end>fetched:continue
        rows.append(dict(observed_at=end.isoformat(),available_at=(end+pd.Timedelta(seconds=60)).isoformat(),value=float(value),series=series,unit='INDEX_POINTS' if series=='DXY' else 'PERCENT',instrument_kind='CASH_INDEX' if series=='DXY' else 'YIELD_INDEX',source='YAHOO_DXY_INDEX' if series=='DXY' else 'YAHOO_TNX_YIELD_INDEX',frequency='INTRADAY',time_basis='BAR_CLOSE_PLUS_60S_ASSUMED'))
    return validate_points(pd.DataFrame(rows,columns=REQUIRED),series)

def series_features(times,frame,series,*,max_age_minutes=10):
    f=validate_points(frame,series);times=np.asarray(times,dtype=np.int64);n=len(times)
    out={f'{series}_fresh':np.zeros(n,bool),f'{series}_observed_ns':np.full(n,np.nan),f'{series}_available_ns':np.full(n,np.nan)}
    for look in (15,60):out[f'{series}_{look}']=np.full(n,np.nan)
    if f.empty:return out
    at=f.available_at.array.asi8;ot=f.observed_at.array.asi8;v=f.value.to_numpy();j=np.searchsorted(at,times,side='right')-1;safe=np.maximum(j,0)
    valid=(j>=0)&(times-ot[safe]>=0)&(times-ot[safe]<=max_age_minutes*MIN)
    out[f'{series}_fresh']=valid;out[f'{series}_observed_ns']=np.where(valid,ot[safe],np.nan);out[f'{series}_available_ns']=np.where(valid,at[safe],np.nan)
    for look in (15,60):
        wanted=times-look*MIN;k=np.searchsorted(at,wanted,side='right')-1;ks=np.maximum(k,0)
        ok=valid&(k>=0)&(wanted-ot[ks]>=0)&(wanted-ot[ks]<=max_age_minutes*MIN)&(np.abs((ot[safe]-ot[ks])-look*MIN)<=5*MIN)
        change=(v[safe]/v[ks]-1)*100 if series=='DXY' else (v[safe]-v[ks])*100
        out[f'{series}_{look}']=np.where(ok,change,np.nan)
    return out

def macro_fields(times,dxy,us10y,us2y=None):
    out={}
    for name,frame in [('DXY',dxy),('US10Y',us10y),('US2Y',us2y)]:
        if frame is None:frame=pd.DataFrame(columns=REQUIRED)
        out.update(series_features(times,frame,name))
    skew=np.abs(out['DXY_observed_ns']-out['US10Y_observed_ns'])
    out['common_fresh']=out['DXY_fresh']&out['US10Y_fresh']&(skew<=5*MIN)&np.isfinite(out['DXY_15'])&np.isfinite(out['US10Y_15'])
    return out

def macro_mask(name,fields,side=1):
    """Starting hypotheses, not calibrated probabilities: DXY0.01%, yield0.5bp."""
    s=np.asarray(side);base=np.asarray(fields['common_fresh'],bool)
    if name=='NONE':return base.copy()  # All controls use the same common-source coverage.
    dx=-s*fields['DXY_15'];y10=-s*fields['US10Y_15']
    if name=='DXY_ONLY':return base&(dx>=.01)
    if name=='DXY_US10Y':return base&(dx>=.01)&(y10>=.5)
    if name=='DXY_BOTH_YIELDS':
        skew=np.abs(fields['US2Y_observed_ns']-fields['DXY_observed_ns'])
        return base&fields['US2Y_fresh']&(skew<=5*MIN)&(dx>=.01)&(y10>=.5)&(-s*fields['US2Y_15']>=.5)
    if name=='DXY_TURN_US10Y':return base&(dx>=.01)&(y10>=.5)&(-s*fields['DXY_60']<=-.01)
    raise ValueError('Unknown DXY/yield rule; legacy EUR rules are not accepted')

def preflight(touch,dxy,us10y,us2y=None):
    times=touch.time_ns.to_numpy(dtype=np.int64);fields=macro_fields(times,dxy,us10y,us2y)
    count=int(fields['common_fresh'].sum());window=fields['common_fresh'].copy()
    if len(times) and not dxy.empty and not us10y.empty:
        first=max(pd.to_datetime(dxy.available_at,utc=True).min().value,pd.to_datetime(us10y.available_at,utc=True).min().value)
        last=min(pd.to_datetime(dxy.observed_at,utc=True).max().value,pd.to_datetime(us10y.observed_at,utc=True).max().value)+10*MIN
        near=(times+15*MIN>=first)&(times<=last)
        for step in range(1,16):
            if near.any():window[near] |= macro_fields(times[near]+step*MIN,dxy,us10y,us2y)['common_fresh']
    def span(f):
        return None if f is None or f.empty else {'first_observed':str(f.observed_at.min()),'last_observed':str(f.observed_at.max()),'rows':len(f),'time_basis':sorted(set(f.time_basis))}
    return {'contract':'RIZAN_ZONE_DXY_YIELD_R5','status':'COMMON_INTRADAY_DATA_PRESENT' if window.any() else 'NEED_MATCHED_INTRADAY_HISTORY','touch_rows':len(touch),'touch_first':str(pd.Timestamp(int(times.min()),tz='UTC')) if len(times) else None,'touch_last':str(pd.Timestamp(int(times.max()),tz='UTC')) if len(times) else None,'common_fresh_at_touch':count,'common_fresh_in_15m_window':int(window.sum()),'DXY':span(dxy),'US10Y':span(us10y),'US2Y':span(us2y),'allowed_macro':['DXY','US10Y','US2Y_OPTIONAL'],'real_yield_10y':'DAILY_CONTEXT_ONLY_NOT_INTRADAY_REPLACEMENT','eur_or_synthetic_fallback':False,'accuracy_computed':False,'note':'Preflight tests only source coverage at touch and during the next15min, not price outcomes. Bar-close+60s timing is assumed, not certified point-in-time. No replay success rate is inferred from coverage.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dxy',type=Path,required=True);p.add_argument('--us10y',type=Path,required=True);p.add_argument('--us2y',type=Path);p.add_argument('--touches',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--xau',type=Path);p.add_argument('--replay',action='store_true');args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    dx=validate_points(pd.read_csv(args.dxy),'DXY');y10=validate_points(pd.read_csv(args.us10y),'US10Y');y2=validate_points(pd.read_csv(args.us2y),'US2Y') if args.us2y else None
    q=pd.read_csv(args.touches);q=q[q['mode']=='TOUCH'].copy() if 'mode' in q else q
    q=q[['family','tf','side','pub_ns','lo','hi','i','time_ns','reference','atr_h1']].copy()
    result=preflight(q,dx,y10,y2);result['input_sha256']={k:hashlib.sha256(path.read_bytes()).hexdigest() for k,path in [('dxy',args.dxy),('us10y',args.us10y),('touches',args.touches)]};(args.out/'preflight.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    if not args.replay:return
    if not result['common_fresh_in_15m_window']:raise SystemExit('Replay blocked: matched DXY and cash-yield intraday history is missing')
    if args.xau is None or not args.xau.is_file():raise SystemExit('Replay requires the archived XAUUSD bid M1 data')
    from research.zone_rebound.r5_entry_core import entry_events,context_events,outcomes,select,metric
    d=pd.read_csv(args.xau,usecols=['timestamp','open','high','low','close','spread']);d.index=pd.to_datetime(d.pop('timestamp'),utc=True)
    if not d.index.is_monotonic_increasing or d.index.has_duplicates:raise ValueError('Invalid XAU time index')
    if (q.i.to_numpy(dtype=int)>=len(d)).any() or not (d.index.asi8[q.i.to_numpy(dtype=int)]==q.time_ns.to_numpy()).all():raise ValueError('Touch ledger and XAU input do not match')
    fields=macro_fields(d.index.asi8,dx,y10,y2);e=entry_events(d,q,fields,macros=MACROS,mask_fn=macro_mask)
    if e.empty:raise SystemExit('No qualifying zone reactions on common data coverage')
    e=context_events(d,e)
    for k,v in outcomes(d,e).items():e[k]=v
    cost=outcomes(d,e,cost=True)
    for k in (3,10):e[f'state{k}_spread']=cost[f'state{k}']
    e.to_csv(args.out/'entries.csv.gz',index=False);summary=[]
    for keys,g in e.groupby(['family','tf','side','trigger','macro']):
        g=g.sort_values('time_ns',kind='stable').reset_index(drop=True);ids=select(g,np.ones(len(g),bool));yr=g.year.to_numpy()
        rule=dict(zip(['family','tf','side','trigger','macro'],keys));rule['tf']=int(rule['tf']);rule['side']=int(rule['side'])
        summary.append({'rule':rule,'annual':{str(y):metric(g,ids[yr[ids]==y]) for y in sorted(set(yr))}})
    (args.out/'replay.json').write_text(json.dumps(summary,indent=2,allow_nan=False))

if __name__=='__main__':main()
