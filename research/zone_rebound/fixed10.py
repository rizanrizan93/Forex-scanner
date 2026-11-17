"""Pre-touch structural-zone research, fixed USD10/oz objective. No live imports.

All zone geometry is frozen when its formation closes. Macro is exploratory:
latest-vintage FRED with conservative release lags, NOT archived PIT data.
"""
from __future__ import annotations
import argparse, hashlib, itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
from fx_scanner.manual_range_reclaim_r3 import bars, atr, adx, map_values
from research.zone_rebound.audit import wilson

MIN=60_000_000_000
MACROS=('NONE','EUR15','EUR60','EUR_TURN','REAL5','NOMINAL5','EUR15_REAL5','BROAD5_LAG14')
REGIMES=('ALL','ADX25','TREND','STRETCH1','ATR5','ATR7','ATR10','ATR5_TREND','ATR5_STRETCH','ATR5_ADX25')
SCENARIOS={f'H{h}_A{a}':(h,a) for h in (60,240) for a in (5,10,20)}


def formations(f, tf):
    """Return zones indexed by *publication* close; never by origin candle."""
    o,h,l,c=[f[k].to_numpy() for k in ('open','high','low','close')]
    a=atr(f).shift(1).to_numpy();t=f.index.asi8;out=[]
    def add(i,origin,side,lo,hi,family,strength):
        if not np.isfinite(a[i]) or a[i]<=0 or not hi>lo:return
        if hi-lo>2*a[i] or hi-lo<.02*a[i]:return
        proximal=hi if side==1 else lo
        if side*(c[i]-proximal)<.05*a[i]:return
        out.append(dict(pub_ns=int(t[i]),origin_ns=int(t[origin]-tf*MIN),tf=tf,
                        side=side,lo=float(lo),hi=float(hi),family=family,strength=float(strength)))
    for i in range(16,len(f)):
        # Observed candles only; allow the regular daily closure, reject long gaps.
        # No interpolation. Exact post-touch completeness is checked separately.
        if np.any(np.diff(t[i-8:i+1])>(2*tf+60)*MIN):continue
        if not np.isfinite(a[i]) or a[i]<=0:continue
        side=1 if c[i]>o[i] else -1;body=abs(c[i]-o[i])/a[i]
        bos=c[i]>max(h[i-6:i]) if side==1 else c[i]<min(l[i-6:i])
        if body>=.8 and bos:
            if abs(c[i-1]-o[i-1])<=.5*a[i]:
                lo,hi=(l[i-1],max(o[i-1],c[i-1])) if side==1 else (min(o[i-1],c[i-1]),h[i-1])
                add(i,i-1,side,lo,hi,'BASE_DISPLACEMENT',body)
            for j in range(i-1,i-6,-1):
                if side*(c[j]-o[j])<0:
                    lo,hi=(l[j],o[j]) if side==1 else (o[j],h[j])
                    add(i,j,side,lo,hi,'ORDER_BLOCK_PROXY',body);break
            level=max(h[i-6:i]) if side==1 else min(l[i-6:i])
            add(i,i,side,level-.1*a[i],level+.1*a[i],'BREAK_RETEST',body)
        middle=abs(c[i-1]-o[i-1])/a[i]
        if l[i]>h[i-2] and l[i]-h[i-2]>=.1*a[i] and middle>=.5:
            add(i,i-2,1,h[i-2],l[i],'FVG',middle)
        if h[i]<l[i-2] and l[i-2]-h[i]>=.1*a[i] and middle>=.5:
            add(i,i-2,-1,h[i],l[i-2],'FVG',middle)
        j=i-2
        if l[j]==min(l[i-4:i+1]) and np.count_nonzero(l[i-4:i+1]==l[j])==1:
            add(i,j,1,l[j]-.05*a[i],l[j]+.1*a[i],'CONFIRMED_PIVOT',0.)
        if h[j]==max(h[i-4:i+1]) and np.count_nonzero(h[i-4:i+1]==h[j])==1:
            add(i,j,-1,h[j]-.1*a[i],h[j]+.05*a[i],'CONFIRMED_PIVOT',0.)
        rng=max(h[i]-l[i],1e-8)
        if l[i]<min(l[i-8:i]) and c[i]>min(l[i-8:i]) and c[i]>o[i] and (min(o[i],c[i])-l[i])/rng>=.35:
            add(i,i,1,l[i],min(o[i],c[i]),'SWEEP_ORIGIN_RETURN',body)
        if h[i]>max(h[i-8:i]) and c[i]<max(h[i-8:i]) and c[i]<o[i] and (h[i]-max(o[i],c[i]))/rng>=.35:
            add(i,i,-1,max(o[i],c[i]),h[i],'SWEEP_ORIGIN_RETURN',body)
    return pd.DataFrame(out)


def first_touches(d,z):
    t=d.index.asi8;o=d.open.to_numpy();h=d.high.to_numpy();l=d.low.to_numpy()
    rows=[];seen=set();published=0;gap=0
    if not len(z):return pd.DataFrame(),dict(unique_publications=0,gap_through_distal=0)
    for q in z.sort_values('pub_ns',kind='stable').to_dict('records'):
        key=(q['family'],q['tf'],q['side'],round(q['lo'],6),round(q['hi'],6))
        if key in seen:continue
        seen.add(key);published+=1
        start=np.searchsorted(t,q['pub_ns']);ttl={15:24,60:72,240:168}[q['tf']]
        end=np.searchsorted(t,q['pub_ns']+ttl*60*MIN)
        if start>=len(t) or t[start]!=q['pub_ns']:continue
        side=q['side'];prox=q['hi'] if side==1 else q['lo'];dist=q['lo'] if side==1 else q['hi']
        if side*(o[start]-prox)<=0:continue
        hit=np.flatnonzero(l[start:end]<=prox if side==1 else h[start:end]>=prox)
        if not len(hit):continue
        i=start+int(hit[0]);reference=min(o[i],prox) if side==1 else max(o[i],prox)
        if side*(reference-dist)<0:gap+=1;continue
        rows.append({**q,'i':i,'time_ns':int(t[i]),'reference':float(reference),'age_hours':(t[i]-q['pub_ns'])/MIN/60})
    return pd.DataFrame(rows),dict(unique_publications=published,gap_through_distal=gap)


def release_index(dates,broad=False):
    dates=pd.DatetimeIndex(dates)
    if broad:
        days=dates+pd.Timedelta(days=14)
    else:
        offset=CustomBusinessDay(n=2,calendar=USFederalHolidayCalendar())
        days=pd.DatetimeIndex([x+offset for x in dates])
    return (days+pd.Timedelta(hours=17)).tz_localize('America/New_York').tz_convert('UTC')


def macro_features(e,eur,fred):
    t=e.time_ns.to_numpy();side=e.side.to_numpy();out={}
    et=eur.index.asi8+MIN;ec=eur.close.to_numpy();j=np.searchsorted(et,t,side='right')-1;safe=np.maximum(j,0)
    fresh=(j>=0)&(t-et[safe]<=2*MIN)
    for look in (15,60):
        k=np.maximum(j-look,0)
        # Exact wall-clock window, including continuous M1 observations.
        ok=fresh&(j>=look)&(et[safe]-et[k]==look*MIN)
        value=side*(ec[safe]/ec[k]-1)*1e4
        out[f'eur{look}']=np.where(ok,value,np.nan)
    f=fred.copy();f.index=pd.to_datetime(f.pop('observation_date'))
    for col,name in [('DFII10','real5'),('DGS2','nom2_5'),('DGS10','nom10_5'),('DTWEXBGS','broad5')]:
        s=f[col].dropna();delta=s-s.shift(5)
        delta.index=release_index(s.index,broad=col=='DTWEXBGS')
        # Negative yield/USD movement supports BUY; positive supports SELL.
        values=map_values(delta,t);clock=map_values(pd.Series(delta.index.asi8,index=delta.index),t)
        out[name]=np.where((t-clock)<=10*24*60*MIN,-side*values,np.nan)
    for k,v in out.items():e[k]=v
    return e


def enrich(d,e,eur,fred):
    t=e.time_ns.to_numpy();side=e.side.to_numpy();h=bars(d,60);a=atr(h);ema=h.close.ewm(span=20,adjust=False,min_periods=20).mean()
    e['atr_h1']=map_values(a,t);e['adx']=map_values(adx(h)[0],t)
    e['slope']=side*map_values((ema-ema.shift(3))/a,t)
    e['stretch']=side*(map_values(ema,t)-e.reference.to_numpy())/e.atr_h1.to_numpy()
    local=pd.to_datetime(t,utc=True).tz_convert('Asia/Jakarta');minute=local.hour*60+local.minute
    e['year']=local.year;e['day']=(t//MIN+420)//1440
    e['phase']=np.where(minute<840,'ASIA',np.where(minute<1140,'LONDON','NEW_YORK'))
    e['spread']=d.spread.to_numpy()[e.i.to_numpy(dtype=int)]
    e=macro_features(e,eur,fred)
    keep=(local.dayofweek<5)&(minute>=420)&(minute<1440)&np.isfinite(e.atr_h1)&(e.atr_h1>0)
    return e.loc[keep].sort_values(['time_ns','family','tf','side'],kind='stable').reset_index(drop=True)


def labels(d,e,cost=False):
    t=d.index.asi8;h=d.high.to_numpy();l=d.low.to_numpy();i=e.i.to_numpy(dtype=int);s=e.side.to_numpy();n=len(e)
    ref=e.reference.to_numpy()+s*(e.spread.to_numpy() if cost else 0)
    gaps=np.r_[0,np.cumsum(np.diff(t)!=MIN)];out={};wins=np.full(n,241,dtype=np.int16)
    bads={a:np.full(n,241,dtype=np.int16) for a in (5,10,20)};mae=np.zeros(n);mae_before=np.zeros(n);mfe=np.zeros(n)
    for step in range(240):
        j=np.minimum(i+step,len(t)-1);fav=np.where(s==1,h[j]-ref,ref-l[j]);bad=np.where(s==1,ref-l[j],h[j]-ref)
        if step==0:fav=np.full(n,-np.inf)
        # Includes entire target candle's adverse extreme: conservative upper bound.
        mae_before=np.maximum(mae_before,np.where(wins==241,bad,0))
        wins=np.where((wins==241)&(fav>=10),step,wins)
        for a in bads:bads[a]=np.where((bads[a]==241)&(bad>=a),step,bads[a])
        mae=np.maximum(mae,bad);mfe=np.maximum(mfe,fav)
        if step+1 in (60,240):
            hz=step+1;end=np.minimum(i+hz,len(t)-1)
            complete=(i+hz<len(t))&(t[end]-t[i]==hz*MIN)&(gaps[end]-gaps[i]==0)
            out[f'complete_{hz}']=complete
            for a in bads:
                out[f'H{hz}_A{a}']=complete&(wins<hz)&(wins<bads[a])
                out[f'H{hz}_A{a}_timeout']=complete&(wins>=hz)&(bads[a]>=hz)
    out['target_minutes']=np.where(wins<240,wins+1,np.nan)
    out['mae_before_target']=np.where(wins<240,mae_before,np.nan)
    out['mfe_240']=mfe;out['mae_240']=mae
    return out


def mask(q,regime,phase,macro):
    m=np.ones(len(q),bool)
    if regime=='ADX25':m&=q.adx.to_numpy()<25
    if regime=='TREND':m&=q.slope.to_numpy()>0
    if regime=='STRETCH1':m&=q.stretch.to_numpy()>=1
    if regime.startswith('ATR'):
        minimum=float(regime.split('_')[0][3:]);m&=q.atr_h1.to_numpy()>=minimum
        if regime.endswith('_TREND'):m&=q.slope.to_numpy()>0
        if regime.endswith('_STRETCH'):m&=q.stretch.to_numpy()>=1
        if regime.endswith('_ADX25'):m&=q.adx.to_numpy()<25
    if phase!='ALL':m&=q.phase.to_numpy()==phase
    if macro=='EUR15':m&=q.eur15.to_numpy()>0
    if macro=='EUR60':m&=q.eur60.to_numpy()>0
    if macro=='EUR_TURN':m&=(q.eur15.to_numpy()>0)&(q.eur60.to_numpy()<0)
    if macro=='REAL5':m&=q.real5.to_numpy()>0
    if macro=='NOMINAL5':m&=(q.nom2_5.to_numpy()>0)&(q.nom10_5.to_numpy()>0)
    if macro=='EUR15_REAL5':m&=(q.eur15.to_numpy()>0)&(q.real5.to_numpy()>0)
    if macro=='BROAD5_LAG14':m&=q.broad5.to_numpy()>0
    return m


def select_indices(q,m):
    ids=np.flatnonzero(m);times=q.time_ns.to_numpy();days=q.day.to_numpy();last=-10**18;day=-1;count=0;out=[]
    for j in ids:
        if days[j]!=day:day=days[j];count=0
        if times[j]-last<240*MIN or count>=2:continue
        out.append(j);last=int(times[j]);count+=1
    return np.asarray(out,dtype=int)


def metric(q,ids,sc):
    z=q.iloc[ids];n=len(z);w=int(z[sc].sum());hz=SCENARIOS[sc][0]
    win=z[z[sc]];complete=z[z[f'complete_{hz}']]
    return dict(n=n,wins=w,rate=w/n if n else None,wilson_low=wilson(w,n),
                data_gaps=int((~z[f'complete_{hz}']).sum()),timeouts=int(z[sc+'_timeout'].sum()),
                median_minutes_success=float(win.target_minutes.median()) if len(win) else None,
                median_mae_before_target_success=float(win.mae_before_target.median()) if len(win) else None,
                median_mfe_240=float(complete.mfe_240.median()) if len(complete) else None)


def search(e):
    ranking=[]
    for group,rows in e.groupby(['family','tf','side'],sort=True):
        q=rows.reset_index(drop=True);yr=q.year.to_numpy()
        for regime,phase,macro in itertools.product(REGIMES,('ALL','ASIA','LONDON','NEW_YORK'),MACROS):
            ids=select_indices(q,mask(q,regime,phase,macro));a=ids[yr[ids]<=2022];b=ids[np.isin(yr[ids],[2023,2024])]
            if len(a)<150 or len(b)<100:continue
            for sc in SCENARIOS:
                x=metric(q,a,sc);y=metric(q,b,sc)
                ranking.append(dict(family=group[0],tf=int(group[1]),side=int(group[2]),regime=regime,phase=phase,macro=macro,scenario=sc,
                                    train_n=x['n'],train_rate=x['rate'],valid_n=y['n'],valid_rate=y['rate'],score=min(x['wilson_low'],y['wilson_low'])))
    rank=pd.DataFrame(ranking).sort_values(['score','valid_n'],ascending=False,kind='stable');selected=[];traces=[]
    # Separate zone-only, EUR-only, yield-only and combined selection enables honest ablation.
    classes={'ZONE':['NONE'],'EUR':['EUR15','EUR60','EUR_TURN'],'YIELD':['REAL5','NOMINAL5'],'COMBINED':['EUR15_REAL5'],'BROAD':['BROAD5_LAG14']}
    for side,sc,(cls,macros) in itertools.product((1,-1),SCENARIOS,classes.items()):
        candidates=rank[(rank.side==side)&(rank.scenario==sc)&rank.macro.isin(macros)]
        if not len(candidates):continue
        rule=candidates.iloc[0].to_dict();q=e[(e.family==rule['family'])&(e.tf==rule['tf'])&(e.side==side)].reset_index(drop=True)
        ids=select_indices(q,mask(q,rule['regime'],rule['phase'],rule['macro']));yr=q.year.to_numpy()
        periods={k:metric(q,ids[m[ids]],sc) for k,m in [('2019_2022',yr<=2022),('2023_2024',np.isin(yr,[2023,2024])),('2025',yr==2025),('2026_Q1',yr==2026)]}
        model=dict(ablation=cls,rule=rule,periods=periods,annual={str(y):metric(q,ids[yr[ids]==y],sc) for y in range(2019,2027)})
        selected.append(model);z=q.iloc[ids].copy();z['model_id']=f'{side}_{sc}_{cls}';traces.append(z)
    return rank,selected,pd.concat(traces,ignore_index=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--xau',type=Path,required=True);p.add_argument('--eur',type=Path,required=True);p.add_argument('--fred',type=Path,required=True);p.add_argument('--baseline',type=Path);p.add_argument('--out',type=Path,required=True);args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    def read(path):
        x=pd.read_csv(path,usecols=['timestamp','open','high','low','close','spread']);x.index=pd.to_datetime(x.pop('timestamp'),utc=True)
        assert x.index.is_monotonic_increasing and not x.index.has_duplicates
        assert x.notna().all().all();return x
    d=read(args.xau);eur=read(args.eur);fred=pd.read_csv(args.fred);pieces=[];audit={}
    for tf in (15,60,240):
        f=bars(d,tf);counts=d.close.resample(f'{tf}min',label='right',closed='left').count().reindex(f.index)
        # Formation bars need >=90% observed minutes; never interpolate missing data.
        f=f[counts>=.9*tf];z=formations(f,tf);e,meta=first_touches(d,z);pieces.append(e);audit[str(tf)]={'formations':len(z),'touches':len(e),**meta};print('ZONES',tf,audit[str(tf)],flush=True)
    if args.baseline:
        b=pd.read_csv(args.baseline);b['time_ns']=pd.to_datetime(b.touch,utc=True).array.asi8;b['pub_ns']=pd.to_datetime(b.publication,utc=True).array.asi8
        b['origin_ns']=b.pub_ns;b['i']=np.searchsorted(d.index.asi8,b.time_ns);b['family']='BASELINE_'+b.zone;b['tf']=0;b['side']=np.where(b.side=='BUY',1,-1);b['reference']=b.entry_reference;b['lo']=b.reference;b['hi']=b.reference;b['strength']=0.;b['age_hours']=(b.time_ns-b.pub_ns)/MIN/60
        pieces.append(b[['time_ns','pub_ns','origin_ns','i','family','tf','side','reference','lo','hi','strength','age_hours']])
    e=enrich(d,pd.concat(pieces,ignore_index=True),eur,fred)
    for k,v in labels(d,e).items():e[k]=v
    cost=labels(d,e,cost=True)
    for k in SCENARIOS:e[k+'_spread']=cost[k]
    e.to_csv(args.out/'all_events.csv.gz',index=False,compression='gzip');print('LABELED',len(e),flush=True)
    rank,selected,traces=search(e);rank.to_csv(args.out/'ranking.csv.gz',index=False,compression='gzip');traces.to_csv(args.out/'selected_ledger.csv.gz',index=False,compression='gzip')
    for model in selected:
        key=f"{model['rule']['side']}_{model['rule']['scenario']}_{model['ablation']}";z=traces[(traces.model_id==key)&(traces.year==2025)];sc=model['rule']['scenario']
        model['spread_proxy_2025']=float(z[sc+'_spread'].mean()) if len(z) else None
        test=model['periods']['2025'];model['observed80_n100']=test['n']>=100 and test['rate']>=.8;model['wilson80_n100']=test['n']>=100 and test['wilson_low']>=.8
    result=dict(contract='RIZAN_PRETOUCH_FIXED10_RESEARCH',live_changed=False,target_usd_per_oz=10,
                first=str(d.index[0]),last=str(d.index[-1]),rows=len(d),candidate_events=len(e),audit=audit,eligible_rule_scenarios=len(rank),
                input_sha256={k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in [('xau',args.xau),('eur',args.eur),('fred',args.fred)]},
                macro_vintage='Latest-vintage FRED, exploratory; yields observation +2 US federal business days 17ET; broad USD +14 calendar days 17ET. EURUSD completed M1 is a USD proxy, not DXY.',
                selection='Min Wilson train2019-22/validation2023-24, n>=150/100; no 2025/2026 ranking. 4h cooldown, max2/day per model. All periods reused in prior project research.',selected=selected)
    (args.out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False));print('DONE',len(rank),len(selected),flush=True)

if __name__=='__main__':main()
