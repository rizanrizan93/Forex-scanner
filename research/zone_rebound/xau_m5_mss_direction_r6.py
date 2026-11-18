"""RIZAN R6: M5 stop-run/reclaim + optional market-structure-shift, H1/H4 direction.

PUBLIC HISTDATA RESEARCH ONLY; no cTrader, orders, bridge, live signals.
M5 candles stamped at *right-edge* completion. A forecast enters next M1 OPEN
at the M5 close timestamp and measures the following 60 or 240 full minutes.
"""
from __future__ import annotations
import hashlib, json
import numpy as np
import pandas as pd
from research.zone_rebound.h1h4_direction_r1 import validate_m1, completed_bars, MINUTE_NS

CONTRACT = 'RIZAN_XAU_M5_SWEEP_MSS_R6'
SOURCE = 'HISTDATA_XAUUSD_M1_PUBLIC_NOT_FP_MARKETS'
COST_SCENARIO = 0.50
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
MODES = ('SWEEP12','SWEEP36','PREVIOUS_DAY')
CONFIRMS = ('RECLAIM_CLOSE','MSS3')
GATES = ('NONE','H4_ALIGN','H4_COUNTER')
SESSIONS = ('ALL','ASIA','LONDON','NEW_YORK')
HORIZONS = (60,240)

def policies():
    return [dict(mode=m,confirmation=c,gate=g,session=s)
            for m in MODES for c in CONFIRMS for g in GATES for s in SESSIONS]

def policy_key(p):
    return '|'.join((p['mode'],p['confirmation'],p['gate'],p['session']))

def _wicks(m):
    span=(m.high-m.low).replace(0,np.nan)
    up=(m.high-pd.concat([m.open,m.close],axis=1).max(axis=1))/span
    lo=(pd.concat([m.open,m.close],axis=1).min(axis=1)-m.low)/span
    return up,lo

def _previous_day(m):
    # Calendar UTC *completed previous observed trading day*, never current-day high/low.
    dates=m.index.floor('D')
    daily=m.groupby(dates).agg({'high':'max','low':'min','close':'count'})
    prev=daily.shift(1).reindex(dates)
    prev.index=m.index
    ready=prev['close']>=100
    return prev['high'].where(ready),prev['low'].where(ready)

def _sweep_masks(m,mode):
    up,lo=_wicks(m)
    tr=pd.concat([m.high-m.low,(m.high-m.close.shift(1)).abs(),
                  (m.low-m.close.shift(1)).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    if mode=='PREVIOUS_DAY':
        refhi,reflo=_previous_day(m)
        continuity=pd.Series(True,index=m.index)
    else:
        n=12 if mode=='SWEEP12' else 36
        refhi=m.high.shift(1).rolling(n,min_periods=n).max()
        reflo=m.low.shift(1).rolling(n,min_periods=n).min()
        previous=pd.Series(m.index,index=m.index).shift(n)
        continuity=(pd.Series(m.index,index=m.index)-previous).dt.total_seconds().eq(n*300)
    buy=(m.low<reflo-.04*atr)&(m.close>reflo+.04*atr)&(lo>=.25)&continuity
    sell=(m.high>refhi+.04*atr)&(m.close<refhi-.04*atr)&(up>=.25)&continuity
    return buy.fillna(False).to_numpy(),sell.fillna(False).to_numpy()

def _events(m,mode,confirmation):
    buy,sell=_sweep_masks(m,mode)
    t=m.index.asi8
    rows=[]
    prior3hi=m.high.shift(1).rolling(3,min_periods=3).max().to_numpy()
    prior3lo=m.low.shift(1).rolling(3,min_periods=3).min().to_numpy()
    closes=m.close.to_numpy()
    for direction,mask in ((1,buy),(-1,sell)):
        for i in np.flatnonzero(mask):
            j=i
            if confirmation=='MSS3':
                j=-1
                for k in range(i+1,min(i+4,len(m))):
                    if t[k]-t[i] != (k-i)*5*MINUTE_NS:break
                    # Market structure break confirmed ONLY at this M5 close.
                    condition=closes[k]>prior3hi[i] if direction==1 else closes[k]<prior3lo[i]
                    if condition:
                        j=k;break
                if j<0:continue
            rows.append((int(t[j]),direction,int(t[i])))
    if not rows:
        return pd.DataFrame(columns=['entry_ns','side','sweep_ns'])
    z=pd.DataFrame(rows,columns=['entry_ns','side','sweep_ns'])
    # If both directions request the same instant, it is intrinsically ambiguous: WAIT.
    nside=z.groupby('entry_ns').side.transform('nunique')
    z=z.loc[nside==1].sort_values(['entry_ns','sweep_ns'])
    return z.drop_duplicates(['entry_ns','side'],keep='first').reset_index(drop=True)

def _context(m,events):
    if events.empty:return events
    h4=completed_bars(m,240) if False else None  # computed from M1 by caller
    return events

def _decorations(m1, events):
    if events.empty:return events
    h4=completed_bars(m1,240)
    ema=h4.close.ewm(span=20,adjust=False,min_periods=20).mean()
    atr=(h4.high-h4.low).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    slope=(ema-ema.shift(3))/atr.replace(0,np.nan)
    dev=(h4.close-ema)/atr.replace(0,np.nan)
    ref=pd.DataFrame({'h4_slope':slope,'h4_dev':dev},index=h4.index)
    times=pd.to_datetime(events.entry_ns,utc=True)
    aligned=ref.reindex(times,method='ffill')
    h4time=pd.Series(ref.index,index=ref.index).reindex(times,method='ffill')
    age=(pd.Series(times.to_numpy(),index=times)-h4time).dt.total_seconds()/3600
    z=events.copy()
    z['h4_slope']=aligned['h4_slope'].to_numpy()
    z['h4_dev']=aligned['h4_dev'].to_numpy()
    z['h4_valid']=(age<=8).to_numpy()
    hours=times.dt.tz_convert('Asia/Jakarta').dt.hour
    z['hour_wib']=hours.to_numpy()
    return z

def _gate(events,gate,session):
    if events.empty:return events
    sel=np.ones(len(events),dtype=bool)
    side=events.side.to_numpy()
    if gate!='NONE':
        alignment=((events.h4_slope.to_numpy()*side)>.05)&((events.h4_dev.to_numpy()*side)>0)
        if gate=='H4_ALIGN':sel &= alignment
        elif gate=='H4_COUNTER':
            sel &= ((events.h4_slope.to_numpy()*side)<-.05)&((events.h4_dev.to_numpy()*side)<0)
        else:raise ValueError('UNKNOWN_GATE')
        sel &= events.h4_valid.to_numpy(dtype=bool)
    h=events.hour_wib.to_numpy()
    if session=='ASIA':sel &= (h>=8)&(h<14)
    elif session=='LONDON':sel &= (h>=14)&(h<19)
    elif session=='NEW_YORK':sel &= (h>=19)|(h<1)
    elif session!='ALL':raise ValueError('UNKNOWN_SESSION')
    return events.loc[sel].copy()

def _cooldown(e,horizon):
    if e.empty:return e
    out=[];last=-10**25
    for i,(ts,side) in enumerate(zip(e.entry_ns.to_numpy(),e.side.to_numpy())):
        if ts-last>=horizon*MINUTE_NS:
            out.append(i);last=int(ts)
    return e.iloc[out].copy()

def _attach_outcome(m1,events,horizon):
    if events.empty:return events.assign(complete=pd.Series(dtype=bool),delta=pd.Series(dtype=float))
    timestamps=m1.index.asi8
    positions=np.searchsorted(timestamps,events.entry_ns.to_numpy())
    end=positions+horizon-1
    valid=(end<len(timestamps))&(positions<len(timestamps))
    start=np.minimum(positions,len(timestamps)-1);stop=np.minimum(end,len(timestamps)-1)
    valid &= timestamps[start]==events.entry_ns.to_numpy()
    valid &= timestamps[stop]==events.entry_ns.to_numpy()+(horizon-1)*MINUTE_NS
    # If the last minute is precisely horizon-1 minutes after the entry,
    # and there are exactly horizon distinct sorted indices, no interior gap exists.
    entry=m1.open.to_numpy()[start]
    exit_=m1.close.to_numpy()[stop]
    z=events.copy();z['complete']=valid
    z['delta']=np.where(valid,(exit_-entry)*z.side.to_numpy(),np.nan)
    return z

def replay_year(price:pd.DataFrame,year:int)->dict:
    if year not in range(2019,2027):raise ValueError('YEAR_OUT_OF_RANGE')
    m1=validate_m1(price)
    m5=completed_bars(m1,5)
    all_signals={}
    for mode in MODES:
        for confirm in CONFIRMS:
            all_signals[(mode,confirm)]=_decorations(m1,_events(m5,mode,confirm))
    metrics={}
    for p in policies():
        ev=all_signals[(p['mode'],p['confirmation'])]
        ev=_gate(ev,p['gate'],p['session'])
        for horizon in HORIZONS:
            selected=_cooldown(ev,horizon)
            entryyear=pd.to_datetime(selected.entry_ns,utc=True).dt.year if not selected.empty else pd.Series([],dtype=int)
            selected=selected.loc[entryyear==year]
            outcomes=_attach_outcome(m1,selected,horizon)
            counts={}
            for side,name in ((1,'BUY'),(-1,'SELL')):
                q=outcomes.loc[outcomes.side==side]
                valid=q.loc[q.complete]
                n=int(len(valid))
                wins=int((valid.delta>COST_SCENARIO).sum())
                counts[name]={'signals':int(len(q)),'evaluated':n,'gaps':int(len(q)-n),
                              'wins':wins,'wins_raw':int((valid.delta>0).sum()),
                              'direction_accuracy':wins/n if n else None}
            metrics.setdefault(policy_key(p),{})[str(horizon)]=counts
    return {'contract':CONTRACT,'year':year,'source':SOURCE,
            'price_rows':int(len(m1)),'m5_bars':int(len(m5)),
            'first_utc':m1.index[0].isoformat(),'last_utc':m1.index[-1].isoformat(),
            'assumed_cost_usd_oz':COST_SCENARIO,'execution_authority':False,
            'execution_influence':False,'policies':metrics}

def wilson(w,n,z=1.9599639845):
    if not n:return 0.
    p=w/n;zz=z*z
    return (p+zz/(2*n)-z*np.sqrt((p*(1-p)+zz/(4*n))/n))/(1+zz/n)

def aggregate(files):
    shards=[json.loads(x.read_text()) for x in files]
    if len(shards)!=8 or {r['year'] for r in shards}!=set(range(2019,2027)):
        raise ValueError('COMPLETE_2019_2026_SHARDS_REQUIRED')
    if any(r['contract']!=CONTRACT for r in shards):
        raise ValueError('SHARD_CONTRACT_MISMATCH')
    def collect(policy,tf,years):
        res={}
        for side in ('BUY','SELL'):
            n=sum(r['policies'][policy][str(tf)][side]['evaluated'] for r in shards if r['year'] in years)
            wins=sum(r['policies'][policy][str(tf)][side]['wins'] for r in shards if r['year'] in years)
            sent=sum(r['policies'][policy][str(tf)][side]['signals'] for r in shards if r['year'] in years)
            res[side]={'signals':sent,'n':n,'wins':wins,
                       'accuracy':wins/n if n else None,'wilson95_lower':wilson(wins,n)}
        return res
    result={}
    for tf in HORIZONS:
        ranking=[]
        for p in policies():
            key=policy_key(p)
            v=collect(key,tf,{2024})
            required=25 if tf==60 else 12
            eligible=all(v[s]['n']>=required for s in ('BUY','SELL'))
            score=min(v[s]['wilson95_lower'] for s in ('BUY','SELL')) if eligible else -1
            ranking.append({'key':key,'score':score,'eligible':eligible,'validation':v})
        ranking.sort(key=lambda x:(-x['score'],-min(x['validation'][s]['n'] for s in ('BUY','SELL')),x['key']))
        best=next((r for r in ranking if r['eligible']),None)
        if best is None:
            result[str(tf)]={'status':'NO_ELIGIBLE_POLICY','top_validation':ranking[:8]};continue
        key=best['key']
        test=collect(key,tf,{2025,2026})
        min_n=100 if tf==60 else 40
        pass60=(all(test[s]['n']>=min_n and test[s]['accuracy']>=.6 for s in ('BUY','SELL')))
        result[str(tf)]={'status':'RESEARCH_ONLY','chosen':key,
                         'train_2019_23':collect(key,tf,set(range(2019,2024))),
                         'validation_2024':best['validation'],
                         'test_2025_26':test,
                         'observed_both_sides_60pct':pass60,
                         'yearly':{str(y):collect(key,tf,{y}) for y in range(2019,2027)},
                         'validation_ranking':ranking}
    return {'contract':CONTRACT+'_AGGREGATE','years':list(range(2019,2027)),
            'source':SOURCE,'split':{'training':'2019-2023','selection':'2024','evaluation':'2025-2026'},
            'cost_scenario_usd_oz':COST_SCENARIO,'result':result,
            'warning':'2025-26 has already been inspected in previous research; NOT pristine project OOS. No broker fills. Results are experimental.',
            'execution_authority':False,'execution_influence':False}
