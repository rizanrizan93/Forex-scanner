"""R13: large fixed grid, sequential independent-account screening, no live IO."""
from __future__ import annotations
import argparse, gzip, hashlib, itertools, json, os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from numba import njit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/r11_profitable_addon_alpha'))
import engine_coverage as base

OUT=ROOT/'artifacts/r13'
FAMILIES=base.old.FAMILIES+('DONCHIAN_MID_RECLAIM','RSI_EXTREME_RECLAIM','ASIAN_RANGE_BREAK','PRIOR_DAY_SWEEP')
TFS=(5,15,30,60);LOOKS=(8,16,32,64);SIDES=(1,-1)
HOLDS=(30,60,120,240);STOPS=(1.,1.5,2.,3.);TARGETS=(.75,1.,1.5,2.5)
REGIMES=('ANY','WITH','AGAINST');SESSIONS=('ALL','ASIA','LONDON','US')
SPREADS=(.15,.35);VOLS=('ALL','LOW','HIGH')
GRID=(TFS,FAMILIES,LOOKS,SIDES,HOLDS,STOPS,TARGETS,REGIMES,SESSIONS,SPREADS,VOLS)
SHAPE=tuple(map(len,GRID));NCONFIG=int(np.prod(SHAPE));NGATES=72;NEXIT=64
assert NCONFIG==2359296
COLS=('n','wins','net_R','gain_R','loss_R','net_USD_flat_1oz','sum_R2')
GATES=list(itertools.product(range(3),range(4),range(2),range(3)))

def dump(path,data):base.dump(path,data)
def decode(i):
    names=('tf','family','look','side','hold','stop','target','regime','session','spread','vol')
    return dict(zip(names,[g[j] for g,j in zip(GRID,np.unravel_index(int(i),SHAPE))]))

def features(d,tf):
    m=d.resample(f'{tf}min',label='right',closed='left').agg(
        o=('bo','first'),h=('bh','max'),l=('bl','min'),c=('bc','last'),n=('bc','count'))
    m.loc[m.n.ne(tf),['o','h','l','c']]=np.nan
    tr=pd.concat([m.h-m.l,(m.h-m.c.shift()).abs(),(m.l-m.c.shift()).abs()],axis=1).max(axis=1)
    m['atr']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    m['ema20']=m.c.ewm(span=20,adjust=False,min_periods=20).mean()
    m['ema50']=m.c.ewm(span=50,adjust=False,min_periods=50).mean()
    m['twap']=m.c.rolling(18,min_periods=18).mean()
    m['volmed']=m.atr.shift().rolling(96,min_periods=48).median()
    m['trend']=base.old.features(d).trend.reindex(m.index).fillna(0)
    delta=m.c.diff();up=delta.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    down=(-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    m['rsi']=100-100/(1+up/down.replace(0,np.nan))
    days=d.index.normalize();daily=d.groupby(days).agg(h=('bh','max'),l=('bl','min'),n=('bc','count'))
    daily.loc[daily.n<600,['h','l']]=np.nan
    prior=daily.reindex(pd.date_range(daily.index[0],daily.index[-1],freq='D')).shift()
    current=m.index.normalize()
    m['day_hi']=prior.h.reindex(current).to_numpy();m['day_lo']=prior.l.reindex(current).to_numpy()
    asia=d[(d.index.hour>=1)&(d.index.hour<6)]
    ar=asia.groupby(asia.index.normalize()).agg(h=('bh','max'),l=('bl','min'),n=('bc','count'))
    ar.loc[ar.n<240,['h','l']]=np.nan
    m['asia_hi']=ar.h.reindex(current).to_numpy();m['asia_lo']=ar.l.reindex(current).to_numpy()
    m.loc[m.index.hour<6,['asia_hi','asia_lo']]=np.nan
    return m

def signals(m,tf,family,look,side):
    # Reuse the disclosed S5 definitions at a different complete-bar timeframe.
    if family in base.old.FAMILIES:
        f=m.copy();f['n']=np.where(m.n.eq(tf),5,0)
        sig=base.old.family_signal(f,side,look,family)
    else:
        o,h,l,c,atr=m.o,m.h,m.l,m.c,m.atr
        candle=side*(c-o)>.15*atr
        if family=='DONCHIAN_MID_RECLAIM':
            mid=(h.shift().rolling(look).max()+l.shift().rolling(look).min())/2
            sig=(side*(c-mid)>0)&(side*(c.shift()-mid.shift())<=0)&candle
        elif family=='RSI_EXTREME_RECLAIM':
            threshold=max(10,35-look/4) if side==1 else min(90,65+look/4)
            sig=(m.rsi>threshold)&(m.rsi.shift()<=threshold)&candle if side==1 else (
                (m.rsi<threshold)&(m.rsi.shift()>=threshold)&candle)
        elif family=='ASIAN_RANGE_BREAK':
            level=m.asia_hi if side==1 else m.asia_lo
            sig=(side*(c-level)>.05*atr)&(side*(c.shift()-level)<=0)&candle
            # Lookback is a prior-only displacement filter, so it is not a dummy dimension.
            sig &= side*(c-c.shift(look))>0
        elif family=='PRIOR_DAY_SWEEP':
            level=m.day_lo if side==1 else m.day_hi
            sig=((l<level-.05*atr)&(c>level)) if side==1 else ((h>level+.05*atr)&(c<level))
            sig &= candle & (side*(c-c.shift(look))>0)
        else:raise ValueError(family)
        sig=sig.fillna(False).to_numpy()
    valid=(m.n.eq(tf)&m.atr.gt(0)&m.volmed.gt(0)&m.c.notna()
           &(m.index.dayofweek<5)&(m.index.hour<16))
    return sig&valid.to_numpy()

@njit(cache=True)
def outcomes(bid,ask,times,pos,atr,anchors,side,hold,stop_mult,target,cost,path):
    # out columns: entry minute, settlement minute, R, USD, risk, entry, exit, reason.
    # path0=stop-first screen, path1=A, path2=B. No future-gap censorship.
    out=np.zeros((len(pos),8),np.float64);out[:,0]=-1
    slip=.05*cost;fee=.06*cost
    quote=bid if side==1 else ask
    for e in range(len(pos)):
        j=pos[e]
        if j<0:continue
        entry=ask[j,0]+slip if side==1 else bid[j,0]-slip
        risk=max(side*(entry-anchors[e]),stop_mult*atr[e])
        if risk<=0 or not np.isfinite(risk):continue
        stop=entry-side*risk;tp=entry+side*target*risk
        price=0.;reason=-1;k=j
        for k in range(j,min(j+hold,len(times))):
            if k>j and times[k]!=times[k-1]+1:
                price=quote[k,0]-side*slip;reason=3;break
            opened=quote[k,0]
            if side*(opened-stop)<=0:
                price=opened-side*slip;reason=0;break
            if side*(opened-tp)>=0:
                price=tp-side*slip;reason=1;break
            if path==0:
                stopped=quote[k,2]<=stop if side==1 else quote[k,1]>=stop
                hit=quote[k,1]>=tp if side==1 else quote[k,2]<=tp
                if stopped:price=stop-side*slip;reason=0;break
                if hit:price=tp-side*slip;reason=1;break
            else:
                # Visit O-L-H-C or O-H-L-C, always independent of position side.
                for vertex in range(1,4):
                    col=(2 if vertex==1 else 1 if vertex==2 else 3) if path==1 else vertex
                    q=quote[k,col]
                    if side*(q-stop)<=0:price=stop-side*slip;reason=0;break
                    if side*(q-tp)>=0:price=tp-side*slip;reason=1;break
                if reason>=0:break
        if reason<0:
            price=quote[k,3]-side*slip
            reason=2 if k-j+1==hold else 4
        swap=3.*cost*max(0,times[k]//1440-times[j]//1440)
        usd=side*(price-entry)-fee-swap
        out[e,0]=times[j];out[e,1]=times[k]+1;out[e,2]=usd/risk
        out[e,3]=usd;out[e,4]=risk;out[e,5]=entry;out[e,6]=price;out[e,7]=reason
    return out

@njit(cache=True)
def score(raw,masks):
    scores=np.zeros((len(masks),7),np.float64)
    for g in range(len(masks)):
        until=-1.
        for e in range(len(raw)):
            if not masks[g,e] or raw[e,0]<0 or raw[e,0]<until:continue
            until=raw[e,1]+5
            r=raw[e,2];scores[g,0]+=1;scores[g,1]+=r>0;scores[g,2]+=r
            scores[g,3]+=max(r,0);scores[g,4]+=max(-r,0);scores[g,5]+=raw[e,3];scores[g,6]+=r*r
    return scores

def context(d,m,events,side,cost):
    times=d.index.asi8//60_000_000_000;mt=m.index.asi8//60_000_000_000
    pos=np.searchsorted(times,mt[events]);safe=np.minimum(pos,len(times)-1)
    pos=np.where((pos<len(times))&(times[safe]==mt[events]),pos,-1)
    b,a=base.repriced_quotes(d.to_numpy(float),cost)
    at=m.atr.to_numpy(float)[events]
    anchor=(m.l.to_numpy(float)[events]-.1*at) if side==1 else (m.h.to_numpy(float)[events]+.1*at)
    spread=np.full(len(events),np.inf);good=pos>=0
    spread[good]=(a[pos[good],0]-b[pos[good],0])/at[good]
    hr=m.index.hour.to_numpy()[events];trend=m.trend.to_numpy()[events]
    low=at<=m.volmed.to_numpy()[events]
    regimes=(np.ones(len(events),bool),trend==side,trend==-side)
    sessions=(np.ones(len(events),bool),(hr>=1)&(hr<6),(hr>=6)&(hr<10),(hr>=12)&(hr<16))
    vols=(np.ones(len(events),bool),low,~low)
    masks=np.array([regimes[r]&sessions[s]&(spread>=0)&(spread<=SPREADS[p])&vols[v] for r,s,p,v in GATES])
    return b,a,times,pos,at,anchor,masks

def acquire(year):
    if year==2026:
        import snowball_s8_xau_2026_partial as partial
        return partial.acquire_2026(year)
    return base.gold.source(year)

def screen(year,pilot=False):
    started=time.monotonic();d,prov=acquire(year)
    if pilot:d=d.iloc[:60000]
    OUT.mkdir(parents=True,exist_ok=True)
    scores=np.zeros((NCONFIG,7),np.float64);offset=0;streams=[]
    # Repriced quotes once per year rather than per stream.
    b,a=base.repriced_quotes(d.to_numpy(float),2)
    times=d.index.asi8//60_000_000_000
    for tf in TFS:
        m=features(d,tf);mt=m.index.asi8//60_000_000_000
        for fam,look,side in itertools.product(FAMILIES,LOOKS,SIDES):
            sig=signals(m,tf,fam,look,side);ev=np.flatnonzero(sig)
            streams.append(dict(tf=tf,family=fam,look=look,side=side,signals=len(ev),
                signal_sha256=hashlib.sha256(mt[ev].astype('<i8').tobytes()).hexdigest()))
            if len(ev):
                # Context includes only observed quote and prior/completed-bar gates.
                pos=np.searchsorted(times,mt[ev]);safe=np.minimum(pos,len(times)-1)
                pos=np.where((pos<len(times))&(times[safe]==mt[ev]),pos,-1)
                at=m.atr.to_numpy()[ev]
                anchor=m.l.to_numpy()[ev]-.1*at if side==1 else m.h.to_numpy()[ev]+.1*at
                spread=np.full(len(ev),np.inf);good=pos>=0
                spread[good]=(a[pos[good],0]-b[pos[good],0])/at[good]
                hr=m.index.hour.to_numpy()[ev];tr=m.trend.to_numpy()[ev];low=at<=m.volmed.to_numpy()[ev]
                reg=(np.ones(len(ev),bool),tr==side,tr==-side)
                sess=(np.ones(len(ev),bool),(hr>=1)&(hr<6),(hr>=6)&(hr<10),(hr>=12)&(hr<16))
                vol=(np.ones(len(ev),bool),low,~low)
                masks=np.array([reg[r]&sess[s]&(spread>=0)&(spread<=SPREADS[p])&vol[v] for r,s,p,v in GATES])
                for hold,stop,tp in itertools.product(HOLDS,STOPS,TARGETS):
                    raw=outcomes(b,a,times,pos,at,anchor,side,hold,stop,tp,2,0)
                    scores[offset:offset+NGATES]=score(raw,masks);offset+=NGATES
            else:offset+=NEXIT*NGATES
        print('R13_TF_COMPLETE',year,tf,'configurations_scored',offset,flush=True)
    assert offset==NCONFIG and len(streams)==512
    suffix=f'{year}'+('_pilot' if pilot else '')
    artifact=OUT/f'scores_{suffix}.npz'
    np.savez_compressed(artifact,scores=scores)
    report=dict(study='R13_MILLION_SCREEN',year=year,pilot=pilot,configurations_scored=offset,
        structural_templates=256,related_families=16,signal_streams=512,
        unique_signal_timestamp_hashes=len({s['signal_sha256'] for s in streams}),
        grid_shape=SHAPE,metric_columns=COLS,nonempty_configurations=int((scores[:,0]>0).sum()),
        positive_netR_configurations=int((scores[:,2]>0).sum()),
        maximum_fills=int(scores[:,0].max()),elapsed_seconds=time.monotonic()-started,
        commit_sha=os.getenv('GITHUB_SHA','LOCAL'),provenance=prov,
        actual_first=str(d.index[0]),actual_last=str(d.index[-1]),signal_definitions=streams,
        score_artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        execution_scenario='COST2_STOP_FIRST',shared_wallet=False,native_parity=False,
        incremental_V1_fills=None,V1_balance_change=None,max_floating_DD_change=None,
        production_changes=False)
    dump(OUT/f'metadata_{suffix}.json',report)
    print('R13_ANNUAL_COMPLETE',json.dumps({k:v for k,v in report.items() if k not in ('provenance','signal_definitions')}),flush=True)

def select(root):
    total=np.zeros((NCONFIG,7),np.float64);positive=np.zeros(NCONFIG,np.int16)
    reports=[]
    for year in range(2012,2019):
        paths=list(Path(root).rglob(f'metadata_{year}.json'));assert len(paths)==1
        meta=json.loads(paths[0].read_text());reports.append(meta)
        assert not meta['pilot'] and meta['configurations_scored']==NCONFIG
        p=paths[0].with_name(f'scores_{year}.npz')
        assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['score_artifact_sha256']
        with np.load(p) as z:x=z['scores']
        assert x.shape==total.shape and np.isfinite(x).all()
        total+=x;positive+=x[:,2]>0
    assert len({x['commit_sha'] for x in reports})==1
    n=total[:,0];mean=np.divide(total[:,2],n,out=np.full(NCONFIG,-np.inf),where=n>0)
    pf=np.divide(total[:,3],total[:,4],out=np.full(NCONFIG,np.inf),where=total[:,4]>0)
    passing=np.flatnonzero((n>=200)&(mean>.02)&(pf>1.10)&(positive>=5))
    ordered=sorted(passing,key=lambda i:(-total[i,2],-total[i,0],i))[:64]
    selected=[dict(id=int(i),parameters=decode(i),development=dict(zip(COLS,total[i].tolist())),
        development_mean_R=mean[i],development_PF_R=pf[i] if np.isfinite(pf[i]) else None,
        positive_years=int(positive[i])) for i in ordered]
    result=dict(study='R13_DEVELOPMENT_SELECTION',configurations=NCONFIG,
        completed_development_years=list(range(2012,2019)),completed_config_years=NCONFIG*7,
        development_qualified=int(len(passing)),selected_count=len(selected),selected=selected,
        commit_sha=reports[0]['commit_sha'],full_grid_shape=SHAPE,
        maximum_aggregate_fills=int(n.max()),
        positive_pooled_R_configurations=int((total[:,2]>0).sum()),
        status='DETAILED_REPLAY_REQUIRED' if selected else 'REJECT_ALL_DEVELOPMENT',
        multiple_testing='2359296 correlated tuples plus prior searches; no independent OOS or significance claim',
        native_parity=False,shared_wallet=False,V1_balance_change=None,production_changes=False)
    OUT.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(OUT/'development_all_scores.npz',scores=total,positive_years=positive)
    dump(OUT/'selection.json',result)
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write(f'count={len(selected)}\n')
    print('R13_SELECTION',json.dumps({k:v for k,v in result.items() if k!='selected'}),flush=True)

def detail(year,selection):
    selected=json.loads(Path(selection).read_text())['selected'];assert selected
    d,prov=acquire(year);frames={};cache={};reports=[]
    OUT.mkdir(parents=True,exist_ok=True)
    ledger=OUT/f'finalists_ledger_{year}.jsonl.gz'
    with gzip.open(ledger,'wt') as f:
        for candidate in selected:
            cfg=candidate['parameters'];tf=cfg['tf']
            if tf not in frames:frames[tf]=features(d,tf)
            m=frames[tf];ek=(tf,cfg['family'],cfg['look'],cfg['side'])
            if ek not in cache:cache[ek]=np.flatnonzero(signals(m,*ek))
            ev=cache[ek];scenarios={}
            g=GATES.index((REGIMES.index(cfg['regime']),SESSIONS.index(cfg['session']),SPREADS.index(cfg['spread']),VOLS.index(cfg['vol'])))
            for cost,path in itertools.product((1,2),(1,2)):
                b,a,times,pos,at,anchor,masks=context(d,m,ev,cfg['side'],cost)
                raw=outcomes(b,a,times,pos,at,anchor,cfg['side'],cfg['hold'],cfg['stop'],cfg['target'],cost,path)
                sc=('A' if path==1 else 'B')+str(cost)
                metric=score(raw,masks[g:g+1])[0];scenarios[sc]=dict(zip(COLS,metric.tolist()))
                until=-1
                for idx,row in enumerate(raw):
                    if not masks[g,idx] or row[0]<0 or row[0]<until:continue
                    until=row[1]+5
                    f.write(json.dumps(dict(config_id=candidate['id'],scenario=sc,
                        signal_utc=str(m.index[ev[idx]]),entry_minute=int(row[0]),exit_minute=int(row[1]),
                        net_R=row[2],net_USD_flat_1oz=row[3],risk_per_oz=row[4],entry=row[5],exit=row[6],
                        reason=int(row[7]),side=cfg['side'],units_oz=1),allow_nan=False)+'\n')
            reports.append(dict(id=candidate['id'],parameters=cfg,scenarios=scenarios))
    dump(OUT/f'detailed_{year}.json',dict(year=year,rows=reports,provenance=prov,
        actual_first=str(d.index[0]),actual_last=str(d.index[-1]),commit_sha=os.getenv('GITHUB_SHA','LOCAL'),
        ledger_sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(),shared_wallet=False,native_parity=False,production_changes=False))
    print('R13_DETAILED_COMPLETE',year,len(reports),flush=True)

def final(root,selection):
    choice=json.loads(Path(selection).read_text());selected=choice['selected'];results=[]
    if selected:
        reports={}
        for year in range(2019,2027):
            files=list(Path(root).rglob(f'detailed_{year}.json'));assert len(files)==1
            x=json.loads(files[0].read_text());assert x['commit_sha']==choice['commit_sha']
            reports[year]={r['id']:r for r in x['rows']}
        for candidate in selected:
            cid=candidate['id'];periods={}
            for name,years in [('validation',range(2019,2023)),('evaluation',range(2023,2026)),('partial2026',[2026])]:
                periods[name]={}
                for sc in ('A1','B1','A2','B2'):
                    ms=[reports[y][cid]['scenarios'][sc] for y in years]
                    sums={k:sum(x[k] for x in ms) for k in COLS}
                    sums.update(mean_R=sums['net_R']/sums['n'] if sums['n'] else None,
                        PF_R=sums['gain_R']/sums['loss_R'] if sums['loss_R'] else None,
                        positive_years=sum(x['net_R']>0 for x in ms))
                    periods[name][sc]=sums
            val=all((x:=periods['validation'][sc])['n']>=100 and x['mean_R']>.01 and x['gain_R']>1.05*x['loss_R'] and x['positive_years']>=3 for sc in ('A2','B2'))
            eva=val and all((x:=periods['evaluation'][sc])['n']>=60 and x['mean_R']>0 and x['positive_years']>=2 for sc in ('A2','B2'))
            results.append(dict(**candidate,periods=periods,validation_pass=val,evaluation_pass=eva,
                decision='INCONCLUSIVE_FORWARD_AND_NATIVE_REQUIRED' if eva else 'REJECT'))
    out=dict(study='R13_FINAL',development=choice,finalists=results,
        validation_qualified=sum(r['validation_pass'] for r in results),
        evaluation_qualified=sum(r['evaluation_pass'] for r in results),native_ACCEPT=0,
        tested_all_configurations_years=choice['completed_development_years'],
        tested_selected_configurations_years=list(range(2019,2027)) if selected else [],
        status='INCONCLUSIVE_FORWARD_AND_NATIVE_REQUIRED' if any(r['evaluation_pass'] for r in results) else 'NO_QUALIFIED_ADDON',
        shared_wallet=False,native_parity=False,incremental_V1_fills=None,V1_balance_change=None,
        max_floating_DD_change=None,production_changes=False)
    dump(OUT/'final.json',out)
    print('R13_FINAL',json.dumps({k:v for k,v in out.items() if k not in ('development','finalists')}),flush=True)

def reference(b,a,t,pos,atr,anchor,side,hold,sm,tp,cost,path):
    # Intentionally scalar independent implementation for replay verification.
    entry=(a[pos,0] if side>0 else b[pos,0])+side*.05*cost
    risk=max(side*(entry-anchor),sm*atr);stop=entry-side*risk;target=entry+side*tp*risk
    q=b if side>0 else a;reason=None
    for k in range(pos,min(pos+hold,len(t))):
        if k>pos and t[k]!=t[k-1]+1:exit=q[k,0]-side*.05*cost;reason=3;break
        order=(0,2,1,3) if path==1 else (0,1,2,3)
        if path==0:order=(0,2,1,3) if side>0 else (0,1,2,3)
        for vertex in order:
            price=q[k,vertex]
            if side*(price-stop)<=0:
                exit=(price if vertex==0 else stop)-side*.05*cost;reason=0;break
            if side*(price-target)>=0:exit=target-side*.05*cost;reason=1;break
        if reason is not None:break
    if reason is None:exit=q[k,3]-side*.05*cost;reason=2 if k-pos+1==hold else 4
    usd=side*(exit-entry)-.06*cost-3*cost*max(0,t[k]//1440-t[pos]//1440)
    return np.array([t[pos],t[k]+1,usd/risk,usd,risk,entry,exit,reason])

def selftest():
    assert len(FAMILIES)==16 and NCONFIG==2359296
    for i in (0,100,4623,NCONFIG-1):
        c=decode(i);assert all(c[k] in g for k,g in zip(c,GRID))
    rng=np.random.default_rng(713);n=400
    c=2000+np.cumsum(rng.normal(0,.8,n))
    b=np.column_stack([c,c+rng.uniform(.1,2,n),c-rng.uniform(.1,2,n),c+.05]);a=b+.25
    t=np.arange(n,dtype=np.int64)+28000000;t[180:]+=60
    for side,cost,path in itertools.product(SIDES,(1,2),(0,1,2)):
        bb,aa=base.repriced_quotes(np.column_stack([b,a]),cost)
        for j in (0,50,178,398):
            anchor=c[j]-side*2
            got=outcomes(bb,aa,t,np.array([j]),np.array([1.]),np.array([anchor]),side,60,1.5,1.5,cost,path)[0]
            want=reference(bb,aa,t,j,1.,anchor,side,60,1.5,1.5,cost,path)
            assert np.allclose(got,want,rtol=1e-12,atol=1e-10),(side,cost,path,j,got,want)
    raw=np.zeros((4,8));raw[:,0]=[100,102,111,130];raw[:,1]=[110,105,120,135];raw[:,2]=[-1,10,10,2];raw[:,3]=raw[:,2]
    s=score(raw,np.ones((1,4),np.bool_))[0]
    assert s[0]==2 and s[2]==1 and s[1]==1,s
    # Explicit intraminute ambiguity and missing-minute liquidation fixtures.
    bb=np.array([[100.,103.,97.,100.]]);aa=bb+.1;tt=np.array([28000000],dtype=np.int64)
    kw=(np.array([0]),np.array([1.]),np.array([99.]),1,1,1.,1.,1)
    ra=outcomes(bb,aa,tt,*kw,1)[0];rb=outcomes(bb,aa,tt,*kw,2)[0]
    assert ra[2]<0 and rb[2]>0
    qq=np.array([[100.,100.2,99.9,100.],[98.,98.2,97.9,98.]])
    gap=outcomes(qq,qq+.1,np.array([28000000,28000060]),np.array([0]),np.array([1.]),np.array([90.]),1,60,1.,10.,1,0)[0]
    assert gap[7]==3 and gap[2]<0 and gap[0]>=0
    # Full-grid signal causality: prefix outputs must match before cutoff.
    ix=pd.date_range('2024-01-01',periods=15000,freq='min',tz='UTC')
    c=2000+np.cumsum(rng.normal(.002,.2,len(ix)))
    d=pd.DataFrame(np.column_stack([c,c+.2,c-.2,c+.01,c+.25,c+.45,c+.05,c+.26]),index=ix,
        columns=['bo','bh','bl','bc','ao','ah','al','ac'])
    cut=12000
    for tf in TFS:
        full=features(d,tf);pre=features(d.iloc[:cut],tf)
        for fam,side in itertools.product(FAMILIES,SIDES):
            x=signals(full,tf,fam,16,side);y=signals(pre,tf,fam,16,side)
            before=pre.index<=d.index[cut]
            assert np.array_equal(x[:len(pre)][before],y[before]),(tf,fam,side)
    print('R13_SELFTEST_PASS compiled/scalar replay, both sides, costs, paths, gaps, chronology, prefix causality and exact grid count',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--selftest',action='store_true');p.add_argument('--year',type=int)
    p.add_argument('--pilot',action='store_true');p.add_argument('--select');p.add_argument('--detail',type=int)
    p.add_argument('--selection');p.add_argument('--final');a=p.parse_args()
    if a.selftest:selftest()
    elif a.select:select(a.select)
    elif a.detail:detail(a.detail,a.selection)
    elif a.final:final(a.final,a.selection)
    elif a.year in range(2012,2019):screen(a.year,a.pilot)
    else:p.error('Choose a research stage')
