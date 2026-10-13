"""20M H4/D1 tuples streamed by source; no cBot execution dependencies."""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fx_scanner.h4_d1_reversal import GRID,SHAPE,LOCAL_SHAPE,CONFIGURATIONS,CONTRACT,COSTS,MIN_RR,MIN_ADR_FRACTION,features,events,config,filter_events
from fx_scanner.reversal_zones import normalize_bars
from research_daily_reversal import simulate,summary,ledger_metrics
FIELDS=['n','wins','target_hits','stops','r_sum','r_sq','gain','loss','stress_sum','reference_sum','risk_sum','tp_sum','points_sum','censored']

@njit(cache=True)
def statistics(days,wick,regime,age,flags,session,r,s,risk,adr):
    # r,s: observation × stop × target × horizon × cost.
    out=np.zeros((5,5,4,5,4,5,5,4,14),np.float32)
    n=len(days);candidates=np.empty(n,np.int64)
    for w in range(5):
      for rg in range(4):
       for ag in range(5):
        for co in range(5):
         for se in range(4):
          count=0
          for i in range(n):
           if flags[i,co] and wick[i,co]>=w and age[i]<=ag and session[i]==se and (rg==0 or regime[i]==rg-1):
            candidates[count]=i;count+=1
          if count==0:continue
          # Precompute jump to next observed day after a trade claims current day.
          jump=np.empty(count,np.int64);k=count-1
          while k>=0:
           end=k+1;day=days[candidates[k]]
           while k>=0 and days[candidates[k]]==day:jump[k]=end;k-=1
          for si in range(5):
           for ti in range(5):
            for hi in range(4):
             values=np.zeros(14,np.float64);k=0
             while k<count:
              i=candidates[k]
              if s[i,si,ti,hi,0]==-8 or s[i,si,ti,hi,1]==-8 or s[i,si,ti,hi,2]==-8:k+=1;continue
              k=jump[k]  # Claim day before reading any future outcome.
              if s[i,si,ti,hi,0]==-9 or s[i,si,ti,hi,1]==-9 or s[i,si,ti,hi,2]==-9:
               values[13]+=1;continue
              rr=r[i,si,ti,hi,1]
              values[0]+=1;values[1]+=rr>0;values[2]+=s[i,si,ti,hi,1]==1;values[3]+=s[i,si,ti,hi,1]==-1
              values[4]+=rr;values[5]+=rr*rr;values[6]+=max(rr,0);values[7]+=max(-rr,0)
              values[8]+=r[i,si,ti,hi,2];values[9]+=r[i,si,ti,hi,0];values[10]+=risk[i,si,ti,hi]
              values[11]+=GRID_TARGETS[ti]*adr[i];values[12]+=rr*risk[i,si,ti,hi]
             out[si,ti,hi,w,rg,ag,co,se]=values
    return out
GRID_TARGETS=np.array([.25,.35,.5,.75,1.])

def labelled(m1,rows,side):
    times=m1.index.asi8//10**9;signal=rows.index.asi8//10**9;starts=np.searchsorted(times,signal)
    good=starts<len(m1);good[good]&=times[starts[good]]==signal[good];rows=rows.loc[good]
    return rows,simulate(times,m1.open.to_numpy(),m1.high.to_numpy(),m1.low.to_numpy(),m1.close.to_numpy(),starts[good],rows.level.to_numpy(),rows.atr.to_numpy(),rows.adr20.to_numpy(),side)

def shard(csv,year,source,output):
    m1=normalize_bars(pd.read_csv(csv));f=features(m1);source_name=GRID['zone_source'][source]
    arrays={k:np.zeros(LOCAL_SHAPE,np.float32) for k in FIELDS}
    for sid,side in enumerate(GRID['side']):
      for pi,padding in enumerate(GRID['padding_atr4']):
        rows=events(f,side,source_name,padding).query('year==@year');rows,(r,s,risk)=labelled(m1,rows,side)
        st=statistics(rows.index.asi8//(86400*10**9),rows[['wick_'+str(i) for i in range(5)]].to_numpy(np.int64),rows.regime_bin.to_numpy(np.int64),rows.age_bin.to_numpy(np.int64),rows[['confirm_'+str(i) for i in range(5)]].to_numpy(bool),rows.session.to_numpy(np.int64),r,s,risk,rows.adr20.to_numpy())
        for fi,k in enumerate(FIELDS):arrays[k][sid,0,pi]=st[...,fi]
        print(f'H4D1_BASE year={year} source={source_name} side={side} padding={padding} n={len(rows)}',flush=True)
    output.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(output,**arrays)
    output.with_suffix('.json').write_text(json.dumps({'contract':CONTRACT,'year':year,'source_index':source,'local_tuples':int(np.prod(LOCAL_SHAPE)),'configurations':CONFIGURATIONS,'source_sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),'year_rows':int((m1.index.year==year).sum()),'first_utc':m1.index[0].isoformat(),'last_utc':m1.index[-1].isoformat()},indent=2)+'\n')

def target_lcb(data):
    n=np.maximum(data['n'],1);p=data['target_hits']/n;z=1.96
    return (p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)

def select(train,val,gt,gv,source,min_train=180,min_val=60,train_years=5,val_years=3):
    n=np.maximum(val['n'],1);mean=val['r_sum']/n;mlcb=mean-1.96*np.sqrt(np.maximum(val['r_sq']/n-mean*mean,0)/n)
    gates={'train_n':train['n']>=min_train,'val_n':val['n']>=min_val,'train_net':train['r_sum']>0,'train_pf':train['gain']>=1.15*train['loss'],'val_pf':val['gain']>=1.2*val['loss'],'stress':val['stress_sum']>0,'mean_lcb':mlcb>0,'train_years':gt>=train_years,'val_years':gv>=val_years,'train_censor':train['censored']/np.maximum(train['n']+train['censored'],1)<=.02,'val_censor':val['censored']/np.maximum(val['n']+val['censored'],1)<=.02}
    eligible=np.ones(LOCAL_SHAPE,bool);audit=[]
    for k,g in gates.items():eligible&=g;audit.append({'gate':k,'remaining':int(eligible.sum())})
    score=target_lcb(val);chosen=[];diagnostic=[]
    for sid in range(2):
      for is_diag,mask,dest in [(False,eligible[sid],chosen),(True,(train['n'][sid]>=min_train)&(val['n'][sid]>=min_val),diagnostic)]:
       ids=np.flatnonzero(mask.ravel())
       if not len(ids):continue
       pick=int(ids[np.argmax(score[sid].ravel()[ids])]);idx=(sid,)+np.unravel_index(pick,LOCAL_SHAPE[1:]);global_idx=(sid,source)+idx[2:]
       dest.append({'index':int(np.ravel_multi_index(global_idx,SHAPE)),'config':config(global_idx),'train':summary({k:v[idx] for k,v in train.items()}),'validation':summary({k:v[idx] for k,v in val.items()}),'descriptive_target_lcb':float(score[idx]),'failed_gates':[k for k,g in gates.items() if not g[idx]],'positive_train_years':int(gt[idx]),'positive_val_years':int(gv[idx]),'status':'DIAGNOSTIC_NOT_VALIDATED' if is_diag else 'LOCKED'})
    return chosen,diagnostic,audit

def aggregate(folder,output):
    paths={}
    for p in folder.rglob('h4d1-*-s*.npz'):
      meta=json.loads(p.with_suffix('.json').read_text());key=(meta['year'],meta['source_index']);assert key not in paths;paths[key]=p
    if set(paths)!={(y,s) for y in range(2016,2026) for s in range(10)}:raise ValueError('100_YEAR_SOURCE_SHARDS_REQUIRED')
    candidates=[];diagnostics=[];audits=[];wf={y:[] for y in range(2020,2026)}
    for source in range(10):
      train={k:np.zeros(LOCAL_SHAPE,np.float64) for k in FIELDS};val={k:np.zeros(LOCAL_SHAPE,np.float64) for k in FIELDS};gt=np.zeros(LOCAL_SHAPE,np.int8);gv=gt.copy()
      for year in range(2016,2026):
       with np.load(paths[year,source]) as d:
        dest=train if year<=2021 else val
        for k in FIELDS:dest[k]+=d[k]
        good=(d['n']>=15)&(d['r_sum']>0)
        if year<=2021:gt+=good
        else:gv+=good
      picked,diag,audit=select(train,val,gt,gv,source);candidates+=picked;diagnostics+=diag;audits.append({'source':GRID['zone_source'][source],'cumulative_gates':audit})
      del train,val,gt,gv
      train={k:np.zeros(LOCAL_SHAPE,np.float64) for k in FIELDS};gt=np.zeros(LOCAL_SHAPE,np.int8);previous=None
      for year in range(2016,2026):
       if year>=2020:
        pp,_,_=select(train,previous,gt,((previous['n']>=15)&(previous['r_sum']>0)).astype(np.int8),source,120,30,max(2,int(.75*(year-2017))),1)
        with np.load(paths[year,source]) as d:
         for w in pp:
          gi=np.unravel_index(w['index'],SHAPE);idx=(gi[0],0)+gi[2:];w['test']=summary({k:d[k][idx] for k in FIELDS});wf[year].append(w)
       if previous is not None:
        for k in FIELDS:train[k]+=previous[k]
        gt+=((previous['n']>=15)&(previous['r_sum']>0))
       with np.load(paths[year,source]) as d:previous={k:d[k].copy() for k in FIELDS}
      del train,gt,previous
      print('H4D1_AGGREGATED_SOURCE',source,flush=True)
    def best_per_side(items):return [max([w for w in items if w['config']['side']==s],key=lambda w:w['descriptive_target_lcb']) for s in [1,-1] if any(w['config']['side']==s for w in items)]
    selected=best_per_side(candidates);lock=hashlib.sha256(json.dumps(selected,sort_keys=True).encode()).hexdigest()
    for w in selected:
      gi=np.unravel_index(w['index'],SHAPE);idx=(gi[0],0)+gi[2:];w['year_metrics']={}
      for year in range(2016,2026):
       with np.load(paths[year,gi[1]]) as d:w['year_metrics'][str(year)]=summary({k:d[k][idx] for k in FIELDS})
    result={'contract':CONTRACT,'configurations_evaluated':CONFIGURATIONS,'grid':GRID,'cost_scenarios':COSTS,'min_reward_risk_stress':MIN_RR,'min_target_adr20_fraction':MIN_ADR_FRACTION,'selected_by_side':selected,'diagnostic_examples':best_per_side(diagnostics),'diagnostics_by_source':diagnostics,'gate_audits':audits,'walk_forward':[{'test_year':y,'selection_data_max_year':y-1,'selected':best_per_side(v)} for y,v in wf.items()],'candidate_lock_sha256':lock,'status':'LOCKED_FOR_2026_TEST' if selected else 'RESEARCH_ONLY','execution_authority':False,'execution_influence':False,'train':'2016-2021','validation':'2022-2025 already seen; exploratory','source_years':[json.loads(paths[y,0].with_suffix('.json').read_text()) for y in range(2016,2026)],'limitations':['20M parameter tuples, not independent strategies; statistical intervals not corrected for selection.','Historical M1 bid with synthetic spread/slippage; no account sizing, compounding or broker tick backtest.','Only fully closed H4/D1 candles; pivots known after right-bar confirmation; OB definition is operational, not proof of institutional orders.','First eligible per day after filters; censored first is not replaced; conservative stop-first/gap/deadline fills.','2026 prices already cached; only locked candidate outcomes evaluated. Empty candidate list means no candidate trades tested in 2026.','H4 minimum180M1 bars per candle; D1 minimum900. Historical data gaps can censor outcomes.']}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print('H4D1_LOCKED winners=',len(selected),flush=True)

def candidate_ledger(csv,year,result,output):
    m1=normalize_bars(pd.read_csv(csv))
    if year==2026:m1=m1.loc[m1.index<pd.Timestamp('2026-10-01T00:00Z')]
    frame=features(m1);ledger=[]
    for w in result['selected_by_side']:
      cfg=w['config'];rows=events(frame,cfg['side'],cfg['zone_source'],cfg['padding_atr4']).query('year==@year');rows=rows.loc[filter_events(rows,cfg)];rows,(r,s,risk)=labelled(m1,rows,cfg['side'])
      si=GRID['stop_extension_atr'].index(cfg['stop_extension_atr']);ti=GRID['target_adr_fraction'].index(cfg['target_adr_fraction']);hi=GRID['horizon_minutes'].index(cfg['horizon_minutes']);day=None
      for i,stamp in enumerate(rows.index):
       if (s[i,si,ti,hi]==-8).any():continue
       if stamp.date()==day:continue
       day=stamp.date();censored=bool((s[i,si,ti,hi]==-9).any())
       ledger.append({'index':w['index'],'at_utc':stamp.isoformat(),'year':year,'month':stamp.strftime('%Y-%m'),'hour_utc':stamp.hour,'r_reference':float(r[i,si,ti,hi,0]),'r_cautious':float(r[i,si,ti,hi,1]),'r_stress':float(r[i,si,ti,hi,2]),'status':-9 if censored else int(s[i,si,ti,hi,1]),'risk_points':float(risk[i,si,ti,hi]),'target_points':float(cfg['target_adr_fraction']*rows.adr20.iloc[i])})
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(ledger)+'\n')

# Keep existing chronological ledger parity, drawdown and monthly-block qualification.
from research_daily_reversal import verify_ledgers as _verify_ledgers

def verify_ledgers(folder,result,output):
    _verify_ledgers(folder,result,output)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--csv',type=Path);p.add_argument('--year',type=int);p.add_argument('--source',type=int);p.add_argument('--shards',type=Path);p.add_argument('--ledgers',type=Path);p.add_argument('--candidates',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.ledgers:verify_ledgers(a.ledgers,json.loads(a.candidates.read_text()),a.output)
 elif a.shards:aggregate(a.shards,a.output)
 elif a.candidates:candidate_ledger(a.csv,a.year,json.loads(a.candidates.read_text()),a.output)
 else:shard(a.csv,a.year,a.source,a.output)
