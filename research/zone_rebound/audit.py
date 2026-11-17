"""Frozen pre-touch zones, BUY/SELL rebound research. Never executes orders.

OHLC M1 conservative path: ignore favorable extremes on the touch candle;
adverse-first if both barriers occur in one subsequent candle. Zones and
context are frozen at publication. No research metric changes Manual R3.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd
from fx_scanner.manual_range_reclaim_r3 import bars, atr, adx
MIN=60_000_000_000
FILTERS=('ALL','RANGE20','RANGE25','H1_SLOPE','H1_H4','RANGE20_SLOPE','RANGE25_SLOPE','H1_PULLBACK')
FILTERS+=('CONFLUENCE2','CONFLUENCE3','CONFLUENCE2_H1H4','CONFLUENCE2_RANGE25','PREMIUM_DISCOUNT','CONFLUENCE2_PD','CONFLUENCE2_RANGE25_PD')
PHASES=('ALL','ASIA','LONDON','NEW_YORK')

def confluence_count(candidates, side, level, a):
    groups=set()
    for name,buy,sell,_,_ in candidates:
        other=buy if side==1 else sell
        if np.isfinite(other) and abs(other-level)<=.15*a:
            group=name.split('_M15_')[0] if '_M15_' in name else name
            groups.add(group)
    return len(groups)


def confirmed_pivots(frame, side, wing=2):
    """Rows are indexed by confirmation close, never by the earlier pivot."""
    price=frame.low if side==1 else frame.high
    candidate=price.shift(wing)
    extreme=price.rolling(2*wing+1,min_periods=2*wing+1)
    extreme=extreme.min() if side==1 else extreme.max()
    unique=price.rolling(2*wing+1).apply(lambda x: np.count_nonzero(x==x.min() if side==1 else x==x.max())==1,raw=True)
    good=(candidate==extreme)&(unique==1)
    out=pd.DataFrame({'price':candidate[good], 'source_ns':pd.Series(frame.index.asi8,index=frame.index).shift(wing)[good]})
    return out


def at(series, timestamp):
    i=series.index.searchsorted(timestamp,side='right')-1
    return float(series.iloc[i]) if i>=0 else float('nan')


def outcome(t, o, h, l, c, i, reference, side, a, target=.25, adverse=.25, horizon=60):
    end=int(np.searchsorted(t,t[i]+horizon*MIN,side='left'))
    # Use a complete wall-clock observation window for every outcome, winners too.
    if end>=len(t) or t[end]!=t[i]+horizon*MIN or np.any(np.diff(t[i:end+1])!=MIN):
        return {'result':'DATA_GAP','correct':False,'mfe_close_atr':None,'pullback_observed':False}
    fav=(h[i:end]-reference)/a if side==1 else (reference-l[i:end])/a
    bad=(reference-l[i:end])/a if side==1 else (h[i:end]-reference)/a
    fav=fav.copy();fav[0]=-np.inf  # the touch minute's high/low may precede touch
    wins=np.flatnonzero(fav>=target);losses=np.flatnonzero(bad>=adverse)
    first_win=int(wins[0]) if len(wins) else horizon+1
    first_loss=int(losses[0]) if len(losses) else horizon+1
    correct=first_win<first_loss and first_win<horizon
    result='BOUNCE' if correct else 'ADVERSE' if first_loss<horizon else 'TIMEOUT'
    path=side*(c[i:end]-reference)/a
    peak=np.maximum.accumulate(np.maximum(path,0))
    pullback=np.flatnonzero(peak-path>=adverse)
    stop=int(pullback[0]) if len(pullback) else len(path)-1
    return {'result':result,'correct':bool(correct),'mfe_close_atr':float(peak[stop]),
            'pullback_observed':bool(len(pullback)), 'minutes_to_result':min(first_win,first_loss,horizon)}


def make_events(d):
    h1=bars(d,60);h4=bars(d,240);m15=bars(d,15)
    a1=atr(h1);a15=atr(m15);adx1=adx(h1)[0]
    e1=h1.close.ewm(span=20,adjust=False,min_periods=20).mean()
    e4=h4.close.ewm(span=20,adjust=False,min_periods=20).mean()
    slope=e1-e1.shift(3);h1side=h1.close-e1;h4side=h4.close-e4
    center=m15.close.ewm(span=20,adjust=False,min_periods=20).mean()
    bb=m15.close.rolling(20).mean();std=m15.close.rolling(20).std(ddof=0)
    daily=d.tz_convert('Asia/Jakarta').resample('1D',label='right',closed='left').agg({'high':'max','low':'min'}).dropna().tz_convert('UTC')
    pivots={(tf,s):confirmed_pivots(f,s) for tf,f in [('H1',h1),('H4',h4)] for s in [1,-1]}
    t=d.index.asi8;o=d.open.to_numpy();h=d.high.to_numpy();l=d.low.to_numpy();c=d.close.to_numpy()
    spread=d.spread.to_numpy();events=[];published=0;skipped_gap=0
    for day in pd.date_range(d.index[0].tz_convert('Asia/Jakarta').normalize(),d.index[-1].tz_convert('Asia/Jakarta').normalize(),freq='D'):
        if day.dayofweek>=5:continue
        for hour,finish,phase in [(7,14,'ASIA'),(14,19,'LONDON'),(19,24,'NEW_YORK')]:
            pub=(day+pd.Timedelta(hours=hour)).tz_convert('UTC');end=(day+pd.Timedelta(hours=finish)).tz_convert('UTC')
            start=int(np.searchsorted(t,pub.value));last=int(np.searchsorted(t,end.value))
            if start<60 or start>=len(t) or t[start]!=pub.value or np.any(np.diff(t[start-60:start+1])!=MIN):continue
            a=at(a1,pub)
            if not np.isfinite(a) or a<=0:continue
            # H1 and H4 context must still be fresh at publication.
            if (pub-h1.index[h1.index.searchsorted(pub,side='right')-1]).total_seconds()>7200:continue
            ctx={'adx':at(adx1,pub),'slope':at(slope,pub),'h1':at(h1side,pub),'h4':at(h4side,pub)}
            candidates=[]
            for k in [1.5,2.,2.5]:
                ce=at(center,pub);w=k*at(a15,pub)
                candidates.append((f'KELTNER_M15_{k:g}',ce-w,ce+w,0.,0.))
            for k in [2.,2.5,3.]:
                ce=at(bb,pub);w=k*at(std,pub)
                candidates.append((f'BOLLINGER_M15_{k:g}',ce-w,ce+w,0.,0.))
            candidates.append(('PREVIOUS_DAY_HL',at(daily.low,pub),at(daily.high,pub),0.,0.))
            if hour>=14:
                begin=(day+pd.Timedelta(hours=7)).tz_convert('UTC');stop=(day+pd.Timedelta(hours=14)).tz_convert('UTC')
                asia=d.loc[(d.index>=begin)&(d.index<stop)]
                if len(asia)>=400:candidates.append(('ASIA_BOX',float(asia.low.min()),float(asia.high.max()),0.,0.))
            for tf in ['H1','H4']:
                z={s:pivots[tf,s].loc[:pub].tail(2) for s in [1,-1]}
                value={s:float(z[s].price.iloc[-1]) if len(z[s]) and (pub-z[s].index[-1]).total_seconds()<=48*3600 else np.nan for s in [1,-1]}
                candidates.append((f'CONFIRMED_SWING_{tf}',value[1],value[-1],0.,0.))
                if tf=='H1':
                    vals={};slopes={}
                    for s in [1,-1]:
                        q=z[s]
                        if len(q)<2 or pub.value-q.source_ns.iloc[-1]>48*60*MIN:vals[s]=np.nan;slopes[s]=0.;continue
                        delta=(q.price.iloc[-1]-q.price.iloc[-2])/((q.source_ns.iloc[-1]-q.source_ns.iloc[-2])/MIN)
                        slopes[s]=float(delta)
                        vals[s]=float(q.price.iloc[-1]+delta*(pub.value-q.source_ns.iloc[-1])/MIN) if s*delta>=0 else np.nan
                    candidates.append(('CONFIRMED_TRENDLINE_H1',vals[1],vals[-1],slopes[1],slopes[-1]))
            for name,buy,sell,bs,ss in candidates:
                for side,level,ls in [(1,buy,bs),(-1,sell,ss)]:
                    if not np.isfinite(level) or level<=0:continue
                    # Freeze band and line coefficients before the touch.
                    proximal=level+side*.05*a+ls*((t[start:last]-pub.value)/MIN)
                    # A zone already reached at publication is not a fresh zone.
                    if not len(proximal):continue
                    initial=min(o[start],c[start-1]) if side==1 else max(o[start],c[start-1])
                    if side*(initial-proximal[0])<=0:continue
                    published+=1
                    prior=np.r_[c[start-1],c[start:last-1]]
                    good=(side*(prior-proximal)>0)&((l[start:last]<=proximal) if side==1 else (h[start:last]>=proximal))
                    hit=np.flatnonzero(good)
                    if not len(hit):continue
                    i=start+int(hit[0]);line=float(proximal[hit[0]])
                    reference=min(o[i],line) if side==1 else max(o[i],line)
                    if abs(reference-line)>.1*a:skipped_gap+=1;continue
                    midpoint=(at(daily.low,pub)+at(daily.high,pub))/2
                    row={'zone':name,'side':'BUY' if side==1 else 'SELL','phase':phase,'publication':pub.isoformat(),'touch':d.index[i].isoformat(),'year':int(d.index[i].year),'entry_reference':float(reference),'center_at_publication':float(level),'line_slope_per_min':ls,'atr_h1':a,'spread_atr':float(spread[i]/a),'confluence':confluence_count(candidates,side,level,a),'premium_discount':bool(side*(midpoint-level)>0),**ctx}
                    for target in [.1,.25,.5]:
                        q=outcome(t,o,h,l,c,i,reference,side,a,target=target)
                        key=str(target).replace('.','_');row['outcome_'+key]=q['result'];row['correct_'+key]=q['correct']
                        if target==.25:row.update({k:v for k,v in q.items() if k not in ['result','correct']})
                    events.append(row)
        if day.month==1 and day.day<=3:print('AUDIT_PROGRESS',str(day.date()),len(events),flush=True)
    return pd.DataFrame(events),{'published_zones':published,'gap_through_zone_skips':skipped_gap}


def wilson(w,n):
    if n==0:return 0.
    z=1.959963984540054;p=w/n
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)


def stats(rows):
    n=len(rows);w=int(rows.correct_0_25.sum()) if n else 0
    return {'n':n,'bounce':w,'rate':w/n if n else None,'wilson_low':wilson(w,n),'data_gaps':int((rows.outcome_0_25=='DATA_GAP').sum()) if n else 0,'timeouts':int((rows.outcome_0_25=='TIMEOUT').sum()) if n else 0,'median_peak_close_atr':float(rows.mfe_close_atr.median()) if n and rows.mfe_close_atr.notna().any() else None,'small_0_1_bounce_rate':float(rows.correct_0_1.mean()) if n else None,'large_0_5_bounce_rate':float(rows.correct_0_5.mean()) if n else None}


def apply_rule(e,rule):
    side=1 if rule['side']=='BUY' else -1
    m=(e.zone==rule['zone'])&(e.side==rule['side'])
    if rule['phase']!='ALL':m&=e.phase==rule['phase']
    f=rule['filter'];direction=side*e.slope>0
    if f.startswith('RANGE20'):m&=e.adx<20
    if f.startswith('RANGE25'):m&=e.adx<25
    if f in ['H1_SLOPE','RANGE20_SLOPE','RANGE25_SLOPE']:m&=direction
    if f=='H1_H4':m&=(side*e.h1>0)&(side*e.h4>0)
    if f=='H1_PULLBACK':m&=(side*e.h1<0)&direction
    if f.startswith('CONFLUENCE2'):m&=e.confluence>=2
    if f=='CONFLUENCE3':m&=e.confluence>=3
    if f=='CONFLUENCE2_H1H4':m&=(side*e.h1>0)&(side*e.h4>0)
    if f.startswith('CONFLUENCE2_RANGE25'):m&=e.adx<25
    if f=='PREMIUM_DISCOUNT' or f.endswith('_PD'):m&=e.premium_discount
    return e[m]


def select(e):
    # Selection sees only 2019-2022. Each side is selected independently.
    train=e[e.year<=2022];rules=[]
    for zone in sorted(e.zone.unique()):
        for side in ['BUY','SELL']:
            for phase in PHASES:
                for f in FILTERS:
                    rule={'zone':zone,'side':side,'phase':phase,'filter':f}
                    s=stats(apply_rule(train,rule));rules.append({**rule,**s})
    ranking=pd.DataFrame(rules).sort_values(['wilson_low','n'],ascending=False)
    selected=[]
    for side in ['BUY','SELL']:
        q=ranking[(ranking.side==side)&(ranking.n>=100)]
        if not len(q):continue
        rule=q.iloc[0][['zone','side','phase','filter']].to_dict();periods={}
        for label,mask in [('2019_2022',e.year<=2022),('2023_2024',e.year.between(2023,2024)),('2025',e.year==2025),('2026_Q1',e.year==2026)]:periods[label]=stats(apply_rule(e[mask],rule))
        passed=all(periods[p]['n']>=100 and periods[p]['rate']>=.8 for p in ['2023_2024','2025'])
        selected.append({'rule':rule,'periods':periods,'passed_80_validation_and_2025':passed})
    return ranking,selected


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',required=True,type=Path);ap.add_argument('--out',required=True,type=Path);args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    d=pd.read_csv(args.input,usecols=['timestamp','open','high','low','close','spread']);d.index=pd.to_datetime(d.pop('timestamp'),utc=True);d=d.sort_index()
    assert not d.index.has_duplicates and d.notna().all().all()
    assert ((d.low<=d[['open','close']].min(axis=1))&(d.high>=d[['open','close']].max(axis=1))).all()
    print('INPUT',len(d),str(d.index[0]),str(d.index[-1]),flush=True)
    events,audit=make_events(d);events.to_csv(args.out/'touch_ledger.csv',index=False)
    ranking,selected=select(events);ranking.to_csv(args.out/'train_ranking.csv',index=False)
    digest=hashlib.sha256(args.input.read_bytes()).hexdigest()
    payload={'contract':'RIZAN_ZONE_REBOUND_RESEARCH_R1','execution_authority':False,'execution_influence':False,'live_strategy_changed':False,'input':{'sha256':digest,'rows':len(d),'first':d.index[0].isoformat(),'last':d.index[-1].isoformat()},'definition':{'primary_bounce_atr_h1':.25,'adverse_atr_h1':.25,'horizon_minutes':60,'zone_half_width_atr_h1':.05,'favorable_touch_bar_ignored':True,'ambiguous_bar':'ADVERSE_FIRST','data_gaps_count_as_not_success':True,'context_frozen_before_touch':True,'first_touch_only_per_published_zone':True},'selection':'2019-2022 only; highest Wilson lower bound with >=100 touches per side','periods_not_untouched':True,'macro_tested':False,'macro_reason':'No publication-time aligned historical macro archive supplied. Current macro must not be backfilled into the historical test.','audit':audit,'touch_events':len(events),'configurations':len(ranking),'selected':selected,'target_80_achieved':all(x['passed_80_validation_and_2025'] for x in selected) and len(selected)==2}
    (args.out/'summary.json').write_text(json.dumps(payload,indent=2,allow_nan=False));print(json.dumps(payload,indent=2),flush=True)

if __name__=='__main__':main()
