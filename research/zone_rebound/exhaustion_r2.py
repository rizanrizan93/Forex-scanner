"""Overextension, liquidity sweep and failed-push research. No live dependencies.

AREA uses a zone published before touch; CONFIRMED uses only completed M1/M5
candles and enters at the following M1 open. Outcomes never enter selection
features. Multiple predeclared target/adverse budgets are kept separate.
"""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd
from fx_scanner.manual_range_reclaim_r3 import bars, atr, adx, rsi, map_values
from research.zone_rebound.audit import confirmed_pivots, wilson
MIN=60_000_000_000
SCENARIOS={'STRICT':(.25,.25),'MODERATE':(.25,.5),'SMALL':(.1,.5),'WIDE':(.25,1.)}
EXTENSIONS=(0.,.5,1.,1.5,2.)
RSI_FILTERS=('NONE','FAST_EXTREME','H1_EXTREME')
REGIMES=('ALL','ADX25','ADX35','FLAT','ADX25_FLAT')
SESSIONS=('ALL','ASIA','LONDON','NEW_YORK')


def map_at(s,t):return map_values(s,np.asarray(t,dtype=np.int64))


def context(d):
    h=bars(d,60);m15=bars(d,15);a=atr(h);ema=h.close.ewm(span=20,adjust=False,min_periods=20).mean()
    mc=m15.close.ewm(span=20,adjust=False,min_periods=20).mean()
    return dict(atr=a,mean=ema,adx=adx(h)[0],slope=(ema-ema.shift(3))/a,rsi_h1=rsi(h.close,14),
                rsi_fast=pd.Series(rsi(d.close,14).to_numpy(),index=d.index+pd.Timedelta(minutes=1)),
                bb_upper=m15.close.rolling(20).mean()+2.5*m15.close.rolling(20).std(ddof=0),
                bb_lower=m15.close.rolling(20).mean()-2.5*m15.close.rolling(20).std(ddof=0),
                kc_upper=mc+2*atr(m15),kc_lower=mc-2*atr(m15),
                h1_clock=pd.Series(h.index.asi8,index=h.index))


def confirmed_events(d,ctx,tf):
    f=bars(d,tf);counts=d.close.resample(f'{tf}min',label='right',closed='left').count().reindex(f.index)
    ts=f.index.asi8;start=ts-tf*MIN;source=d.index.asi8;ids=np.searchsorted(source,ts)
    exists=ids<len(source);exact=np.zeros(len(f),bool);exact[exists]=source[ids[exists]]==ts[exists]
    a=map_at(ctx['atr'],ts);mean=map_at(ctx['mean'],ts);ax=map_at(ctx['adx'],ts);slope=map_at(ctx['slope'],ts)
    rh=map_at(ctx['rsi_h1'],ts);rf=map_at(ctx['rsi_fast'],ts);age=(ts-map_at(ctx['h1_clock'],ts))/MIN
    local=f.index.tz_convert('Asia/Jakarta');minute=local.hour.to_numpy()*60+local.minute.to_numpy()
    valid=exact&(counts.to_numpy()==tf)&np.isfinite(a)&(a>0)&(age>=0)&(age<=120)&(local.dayofweek<5)&(minute>=420)&(minute<1435)
    o=f.open.to_numpy();h=f.high.to_numpy();l=f.low.to_numpy();c=f.close.to_numpy();prior=f.close.shift(1).to_numpy();rng=np.maximum(h-l,1e-9)
    hour_hi=f.high.rolling(60//tf,min_periods=60//tf).max().shift(1).to_numpy();hour_lo=f.low.rolling(60//tf,min_periods=60//tf).min().shift(1).to_numpy()
    four_hi=f.high.rolling(240//tf,min_periods=240//tf).max().shift(1).to_numpy();four_lo=f.low.rolling(240//tf,min_periods=240//tf).min().shift(1).to_numpy()
    impulse=f.close.diff(30//tf).to_numpy()/a
    records=[]
    for side in [1,-1]:
        wick=(np.minimum(o,c)-l)/rng if side==1 else (h-np.maximum(o,c))/rng
        reject=(wick>=.35)&(side*(c-o)>0)
        features={'kind':'CONFIRMED','tf':tf,'side':side,'i':ids,'time_ns':ts,'atr_h1':a,'stretch':(mean-l)/a if side==1 else (h-mean)/a,'rsi_fast':side*(50-rf),'rsi_h1':side*(50-rh),'adx':ax,'slope':slope,'phase':np.where(minute<840,'ASIA',np.where(minute<1140,'LONDON','NEW_YORK')),'year':local.year,'day':(ts//MIN+420)//1440,'confirmation_minutes':tf,'bounce_already_atr':(c-l)/a if side==1 else (h-c)/a}
        patterns={}
        for band in ['bb','kc']:
            level=map_at(ctx[band+'_lower' if side==1 else band+'_upper'],start)
            touch=l<=level if side==1 else h>=level
            patterns[band.upper()+'_REENTRY']=touch&(side*(prior-level)>0)&(side*(c-level)>0)
        for name,level in [('HOUR_SWEEP',hour_lo if side==1 else hour_hi),('FOUR_HOUR_SWEEP',four_lo if side==1 else four_hi)]:
            touch=l<level if side==1 else h>level
            patterns[name]=touch&(side*(c-level)>0)&reject
        patterns['IMPULSE_WICK']=(side*impulse<=-.75)&reject
        piv=confirmed_pivots(f,side);pidx=f.index.get_indexer(piv.index)-2
        piv_rsi=pd.Series(rsi(f.close,14).to_numpy()[np.maximum(pidx,0)],index=piv.index)
        pp=map_at(piv.price,start) if len(piv) else np.full(len(f),np.nan)
        pr=map_at(piv_rsi,start) if len(piv) else np.full(len(f),np.nan)
        current_rsi=rsi(f.close,14).to_numpy()
        beyond=l<pp if side==1 else h>pp
        divergence=side*(current_rsi-pr)>=5
        patterns['PIVOT_DIVERGENCE']=beyond&divergence&reject
        for family,mask in patterns.items():
            use=valid&mask&np.isfinite(features['stretch'])&np.isfinite(rf)&np.isfinite(rh)
            q=pd.DataFrame({k:(np.asarray(v)[use] if not np.isscalar(v) else v) for k,v in features.items()})
            q['family']=family
            if len(q):records.append(q)
    return pd.concat(records,ignore_index=True) if records else pd.DataFrame()


def area_events(d,ctx,path):
    q=pd.read_csv(path);q['time_ns']=pd.to_datetime(q.pop('touch'),utc=True).array.asi8;q['i']=np.searchsorted(d.index.asi8,q['time_ns'])
    q['side']=np.where(q.side=='BUY',1,-1);q['kind']='AREA';q['tf']=0;q['family']=q.pop('zone');t=q['time_ns'].to_numpy();s=q.side.to_numpy();a=map_at(ctx['atr'],t)
    # The source zone's ATR/band stays frozen. Exhaustion is evaluated before touch.
    q['stretch']=s*(map_at(ctx['mean'],t)-q.entry_reference.to_numpy())/a
    q['rsi_fast']=s*(50-map_at(ctx['rsi_fast'],t));q['rsi_h1']=s*(50-map_at(ctx['rsi_h1'],t));q['adx']=map_at(ctx['adx'],t);q['slope']=map_at(ctx['slope'],t)
    q['day']=(t//MIN+420)//1440;q['confirmation_minutes']=0;q['bounce_already_atr']=0.
    return q[np.isfinite(q.stretch)&np.isfinite(q.rsi_fast)&np.isfinite(q.rsi_h1)].copy()


def label(d,e,*,horizon=60,cost=None,delay=0,random_side=None):
    t=d.index.asi8;o=d.open.to_numpy();h=d.high.to_numpy();l=d.low.to_numpy();c=d.close.to_numpy()
    i=e.i.to_numpy(dtype=np.int64)+delay;s=e.side.to_numpy() if random_side is None else np.asarray(random_side);a=e.atr_h1.to_numpy();n=len(e)
    reference=e.reference.to_numpy().copy() if delay==0 else o[np.minimum(i,len(o)-1)]
    if cost is not None:reference=reference+s*np.asarray(cost)
    gaps=np.r_[0,np.cumsum(np.diff(t)!=MIN)];safe=np.minimum(i+horizon,len(t)-1)
    complete=(i+horizon<len(t))&(t[safe]-t[np.minimum(i,len(t)-1)]==horizon*MIN)&(gaps[safe]-gaps[np.minimum(i,len(t)-1)]==0)
    first_win={k:np.full(n,horizon+1,dtype=np.int16) for k in SCENARIOS};first_bad={k:np.full(n,horizon+1,dtype=np.int16) for k in SCENARIOS}
    ignore=(e.kind.to_numpy()=='AREA')&(delay==0)
    mae=np.zeros(n);mfe=np.zeros(n)
    for step in range(horizon):
        j=np.minimum(i+step,len(t)-1)
        fav=np.where(s==1,h[j]-reference,reference-l[j])/a
        bad=np.where(s==1,reference-l[j],h[j]-reference)/a
        if step==0:fav=np.where(ignore,-np.inf,fav)
        mfe=np.maximum(mfe,fav);mae=np.maximum(mae,bad)
        for key,(target,adverse) in SCENARIOS.items():
            first_win[key]=np.where((first_win[key]>horizon)&(fav>=target),step,first_win[key])
            first_bad[key]=np.where((first_bad[key]>horizon)&(bad>=adverse),step,first_bad[key])
    out={'complete':complete,'mfe_60_atr':mfe,'mae_60_atr':mae}
    for key in SCENARIOS:
        w=first_win[key];b=first_bad[key];out[key]=complete&(w<b)&(w<horizon)
        out[key+'_timeout']=complete&(w>=horizon)&(b>=horizon)
    return out


def prospective_indices(e,mask):
    ids=np.flatnonzero(mask);chosen=[];last=None;last_day=None;count=0
    for j in ids:
        day=int(e.day.iloc[j]);clock=int(e['time_ns'].iloc[j])
        if day!=last_day:count=0;last_day=day
        if count>=2 or last is not None and clock-last<60*MIN:continue
        chosen.append(j);last=clock;count+=1
    return np.array(chosen,dtype=np.int64)


def rule_mask(e,extension,rsi_filter,regime,session):
    m=e.stretch.to_numpy()>=extension
    if rsi_filter=='FAST_EXTREME':m&=e.rsi_fast.to_numpy()>=20
    if rsi_filter=='H1_EXTREME':m&=e.rsi_h1.to_numpy()>=20
    if regime.startswith('ADX25'):m&=e.adx.to_numpy()<25
    if regime=='ADX35':m&=e.adx.to_numpy()<35
    if 'FLAT' in regime:m&=np.abs(e.slope.to_numpy())<.25
    if session!='ALL':m&=e.phase.to_numpy()==session
    return m


def metric(e,indices,scenario):
    n=len(indices)
    if not n:return {'n':0,'correct':0,'rate':None,'wilson_low':0.,'data_gaps':0}
    q=e.iloc[indices];w=int(q[scenario].sum());full=q[q.complete]
    return {'n':n,'correct':w,'rate':w/n,'wilson_low':wilson(w,n),'data_gaps':int((~q.complete).sum()),'timeouts':int(q[scenario+'_timeout'].sum()),'median_mfe_60_atr':float(full.mfe_60_atr.median()) if len(full) else None,'median_mae_60_atr':float(full.mae_60_atr.median()) if len(full) else None,'median_bounce_already_atr':float(q.bounce_already_atr.median())}


def search(e):
    ranked=[];selected=[];years=e.year.to_numpy()
    # Both development periods can select rules; 2025 never enters ranking.
    for group,rows in e.groupby(['kind','tf','family','side'],sort=True):
        q=rows.sort_values('time_ns',kind='stable').reset_index(drop=True)
        for ex in EXTENSIONS:
            for rf in RSI_FILTERS:
                for regime in REGIMES:
                    for session in SESSIONS:
                        m=rule_mask(q,ex,rf,regime,session);ids=prospective_indices(q,m)
                        train=ids[q.year.to_numpy()[ids]<=2022];valid=ids[np.isin(q.year.to_numpy()[ids],[2023,2024])]
                        if len(train)<150 or len(valid)<100:continue
                        rule=dict(kind=group[0],tf=int(group[1]),family=group[2],side=int(group[3]),extension=ex,rsi_filter=rf,regime=regime,session=session)
                        for scenario in ['STRICT','SMALL','WIDE']:
                            a=metric(q,train,scenario);b=metric(q,valid,scenario)
                            ranked.append({**rule,'scenario':scenario,'train_n':a['n'],'train_rate':a['rate'],'valid_n':b['n'],'valid_rate':b['rate'],'robust_score':min(a['wilson_low'],b['wilson_low'])})
    rank=pd.DataFrame(ranked).sort_values(['robust_score','valid_n'],ascending=False,kind='stable')
    for group,winner in rank.groupby(['kind','side','scenario'],sort=True):
        rule=winner.iloc[0].to_dict();q=e[(e.kind==rule['kind'])&(e.tf==rule['tf'])&(e.family==rule['family'])&(e.side==rule['side'])].sort_values('time_ns',kind='stable').reset_index(drop=True)
        ids=prospective_indices(q,rule_mask(q,rule['extension'],rule['rsi_filter'],rule['regime'],rule['session']))
        periods={}
        for name,yearmask in [('2019_2022',q.year<=2022),('2023_2024',q.year.between(2023,2024)),('2025',q.year==2025),('2026_Q1',q.year==2026)]:
            keep=ids[yearmask.to_numpy()[ids]];periods[name]={sc:metric(q,keep,sc) for sc in SCENARIOS}
        selected.append({'rule':rule,'periods':periods,'indices':q.iloc[ids].index.tolist(),'events':q.iloc[ids].copy()})
    return rank,selected


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--areas',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    d=pd.read_csv(args.input,usecols=['timestamp','open','high','low','close','spread']);d.index=pd.to_datetime(d.pop('timestamp'),utc=True)
    assert d.index.is_monotonic_increasing and not d.index.has_duplicates and d.notna().all().all()
    ctx=context(d);pieces=[area_events(d,ctx,args.areas)]
    for tf in [1,5]:
        part=confirmed_events(d,ctx,tf);pieces.append(part);print('CANDIDATES',tf,len(part),flush=True)
    e=pd.concat(pieces,ignore_index=True).sort_values(['time_ns','kind','family','side'],kind='stable').reset_index(drop=True)
    e['reference']=np.where(e.kind=='AREA',e.entry_reference,d.open.to_numpy()[e.i.to_numpy(dtype=int)])
    for k,v in label(d,e).items():e[k]=v
    print('LABELED',len(e),flush=True)
    rank,selected=search(e);print('ELIGIBLE_RULE_SCENARIOS',len(rank),flush=True);rank.to_csv(args.out/'ranking.csv',index=False)
    traces=[]
    for model in selected:
        q=model.pop('events');model.pop('indices');scenario=model['rule']['scenario'];y=label(d,q,delay=1);cost=label(d,q,cost=d.spread.to_numpy()[q.i.to_numpy(dtype=int)]);rnd=np.random.default_rng(1711).choice([-1,1],size=len(q));null=label(d,q,random_side=rnd)
        q['selected_scenario']=scenario;q['delay_1m_success']=y[scenario];q['spread_proxy_success']=cost[scenario];q['random_direction_success']=null[scenario]
        model['followup']={}
        for yr in [2025,2026]:
            ix=q.year.to_numpy()==yr;n=int(ix.sum());model['followup'][str(yr)]={k:float(v[ix].mean()) if n else None for k,v in [('delay_1m_rate',y[scenario]),('spread_proxy_rate',cost[scenario]),('random_direction_rate',null[scenario])]}
        test=model['periods']['2025'][scenario];model['observed_80_in_2025_n100']=test['n']>=100 and test['rate']>=.8;model['wilson_lower_80_in_2025_n100']=test['n']>=100 and test['wilson_low']>=.8
        traces.append(q)
    pd.concat(traces).to_csv(args.out/'selected_ledger.csv',index=False)
    result={'contract':'RIZAN_EXHAUSTION_REBOUND_RESEARCH_R2','execution_authority':False,'execution_influence':False,'live_strategy_changed':False,'input_sha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),'input_rows':len(d),'first':d.index[0].isoformat(),'last':d.index[-1].isoformat(),'candidate_rows':len(e),'eligible_rule_scenarios':len(rank),'full_grid_upper_bound':len(e.groupby(['kind','tf','family','side']))*len(EXTENSIONS)*len(RSI_FILTERS)*len(REGIMES)*len(SESSIONS),'scenarios':SCENARIOS,'horizon_minutes':60,'selection':'min Wilson lower bound 2019-2022 and 2023-2024; n>=150/100. 2025 excluded from ranking. At most 2 events/day, >=60 minutes apart.','periods_previously_used_in_other_research':True,'area_vs_confirmed':'AREA is pre-touch; CONFIRMED is next M1 open after completed M1/M5 rejection. Do not call confirmed performance pre-touch probability.','cost_limit':'Spread proxy uses entry-minute spread, not true broker bid/ask execution; not net trading win rate.','macro_tested':False,'selected':selected}
    (args.out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False));print('RESULT',json.dumps([dict(kind=x['rule']['kind'],side=x['rule']['side'],scenario=x['rule']['scenario'],rule=x['rule'],test=x['periods']['2025'][x['rule']['scenario']],followup=x['followup']['2025']) for x in selected],indent=2),flush=True)

if __name__=='__main__':main()
