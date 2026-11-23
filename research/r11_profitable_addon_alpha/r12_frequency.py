"""Preregistered standalone M15/M30 pullback screen; never a V1 wallet replay."""
from __future__ import annotations
import argparse, gzip, hashlib, itertools, json, os
from pathlib import Path
import numpy as np
import pandas as pd
import engine_coverage as base

ROOT=base.ROOT
OUT=ROOT/'artifacts/r12'
SCENARIOS=base.SCENARIOS

def configurations():
    for tf,ema,side,hold,target in itertools.product((15,30),(20,50),(1,-1),(120,240),(1.5,2.5)):
        yield dict(tf=tf,ema=ema,side=side,hold=hold,target=target)

def key(c):return '|'.join(str(c[k]) for k in ('tf','ema','side','hold','target'))

def features(d,tf):
    m=d.resample(f'{tf}min',label='right',closed='left').agg(
        o=('bo','first'),h=('bh','max'),l=('bl','min'),c=('bc','last'),n=('bc','count'))
    m.loc[m.n.ne(tf),['o','h','l','c']]=np.nan
    tr=pd.concat([m.h-m.l,(m.h-m.c.shift()).abs(),(m.l-m.c.shift()).abs()],axis=1).max(axis=1)
    m['atr']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    for span in (20,50):m[f'e{span}']=m.c.ewm(span=span,adjust=False,min_periods=span).mean()
    # Reuse unchanged completed-H4 direction and validity from historical engine.
    h4=base.old.features(d).trend
    m['trend']=h4.reindex(m.index).fillna(0)
    return m

def events(m,tf,ema,side):
    a=m[['o','h','l','c','atr','n','trend',f'e{ema}']].to_numpy(float)
    minutes=m.index.asi8//60_000_000_000
    result=[];pending=None
    for i in range(1,len(m)):
        o,h,l,c,atr,n,trend,e=a[i]
        if (not np.isfinite(a[i]).all() or n!=tf or atr<=0 or trend!=side
                or minutes[i]-minutes[i-1]!=tf or a[i-1,5]!=tf
                or not np.isfinite(a[i-1]).all() or m.index[i].dayofweek>=5
                or m.index[i].hour>=16):
            pending=None;continue
        if pending is not None:
            if i-pending['born']>4 or side*(c-pending['anchor'])<=0:
                pending=None
            elif (side*(c-pending['break'])>.05*pending['atr']
                    and side*(c-o)>.15*atr):
                result.append((i,pending['anchor'],pending['born']))
                pending=None
                continue
        if pending is not None:continue
        previous_on_side=side*(a[i-1,3]-a[i-1,7])>0
        touch=(l<=e+.10*atr) if side==1 else (h>=e-.10*atr)
        if previous_on_side and touch and side*(c-e)>0:
            pending=dict(born=i,anchor=l-.10*atr if side==1 else h+.10*atr,
                         **{'break':h if side==1 else l},atr=atr)
    return result

def execute(year,pilot=False):
    if year==2026:
        import snowball_s8_xau_2026_partial as partial
        d,provenance=partial.acquire_2026(year)
    else:d,provenance=base.gold.source(year)
    if pilot:d=d.iloc[:60000]
    OUT.mkdir(parents=True,exist_ok=True)
    frames={tf:features(d,tf) for tf in (15,30)}
    cache={};out=[]
    ledger=OUT/f'ledger_{year}{"_pilot" if pilot else ""}.jsonl.gz'
    with gzip.open(ledger,'wt') as f:
        for cfg in configurations():
            name=key(cfg);ek=(cfg['tf'],cfg['ema'],cfg['side']);m=frames[cfg['tf']]
            if ek not in cache:cache[ek]=events(m,*ek)
            metrics={};rejects={}
            for scenario in SCENARIOS:
                raw,r=base.replay(d,m,cache[ek],cfg['side'],cfg['hold'],cfg['target'],scenario)
                chosen,admission=base.admit(raw,False)
                metrics[scenario]=base.metric(chosen);rejects[scenario]={**r,**admission}
                for row in chosen:f.write(json.dumps(dict(config=name,**row),allow_nan=False)+'\n')
            out.append(dict(config=name,parameters=cfg,opportunities=len(cache[ek]),scenarios=metrics,rejects=rejects))
    report=dict(study='R12_STANDALONE_PULLBACK',year=year,pilot=pilot,configurations=32,
        commit_sha=os.getenv('GITHUB_SHA','LOCAL'),provenance=provenance,
        actual_first=str(d.index[0]),actual_last=str(d.index[-1]),rows=out,
        ledger_sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(),
        native_parity=False,shared_wallet=False,production_changes=False,
        incremental_v1_baskets=None,wallet_balance_change=None,max_floating_DD_change=None)
    base.dump(OUT/f'result_{year}{"_pilot" if pilot else ""}.json',report)
    print('R12_YEAR',year,'pilot',pilot,'policies',len(out),flush=True)

def aggregate(root):
    raw=[json.loads(p.read_text()) for p in Path(root).rglob('result_*.json') if '_pilot' not in p.name]
    assert len(raw)==15 and {x['year'] for x in raw}==set(range(2012,2027))
    assert len({x['commit_sha'] for x in raw})==1
    reports={x['year']:{r['config']:r for r in x['rows']} for x in raw}
    names=sorted(reports[2012]);assert len(names)==32
    assert all(set(r)==set(names) for r in reports.values())
    summary=[]
    for name in names:
        periods={label:{s:base.fold(reports,name,years,s) for s in SCENARIOS} for label,years in (
            ('development',range(2012,2019)),('validation',range(2019,2023)),
            ('evaluation',range(2023,2026)),('partial_2026',[2026]))}
        d=all((x:=periods['development'][s])['n']>=100 and x['mean_R']>.02 and (x['pf'] or 0)>1.1 and x['positive_years']>=5 for s in ('A2','B2'))
        v=d and all((x:=periods['validation'][s])['n']>=50 and x['mean_R']>.01 and (x['pf'] or 0)>1.05 and x['positive_years']>=3 for s in ('A2','B2'))
        e=v and all((x:=periods['evaluation'][s])['n']>=30 and x['mean_R']>0 and x['positive_years']>=2 for s in ('A2','B2'))
        summary.append(dict(config=name,periods=periods,development_pass=d,validation_pass=v,
            evaluation_pass=e,decision='INCONCLUSIVE_NATIVE_REQUIRED' if e else 'REJECT',
            annual={str(y):reports[y][name]['scenarios'] for y in range(2012,2027)},
            annual_rejects={str(y):reports[y][name]['rejects'] for y in range(2012,2027)}))
    walk=[]
    for y in range(2019,2027):
        ranked=[]
        for name in names:
            f=[base.fold(reports,name,range(2012,y),s) for s in ('A2','B2')]
            if all(x['n']>=100 and x['mean_R']>.02 and (x['pf'] or 0)>1.1 and x['positive_years']>=int(np.ceil(.65*(y-2012))) for x in f):
                ranked.append((min(x['mean_R'] for x in f),name))
        selected=max(ranked)[1] if ranked else None
        walk.append(dict(year=y,selected_from_past_only=selected,next_year=reports[y][selected]['scenarios'] if selected else None))
    result=dict(study='R12_32_PULLBACK_POLICIES',configurations=32,related_ema_hypotheses=2,
        years=15,scenarios=4,scenario_model_years=1920,
        development_qualified=sum(x['development_pass'] for x in summary),
        validation_qualified=sum(x['validation_pass'] for x in summary),
        evaluation_qualified=sum(x['evaluation_pass'] for x in summary),
        commit_sha=raw[0]['commit_sha'],walk_forward=walk,all_results=summary,
        provenance=[dict(year=x['year'],first=x['actual_first'],last=x['actual_last'],provenance=x['provenance']) for x in sorted(raw,key=lambda x:x['year'])],
        native_parity=False,shared_wallet=False,production_changes=False,
        incremental_v1_baskets=None,wallet_balance_change=None,max_floating_DD_change=None,
        limitations=['Reused historical sample; no independent OOS or significance claim',
            'Fixed1oz independent opportunities; not V1 fills, equity or compounding',
            'Third-party Dukascopy-derived M1 OHLC; not FP Markets ticks',
            'Hypothetical fee/slippage and two intrabar paths; broker capacity unverified',
            '2026 Jan-Aug partial; native input/reference ledger blockers unchanged'])
    base.dump(OUT/'aggregate.json',result)
    print('R12_AGGREGATE',json.dumps({k:v for k,v in result.items() if k not in ('all_results','walk_forward','provenance')}),flush=True)

def selftest():
    base.selftest()
    assert len(list(configurations()))==32
    for side in (1,-1):
        ix=pd.date_range('2024-01-02T08:00Z',periods=10,freq='15min')
        a=np.tile([101.,102.,100.5,101.5,2.,15.,1.,100.],(10,1))
        a[2,:4]=[101.,102.,99.9,101.]
        a[3,:4]=[101.,103.,100.8,102.8]
        if side==-1:
            a[:,:4]=200-a[:,:4];a[:,[1,2]]=a[:,[2,1]];a[:,6]=-1;a[:,7]=100
        m=pd.DataFrame(a,columns=['o','h','l','c','atr','n','trend','e20'],index=ix)
        full=events(m,15,20,side)
        assert full==[(3,99.7 if side==1 else 100.3,2)],full
        assert events(m.iloc[:3],15,20,side)==[]
        for cut in range(1,len(m)+1):assert events(m.iloc[:cut],15,20,side)==[r for r in full if r[0]<cut]
        broken=m.copy();broken.iloc[2,broken.columns.get_loc('n')]=14
        assert events(broken,15,20,side)==[]
    print('R12_SELFTEST_PASS both sides, delayed locked pullback, prefix causality, incomplete reset',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--selftest',action='store_true');p.add_argument('--year',type=int)
    p.add_argument('--pilot',action='store_true');p.add_argument('--aggregate');a=p.parse_args()
    if a.selftest:selftest()
    elif a.aggregate:aggregate(a.aggregate)
    elif a.year in range(2012,2027):execute(a.year,a.pilot)
    else:p.error('Choose --selftest, --year or --aggregate')
