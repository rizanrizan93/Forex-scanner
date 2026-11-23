"""R12 sequential session hypotheses and standalone capital diagnostics."""
from __future__ import annotations
import argparse, contextlib, gzip, io, itertools, json, math, sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/r11_profitable_addon_alpha'))
import engine_coverage as base
original_features=base.features
original_events=base.events
original_families=base.FAMILIES
original_configurations=base.configurations
OUT=ROOT/'artifacts/r12'
FAMILIES=tuple(f'{family}_{session}_{gate}' for family,session,gate in itertools.product(
    ('OR30','M15PULLBACK'),('LONDON','NEWYORK'),('H4','BOTH')))

def features(d):
    m=original_features(d)
    q=d.resample('15min',label='right',closed='left').agg(o=('bo','first'),h=('bh','max'),l=('bl','min'),c=('bc','last'),n=('bc','count'))
    q.loc[q.n!=15,['o','h','l','c']]=np.nan
    q['ema']=q.c.ewm(span=20,adjust=False,min_periods=40).mean()
    for col in ('o','h','l','c','n','ema'):
        m['q_'+col]=q[col].reindex(m.index,method='ffill',tolerance=pd.Timedelta('15min'))
    return m

def events(m,family,side,look,wait):
    kind,session,gate=family.split('_')
    local=m.index.tz_convert('Europe/London' if session=='LONDON' else 'America/New_York')
    start=480 if session=='LONDON' else 570
    minute=local.hour*60+local.minute-start
    dates=local.strftime('%Y-%m-%d')
    vals=m[['o','h','l','c','atr','n','trend','h1','q_o','q_h','q_l','q_c','q_n','q_ema']].to_numpy(float)
    t=m.index.asi8//60_000_000_000
    result=[];day=None;pending=None;used=False;rangebars=[];rangehi=rangelo=None;broken=False
    for i in range(100,len(m)):
        o,h,l,c,atr,n,h4,h1,qo,qh,ql,qc,qn,ema=vals[i]
        if dates[i]!=day:
            day=dates[i];pending=None;used=False;rangebars=[];rangehi=rangelo=None;broken=False
        active=0<minute[i]<=180
        complete=n==5 and np.isfinite(vals[i,:8]).all() and atr>0 and t[i]-t[i-1]==5
        if not active or not complete:
            pending=None
            if active and minute[i]<=30:broken=True
            continue
        if kind=='OR30' and minute[i]<=30:
            rangebars.append((minute[i],h,l))
            if minute[i]==30 and not broken and [x[0] for x in rangebars]==[5,10,15,20,25,30]:
                rangehi=max(x[1] for x in rangebars);rangelo=min(x[2] for x in rangebars)
            continue
        aligned=h4==side and (gate=='H4' or h1==side)
        if not aligned or used:
            pending=None;continue
        if pending:
            age=i-pending['born']
            if age>wait or side*(c-pending['invalid'])<=0:
                pending=None
            elif age>=2:
                confirm=(c-o)*side>.2*atr
                if kind=='OR30':confirm &= l<=pending['hi'] and h>=pending['lo'] and (c>pending['hi'] if side==1 else c<pending['lo'])
                else:confirm &= c>max(vals[i-2:i,1]) if side==1 else c<min(vals[i-2:i,2])
                if confirm:
                    result.append((i,pending['invalid'],pending['born']));pending=None;used=True
                    continue
        if pending:continue
        if kind=='OR30' and rangehi is not None:
            level=rangehi if side==1 else rangelo
            if (c-o)*side>.5*atr and side*(c-level)>.15*atr and side*(vals[i-1,3]-level)<=0:
                pending=dict(born=i,lo=level-.15*atr,hi=level+.15*atr,invalid=level-side*.8*atr)
        elif kind=='M15PULLBACK' and m.index[i].minute%15==0 and qn==15 and np.isfinite(vals[i,8:]).all():
            reclaim=(ql<=ema and qc>ema and qc>qo) if side==1 else (qh>=ema and qc<ema and qc<qo)
            if reclaim:
                pending=dict(born=i,invalid=ql-.1*atr if side==1 else qh+.1*atr)
    return result

def configurations():
    for fam,side,hold,tp in itertools.product(FAMILIES,(1,-1),(60,180),(1.5,2.5)):
        yield dict(family=fam,side=side,look=12,wait=12,hold=hold,target=tp,guard=False)

def wallet(rows,start=100.):
    cash=start;peak=start;dd=0.;until=-1;filled=0;rejects={};hits={str(v):None for v in (125,250,1000)}
    for r in sorted(rows,key=lambda x:x['entry_minute']):
        if r['entry_minute']<until:continue
        budget=.08 if cash<125 else .03
        risk=r['risk_per_oz']+r['commission_usd']+2*r['slippage_per_side']
        margin=r['entry']/200
        units=math.floor(min(cash*budget/risk,cash*.5/margin)) if cash>0 else 0
        if units<1:
            rejects['minlot_risk_or_margin']=rejects.get('minlot_risk_or_margin',0)+1;continue
        cash+=units*r['net_usd_1oz'];filled+=1;until=r['exit_minute']+5
        peak=max(peak,cash);dd=max(dd,(peak-cash)/peak)
        for level in hits:
            if hits[level] is None and cash>=float(level):hits[level]=r['exit_utc']
        if cash<=0:break
    return dict(initial_cash=start,ending_cash=cash,filled=filled,rejects=rejects,
        first_settled_threshold_utc=hits,max_settled_cash_DD=dd,
        native_wallet=False,floating_DD=None,broker_specs_certified=False)

def execute(year,pilot=False):
    with contextlib.redirect_stdout(io.StringIO()) as log:base.execute(year,pilot)
    print(log.getvalue().replace('R11B','R12').replace('R11','R12'),end='')
    suffix='_pilot' if pilot else ''
    p=OUT/f'result_{year}{suffix}.json';report=json.loads(p.read_text());report['study']='R12_SESSION_STAGE_SCREEN'
    report['structural_families']=2
    report['limitations']+=['Standalone 8% bootstrap/3% growth sizing, not Frozen V1 compounding; no floating DD']
    streams={}
    with gzip.open(OUT/f'ledger_{year}{suffix}.jsonl.gz','rt') as f:
        for line in f:
            row=json.loads(line);streams.setdefault((row['config'],row['scenario']),[]).append(row)
    for r in report['rows']:
        r['standalone_annual_wallet']={s:wallet(streams.get((r['config'],s),[])) for s in base.SCENARIOS}
    base.dump(p,report)
    print('R12_YEAR',json.dumps(dict(year=year,configurations=64,any_stage125=sum(any(v['first_settled_threshold_utc']['125'] for v in r['standalone_annual_wallet'].values()) for r in report['rows']),native_parity=False)),flush=True)

def aggregate(root):
    with contextlib.redirect_stdout(io.StringIO()):base.aggregate(root)
    p=OUT/'aggregate.json';report=json.loads(p.read_text());report.update(study='R12_64_SESSION_STAGE_POLICIES',families=2,multiple_testing='64 related policies across two families, plus all prior searches S5-S10/R11/R11B. No significance or pristine OOS claim; forward and family-wise evidence required.')
    raw={r['year']:r for r in (json.loads(p.read_text()) for p in Path(root).rglob('result_*.json') if '_pilot' not in p.name)}
    report['annual_standalone_wallets']={str(y):{r['config']:r['standalone_annual_wallet'] for r in obj['rows']} for y,obj in raw.items()}
    metrics={y:{r['config']:r for r in obj['rows']} for y,obj in raw.items()}
    for sel in report['walk_forward']:
        y=sel['year'];ranked=[]
        for name in sorted(metrics[2012]):
            fs=[base.fold(metrics,name,range(2012,y),sc) for sc in ('A2','B2')]
            if all(x['n']>=100 and x['mean_R']>.02 and (x['pf'] or 0)>1.10 and x['positive_years']>=math.ceil(.65*(y-2012)) for x in fs):
                ranked.append((min(x['mean_R'] for x in fs),name))
        sel['selected_from_past_only']=max(ranked)[1] if ranked else None
        sel['next_year']=metrics[y][sel['selected_from_past_only']]['scenarios'] if ranked else None
    # Keep exact selected-by-past stream; never mix hindsight annual winners.
    cash={s:100. for s in base.SCENARIOS};walk=[]
    for selection in report['walk_forward']:
        y=selection['year'];name=selection['selected_from_past_only'];period={}
        for s in base.SCENARIOS:
            rows=[]
            if name:
                matches=list(Path(root).rglob(f'ledger_{y}.jsonl.gz'));assert len(matches)==1
                with gzip.open(matches[0],'rt') as f:
                    for line in f:
                        r=json.loads(line)
                        if r['config']==name and r['scenario']==s:rows.append(r)
            period[s]=wallet(rows,cash[s]);cash[s]=period[s]['ending_cash']
        walk.append(dict(year=y,selected_using_prior_years=name,wallet=period))
    report.update(standalone_past_only_annual_switch=walk,standalone_past_only_ending_cash=cash,
        selection_warning='All per-policy annual wallets are descriptive; no Frozen balance improvement. Reused history; no pristine OOS.',
        target_10_billion_verified=False)
    base.dump(p,report)
    print('R12_AGGREGATE',json.dumps({k:v for k,v in report.items() if k not in ('all_results','walk_forward','annual_standalone_wallets','standalone_past_only_annual_switch')}),flush=True)

def selftest():
    assert len(list(configurations()))==64
    base.events=original_events;base.FAMILIES=original_families;base.NCONFIG=256;base.configurations=original_configurations
    try:base.selftest()
    finally:base.events=events;base.FAMILIES=FAMILIES;base.NCONFIG=64;base.configurations=configurations
    rng=np.random.default_rng(812)
    ix=pd.date_range('2024-01-01',periods=8000,freq='5min',tz='UTC')
    c=2000+np.cumsum(rng.normal(.03,.9,len(ix)))
    m=pd.DataFrame(dict(o=c-.5,h=c+.8,l=c-.8,c=c,atr=2.,n=5,trend=1.,h1=1.,q_o=c-.5,q_h=c+.8,q_l=c-.8,q_c=c,q_n=15,q_ema=c-.2),index=ix)
    for fam in FAMILIES:
        for side in (1,-1):
            full=events(m,fam,side,12,12)
            for cut in (3000,6000):assert events(m.iloc[:cut],fam,side,12,12)==[e for e in full if e[0]<cut]
    # Hand-built OR: completed range, later breakout, then two bars later retest.
    fixture=m.iloc[:500].copy();fixture[['trend','h1']]=1.
    fixture[['o','h','l','c']]=[100.,101.,99.,100.];fixture['atr']=1.
    at=pd.Timestamp('2024-01-02T08:35Z');j=fixture.index.get_loc(at)
    fixture.loc[at,['o','h','l','c']]=[100.,102.2,100.,102.]
    fixture.iloc[j+1,fixture.columns.get_indexer(['o','h','l','c'])]=[102.,102.5,101.5,102.]
    fixture.iloc[j+2,fixture.columns.get_indexer(['o','h','l','c'])]=[101.,102.,100.9,101.8]
    got=events(fixture,'OR30_LONDON_H4',1,12,12)
    assert len(got)==1 and got[0][0]==j+2,got
    fixture.loc[pd.Timestamp('2024-01-02T08:15Z'),'n']=4
    assert not events(fixture,'OR30_LONDON_H4',1,12,12)

    row=dict(entry_minute=1,exit_minute=2,exit_utc='2024-01-01T00:02Z',risk_per_oz=2.,commission_usd=.12,slippage_per_side=.1,entry=2000.,net_usd_1oz=10.)
    result=wallet([row]);assert result['filled']==1 and result['ending_cash']==130 and result['first_settled_threshold_utc']['125']
    assert wallet([{**row,'risk_per_oz':10}])['filled']==0
    assert wallet([{**row,'entry':30000}])['filled']==0
    # Growth budget must reduce units at $125; no hindsight selection or increased risk.
    assert wallet([row],125)['ending_cash']==135
    print('R12_SELFTEST_PASS causal prefix, quote paths, costs, gaps, stage sizing, minimum lot and margin')

base.OUT=OUT;base.NCONFIG=64;base.FAMILIES=FAMILIES;base.events=events;base.configurations=configurations
base.features=features
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--selftest',action='store_true');p.add_argument('--year',type=int);p.add_argument('--pilot',action='store_true');p.add_argument('--aggregate');a=p.parse_args()
    if a.selftest:selftest()
    elif a.aggregate:aggregate(a.aggregate)
    elif a.year in range(2012,2027):execute(a.year,a.pilot)
    else:p.error('Choose --selftest, --year or --aggregate')
