"""20M alternative-family tuples with micro stops and conservative retest fills."""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np,pandas as pd
from numba import njit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fx_scanner.reversal_families_v2 import GRID,SHAPE,LOCAL_SHAPE,CONTRACT,CONFIGURATIONS,COSTS,MIN_RR,MIN_ADR_FRACTION,features,events,config,filter_events
from fx_scanner.reversal_zones import normalize_bars
from research_daily_reversal import summary as old_summary,ledger_metrics as old_ledger_metrics
FIELDS=['n','wins','target_hits','stops','r_sum','r_sq','gain','loss','stress_sum','reference_sum','risk_sum','tp_sum','points_sum','censored','not_filled']
STOP=np.array([.25,.5,.75,1.,1.5]);TARGET=np.array([.15,.25,.35,.5,.75]);HORIZON=np.array([60,120,240,360,480])

def summary(d):
 out=old_summary(d);out['not_filled']=int(d.get('not_filled',0));out['fill_rate']=out['n']/max(out['n']+out['not_filled']+out['censored'],1);return out

def ledger_metrics(rows):
 missed=sum(x['status']==-7 for x in rows);out=old_ledger_metrics([x for x in rows if x['status']!=-7]);out['not_filled']=missed;out['fill_rate']=out['n']/max(out['n']+missed+out['censored'],1);return out

@njit(cache=True)
def simulate(times,op,high,low,starts,level,atr5,adr,retest,side):
 n=len(starts);r=np.zeros((n,2,5,5,5,3));s=np.full((n,2,5,5,5,3),-8,np.int8);risk=np.zeros((n,2,5,5,5));fill_time=np.zeros((n,2),np.int64)
 spreads=np.array([.25,.5,1.]);slips=np.array([.05,.1,.2])
 for e in range(n):
  begin=starts[e];rollover=times[begin]//86400*86400+20*3600+55*60
  for em in range(2):
   reference=op[begin] if em==0 else retest[e];fill=begin;pending=-7
   if em==1:
    prev=times[begin]-60
    for j in range(begin,len(times)):
     if times[j]>=min(times[begin]+1800,rollover):break
     if times[j]-prev>300:pending=-9;break
     prev=times[j]
     if (low[j]<=reference if side==1 else high[j]>=reference):fill=j;pending=1;break
    if j==len(times)-1 and pending==-7 and times[j]<times[begin]+1800:pending=-9
   else:pending=1
   if pending==1:fill_time[e,em]=times[fill]
   for si in range(5):
    sl=level[e]-side*STOP[si]*atr5[e];stress_entry=reference+(1. if side==1 else 0.)+side*.2;stress_risk=side*(stress_entry-sl)
    if stress_risk<=0:continue
    for ti in range(5):
     move=TARGET[ti]*adr[e]
     if (move-.2)/(stress_risk+.2)<1.5:continue
     for hi in range(5):
      for ci in range(3):
       entry=reference+(spreads[ci] if side==1 else 0.)+side*slips[ci];rrisk=side*(entry-sl)
       if rrisk<=0:continue
       if ci==1:risk[e,em,si,ti,hi]=rrisk
       if pending!=1:s[e,em,si,ti,hi,ci]=pending;continue
       end=min(times[fill]+HORIZON[hi]*60,rollover);tp=entry+side*move;state=-9;exit_price=0.;prev=times[fill]-60
       for j in range(fill,len(times)):
        if times[j]>=end:
         if times[j]==end:state=0;exit_price=op[j]+(spreads[ci] if side==-1 else 0.)-side*slips[ci]
         break
        if times[j]-prev>300:break
        prev=times[j]
        invalid=low[j]<=sl if side==1 else high[j]+spreads[ci]>=sl
        reached=high[j]>=tp if side==1 else low[j]+spreads[ci]<=tp
        if invalid:state=-1;exit_price=(min(sl,op[j]) if side==1 else max(sl,op[j]+spreads[ci]))-side*slips[ci];break
        # Ignore optimistic TP in intrabar retest fill candle; stop-first always.
        at_open=(op[j]<=reference if side==1 else op[j]>=reference)
        if reached and (em==0 or j!=fill or at_open):state=1;exit_price=tp-side*slips[ci];break
       s[e,em,si,ti,hi,ci]=state
       if state!=-9:r[e,em,si,ti,hi,ci]=side*(exit_price-entry)/rrisk
 return r,s,risk,fill_time

@njit(cache=True)
def statistics(days,strength,flags,regime,phase,session,r,s,risk,adr):
 out=np.zeros((2,5,5,5,5,5,4,5,4,15),np.float32);n=len(days);cand=np.empty(n,np.int64)
 for st in range(5):
  for co in range(5):
   for rg in range(4):
    for ph in range(5):
     for se in range(4):
      count=0
      for i in range(n):
       p=phase[i];validphase=ph==0 or (ph==1 and p<60) or (ph==2 and 60<=p<120) or (ph==3 and 120<=p<240) or (ph==4 and p>=240)
       if strength[i]>=st and flags[i,co] and (rg==0 or regime[i]==rg-1) and validphase and session[i]==se:cand[count]=i;count+=1
      if not count:continue
      jump=np.empty(count,np.int64);k=count-1
      while k>=0:
       end=k+1;day=days[cand[k]]
       while k>=0 and days[cand[k]]==day:jump[k]=end;k-=1
      for em in range(2):
       for si in range(5):
        for ti in range(5):
         for hi in range(5):
          values=np.zeros(15,np.float64);k=0
          while k<count:
           i=cand[k]
           if (s[i,em,si,ti,hi,0]==-8 or s[i,em,si,ti,hi,1]==-8 or s[i,em,si,ti,hi,2]==-8):k+=1;continue
           k=jump[k]
           if s[i,em,si,ti,hi,1]==-7:values[14]+=1;continue
           if (s[i,em,si,ti,hi,0]==-9 or s[i,em,si,ti,hi,1]==-9 or s[i,em,si,ti,hi,2]==-9):values[13]+=1;continue
           rr=r[i,em,si,ti,hi,1];values[0]+=1;values[1]+=rr>0;values[2]+=s[i,em,si,ti,hi,1]==1;values[3]+=s[i,em,si,ti,hi,1]==-1
           values[4]+=rr;values[5]+=rr*rr;values[6]+=max(rr,0);values[7]+=max(-rr,0);values[8]+=r[i,em,si,ti,hi,2];values[9]+=r[i,em,si,ti,hi,0];values[10]+=risk[i,em,si,ti,hi];values[11]+=TARGET[ti]*adr[i];values[12]+=rr*risk[i,em,si,ti,hi]
          out[em,si,ti,hi,st,co,rg,ph,se]=values
 return out

def labelled(m1,rows,side):
 t=m1.index.asi8//10**9;starts=np.searchsorted(t,rows.index.asi8//10**9);good=starts<len(m1);good[good]&=t[starts[good]]==rows.index.asi8[good]//10**9;rows=rows.loc[good]
 return rows,simulate(t,m1.open.to_numpy(),m1.high.to_numpy(),m1.low.to_numpy(),starts[good],rows.level.to_numpy(),rows.atr5.to_numpy(),rows.adr20.to_numpy(),rows.retest.to_numpy(),side)

def shard(csv,year,source,output):
 m1=normalize_bars(pd.read_csv(csv));f=features(m1);arrays={k:np.zeros(LOCAL_SHAPE,np.float32) for k in FIELDS}
 for sid,side in enumerate(GRID['side']):
  e=events(f,side,GRID['family'][source]).query('year==@year');e,(r,s,risk,ft)=labelled(m1,e,side)
  st=statistics(e.index.asi8//(86400*10**9),e.strength_bin.to_numpy(np.int64),e[['confirm_'+str(i) for i in range(5)]].to_numpy(bool),e.regime_bin.to_numpy(np.int64),e.phase_minute.to_numpy(np.int64),e.session.to_numpy(np.int64),r,s,risk,e.adr20.to_numpy())
  for fi,k in enumerate(FIELDS):arrays[k][sid,0]=st[...,fi]
  print(f'FAMILIES_BASE year={year} source={source} family={GRID["family"][source]} side={side} n={len(e)}',flush=True)
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


def source_lock(folder,source,output):
 paths={}
 for p in folder.rglob('families-*-s'+str(source)+'.npz'):
  meta=json.loads(p.with_suffix('.json').read_text());assert meta['contract']==CONTRACT and meta['source_index']==source;paths[meta['year']]=p
 assert set(paths)==set(range(2016,2026))
 train={k:np.zeros(LOCAL_SHAPE,np.float64) for k in FIELDS};val={k:np.zeros(LOCAL_SHAPE,np.float64) for k in FIELDS};gt=np.zeros(LOCAL_SHAPE,np.int8);gv=gt.copy()
 for y,p in sorted(paths.items()):
  with np.load(p) as d:
   dest=train if y<=2021 else val
   for k in FIELDS:dest[k]+=d[k]
   good=(d['n']>=15)&(d['r_sum']>0)
   if y<=2021:gt+=good
   else:gv+=good
 chosen,diag,audit=select(train,val,gt,gv,source);del train,val,gt,gv
 for w in chosen:
  gi=np.unravel_index(w['index'],SHAPE);idx=(gi[0],0)+gi[2:];w['year_metrics']={}
  for y,p in sorted(paths.items()):
   with np.load(p) as d:w['year_metrics'][str(y)]=summary({k:d[k][idx] for k in FIELDS})
 train={k:np.zeros(LOCAL_SHAPE,np.float64) for k in FIELDS};gt=np.zeros(LOCAL_SHAPE,np.int8);previous=None;wf=[]
 for y,p in sorted(paths.items()):
  if y>=2020:
   picked,_,_=select(train,previous,gt,((previous['n']>=15)&(previous['r_sum']>0)).astype(np.int8),source,120,30,max(2,int(.75*(y-2017))),1)
   with np.load(p) as d:
    for w in picked:
     gi=np.unravel_index(w['index'],SHAPE);idx=(gi[0],0)+gi[2:];w['test']=summary({k:d[k][idx] for k in FIELDS})
   wf.append({'test_year':y,'selection_data_max_year':y-1,'selected':picked})
  if previous is not None:
   for k in FIELDS:train[k]+=previous[k]
   gt+=((previous['n']>=15)&(previous['r_sum']>0))
  with np.load(p) as d:previous={k:d[k].copy() for k in FIELDS}
 result={'contract':CONTRACT,'source_index':source,'family':GRID['family'][source],'candidates':chosen,'diagnostic':diag,'audit':audit,'walk_forward':wf,'source_years':[json.loads(p.with_suffix('.json').read_text()) for p in paths.values()]}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print('FAMILY_LOCK',source,'winners=',len(chosen),flush=True)

def aggregate(folder,output):
 results=[json.loads(p.read_text()) for p in folder.rglob('source-*.json')];assert {r['source_index'] for r in results}==set(range(20)) and len(results)==20
 def best(items):return [max([w for w in items if w['config']['side']==s],key=lambda x:x['descriptive_target_lcb']) for s in [1,-1] if any(w['config']['side']==s for w in items)]
 selected=best([w for r in results for w in r['candidates']]);diag=[w for r in results for w in r['diagnostic']];wf=[]
 for y in range(2020,2026):wf.append({'test_year':y,'selection_data_max_year':y-1,'selected':best([w for r in results for f in r['walk_forward'] if f['test_year']==y for w in f['selected']])})
 lock=hashlib.sha256(json.dumps(selected,sort_keys=True).encode()).hexdigest()
 out={'contract':CONTRACT,'configurations_evaluated':CONFIGURATIONS,'grid':GRID,'cost_scenarios':COSTS,'min_reward_risk_stress':MIN_RR,'min_target_adr20_fraction':MIN_ADR_FRACTION,'selected_by_side':selected,'diagnostic_examples':best(diag),'diagnostics_by_source':diag,'gate_audits':[{'source':r['family'],'cumulative_gates':r['audit']} for r in sorted(results,key=lambda x:x['source_index'])],'walk_forward':wf,'candidate_lock_sha256':lock,'status':'LOCKED_FOR_2026_TEST' if selected else 'RESEARCH_ONLY','execution_authority':False,'execution_influence':False,'train':'2016-2021','validation':'2022-2025 already seen; exploratory','source_years':results[0]['source_years'],'limitations':['20M parameter tuples across 20 operational families, not independent strategies.','Target 15-75% ADR20 differs from earlier 25-100% studies; TP-hit not directly comparable across distances.','Conservative M1 retest-on-touch model, not exact tick replay or guaranteed broker limit fills; TP ignored in intrabar fill candle.','First eligible intent claims day even when unfilled/censored; unfilled intents excluded from trade WR and reported separately.','Fixed synthetic costs, no sizing or compounding. D1 regimes and all anchors use completed candles.','2026 prices cached; only locked outcomes evaluated, not a pristine holdout. Confidence is descriptive after multiple searches.']}
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print('FAMILIES_LOCKED winners=',len(selected),flush=True)

def candidate_ledger(csv,year,result,output):
 m1=normalize_bars(pd.read_csv(csv))
 if year==2026:m1=m1.loc[m1.index<pd.Timestamp('2026-10-01T00:00Z')]
 f=features(m1);ledger=[]
 for w in result['selected_by_side']:
  c=w['config'];e=events(f,c['side'],c['family']).query('year==@year');e=e.loc[filter_events(e,c)];e,(r,s,risk,ft)=labelled(m1,e,c['side'])
  em=GRID['entry'].index(c['entry']);si=GRID['stop_atr5'].index(c['stop_atr5']);ti=GRID['target_adr_fraction'].index(c['target_adr_fraction']);hi=GRID['horizon_minutes'].index(c['horizon_minutes']);day=None
  for i,stamp in enumerate(e.index):
   if (s[i,em,si,ti,hi]==-8).any():continue
   if stamp.date()==day:continue
   day=stamp.date();cs=bool((s[i,em,si,ti,hi]==-9).any());state=-9 if cs else int(s[i,em,si,ti,hi,1])
   ledger.append({'index':w['index'],'at_utc':stamp.isoformat(),'year':year,'month':stamp.strftime('%Y-%m'),'hour_utc':stamp.hour,'fill_utc':int(ft[i,em]),'r_reference':float(r[i,em,si,ti,hi,0]),'r_cautious':float(r[i,em,si,ti,hi,1]),'r_stress':float(r[i,em,si,ti,hi,2]),'status':state,'risk_points':float(risk[i,em,si,ti,hi]),'target_points':float(c['target_adr_fraction']*e.adr20.iloc[i])})
 output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(ledger)+'\n')

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
        winner['fresh_2026']['trades_per_month']=winner['fresh_2026']['n']/9
        # Block-month uncertainty, not a claim of independent trades.
        monthly=[]
        observed=[x for x in test if x['status'] not in [-9,-7]]
        for month in sorted(set(x['month'] for x in observed)):
            rr=[x['r_cautious'] for x in observed if x['month']==month];monthly.append([len(rr),sum(rr)])
        if monthly:
            blocks=np.array(monthly);rng=np.random.default_rng(20261013)
            draws=blocks[rng.integers(0,len(blocks),size=(10000,len(blocks)))].sum(axis=1)
            ci=np.quantile(draws[:,1]/draws[:,0],[.025,.975]).tolist()
        else:ci=[None,None]
        winner['fresh_2026']['month_block_mean_r_ci95']=ci
        o=winner['fresh_2026']
        winner['qualified']=bool(o['n']>=30 and o['mean_net_r']>0 and (o['profit_factor'] or 0)>=1.2
            and o['mean_stress_r']>0 and ci[0] is not None and ci[0]>0
            and o['censored']/max(o['n']+o['censored'],1)<=.02)
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
    print('DAILY_VERIFICATION_COMPLETE status=',result['status'],flush=True)


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--csv',type=Path);p.add_argument('--year',type=int);p.add_argument('--source',type=int);p.add_argument('--shards',type=Path);p.add_argument('--source-results',type=Path);p.add_argument('--candidates',type=Path);p.add_argument('--ledgers',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.ledgers:verify_ledgers(a.ledgers,json.loads(a.candidates.read_text()),a.output)
 elif a.source_results:aggregate(a.source_results,a.output)
 elif a.shards:source_lock(a.shards,a.source,a.output)
 elif a.candidates:candidate_ledger(a.csv,a.year,json.loads(a.candidates.read_text()),a.output)
 else:shard(a.csv,a.year,a.source,a.output)
