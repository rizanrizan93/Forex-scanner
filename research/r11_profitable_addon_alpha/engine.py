"""R11 independent XAU hypothesis screening. Never a Frozen wallet replay.

Sequential completed-bar events; no generated prices used in research runs.
Each simulated fill is a standalone one-ounce opportunity, not an incremental
Frozen basket. Costs/specs are explicitly hypothetical. No live interfaces.
"""
from __future__ import annotations
import argparse, gzip, hashlib, itertools, json, os, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import snowball_s6_xau_grid as gold
import snowball_s5_fxcm_grid as old

FAMILIES=('IMPULSE_FVG_RETEST','LOCKED_BREAKOUT_RETEST',
          'SWEEP_MSS_ORIGIN_RETEST','COMPRESSION_EXPANSION_RETEST')
OUT=ROOT/'artifacts/r11'
SCENARIOS=('A1','B1','A2','B2')
NCONFIG=256

def dump(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')

def features(d):
    m=old.features(d)
    # Separate completed H1 confirmation. M5 labels are decision times.
    h=d.resample('60min',closed='left',label='right').agg(c=('bc','last'),n=('bc','count'))
    fast=h.c.ewm(span=20,adjust=False,min_periods=80).mean()
    slow=h.c.ewm(span=80,adjust=False,min_periods=80).mean()
    h['side']=np.sign(fast-slow).where(h.n.eq(60),0)
    m['h1']=h.side.reindex(m.index,method='ffill',tolerance=pd.Timedelta('60min')).fillna(0)
    return m

def events(m,family,side,look,wait):
    """Explicit state machine: setup -> later retest -> confirmation.

    Locked levels never slide after the setup. Expiry/reset uses only current
    time. No state survives missing M5 bars, a session boundary, or invalidation.
    """
    a=m[['o','h','l','c','atr','n','trend','h1']].to_numpy(float)
    t=m.index.asi8//60_000_000_000
    hi=m.h.shift().rolling(look,min_periods=look).max().to_numpy()
    lo=m.l.shift().rolling(look,min_periods=look).min().to_numpy()
    compression=(m.h.shift().rolling(6).max()-m.l.shift().rolling(6).min()).to_numpy()
    previous_atr=m.atr.shift().rolling(96,min_periods=48).median().to_numpy()
    result=[];pending=None
    for i in range(max(look+2,100),len(m)):
        o,h,l,c,atr,n,h4,h1=a[i]
        # Strict H1/H4 alignment and observed prior bar completeness.
        valid=(n==5 and np.isfinite(a[i]).all() and atr>0 and h4==side and h1==side
               and t[i]-t[i-1]==5 and m.index[i].dayofweek<5)
        if not valid:
            pending=None;continue
        body=(c-o)*side
        if pending is not None:
            age=i-pending['born']
            if age>wait or side*(c-pending['invalid'])<=0:
                pending=None
            elif age>=2:
                zlo,zhi=pending['lo'],pending['hi']
                touched=l<=zhi and h>=zlo
                confirmed=(body>.20*atr and (c-zhi)*side>0) if side==1 else (
                    body>.20*atr and c<zlo)
                # MSS must occur on a later bar than sweep, then origin retest.
                if family=='SWEEP_MSS_ORIGIN_RETEST' and pending['stage']==0:
                    if side*(c-pending['mss'])>.10*atr and body>.6*atr:
                        pending['stage']=1;pending['mss_at']=i
                    continue
                ready=(family!='SWEEP_MSS_ORIGIN_RETEST' or i>pending.get('mss_at',i))
                if touched and confirmed and ready:
                    result.append((i,pending['invalid'],pending['born']))
                    pending=None
                    continue
        if pending is not None:continue
        impulse=body>.9*atr and (c-a[i-1,3])*side>.6*atr
        invalid=l-.1*atr if side==1 else h+.1*atr
        zlo=zhi=None;stage=1;mss=0.
        if family=='IMPULSE_FVG_RETEST':
            gap=(l-a[i-2,1]) if side==1 else (a[i-2,2]-h)
            if gap>.10*atr and impulse:
                zlo,zhi=(a[i-2,1],l) if side==1 else (h,a[i-2,2])
                invalid=zlo-.25*atr if side==1 else zhi+.25*atr
        elif family=='LOCKED_BREAKOUT_RETEST':
            level=hi[i] if side==1 else lo[i]
            if impulse and side*(c-level)>.15*atr and side*(a[i-1,3]-level)<=0:
                zlo=level-.15*atr;zhi=level+.15*atr
                invalid=level-.8*atr if side==1 else level+.8*atr
        elif family=='SWEEP_MSS_ORIGIN_RETEST':
            level=lo[i] if side==1 else hi[i]
            sweep=(l<level-.15*atr and c>level) if side==1 else (h>level+.15*atr and c<level)
            if sweep and body>.2*atr:
                zlo=min(o,c);zhi=max(o,c);stage=0
                mss=max(a[i-3:i,1]) if side==1 else min(a[i-3:i,2])
        elif family=='COMPRESSION_EXPANSION_RETEST':
            level=hi[i] if side==1 else lo[i]
            # A compact prior range followed by a completed displacement bar,
            # later retest; not the S8 first-breakout entry.
            if (compression[i]<2.8*previous_atr[i] and impulse
                and atr>1.05*previous_atr[i] and side*(c-level)>.10*atr):
                zlo=level-.20*atr;zhi=level+.20*atr
                invalid=level-.8*atr if side==1 else level+.8*atr
        else:raise ValueError(family)
        if zlo is not None and np.isfinite([zlo,zhi,invalid]).all():
            pending=dict(born=i,lo=zlo,hi=zhi,invalid=invalid,stage=stage,mss=mss)
    return result

def repriced_quotes(a,cost):
    b=a[:,:4].copy();q=a[:,4:].copy()
    # Cost2 reruns widened quotes, triggers, fills and admission, not a PnL haircut.
    # Vendor OHLC extrema are not synchronous tick spreads; disclose approximation.
    extra=np.maximum(q-b,0)*(cost-1)/2
    return b-extra,q+extra

def replay(d,m,ev,side,hold,target,scenario):
    """M1 paths A=O-L-H-C, B=O-H-L-C, independent of position side.

    Genuine future gaps do not censor entries: position is liquidated at first
    next available quote with adverse slippage, even beyond planned holding time.
    Fixed 1oz units; no wallet sizing, margin assumptions, or V1 modification.
    """
    if not ev:return [],{}
    cost=int(scenario[1]);path=scenario[0]
    bid,ask=repriced_quotes(d.to_numpy(float),cost)
    quote=bid if side==1 else ask
    times=d.index.asi8//60_000_000_000
    mt=m.index.asi8//60_000_000_000
    slip=.05*cost;fee=.06*cost
    reject={};rows=[]
    for i,anchor,born in ev:
        j=int(np.searchsorted(times,mt[i]))
        if j>=len(times) or times[j]!=mt[i]:
            reject['missing_entry_quote']=reject.get('missing_entry_quote',0)+1;continue
        spread=ask[j,0]-bid[j,0]
        if spread<0 or spread>.15*m.atr.iloc[i]:
            reject['observed_spread_gate']=reject.get('observed_spread_gate',0)+1;continue
        entry=(ask[j,0]+slip) if side==1 else (bid[j,0]-slip)
        risk=max(side*(entry-anchor),1.25*m.atr.iloc[i])
        if not np.isfinite(risk) or risk<=0:
            reject['invalid_stop']=reject.get('invalid_stop',0)+1;continue
        stop=entry-side*risk;tp=entry+side*target*risk
        mae=mfe=0.;exitprice=None;why=None;k=j
        for k in range(j,min(j+hold,len(times))):
            if k>j and times[k]!=times[k-1]+1:
                exitprice=quote[k,0]-side*slip;why='gap_liquidation';break
            # If close is beyond UTC year boundary, liquidate. Annual screens
            # have separate warmup/state and are not a continuous account.
            order=(0,2,1,3) if path=='A' else (0,1,2,3)
            prev=quote[k,0]
            for vertex in order:
                price=quote[k,vertex]
                # Segment barrier first-hit; open can gap through stop/target.
                if side*(price-stop)<=0:
                    exitprice=min(price,stop)-slip if side==1 and vertex==0 else (
                        max(price,stop)+slip if side==-1 and vertex==0 else stop-side*slip)
                    mae=max(mae,max(0.,side*(entry-exitprice))/risk)
                    why='stop';break
                if side*(price-tp)>=0:
                    exitprice=tp-side*slip;why='target';break
                mae=max(mae,max(0.,side*(entry-price))/risk)
                mfe=max(mfe,max(0.,side*(price-entry))/risk)
                prev=price
            if exitprice is not None:break
        if exitprice is None:
            exitprice=quote[k,3]-side*slip
            why='timeout' if k-j+1==hold else 'data_cutoff'
        net=side*(exitprice-entry)-fee
        # Swap is avoided by pre-entry session gate and time stop. Any actual
        # gap spanning roll remains INCONCLUSIVE, with conservative $3/oz/day.
        roll_days=max(0,int(times[k]//1440-times[j]//1440))
        swap=3.*cost*roll_days
        net-=swap
        # Ledger timestamps use minute end for intrabar exits, conservative
        # ordering for same-timestamp settlement/admission.
        rows.append(dict(signal_utc=str(m.index[i]),setup_utc=str(m.index[born]),
            entry_minute=int(times[j]),exit_minute=int(times[k]+1),
            entry_utc=str(d.index[j]),exit_utc=str(d.index[k]+pd.Timedelta('1min')),
            symbol='XAUUSD',side=side,units_oz=1.,entry=entry,exit=exitprice,
            stop=stop,target=tp,risk_per_oz=risk,spread_entry=spread,
            commission_usd=fee,slippage_per_side=slip,swap_usd=swap,
            net_usd_1oz=net,net_R=net/risk,mfe_R=max(mfe,max(0.,side*(exitprice-entry))/risk),
            mae_R=mae,reason=why,scenario=scenario))
    return rows,reject

def admit(rows,guard):
    # One active independent position, 5-minute embargo after settlement.
    # 30-day guard uses realized past losses only. Each scenario is re-admitted.
    chosen=[];until=-1;pause=-1;losses=0;reject={}
    for r in rows:
        if r['entry_minute']<until:
            reject['position_or_embargo']=reject.get('position_or_embargo',0)+1;continue
        if r['entry_minute']<pause:
            reject['causal_loss_pause']=reject.get('causal_loss_pause',0)+1;continue
        chosen.append(r);until=r['exit_minute']+5
        if guard and r['net_usd_1oz']<0:
            losses+=1
            if losses==2:pause=r['exit_minute']+30*1440;losses=0
        elif r['net_usd_1oz']>0:losses=0
    return chosen,reject

def metric(rows):
    n=len(rows);v=np.array([r['net_R'] for r in rows]);usd=np.array([r['net_usd_1oz'] for r in rows])
    return dict(n=n,wins=int((v>0).sum()),losses=int((v<0).sum()),net_R=float(v.sum()),
        sum_R2=float((v*v).sum()),gain_R=float(v[v>0].sum()),loss_R=float(-v[v<0].sum()),
        mean_R=float(v.mean()) if n else None,net_usd_flat_1oz=float(usd.sum()),
        average_win_R=float(v[v>0].mean()) if (v>0).any() else None,
        average_loss_R=float(v[v<0].mean()) if (v<0).any() else None,
        mfe_R_sum=sum(r['mfe_R'] for r in rows),mae_R_sum=sum(r['mae_R'] for r in rows),
        gap_exits=sum(r['reason']=='gap_liquidation' for r in rows),
        occupied_minutes=sum(r['exit_minute']-r['entry_minute'] for r in rows),
        native_incremental_filled_baskets=None,native_floating_DD=None)

def configurations():
    for fam,side,look,wait,hold,tp,guard in itertools.product(
        FAMILIES,(1,-1),(12,24),(6,12),(60,180),(1.5,2.5),(False,True)):
        yield dict(family=fam,side=side,look=look,wait=wait,hold=hold,target=tp,guard=guard)

def key(c):return '|'.join(str(c[k]) for k in ('family','side','look','wait','hold','target','guard'))

def execute(year,pilot=False):
    OUT.mkdir(parents=True,exist_ok=True)
    if year==2026:
        import snowball_s8_xau_2026_partial as partial
        d,provenance=partial.acquire_2026(year)
    else:d,provenance=gold.source(year)
    if pilot:d=d.iloc[:min(len(d),60000)]
    # Decisions before 19:00 UTC, expires max 3 hours; avoid ordinary rollover
    # 21/22 UTC. Entry gate never uses future gap or future spread.
    m=features(d)
    cache={};out=[];fingerprints={}
    ledger=OUT/f'ledger_{year}{"_pilot" if pilot else ""}.jsonl.gz'
    with gzip.open(ledger,'wt') as f:
        for cfg in configurations():
            name=key(cfg);e_key=tuple(cfg[k] for k in ('family','side','look','wait'))
            if e_key not in cache:
                e=events(m,*e_key)
                cache[e_key]=[r for r in e if m.index[r[0]].hour<18]
            ev=cache[e_key];metrics={};rejections={}
            for scenario in SCENARIOS:
                raw,reject=replay(d,m,ev,cfg['side'],cfg['hold'],cfg['target'],scenario)
                chosen,admission=admit(raw,cfg['guard'])
                metrics[scenario]=metric(chosen);rejections[scenario]={**reject,**admission}
                digest=hashlib.sha256(json.dumps([(r['entry_minute'],r['exit_minute'],r['net_R']) for r in chosen]).encode()).hexdigest()
                fingerprints.setdefault(scenario,set()).add(digest)
                for row in chosen:
                    f.write(json.dumps(dict(config=name,**row),allow_nan=False)+'\n')
            out.append(dict(config=name,parameters=cfg,opportunities=len(ev),scenarios=metrics,rejects=rejections))
    assert len(out)==NCONFIG
    report=dict(study='R11_INDEPENDENT_XAU_SEQUENTIAL_SCREEN',year=year,pilot=pilot,
        commit_sha=os.getenv('GITHUB_SHA','LOCAL_TEST_ONLY'),
        run_url=f"https://github.com/{os.getenv('GITHUB_REPOSITORY','rizanrizan93/Forex-scanner')}/actions/runs/{os.getenv('GITHUB_RUN_ID','LOCAL')}",
        provenance=provenance,actual_screen_first=str(d.index[0]),actual_screen_last=str(d.index[-1]),
        configurations=NCONFIG,structural_families=len(FAMILIES),
        unique_nonempty_or_empty_ledger_fingerprints={k:len(v) for k,v in fingerprints.items()},
        rows=out,ledger_sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(),
        native_parity=False,shared_wallet=False,production_changes=False,
        limitations=['Dukascopy-derived public vendor OHLC; not original Frozen dataset or FP Markets',
            'Fixed 1oz standalone opportunities: not incremental baskets or compounding',
            'Hypothetical fee .06/oz round trip and .05/oz slippage each side; cost2 reprices spread and triggers',
            'OHLC bid/ask extrema not synchronous tick spreads; two possible intrabar paths only',
            'Yearly independent state/warmup; 2026 source stops in August, not November',
            'No broker capacity, minlot, risk/margin, funding certification or core displacement proof',
            'All history previously researched, no pristine OOS; promotion requires new forward shadow'])
    filename=OUT/f'result_{year}{"_pilot" if pilot else ""}.json';dump(filename,report)
    print('R11_SCREEN_COMPLETE',json.dumps({k:v for k,v in report.items() if k in
        ('year','pilot','commit_sha','run_url','configurations','structural_families','unique_nonempty_or_empty_ledger_fingerprints')}),flush=True)

def fold(reports,name,years,scenario):
    ms=[reports[y][name]['scenarios'][scenario] for y in years]
    total={k:sum(x[k] for x in ms) for k in ('n','wins','losses','net_R','sum_R2','gain_R','loss_R','net_usd_flat_1oz')}
    n=total['n'];mean=total['net_R']/n if n else None
    total.update(mean_R=mean,pf=total['gain_R']/total['loss_R'] if total['loss_R'] else None,
        positive_years=sum(x['net_R']>0 for x in ms),yearly_n=[x['n'] for x in ms])
    return total

def aggregate(root):
    files=list(Path(root).rglob('result_*.json'))
    raw=[json.loads(p.read_text()) for p in files if '_pilot' not in p.name]
    assert len(raw)==15 and {r['year'] for r in raw}==set(range(2012,2027))
    assert len({r['commit_sha'] for r in raw})==1
    reports={r['year']:{x['config']:x for x in r['rows']} for r in raw}
    names=set(reports[2012]);assert len(names)==NCONFIG
    assert all(set(r)==names for r in reports.values())
    summary=[];passes=[]
    for name in sorted(names):
        periods={label:{s:fold(reports,name,years,s) for s in SCENARIOS} for label,years in (
            ('development',range(2012,2019)),('validation',range(2019,2023)),('evaluation',range(2023,2026)),('partial_2026',[2026]))}
        # Pre-registered minimum sample, both independent A/B paths, and 2x costs.
        dev=all(periods['development'][s]['n']>=100 and periods['development'][s]['mean_R']>.02
            and (periods['development'][s]['pf'] or 0)>1.1
            and periods['development'][s]['positive_years']>=5 for s in ('A2','B2'))
        val=dev and all(periods['validation'][s]['n']>=50 and periods['validation'][s]['mean_R']>.01
            and (periods['validation'][s]['pf'] or 0)>1.05
            and periods['validation'][s]['positive_years']>=3 for s in ('A2','B2'))
        ev=val and all(periods['evaluation'][s]['n']>=30 and periods['evaluation'][s]['mean_R']>0
            and periods['evaluation'][s]['positive_years']>=2 for s in ('A2','B2'))
        row=dict(config=name,periods=periods,development_pass=dev,validation_pass=val,evaluation_pass=ev,
            decision='INCONCLUSIVE_SCREEN_PASS_NATIVE_REQUIRED' if ev else 'REJECT',
            annual={str(y):reports[y][name]['scenarios'] for y in range(2012,2027)})
        summary.append(row)
        if ev:passes.append(name)
    # Expanding walk-forward: at year y choose using years <y, 3h purge/time stop
    # and 5-minute embargo enforced per stream. Reused history disclosed.
    walk=[]
    for y in range(2019,2027):
        ranked=[]
        for name in names:
            fs=[fold(reports,name,range(2012,y),s) for s in ('A2','B2')]
            if all(x['n']>=100 and x['mean_R']>.02 and x['positive_years']>=int(.65*(y-2012)) for x in fs):
                ranked.append((min(x['mean_R'] for x in fs),name))
        selected=max(ranked)[1] if ranked else None
        walk.append(dict(year=y,selected_from_past_only=selected,
            next_year=reports[y][selected]['scenarios'] if selected else None))
    positive=sum(all(fold(reports,x,range(2012,2027),s)['net_R']>0 for s in ('A2','B2')) for x in names)
    result=dict(study='R11_256_SEQUENTIAL_POLICIES_15_YEARS',
        configurations=NCONFIG,families=4,model_years=NCONFIG*15,execution_scenarios=4,
        scenario_model_years=NCONFIG*15*4,development_qualified=sum(x['development_pass'] for x in summary),
        validation_qualified=sum(x['validation_pass'] for x in summary),evaluation_qualified=len(passes),
        positive_pooled_stress_expectancy_configurations=positive,
        screen_survivors=passes,native_ACCEPT=0,native_parity=False,
        incremental_filled_baskets=None,incremental_winning_baskets=None,
        continuous_wallet_balance_change=None,max_floating_DD_change=None,
        run_url=raw[0]['run_url'],commit_sha=raw[0]['commit_sha'],
        walk_forward=walk,all_results=summary,
        multiple_testing='No significance claim: 256 correlated policies, prior searches S5-S10. Forward shadow and family-wise block bootstrap required before acceptance.',
        status='INCONCLUSIVE_NATIVE_BLOCKED' if passes else 'REJECT_ALL_SCREENED',
        production_changes=False)
    dump(OUT/'aggregate.json',result)
    print('R11_AGGREGATE',json.dumps({k:v for k,v in result.items() if k not in ('all_results','walk_forward')}),flush=True)
    top=sorted(summary,key=lambda x:min(x['periods']['development'][s]['mean_R'] or -999 for s in ('A2','B2')),reverse=True)[:3]
    print('R11_TOP_DEVELOPMENT_DIAGNOSTICS',json.dumps(top),flush=True)

def selftest():
    assert len(list(configurations()))==NCONFIG
    # Synthetic data tests causality only, never written as a research result.
    rng=np.random.default_rng(715)
    ix=pd.date_range('2024-01-01',periods=8000,freq='5min',tz='UTC')
    c=2000+np.cumsum(rng.normal(.03,.9,len(ix)))
    m=pd.DataFrame(dict(o=c-.5,h=c+.8,l=c-.8,c=c,atr=np.full(len(ix),2.),n=np.full(len(ix),5),trend=np.ones(len(ix)),h1=np.ones(len(ix))),index=ix)
    for f in FAMILIES:
        for side in (1,-1):
            full=events(m,f,side,12,12)
            for cut in (3000,6000):
                prefix=events(m.iloc[:cut],f,side,12,12)
                assert prefix==[e for e in full if e[0]<cut],(f,side)
    # Same minute stop/target ambiguity must depend on A/B, not side.
    d=pd.DataFrame([[100,103,97,100,100.1,103.1,97.1,100.1]],
        columns=['bo','bh','bl','bc','ao','ah','al','ac'],index=pd.DatetimeIndex(['2024-01-01T10:00Z']))
    mm=pd.DataFrame({'atr':[2.]},index=d.index)
    ra,_=replay(d,mm,[(0,99.,0)],1,1,1.,'A1')
    rb,_=replay(d,mm,[(0,99.,0)],1,1,1.,'B1')
    assert ra[0]['net_R']<0 and rb[0]['net_R']>0
    stress,_=replay(d,mm,[(0,99.,0)],1,1,1.,'B2')
    assert stress[0]['entry']>rb[0]['entry'] and stress[0]['commission_usd']==.12
    # A gap cannot erase a losing entry after the fact.
    dg=pd.concat([d,d.set_axis(d.index+pd.Timedelta('1h'))])
    dg.iloc[0]=[100,100.2,99.9,100,100.1,100.3,100,100.1]
    gap,_=replay(dg,mm,[(0,90.,0)],1,60,10.,'A1')
    assert gap[0]['reason']=='gap_liquidation' and len(gap)==1
    fixture=[dict(entry_minute=i*1440,exit_minute=i*1440+60,net_usd_1oz=p) for i,p in [(0,-1),(1,-1),(2,100),(33,1)]]
    accepted,reject=admit(fixture,True)
    assert len(accepted)==3 and reject['causal_loss_pause']==1
    print('R11_SELFTEST_PASS prefix causality, A/B barriers, cost repricing, gap retention, realized-loss pause',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--selftest',action='store_true')
    p.add_argument('--year',type=int);p.add_argument('--pilot',action='store_true')
    p.add_argument('--aggregate');args=p.parse_args()
    if args.selftest:selftest()
    elif args.aggregate:aggregate(args.aggregate)
    elif args.year in range(2012,2027):execute(args.year,args.pilot)
    else:p.error('Use --selftest, --year, or --aggregate directory')
