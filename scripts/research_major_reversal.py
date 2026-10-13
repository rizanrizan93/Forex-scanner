"""10M major-reversal tuples ranked on cost-adjusted returns, not bounce rate.

Past 2024-25 was already seen: new qualification requires a locked 2026 test.
No capital/lot sizing/compounding, orders, cBot state, or database changes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fx_scanner.reversal_zones import normalize_bars
from fx_scanner.major_reversal import (GRID,SHAPE,CONTRACT,CONFIGURATIONS,COSTS,MIN_RR,MIN_ADR_FRACTION,
                                      features,events,config,filter_events)

FIELDS=['n','wins','target_hits','stops','r_sum','r_sq','gain','loss','stress_sum','reference_sum','risk_sum','tp_sum','points_sum']


@njit(cache=True)
def simulate(times,opens,high,low,close,starts,level,atr,adr,side):
    # Result: event,stop,target,horizon,cost; -9 status = ineligible/censored.
    n=len(starts)
    returns=np.zeros((n,5,5,4,3),np.float64)
    status=np.full((n,5,5,4,3),-9,np.int8)
    risks=np.zeros((n,5,5,4),np.float64)
    spreads=np.array([.25,.5,1.]);slips=np.array([.05,.1,.2])
    stops=np.array([.15,.25,.35,.5,.75]);targets=np.array([1.,1.5,2.,2.5,3.]);horizons=np.array([120,240,360,480])
    for e in range(n):
        begin=starts[e]
        rollover=(times[begin]//86400)*86400+20*3600+55*60
        for si in range(5):
            sl=level[e]-side*stops[si]*atr[e]
            entry_stress=opens[begin]+(1. if side==1 else 0.)+side*.2
            stress_risk=side*(entry_stress-sl)
            if stress_risk<=.35: continue
            for ti in range(5):
                move=targets[ti]*atr[e]
                # All scenarios use the same eligible observation set. Net
                # target reward, including exit slip, must exceed 1.5x risk.
                if move<MIN_ADR_FRACTION*adr[e] or (move-.2)/stress_risk<MIN_RR: continue
                for hi in range(4):
                    end=min(times[begin]+horizons[hi]*60,rollover)
                    for ci in range(3):
                        entry=opens[begin]+(spreads[ci] if side==1 else 0.)+side*slips[ci]
                        risk=side*(entry-sl)
                        if risk<=0: continue
                        tp=entry+side*move
                        prev=times[begin]-60
                        state=-9;exit_price=0.
                        for j in range(begin,len(times)):
                            if times[j]>=end:
                                if j>begin and times[j-1]>=end-300:
                                    exit_price=close[j-1]+(spreads[ci] if side==-1 else 0.)-side*slips[ci]
                                    state=0
                                break
                            if times[j]-prev>300: break
                            prev=times[j]
                            invalid=low[j]<=sl if side==1 else high[j]+spreads[ci]>=sl
                            reached=high[j]>=tp if side==1 else low[j]+spreads[ci]<=tp
                            if invalid:
                                exit_price=(min(sl,opens[j]) if side==1 else max(sl,opens[j]+spreads[ci]))-side*slips[ci]
                                state=-1;break
                            if reached:
                                exit_price=tp-side*slips[ci]
                                state=1;break
                        if state!=-9:
                            returns[e,si,ti,hi,ci]=side*(exit_price-entry)/risk
                            status[e,si,ti,hi,ci]=state
                        if ci==1: risks[e,si,ti,hi]=risk
    return returns,status,risks


def labelled(m1,rows,side):
    times=m1.index.asi8//10**9;signal=rows.index.asi8//10**9
    starts=np.searchsorted(times,signal)
    good=starts<len(m1);good[good]&=times[starts[good]]==signal[good]
    rows=rows.loc[good]
    return rows,simulate(times,m1.open.to_numpy(),m1.high.to_numpy(),m1.low.to_numpy(),m1.close.to_numpy(),
        starts[good],rows.level.to_numpy(),rows.atr.to_numpy(),rows.adr20.to_numpy(),side)


def expanded(hist):
    hist=np.flip(np.cumsum(np.flip(hist,axis=0),axis=0),axis=0)
    hist=np.flip(np.cumsum(np.flip(hist,axis=1),axis=1),axis=1)
    hist=np.cumsum(hist,axis=2)
    return np.concatenate([hist.sum(axis=3,keepdims=True),hist],axis=3).transpose(0,3,1,2,4)


def shard(csv,year,output):
    m1=normalize_bars(pd.read_csv(csv));frame=features(m1)
    arrays={name:np.zeros(SHAPE,np.float32) for name in FIELDS}
    for sid,side in enumerate(GRID['side']):
        for li,lb in enumerate(GRID['lookback_h1']):
            for wi,width in enumerate(GRID['half_width_atr']):
                rows=events(frame,side,lb,width).query('year==@year')
                rows,(r,s,risk)=labelled(m1,rows,side)
                bins=tuple(rows[c].to_numpy(int) for c in ['wick_bin','approach_bin','age_bin','trend_bin','session'])
                for si in range(5):
                    for ti in range(5):
                        for hi in range(4):
                            mask=(s[:,si,ti,hi]!=-9).all(axis=1)
                            rr=r[mask,si,ti,hi,1];rs=risk[mask,si,ti,hi]
                            st=s[mask,si,ti,hi,1]
                            values=[np.ones(len(rr)),rr>0,st==1,st==-1,rr,rr*rr,np.maximum(rr,0),np.maximum(-rr,0),
                                r[mask,si,ti,hi,2],r[mask,si,ti,hi,0],rs,
                                GRID['reaction_atr'][ti]*rows.atr.to_numpy()[mask],rr*rs]
                            for name,value in zip(FIELDS,values):
                                hist=np.zeros((5,5,5,3,4),np.float64)
                                np.add.at(hist,tuple(x[mask] for x in bins),value)
                                arrays[name][sid,li,wi,si,ti,hi]=expanded(hist)
                print(f'MAJOR_BASE year={year} side={side} lookback={lb} width={width} observations={len(rows)}',flush=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(output,**arrays)
    meta={'year':year,'contract':CONTRACT,'configurations':CONFIGURATIONS,'source_sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),
          'year_rows':int((m1.index.year==year).sum()),'first_utc':m1.index[0].isoformat(),'last_utc':m1.index[-1].isoformat()}
    output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')


def summary(data):
    n=float(data['n']);mean=data['r_sum']/max(n,1)
    var=max(0.,float(data['r_sq'])/max(n,1)-mean*mean)
    return {'n':int(round(n)),'win_rate':float(data['wins']/n) if n else None,
        'target_hit_rate':float(data['target_hits']/n) if n else None,'stop_rate':float(data['stops']/n) if n else None,
        'mean_net_r':float(mean),'net_r_sum':float(data['r_sum']),
        'profit_factor':float(data['gain']/data['loss']) if data['loss']>0 else None,
        'mean_stress_r':float(data['stress_sum']/max(n,1)), 'mean_reference_r':float(data['reference_sum']/max(n,1)),
        'mean_risk_points':float(data['risk_sum']/max(n,1)), 'mean_target_points':float(data['tp_sum']/max(n,1)),
        'mean_net_points':float(data['points_sum']/max(n,1)),
        'descriptive_lcb_mean_r':float(mean-1.96*np.sqrt(var/max(n,1)))}


def select(train,val,good_years,val_good_years,min_train=180,min_val=60,required_train_years=5,required_val_years=3):
    n=np.maximum(val['n'],1);mean=val['r_sum']/n
    variance=np.maximum(val['r_sq']/n-mean*mean,0)
    score=mean-1.96*np.sqrt(variance/n)
    eligible=((train['n']>=min_train)&(val['n']>=min_val)&(train['r_sum']>0)&
        (train['gain']>=1.15*train['loss'])&(val['gain']>=1.2*val['loss'])&
        (val['stress_sum']>0)&(score>0)&(good_years>=required_train_years)&(val_good_years>=required_val_years))
    result=[]
    for sid in range(2):
        candidate=np.flatnonzero(eligible[sid].ravel())
        if len(candidate):
            chosen=int(candidate[np.argsort(score[sid].ravel()[candidate],kind='stable')[-1]])
            idx=(sid,)+np.unravel_index(chosen,SHAPE[1:])
            result.append({'index':int(np.ravel_multi_index(idx,SHAPE)),'config':config(idx),
                          'train':summary({k:v[idx] for k,v in train.items()}),
                          'validation':summary({k:v[idx] for k,v in val.items()})})
    return result


def aggregate(folder,output):
    paths={int(p.stem.split('-')[-1]):p for p in folder.rglob('major-*.npz')}
    if set(paths)!=set(range(2016,2026)):raise ValueError('TEN_YEARS_REQUIRED')
    # Sufficient statistics kept in float64 while accumulating float32 shards.
    train={k:np.zeros(SHAPE,np.float64) for k in FIELDS};val={k:np.zeros(SHAPE,np.float64) for k in FIELDS}
    good_train=np.zeros(SHAPE,np.int8);good_val=np.zeros(SHAPE,np.int8)
    for year,p in sorted(paths.items()):
        with np.load(p) as d:
            dest=train if year<=2021 else val
            for k in FIELDS:dest[k]+=d[k]
            good=(d['n']>=15)&(d['r_sum']>0)
            if year<=2021:good_train+=good
            else:good_val+=good
        print('MAJOR_AGGREGATE_YEAR',year,flush=True)
    selected=select(train,val,good_train,good_val)
    # Freeze side-specific winners before fetching/reading ANY 2026 prices.
    lock=hashlib.sha256(json.dumps(selected,sort_keys=True).encode()).hexdigest()
    for winner in selected:
        idx=np.unravel_index(winner['index'],SHAPE)
        winner['year_metrics']={}
        for year,p in sorted(paths.items()):
            with np.load(p) as d:winner['year_metrics'][str(year)]=summary({k:d[k][idx] for k in FIELDS})
    del train,val,good_train,good_val
    # Rolling selection: test year Y never participates in selecting its config.
    # Still exploratory because the family was designed after prior research.
    wf_train={k:np.zeros(SHAPE,np.float64) for k in FIELDS}
    wf_good=np.zeros(SHAPE,np.int8);previous=None;walk_forward=[]
    for year,p in sorted(paths.items()):
        if year>=2020:
            vg=(previous['n']>=15)&(previous['r_sum']>0)
            picked=select(wf_train,previous,wf_good,vg.astype(np.int8),min_train=120,min_val=30,
                required_train_years=max(2,int(.75*(year-2017))),required_val_years=1)
            with np.load(p) as d:
                for w in picked:
                    idx=np.unravel_index(w['index'],SHAPE)
                    w['test_year']=year;w['test']=summary({k:d[k][idx] for k in FIELDS})
            walk_forward.append({'test_year':year,'selection_data_max_year':year-1,'selected':picked})
        if previous is not None:
            for k in FIELDS:wf_train[k]+=previous[k]
            wf_good+=((previous['n']>=15)&(previous['r_sum']>0))
        with np.load(p) as d:previous={k:d[k].copy() for k in FIELDS}
        print('MAJOR_WALK_FORWARD_YEAR',year,flush=True)
    result={'contract':CONTRACT,'configurations_evaluated':CONFIGURATIONS,'grid':GRID,'cost_scenarios':COSTS,
        'min_reward_risk_stress':MIN_RR,'min_target_adr20_fraction':MIN_ADR_FRACTION,
        'selected_by_side':selected,'walk_forward':walk_forward,'candidate_lock_sha256':lock,'status':'LOCKED_FOR_2026_TEST' if selected else 'NO_QUALIFIED_CANDIDATE',
        'execution_authority':False,'execution_influence':False,'train':'2016-2021','validation':'2022-2025 (already seen history)',
        'fresh_test':'2026-01-01 through 2026-09-30, fetched only AFTER this lock',
        'source_years':[json.loads(p.with_suffix('.json').read_text()) for p in paths.values()],
        'limitations':['Historical bid M1 and synthetic spread/slippage, not broker historical bid/ask.',
            '2024-2025 already seen; cannot claim pristine holdout on that period.',
            'Eight-hour non-overlap per base, configurations dependent; descriptive confidence not multiple-testing corrected.',
            'PF and R are equal nominal risk model, not equity/lot sizing or cBot backtest.',
            'Costs modeled each fill; timeout closes at market; stops fill worse on adverse opening gap; no overnight positions.',
            'No claim of one reversal every day; report observed frequency and missing days.']}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print('MAJOR_SEARCH_LOCKED configurations=',CONFIGURATIONS,'winners=',len(selected),'lock=',lock,flush=True)


def candidate_ledger(csv,year,result,output):
    m1=normalize_bars(pd.read_csv(csv))
    if year==2026:m1=m1.loc[m1.index<pd.Timestamp('2026-10-01T00:00Z')]
    frame=features(m1);ledger=[]
    for winner in result['selected_by_side']:
        cfg=winner['config'];rows=events(frame,cfg['side'],cfg['lookback_h1'],cfg['half_width_atr']).query('year==@year')
        rows=rows.loc[filter_events(rows,cfg)]
        rows,(r,s,risk)=labelled(m1,rows,cfg['side'])
        si=GRID['invalidation_atr'].index(cfg['invalidation_atr']);ti=GRID['reaction_atr'].index(cfg['reaction_atr']);hi=GRID['horizon_minutes'].index(cfg['horizon_minutes'])
        for i,stamp in enumerate(rows.index):
            if (s[i,si,ti,hi]==-9).any():continue
            ledger.append({'index':winner['index'],'at_utc':stamp.isoformat(),'year':year,'month':stamp.strftime('%Y-%m'),
                'hour_utc':stamp.hour,'r_reference':float(r[i,si,ti,hi,0]),'r_cautious':float(r[i,si,ti,hi,1]),
                'r_stress':float(r[i,si,ti,hi,2]),'status':int(s[i,si,ti,hi,1]),
                'risk_points':float(risk[i,si,ti,hi]),'target_points':float(cfg['reaction_atr']*rows.atr.iloc[i])})
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(ledger)+'\n')


def ledger_metrics(rows):
    r=np.array([x['r_cautious'] for x in rows]);eq=np.r_[0,np.cumsum(r)]
    metrics=summary({'n':len(r),'wins':(r>0).sum(),'target_hits':sum(x['status']==1 for x in rows),
        'stops':sum(x['status']==-1 for x in rows),'r_sum':r.sum(),'r_sq':(r*r).sum(),
        'gain':np.maximum(r,0).sum(),'loss':np.maximum(-r,0).sum(),
        'stress_sum':sum(x['r_stress'] for x in rows),'reference_sum':sum(x['r_reference'] for x in rows),
        'risk_sum':sum(x['risk_points'] for x in rows),'tp_sum':sum(x['target_points'] for x in rows),
        'points_sum':sum(x['r_cautious']*x['risk_points'] for x in rows)})
    metrics['max_drawdown_r']=float(np.max(np.maximum.accumulate(eq)-eq))
    return metrics


def verify_ledgers(folder,result,output):
    paths={int(p.stem.split('-')[-1]):p for p in folder.rglob('ledger-*.json')}
    if set(paths)!=set(range(2016,2027)):raise ValueError('ELEVEN_YEAR_LEDGERS_REQUIRED')
    rows=[]
    for p in paths.values():rows.extend(json.loads(p.read_text()))
    all_rows=pd.DataFrame(rows)
    for winner in result['selected_by_side']:
        chosen=sorted([x for x in rows if x['index']==winner['index']],key=lambda x:x['at_utc'])
        metrics={str(y):ledger_metrics([x for x in chosen if x['year']==y]) for y in range(2016,2027)}
        for y in range(2016,2026):
            expected=winner['year_metrics'][str(y)]
            assert metrics[str(y)]['n']==expected['n'],'COUNT_PARITY'
            assert abs(metrics[str(y)]['net_r_sum']-expected['net_r_sum'])<.001,'NET_R_PARITY'
        historical=[x for x in chosen if x['year']<2026]
        winner['historical_ledger']=ledger_metrics(historical)
        test=[x for x in chosen if x['year']==2026];winner['fresh_2026']=ledger_metrics(test)
        winner['fresh_2026']['trades_per_month']=len(test)/9
        # Block-month uncertainty, not a claim of independent trades.
        monthly=[]
        for month in sorted(set(x['month'] for x in test)):
            rr=[x['r_cautious'] for x in test if x['month']==month];monthly.append([len(rr),sum(rr)])
        if monthly:
            blocks=np.array(monthly);rng=np.random.default_rng(20261013)
            draws=blocks[rng.integers(0,len(blocks),size=(10000,len(blocks)))].sum(axis=1)
            ci=np.quantile(draws[:,1]/draws[:,0],[.025,.975]).tolist()
        else:ci=[None,None]
        winner['fresh_2026']['month_block_mean_r_ci95']=ci
        o=winner['fresh_2026']
        winner['qualified']=bool(o['n']>=30 and o['mean_net_r']>0 and (o['profit_factor'] or 0)>=1.2
            and o['mean_stress_r']>0 and ci[0] is not None and ci[0]>0)
        # Best one-hour window chosen using 2016-25 only, then test 2026.
        hourly=[]
        for hour in range(24):
            old=[x for x in historical if x['hour_utc']==hour]
            met=ledger_metrics(old)
            if met['n']>=50:hourly.append({'hour_utc':hour,'hour_wib':(hour+7)%24,**met})
        best=max(hourly,key=lambda x:x['descriptive_lcb_mean_r']) if hourly else None
        winner['best_hour_historical']=best
        if best:winner['best_hour_2026']=ledger_metrics([x for x in test if x['hour_utc']==best['hour_utc']])
        winner['verified_year_metrics']=metrics
    result['status']='VALIDATED_2026' if any(x['qualified'] for x in result['selected_by_side']) else 'RESEARCH_ONLY'
    result['execution_authority']=False;result['execution_influence']=False
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print('MAJOR_VERIFICATION_COMPLETE status=',result['status'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--csv',type=Path);p.add_argument('--year',type=int)
    p.add_argument('--shards',type=Path);p.add_argument('--ledgers',type=Path);p.add_argument('--candidates',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.ledgers:verify_ledgers(a.ledgers,json.loads(a.candidates.read_text()),a.output)
    elif a.shards:aggregate(a.shards,a.output)
    elif a.candidates:candidate_ledger(a.csv,a.year,json.loads(a.candidates.read_text()),a.output)
    else:shard(a.csv,a.year,a.output)
