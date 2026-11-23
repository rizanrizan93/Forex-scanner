"""User-selected sparse anchor plus fixed additional policies; no live interface."""
from __future__ import annotations
import argparse, gzip, hashlib, io, itertools, json, os, sys, zipfile
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'research/r13_million_frequency'))
import search as r13
OUT=ROOT/'artifacts/r14'
HERE=Path(__file__).resolve().parent
REGISTRY=HERE/'candidate_registry.json'
SCENARIOS=('A1','B1','A2','B2')
ANCHOR_ID=27615
SOURCE_ZIP_SHA='48fd5a297365cfa14f0c55e53ab8c97333e843afdca1816d42f1d2d78d042ef3'

def dump(p,d):r13.dump(p,d)

def build_registry(archive):
    raw=Path(archive).read_bytes();assert hashlib.sha256(raw).hexdigest()==SOURCE_ZIP_SHA
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        with np.load(io.BytesIO(z.read('development_all_scores.npz'))) as a:
            scores=a['scores'];positive=a['positive_years']
    n=scores[:,0];mean=np.divide(scores[:,2],n,out=np.zeros(len(n)),where=n>0)
    eligible=np.flatnonzero((n>=30)&(mean>.05)&(scores[:,3]>1.20*scores[:,4])&(positive>=5))
    order=sorted(eligible,key=lambda i:(-scores[i,2],-scores[i,0],i))
    ids=[ANCHOR_ID];anchor=r13.decode(ANCHOR_ID)
    buckets={(anchor['family'],anchor['tf'],anchor['side'])}
    aliases={tuple(scores[ANCHOR_ID].tolist())+(int(positive[ANCHOR_ID]),)}
    for i in order:
        if len(ids)>=16:break
        cfg=r13.decode(i);bucket=(cfg['family'],cfg['tf'],cfg['side'])
        fingerprint=tuple(scores[i].tolist())+(int(positive[i]),)
        if bucket in buckets or fingerprint in aliases:continue
        ids.append(int(i));buckets.add(bucket);aliases.add(fingerprint)
    candidates=[]
    for priority,i in enumerate(ids):
        q=dict(zip(r13.COLS,scores[i].tolist()))
        candidates.append(dict(id=i,priority=priority,role='ANCHOR' if i==ANCHOR_ID else 'ADDITIONAL',
            parameters=r13.decode(i),development=q,development_mean_R=float(mean[i]),
            development_PF_R=float(q['gain_R']/q['loss_R']) if q['loss_R'] else None,
            development_positive_years=int(positive[i]),
            state='FIXED_RESEARCH_PARAMETERS_AWAITING_LATER_REPLAY',production_enabled=False))
    result=dict(study='R14_FIXED_SPARSE_REGISTRY',source_r13_selection_zip_sha256=SOURCE_ZIP_SHA,
        source_r13_commit='3bcc84ab54669553217394794aafcb33c7cacaa6',
        original_search_tuples=r13.NCONFIG,development_years=list(range(2012,2019)),
        exploratory_gate_tuples=int(len(eligible)),slots=len(candidates),candidates=candidates,
        user_selected_anchor=ANCHOR_ID,selection_uses_only_development=True,
        retrospective_R13_promotion=False,production_enabled=False,native_parity=False)
    dump(REGISTRY,result)
    print('R14_REGISTRY',json.dumps(result),flush=True)

def metrics(rows):
    if not rows:return dict(n=0,wins=0,net_R=0.,gain_R=0.,loss_R=0.,net_USD_flat_1oz=0.,sum_R2=0.)
    v=np.array([x['net_R'] for x in rows]);usd=np.array([x['net_USD_flat_1oz'] for x in rows])
    return dict(n=len(rows),wins=int((v>0).sum()),net_R=float(v.sum()),gain_R=float(v[v>0].sum()),
        loss_R=float(-v[v<0].sum()),net_USD_flat_1oz=float(usd.sum()),sum_R2=float((v*v).sum()))

def admit(rows):
    """Chronological one-slot basket, no use of PnL to choose candidates."""
    chosen=[];rejected=[];until=-1;seen=set()
    for row in sorted(rows,key=lambda x:(x['entry_minute'],x['priority'])):
        key=(row['entry_minute'],row['side'])
        if key in seen:rejected.append(dict(**row,reject_reason='same_time_side_alternative'));continue
        seen.add(key)
        if row['entry_minute']<until:
            rejected.append(dict(**row,reject_reason='open_position_or_five_minute_embargo'));continue
        chosen.append(row);until=row['exit_minute']+5
    return chosen,rejected

def baskets(raw):
    control,rejected0=admit([x for x in raw if x['config_id']==ANCHOR_ID])
    together,rejected=admit(raw)
    anchor_keys={(x['entry_minute'],x['side']) for x in control}
    retained_anchor_keys={(x['entry_minute'],x['side']) for x in together if x['config_id']==ANCHOR_ID}
    return dict(anchor=metrics(control),combined=metrics(together),
        additional_slot_fills=sum(x['config_id']!=ANCHOR_ID for x in together),
        anchor_control_fills_displaced=len(anchor_keys-retained_anchor_keys),
        duplicate_alternatives=sum(x['reject_reason']=='same_time_side_alternative' for x in rejected),
        occupancy_or_embargo_rejects=sum(x['reject_reason']=='open_position_or_five_minute_embargo' for x in rejected),
        combined_minus_anchor_fills=len(together)-len(control),
        combined_minus_anchor_flat_USD=sum(x['net_USD_flat_1oz'] for x in together)-sum(x['net_USD_flat_1oz'] for x in control)),control,together,rejected

def execute(year):
    registry=json.loads(REGISTRY.read_text());OUT.mkdir(parents=True,exist_ok=True)
    d,provenance=r13.acquire(year);frames={};signals={};allraw={sc:[] for sc in SCENARIOS};individual=[]
    for candidate in registry['candidates']:
        cfg=candidate['parameters'];tf=cfg['tf'];key=(tf,cfg['family'],cfg['look'],cfg['side'])
        if tf not in frames:frames[tf]=r13.features(d,tf)
        m=frames[tf]
        if key not in signals:signals[key]=np.flatnonzero(r13.signals(m,*key))
        ev=signals[key]
        g=r13.GATES.index((r13.REGIMES.index(cfg['regime']),r13.SESSIONS.index(cfg['session']),r13.SPREADS.index(cfg['spread']),r13.VOLS.index(cfg['vol'])))
        summaries={}
        for cost,path in itertools.product((1,2),(1,2)):
            b,a,times,pos,at,anchor,masks=r13.context(d,m,ev,cfg['side'],cost)
            raw=r13.outcomes(b,a,times,pos,at,anchor,cfg['side'],cfg['hold'],cfg['stop'],cfg['target'],cost,path)
            scenario=('A' if path==1 else 'B')+str(cost);rows=[]
            for e,v in enumerate(raw):
                if not masks[g,e] or v[0]<0:continue
                rows.append(dict(config_id=candidate['id'],priority=candidate['priority'],scenario=scenario,
                    signal_utc=str(m.index[ev[e]]),entry_minute=int(v[0]),exit_minute=int(v[1]),side=cfg['side'],
                    net_R=v[2],net_USD_flat_1oz=v[3],risk_per_oz=v[4],entry=v[5],exit=v[6],reason=int(v[7]),units_oz=1.))
            allraw[scenario].extend(rows)
            chosen,rejected=admit(rows)
            summaries[scenario]=dict(**metrics(chosen),raw_observed_gate_opportunities=len(rows),
                own_occupancy_or_embargo_rejects=len(rejected))
        individual.append(dict(id=candidate['id'],priority=candidate['priority'],parameters=cfg,scenarios=summaries))
    scenarios={}
    ledger=OUT/f'opportunities_and_fills_{year}.jsonl.gz'
    with gzip.open(ledger,'wt') as f:
        for sc,raw in allraw.items():
            stats,control,together,rejected=baskets(raw);scenarios[sc]=stats
            individual_fills=set()
            for candidate in registry['candidates']:
                chosen,_=admit([x for x in raw if x['config_id']==candidate['id']])
                individual_fills.update((x['config_id'],x['entry_minute']) for x in chosen)
            for row in sorted(raw,key=lambda x:(x['entry_minute'],x['priority'])):
                f.write(json.dumps(dict(**row,ledger='RAW_COUNTERFACTUAL',individually_admitted=(row['config_id'],row['entry_minute']) in individual_fills),allow_nan=False)+'\n')
            for label,rows in [('ANCHOR_ONLY_FILLED',control),('ALL_SLOTS_FILLED',together),('ALL_SLOTS_REJECTED',rejected)]:
                for row in rows:f.write(json.dumps(dict(**row,ledger=label),allow_nan=False)+'\n')
    report=dict(study='R14_SPARSE_ANNUAL',year=year,registry_sha256=hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
        commit_sha=os.getenv('GITHUB_SHA','LOCAL'),slots=registry['slots'],individual=individual,basket_scenarios=scenarios,
        provenance=provenance,actual_first=str(d.index[0]),actual_last=str(d.index[-1]),
        ledger_sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(),
        native_parity=False,shared_V1_wallet=False,V1_incremental_funded_fills=None,V1_balance_change=None,
        production_changes=False)
    dump(OUT/f'annual_{year}.json',report)
    print('R14_ANNUAL',year,'slots',registry['slots'],'stress',json.dumps({s:scenarios[s] for s in ('A2','B2')}),flush=True)

def fold(ms):
    keys=('n','wins','net_R','gain_R','loss_R','net_USD_flat_1oz','sum_R2')
    result={k:sum(x[k] for x in ms) for k in keys}
    result.update(mean_R=result['net_R']/result['n'] if result['n'] else None,
        PF_R=result['gain_R']/result['loss_R'] if result['loss_R'] else None,
        positive_years=sum(x['net_R']>0 for x in ms),yearly_n=[x['n'] for x in ms])
    return result

def aggregate(root):
    paths=list(Path(root).rglob('annual_*.json'));assert len(paths)==8
    annual={x['year']:x for x in map(lambda p:json.loads(p.read_text()),paths)}
    assert set(annual)==set(range(2019,2027))
    assert len({x['commit_sha'] for x in annual.values()})==1
    assert len({x['registry_sha256'] for x in annual.values()})==1
    registry=json.loads(REGISTRY.read_text());assert hashlib.sha256(REGISTRY.read_bytes()).hexdigest()==annual[2019]['registry_sha256']
    candidates=[]
    for candidate in registry['candidates']:
        cid=candidate['id'];periods={}
        for label,years in [('validation',range(2019,2023)),('evaluation',range(2023,2026)),('partial2026',[2026])]:
            periods[label]={sc:fold([next(x for x in annual[y]['individual'] if x['id']==cid)['scenarios'][sc] for y in years]) for sc in SCENARIOS}
        val=all((x:=periods['validation'][sc])['n']>=20 and x['mean_R']>0 and x['gain_R']>1.05*x['loss_R'] and x['positive_years']>=3 for sc in ('A2','B2'))
        eva=val and all((x:=periods['evaluation'][sc])['n']>=15 and x['mean_R']>0 and x['positive_years']>=2 for sc in ('A2','B2'))
        candidates.append(dict(**candidate,periods=periods,validation_pass=val,evaluation_pass=eva,
            decision='INCONCLUSIVE_FORWARD_NATIVE_REQUIRED' if eva else 'REJECT_LATER_PERIOD_SCREEN'))
    comparison={}
    for label,years in [('full2019_2025',range(2019,2026)),('partial2026',[2026])]:
        comparison[label]={}
        for sc in SCENARIOS:
            rows=[annual[y]['basket_scenarios'][sc] for y in years]
            a=fold([x['anchor'] for x in rows]);b=fold([x['combined'] for x in rows])
            comparison[label][sc]=dict(anchor=a,combined=b,
                additional_slot_fills=sum(x['additional_slot_fills'] for x in rows),
                anchor_control_fills_displaced=sum(x['anchor_control_fills_displaced'] for x in rows),
                duplicates=sum(x['duplicate_alternatives'] for x in rows),
                occupancy_or_embargo_rejects=sum(x['occupancy_or_embargo_rejects'] for x in rows),
                combined_minus_anchor_fills=b['n']-a['n'],combined_minus_anchor_flat_USD=b['net_USD_flat_1oz']-a['net_USD_flat_1oz'])
    passed=all((x:=comparison['full2019_2025'][sc])['combined']['n']>=80
        and x['combined']['mean_R']>0 and x['combined']['gain_R']>1.05*x['combined']['loss_R']
        and x['combined']['positive_years']>=5 and x['combined']['net_USD_flat_1oz']>0
        and x['combined_minus_anchor_fills']>0 and x['combined_minus_anchor_flat_USD']>0 for sc in ('A2','B2'))
    report=dict(study='R14_FIXED_SPARSE_ADDONS',source_commit=annual[2019]['commit_sha'],registry=registry,
        registered_slots=registry['slots'],candidate_results=candidates,basket_comparison=comparison,
        individual_screen_survivors=sum(x['evaluation_pass'] for x in candidates),fixed_basket_screen_pass=passed,
        status='INCONCLUSIVE_FORWARD_NATIVE_REQUIRED' if passed else 'REJECT_FIXED_BASKET',
        native_ACCEPT=0,shared_V1_wallet=False,native_parity=False,V1_incremental_funded_fills=None,V1_balance_change=None,
        max_V1_floating_DD_change=None,production_changes=False,
        annual_provenance=[dict(year=y,actual_first=annual[y]['actual_first'],actual_last=annual[y]['actual_last'],provenance=annual[y]['provenance']) for y in sorted(annual)])
    dump(OUT/'final.json',report)
    print('R14_FINAL',json.dumps({k:v for k,v in report.items() if k not in ('registry','candidate_results','annual_provenance')}),flush=True)

def selftest():
    r13.selftest()
    assert r13.decode(ANCHOR_ID)==dict(tf=5,family='BREAKOUT',look=32,side=-1,hold=240,stop=3.,target=2.5,regime='WITH',session='LONDON',spread=.35,vol='ALL')
    def row(cid,p,t,end,pnl):return dict(config_id=cid,priority=p,entry_minute=t,exit_minute=end,side=-1,net_R=pnl,net_USD_flat_1oz=pnl)
    raw=[row(ANCHOR_ID,0,100,110,1),row(2,1,100,105,100),row(2,1,116,130,-1),row(ANCHOR_ID,0,120,125,3),row(ANCHOR_ID,0,140,145,2)]
    stats,a,b,rejected=baskets(raw)
    assert stats['duplicate_alternatives']==1 and stats['anchor_control_fills_displaced']==1
    assert [x['entry_minute'] for x in b]==[100,116,140]
    # The rejected later anchor's +3 cannot override actual occupancy; no future-profit selection.
    assert metrics(b)['net_R']==2
    # Combined basket must start from raw signals: a later signal can be free after
    # an individually preferred earlier trade is displaced by the anchor.
    fixture=[row(ANCHOR_ID,0,100,110,1),row(2,1,105,150,-1),row(2,1,120,125,2)]
    _,_,chosen,_=baskets(fixture);assert [x['entry_minute'] for x in chosen]==[100,120]
    print('R14_SELFTEST_PASS exact anchor, causal combined admission, raw opportunities, duplicates and later-anchor displacement',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--register');p.add_argument('--selftest',action='store_true')
    p.add_argument('--year',type=int);p.add_argument('--aggregate');a=p.parse_args()
    if a.selftest:selftest()
    elif a.register:build_registry(a.register)
    elif a.aggregate:aggregate(a.aggregate)
    elif a.year in range(2019,2027):execute(a.year)
    else:p.error('Choose --register, --selftest, --year or --aggregate')
