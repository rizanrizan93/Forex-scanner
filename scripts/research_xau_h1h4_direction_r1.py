"""Read-only XAU H1/H4 annual backtest. Train 2019-23; validate 2024; test 2025-26."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import pandas as pd
from research.zone_rebound.h1h4_direction_r1 import validate_m1,candidates,apply_policy,replay,summary

POLICIES=[{'threshold':t,'require_h4':g} for t in (3,4,5,6) for g in (False,True)]
TRAIN=set(range(2019,2024))
VALID={2024}
TEST={2025,2026}

def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def label(p):return f"threshold{p['threshold']}_requireH4{int(p['require_h4'])}"

def year_run(price_csv:Path,*,year:int,spread_scenario_usd:float=.5,
             provenance:Path|None=None)->dict:
    d=validate_m1(pd.read_csv(price_csv))
    prov=json.loads(provenance.read_text()) if provenance and provenance.exists() else None
    if prov:
        if prov.get('year')!=year or prov.get('normalized_csv_sha256')!=sha256(price_csv):
            raise ValueError('PROVENANCE_OR_INPUT_SHA_MISMATCH')
    res={}
    for tf in (60,240):
        c=candidates(d,timeframe=tf)
        c=c.loc[c.index.year==year]
        for p in POLICIES:
            signals=apply_policy(c,**p)
            ledger=replay(d,signals,spread_scenario_usd=spread_scenario_usd)
            res.setdefault(label(p),{})[str(tf)]={
                'rows':summary(ledger),'generated':len(signals),
                'active':int((signals.side!=0).sum()),
                'wait':int((signals.side==0).sum()),
                'examples':ledger.head(5).to_dict('records') if not ledger.empty else []}
    return {'contract':'RIZAN_XAU_H1H4_DIRECTION_R1_REPLAY','year':year,
        'source':'HISTDATA_PUBLIC_M1_NONEXECUTABLE','price_hash':sha256(price_csv),
        'price_rows':len(d),'first_utc':d.index[0].isoformat(),'last_utc':d.index[-1].isoformat(),
        'provenance':prov,'assumed_roundtrip_cost_usd_per_oz':spread_scenario_usd,
        'metric':'HORIZON_NET_DIRECTION_AND_NET10_BEFORE_GROSS10_ADVERSE',
        'observational_only':True,'execution_authority':False,'execution_influence':False,
        'policies':res}

def wilson_lower(w:int,n:int,z:float=1.96)->float:
    if n==0:return 0.
    p=w/n
    return (p+z*z/(2*n)-z*((p*(1-p)/n+z*z/(4*n*n))**.5))/(1+z*z/n)

def aggregate(year_files:list[Path])->dict:
    shards=[json.loads(p.read_text()) for p in year_files]
    years=[int(x['year']) for x in shards]
    if len(years)!=len(set(years)) or set(years)!=set(range(2019,2027)):
        raise ValueError('EIGHT_UNIQUE_YEARS_2019_2026_REQUIRED')
    if any(x['contract']!='RIZAN_XAU_H1H4_DIRECTION_R1_REPLAY' for x in shards):
        raise ValueError('INVALID_SHARD_CONTRACT')
    costs={x['assumed_roundtrip_cost_usd_per_oz'] for x in shards}
    if len(costs)!=1:raise ValueError('COST_SCENARIO_MISMATCH')
    def collect(policy,tf,subset):
        totals={side:{'signals':0,'evaluated':0,'gaps':0,'directional_wins':0,
                      'net10_before_adverse10':0} for side in ('BUY','SELL')}
        for sh in shards:
            if sh['year'] not in subset:continue
            for r in sh['policies'][policy][str(tf)]['rows']:
                v=totals[r['side']]
                for k in v:v[k]+=int(r[k])
        for side,d in totals.items():
            n=d['evaluated']
            d['directional_accuracy']=d['directional_wins']/n if n else None
            d['net10_rate']=d['net10_before_adverse10']/n if n else None
            d['wilson_lower95_directional']=wilson_lower(d['directional_wins'],n)
        return totals
    selected={}
    for tf in (60,240):
        ranking=[]
        for p in POLICIES:
            name=label(p);train=collect(name,tf,TRAIN)
            enough=min(train[s]['evaluated'] for s in ('BUY','SELL'))>=50
            score=min(train[s]['wilson_lower95_directional'] for s in ('BUY','SELL')) if enough else -1
            ranking.append((score,name,train))
        ranking.sort(key=lambda x:(-x[0],x[1]));best=ranking[0]
        if best[0]<0:
            selected[str(tf)]={'status':'NO_ELIGIBLE_POLICY',
                'ranking':[{'policy':name,'score':score} for score,name,_ in ranking]}
            continue
        name=best[1]
        selected[str(tf)]={'status':'RESEARCH_ONLY','policy':name,
            'train_2019_2023':best[2],
            'validation_2024':collect(name,tf,VALID),
            'locked_test_2025_2026':collect(name,tf,TEST),
            'annual':{str(y):collect(name,tf,{y}) for y in range(2019,2027)},
            'ranking_train':[{'policy':n,'minimum_side_wilson95':s} for s,n,_ in ranking]}
    return {'contract':'RIZAN_XAU_H1H4_DIRECTION_R1_AGGREGATE',
        'years':sorted(years),
        'split':{'training':'2019-2023','validation':'2024','locked_test':'2025-2026'},
        'source':'HISTDATA_PUBLIC_M1_NONEXECUTABLE',
        'assumed_roundtrip_cost_usd_per_oz':costs.pop(),
        'execution_authority':False,'execution_influence':False,
        'warning':'Not FP Markets bid/ask replay; 2026 partial. DXY/yield not yet available in full. Directional hit rate is not the USD10 win rate.',
        'selected':selected}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--csv',type=Path);p.add_argument('--year',type=int)
    p.add_argument('--provenance',type=Path);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--aggregate',nargs='*',type=Path);p.add_argument('--cost',type=float,default=.5)
    a=p.parse_args()
    if a.aggregate is not None:result=aggregate(a.aggregate)
    else:
        if a.csv is None or a.year not in range(2019,2027):
            p.error('CSV and year 2019..2026 required')
        result=year_run(a.csv,year=a.year,spread_scenario_usd=a.cost,provenance=a.provenance)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,default=str,allow_nan=False)+'\n')
    print('XAU_DIRECTION_REPLAY '+json.dumps({'contract':result['contract'],
        'year':result.get('year'),'years':result.get('years'),
        'output':str(a.out),'execution_authority':False}))

if __name__=='__main__':main()
