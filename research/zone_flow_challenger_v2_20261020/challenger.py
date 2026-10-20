from pathlib import Path
import json,importlib.util,hashlib,math
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parent

def upstream():
    p=ROOT/'upstream'/'manual_reversal_map.py'
    spec=importlib.util.spec_from_file_location('manual_original',p)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

def load_day(day):
    at=pd.Timestamp(day,tz='UTC');days=[str((at-pd.Timedelta(days=i)).date()) for i in [3,2,1,0]]
    xs=[np.load(ROOT/'derived'/f'{d}_book.npz') for d in days]
    raw=np.concatenate([x['exchange_ms'] for x in xs]);t=np.concatenate([x['available_ms'] for x in xs]);q=np.concatenate([x['quotes'] for x in xs])
    assert np.all(np.diff(t)==1000)
    mid=(q[:,0]+q[:,1])/2
    f=pd.DataFrame({'mid':mid},index=pd.to_datetime(raw,unit='ms',utc=True))
    bars={}
    for tf,rule in [('M1','1min'),('M5','5min'),('M15','15min'),('H1','1h'),('H4','4h')]:
        b=f.mid.resample(rule,closed='left',label='left').ohlc()
        b.index.name='timestamp';b['count']=f.mid.resample(rule).count();bars[tf]=b
    h=bars['H1'];tr=pd.concat([h.high-h.low,(h.high-h.close.shift()).abs(),(h.low-h.close.shift()).abs()],axis=1).max(axis=1)
    h['atr']=tr.rolling(14).mean()
    return raw,t,q,mid,bars

def born_zones(h1):
    mod=upstream();seen=set();zones=[]
    rows=h1.dropna(subset=['open','high','low','close']).reset_index().to_dict('records')
    for n in range(24,len(rows)+1):
        now=pd.Timestamp(rows[n-1]['timestamp'])+pd.Timedelta(hours=1)
        for z in mod.detect(rows[:n],'H1',now):
            if z['zone_id'] in seen:continue
            seen.add(z['zone_id']);z=dict(z)
            z['effective_ms']=max(pd.Timestamp(z['available_at']).value//1_000_000,now.value//1_000_000)
            zones.append(z)
    return zones

def context(h4,ms):
    ready=h4.loc[h4.index+pd.Timedelta(hours=4)<=pd.to_datetime(ms,unit='ms',utc=True)]
    if len(ready)<2:return 'UNKNOWN'
    a,b=ready.iloc[-2],ready.iloc[-1]
    if b.high>a.high and b.low>a.low:return 'BULL'
    if b.high<a.high and b.low<a.low:return 'BEAR'
    return 'RANGE'

def opportunities(day,raw,t,mid,bars):
    begin=pd.Timestamp(day,tz='UTC').value//1_000_000;end=begin+86_400_000
    births=born_zones(bars['H1']);events=[]
    for z in births:
        side=1 if z['direction']=='BUY' else -1
        a=np.searchsorted(t,z['effective_ms']);b=np.searchsorted(t,min(z['effective_ms']+43_200_000,end))
        if a>=b:continue
        proximal=z['high'] if side==1 else z['low']
        hit=np.flatnonzero(side*(mid[a:b]-proximal)<=0)
        if not len(hit):continue
        j=a+hit[0]
        if not begin<=t[j]<end:continue
        events.append({'day':day,'family':'H1_SD','event_id':day+'|'+z['zone_id'],'zone_id':z['zone_id'],
                       'available_ms':z['effective_ms'],'touch_ms':int(t[j]),'touch_ix':int(j),'side':side,
                       'low':z['low'],'high':z['high'],'atr':z['atr'],'bos':z['structural_bos']})
    # Prior known extremes, not extrema of the touch candle.
    m=bars['M15'].copy();m['hi']=m.high.shift().rolling(16).max();m['lo']=m.low.shift().rolling(16).min()
    for at,r in m.loc[(m.index>=pd.Timestamp(day,tz='UTC'))].iterrows():
        ms=at.value//1_000_000
        h=bars['H1'].loc[bars['H1'].index+pd.Timedelta(hours=1)<=at]
        if h.empty or not np.isfinite(h.atr.iloc[-1]):continue
        a=np.searchsorted(t,ms);b=np.searchsorted(t,ms+900_000)
        hit=np.flatnonzero((mid[a:b]<=r.lo)|(mid[a:b]>=r.hi))
        if not len(hit):continue
        j=a+hit[0];side=1 if mid[j]<=r.lo else -1;level=r.lo if side==1 else r.hi
        # Explicit band geometry so invalidation is identical across timing variants.
        atr=h.atr.iloc[-1];low=level-.5*atr if side==1 else level;high=level if side==1 else level+.5*atr
        events.append({'day':day,'family':'M15_EXTREME_CONTROL','event_id':day+'|M15|'+str(ms),'zone_id':'M15|'+str(ms),
                       'available_ms':ms,'touch_ms':int(t[j]),'touch_ix':int(j),'side':side,'low':low,'high':high,
                       'atr':atr,'bos':False})
    for e in events:
        s=e['side'];e['proximal']=e['high'] if s==1 else e['low'];e['distal']=e['low'] if s==1 else e['high']
        e['stop']=e['distal']-s*.1*e['atr'];e['h4_context']=context(bars['H4'],e['touch_ms'])
        e['h4_aligned']=e['h4_context']==('BULL' if s==1 else 'BEAR')
        a=max(0,e['touch_ix']-900);history=mid[a:e['touch_ix']]
        e['sweep_level']=float(np.nanmin(history) if s==1 else np.nanmax(history))
        # Candidate opposing destinations must exist and remain valid as-of touch.
        ready=bars['H1'].loc[bars['H1'].index+pd.Timedelta(hours=1)<=pd.to_datetime(e['touch_ms'],unit='ms',utc=True)]
        dest=[]
        for z in births:
            zs=1 if z['direction']=='BUY' else -1
            if zs==s or z['effective_ms']>e['touch_ms']:continue
            future=ready.loc[ready.index>=pd.to_datetime(z['effective_ms'],unit='ms',utc=True)]
            if (zs*(future.close-z['invalidation'])<0).any():continue
            price=z['low'] if s==1 else z['high']
            if s*(price-e['proximal'])>0:dest.append(price)
        e['opposing_target_at_touch']=float(min(dest) if s==1 else max(dest)) if dest else None
        assert e['available_ms']<=e['touch_ms']
    return sorted(events,key=lambda e:(e['touch_ms'],e['event_id'])),births

def flow_arrays(day,t):
    z=np.load(ROOT/'derived'/f'{day}_trades.npz')
    # Bin trades into the first grid tick strictly AFTER arrival.
    ix=np.searchsorted(t*1000,z['available_us'],side='right')
    ok=(ix>=0)&(ix<len(t));notional=z['price']*z['amount']
    buy=np.bincount(ix[ok&(z['side']==1)],weights=notional[ok&(z['side']==1)],minlength=len(t))
    sell=np.bincount(ix[ok&(z['side']==-1)],weights=notional[ok&(z['side']==-1)],minlength=len(t))
    b15=pd.Series(buy).rolling(15,min_periods=15).sum().to_numpy()
    s15=pd.Series(sell).rolling(15,min_periods=15).sum().to_numpy()
    bp=pd.Series(b15).shift().rolling(1800,min_periods=1800).quantile(.75).to_numpy()
    sp=pd.Series(s15).shift().rolling(1800,min_periods=1800).quantile(.75).to_numpy()
    start=pd.Timestamp(day,tz='UTC').value//1_000_000
    ready=t>=start+1_815_000
    return {'tape':z,'buy15':b15,'sell15':s15,'buy_p75':bp,'sell_p75':sp,'ready':ready,
            'first_arrival_us':int(z['available_us'][0]),'last_arrival_us':int(z['available_us'][-1])}

def absorption(e,t,q,mid,flow):
    if not flow['ready'][e['touch_ix']]:return None,'NO_TAPE_WARMUP_AT_TOUCH'
    side=e['side'];a=e['touch_ix'];end=min(a+600,len(t)-1)
    counter=flow['sell15'] if side==1 else flow['buy15'];threshold=flow['sell_p75'] if side==1 else flow['buy_p75']
    total=flow['buy15']+flow['sell15'];tape=flow['tape'];swept=False
    best=None
    for j in range(a,end+1):
        if not np.isfinite(mid[j]):return None,'BOOK_GAP_BEFORE_SIGNAL'
        if side*((q[j,0] if side==1 else q[j,1])-e['stop'])<=0:return None,'ZONE_INVALIDATED_BEFORE_SIGNAL'
        swept=swept or bool(side*(mid[j]-e['sweep_level'])<0)
        if not swept or not flow['ready'][j] or j<15:continue
        if not (counter[j]>=threshold[j]>0 and total[j]>0 and counter[j]/total[j]>=.6):continue
        if np.isfinite(mid[j-14:j+1]).sum()<10:continue
        adverse=max(0.,-side*(mid[j]-mid[j-14]))
        if adverse>.1*e['atr']:continue
        if not e['low']-.25*e['atr']<=mid[j]<=e['high']+.25*e['atr']:continue
        # Trade evidence must have occurred around this exact zone, not elsewhere.
        u=np.searchsorted(tape['available_us'],(t[j]-15000)*1000,side='left')
        v=np.searchsorted(tape['available_us'],t[j]*1000,side='left')
        loc=(tape['price'][u:v]>=e['low']-.1*e['atr'])&(tape['price'][u:v]<=e['high']+.1*e['atr'])&(tape['side'][u:v]==-side)
        near=float(np.sum(tape['price'][u:v][loc]*tape['amount'][u:v][loc]))
        if near<=0:continue
        den=q[j,2]+q[j,3];imb=(q[j,2]-q[j,3])/den if den>0 else np.nan
        allied=2 if side==1 else 3;depth=q[j,allied];prior=q[max(0,j-14),allied]
        best={'signal_ms':int(t[j]),'signal_ix':j,'counter_notional_15s':float(counter[j]),
              'counter_p75':float(threshold[j]),'counter_share':float(counter[j]/total[j]),
              'counter_notional_near_zone':near,'adverse_progress_ATR':float(adverse/e['atr']),
              'aligned_depth_imbalance':float(side*imb),'near_depth_retention_proxy':float(depth/prior) if prior>0 else None,
              'trade_last_available_us':int(tape['available_us'][v-1]) if v>u else None,
              'swept':True,'probability':None,'execution_influence':False}
        assert best['trade_last_available_us']<best['signal_ms']*1000
        break
    return best,'ABSORPTION_PROXY_OBSERVED' if best else 'NO_ABSORPTION_WITHIN10M'

def reclaim(e,signal,t,q,mid,bars):
    a=signal['signal_ms'];end=a+600_000;side=e['side']
    closes=bars['M1'].index.asi8//1_000_000+60_000
    candidates=bars['M1'].loc[(closes>a)&(closes<=end)]
    for at,r in candidates.iterrows():
        close_ms=at.value//1_000_000+60_000
        if not a<close_ms<=end:continue
        j=np.searchsorted(t,close_ms)
        begin=signal['signal_ix']
        px=q[begin:j+1,0 if side==1 else 1]
        if np.any(~np.isfinite(px)) or np.any(side*(px-e['stop'])<=0):return None,'INVALIDATED_OR_GAP_BEFORE_RECLAIM'
        if side*(r.close-e['proximal'])>0:
            return int(close_ms),'M1_RECLAIM_CLOSED'
    return None,'NO_M1_RECLAIM_WITHIN10M'

def simulate(e,decision_ms,t,q,horizon):
    if decision_ms is None:return {'status':'NO_ENTRY_SIGNAL'}
    j=np.searchsorted(t,decision_ms+1000)
    if j>=len(t) or not np.isfinite(q[j,0]):return {'status':'NO_ENTRY_QUOTE'}
    side=e['side'];entry=q[j,1 if side==1 else 0];risk=side*(entry-e['stop'])
    if not .15*e['atr']<=risk<=4*e['atr']:return {'status':'INVALID_RISK'}
    cap=np.searchsorted(t,t[j]+horizon*60_000)
    if cap>=len(t):return {'status':'RIGHT_CENSORED'}
    target=entry+side*risk;px=q[j:cap+1,0 if side==1 else 1]
    stop=side*(px-e['stop'])<=0;tp=side*(px-target)>=0;bad=~np.isfinite(px)
    hits=np.flatnonzero(stop|tp|bad);k=int(hits[0]) if len(hits) else len(px)-1
    if bad[k]:return {'status':'QUOTE_GAP_CENSORED'}
    ex=float(px[k]);duration=(t[j+k]-t[j])/1000;gross=side*(ex-entry)
    cost=(entry+ex)*.00065+entry*.0003*duration/86400
    favorable=side*(px[:k+1]-entry)/risk
    result={'status':'COMPLETE','decision_ms':int(decision_ms),'entry_ms':int(t[j]),'exit_ms':int(t[j+k]),
            'entry_px':float(entry),'exit_px':ex,'risk_usd_per_btc':float(risk),'target':float(target),
            'reason':'STOP' if stop[k] else 'TARGET' if tp[k] else 'TIMEOUT','duration_s':duration,
            'gross_R':float(gross/risk),'cost_R':float(cost/risk),'MFE_R':float(max(0,np.nanmax(favorable))),
            'MAE_R':float(max(0,-np.nanmin(favorable)))}
    destination=e.get('opposing_target_at_touch')
    result['opposing_room_R_at_entry']=float(side*(destination-entry)/risk) if destination is not None else None
    for multiple in (1,1.5,2):result[f'net_R_{multiple:g}x']=float((gross-multiple*cost)/risk)
    return result

def phase_times(e,t,q,mid,bars):
    """Actual repo M15->M5 closed-candle semantics on growing prefixes."""
    mod=upstream();out=[]
    zone={'zone_id':e['zone_id'],'direction':'BUY' if e['side']==1 else 'SELL',
          'available_at':pd.to_datetime(e['available_ms'],unit='ms',utc=True).isoformat(),
          'low':e['low'],'high':e['high'],'invalidation':e['stop']}
    start=e['touch_ms'];side=e['side'];a=e['touch_ix']
    for ms in np.arange((start//300_000+1)*300_000,start+3_600_000,300_000):
        j=np.searchsorted(t,ms)
        if j>=len(t):break
        px=q[a:j+1,0 if side==1 else 1]
        if np.any(~np.isfinite(px)) or np.any(side*(px-e['stop'])<=0):break
        now=pd.to_datetime(ms,unit='ms',utc=True)
        frames={}
        for tf,minutes in [('M15',15),('M5',5)]:
            b=bars[tf];closed=b.index+pd.Timedelta(minutes=minutes)
            lookback=8*60 if tf=='M15' else 120
            frames[tf]=b.loc[(closed<=now)&(b.index>=now-pd.Timedelta(minutes=lookback))].reset_index()
        r=mod.reversal_phase(zone,frames,float(mid[j]),now)
        if r['phase']=='KONFIRMASI_STRUKTUR':
            confirmed=pd.Timestamp(r['confirmation_m5_at']).value//1_000_000
            out.append({'observed_ms':int(ms),'m15_closed_ms':pd.Timestamp(r['rejection_m15_at']).value//1_000_000,
                        'm5_closed_ms':int(confirmed),'phase':r['phase']})
    return out

def summarize(ledger):
    rows=[]
    # Each baseline-complete event establishes the matched opportunity denominator.
    for (split,family,horizon),g in ledger.groupby(['split','family','horizon_min']):
        base=g[(g.variant=='baseline_first_touch')&(g.status=='COMPLETE')&g.tape_ready]
        ids=set(base.event_id)
        for variant,v in g.groupby('variant'):
            accepted=v[(v.status=='COMPLETE')&v.event_id.isin(ids)].sort_values(['entry_ms','event_id'])
            for scope in ('event_study','one_position'):
                x=accepted
                if scope=='one_position':
                    keep=[];last=-1
                    for idx,r in x.iterrows():
                        if r.entry_ms>last:keep.append(idx);last=r.exit_ms
                    x=x.loc[keep]
                for multiple in (1,1.5,2):
                    p=x[f'net_R_{multiple:g}x'];loss=-p[p<0].sum();n=len(x)
                    cum=np.r_[0,np.cumsum(p)];dd=np.maximum.accumulate(cum)-cum
                    rows.append({'split':split,'family':family,'horizon_min':horizon,'variant':variant,'scope':scope,
                                 'cost_multiple':multiple,'baseline_opportunities':len(ids),'n':n,'coverage_pct':100*n/len(ids) if ids else None,
                                 'wins':int((p>0).sum()),'win_pct':100*(p>0).mean() if n else None,
                                 'mean_net_R':p.mean() if n else None,'PF_R':p[p>0].sum()/loss if loss>0 else None,
                                 'sum_net_R':p.sum(),'max_cumulative_R_drawdown':dd.max() if n else None,
                                 'mean_R_per_baseline_opportunity':p.sum()/len(ids) if ids else None,
                                 'target_first_n':int(x.reason.eq('TARGET').sum()),'stop_first_n':int(x.reason.eq('STOP').sum()),
                                 'timeout_n':int(x.reason.eq('TIMEOUT').sum())})
    return pd.DataFrame(rows)

def main():
    cfg=json.loads((ROOT/'LOCKED_PROTOCOL.json').read_text());ledgers=[];obs=[];zone_rows=[];phases=[]
    for day in cfg['sample_days']:
        raw,t,q,mid,bars=load_day(day);events,births=opportunities(day,raw,t,mid,bars);flow=flow_arrays(day,t)
        print(day,'births',len(births),'touch events',len(events),flush=True)
        for e in events:
            e['tape_ready']=bool(flow['ready'][e['touch_ix']])
            zone_rows.append(e)
            signal,why=absorption(e,t,q,mid,flow)
            rec,recwhy=reclaim(e,signal,t,q,mid,bars) if signal else (None,'NO_ABSORPTION')
            phase=phase_times(e,t,q,mid,bars)
            plain_phase=phase[0]['observed_ms'] if phase else None
            after=[x for x in phase if signal and x['m5_closed_ms']>signal['signal_ms']]
            flow_phase=after[0]['observed_ms'] if after else None
            phases.extend({'event_id':e['event_id'],**x} for x in phase)
            obs.append({**e,'absorption_reason':why,'reclaim_reason':recwhy,'reclaim_ms':rec,
                        'baseline_m15_m5_ms':plain_phase,'absorption_m15_m5_ms':flow_phase,
                        **({**signal} if signal else {'signal_ms':None})})
            for variant,decision in [('baseline_first_touch',e['touch_ms']),('absorption_early',signal['signal_ms'] if signal else None),('absorption_reclaim',rec),('baseline_M15_M5',plain_phase),('absorption_M15_M5',flow_phase)]:
                for horizon in cfg['horizons_minutes']:
                    r={**e,'variant':variant,'horizon_min':horizon,'split':'development' if day in cfg['development'] else 'holdout',
                       'signal_reason':why,'reclaim_reason':recwhy,**simulate(e,decision,t,q,horizon)}
                    ledgers.append(r)
    ledger=pd.DataFrame(ledgers)
    for name in ['available_ms','touch_ms','decision_ms','entry_ms','exit_ms']:
        ledger[name.replace('_ms','_utc')]=pd.to_datetime(ledger[name],unit='ms',utc=True)
    ledger.to_csv(ROOT/'EVENT_LEDGER.csv',index=False)
    pd.DataFrame(obs).to_csv(ROOT/'ORDERFLOW_EVIDENCE.csv',index=False)
    pd.DataFrame(zone_rows).to_csv(ROOT/'ZONE_OPPORTUNITIES.csv',index=False)
    pd.DataFrame(phases).to_csv(ROOT/'M15_M5_PHASE_EVIDENCE.csv',index=False)
    s=summarize(ledger);s.to_csv(ROOT/'COMPARISON.csv',index=False)
    audit={'zone_opportunities':len(zone_rows),'by_day':pd.DataFrame(zone_rows).groupby(['day','family']).size().to_dict(),
           'status_counts':ledger.status.value_counts().to_dict(),'absorption_reasons':pd.DataFrame(obs).absorption_reason.value_counts().to_dict(),
           'source_manual_sha256':hashlib.sha256((ROOT/'upstream'/'manual_reversal_map.py').read_bytes()).hexdigest(),
           'execution_influence':False,'probability':None,'live_modified':False}
    audit['by_day']={str(k):v for k,v in audit['by_day'].items()}
    (ROOT/'RESULT_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(s[(s.split=='holdout')&(s.scope=='one_position')&(s.cost_multiple==1)].to_string(index=False),flush=True)
    print(json.dumps(audit,indent=2),flush=True)

if __name__=='__main__':main()
