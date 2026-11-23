"""R13 EURUSD cross-instrument replication; no Frozen portfolio authority."""
import argparse,contextlib,gzip,hashlib,importlib.util,io,json,math,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('r12_stage',ROOT/'research/r12_stage_growth/engine.py')
r12=importlib.util.module_from_spec(spec);spec.loader.exec_module(r12)
b=r12.base
OUT=ROOT/'artifacts/r13'
original_fx_source=b.old.get_data

def source(year):
    d,prov=original_fx_source(year)
    prov['quote_scale_USD_per_1000EUR']=1000
    prov['unit']='1000EUR research block, not gold ounces'
    return d*1000,prov

def rename(x):
    if isinstance(x,dict):return {k.replace('units_oz','blocks_1000eur').replace('net_usd_flat_1oz','net_usd_flat_1000eur').replace('net_usd_1oz','net_usd_1000eur').replace('risk_per_oz','risk_per_1000eur'):rename(v) for k,v in x.items()}
    if isinstance(x,list):return [rename(v) for v in x]
    if x=='XAUUSD':return 'EURUSD'
    return x

def execute(year,pilot=False):
    b.OUT=OUT;b.gold.source=source
    with contextlib.redirect_stdout(io.StringIO()):b.execute(year,pilot)
    suffix='_pilot' if pilot else '';p=OUT/f'result_{year}{suffix}.json'
    obj=json.loads(p.read_text());streams={};ledger=OUT/f'ledger_{year}{suffix}.jsonl.gz'
    with gzip.open(ledger,'rt') as f:
        rows=[json.loads(line) for line in f]
    for r in rows:streams.setdefault((r['config'],r['scenario']),[]).append(r)
    for r in obj['rows']:r['standalone_annual_wallet']={s:r12.wallet(streams.get((r['config'],s),[])) for s in b.SCENARIOS}
    with gzip.open(ledger,'wt') as f:
        for row in rows:f.write(json.dumps(rename(row))+'\n')
    obj.update(study='R13_EURUSD_64_R12_POLICY_REPLICATION',structural_families=2,
        ledger_sha256=hashlib.sha256(ledger.read_bytes()).hexdigest(),
        limitations=['FXCM EURUSD observed bid/ask, 2012-2025 only; no2026 source',
        'Standalone1000EUR block, hypothetical fees/slippage/margin/minimum; not FP Markets certified',
        'Risk8percent below125 and3percent above; settled DD only, no native/Frozen portfolio balance',
        'Inherited3USD/block/day gap reserve is conservative assumption, not verified swap',
        'R12 hypotheses reused cross-instrument; no pristine OOS, all previous searches count'])
    obj=rename(obj);b.dump(p,obj)
    print('R13_YEAR',json.dumps(dict(year=year,pilot=pilot,configurations=64,
        stage125_any_scenario=sum(any(w['first_settled_threshold_utc']['125'] for w in r['standalone_annual_wallet'].values()) for r in obj['rows']),native_parity=False)),flush=True)

def fold(reports,name,years,s):
    ms=[reports[y][name]['scenarios'][s] for y in years]
    n=sum(m['n'] for m in ms);gain=sum(m['gain_R'] for m in ms);loss=sum(m['loss_R'] for m in ms)
    return dict(n=n,net_R=sum(m['net_R'] for m in ms),mean_R=sum(m['net_R'] for m in ms)/n if n else None,pf=gain/loss if loss else None,positive_years=sum(m['net_R']>0 for m in ms))

def aggregate(root):
    raw=[json.loads(p.read_text()) for p in Path(root).rglob('result_*.json') if '_pilot' not in p.name]
    assert len(raw)==14 and {x['year'] for x in raw}==set(range(2012,2026))
    assert len({x['commit_sha'] for x in raw})==1
    reports={x['year']:{r['config']:r for r in x['rows']} for x in raw};names=sorted(reports[2012]);assert len(names)==64
    assert all(set(q)==set(names) for q in reports.values())
    summary=[]
    for name in names:
        periods={label:{s:fold(reports,name,years,s) for s in b.SCENARIOS} for label,years in [('development',range(2012,2019)),('validation',range(2019,2023)),('evaluation',range(2023,2026))]}
        dev=all(x['n']>=100 and x['mean_R']>.02 and (x['pf'] or 0)>1.10 and x['positive_years']>=5 for s,x in periods['development'].items() if s in ('A2','B2'))
        val=dev and all(x['n']>=50 and x['mean_R']>.01 and (x['pf'] or 0)>1.05 and x['positive_years']>=3 for s,x in periods['validation'].items() if s in ('A2','B2'))
        ev=val and all(x['n']>=30 and x['mean_R']>0 and x['positive_years']>=2 for s,x in periods['evaluation'].items() if s in ('A2','B2'))
        summary.append(dict(config=name,periods=periods,development_pass=dev,validation_pass=val,evaluation_pass=ev))
    cash={s:100. for s in b.SCENARIOS};walk=[]
    for y in range(2019,2026):
        ranking=[]
        for name in names:
            fs=[fold(reports,name,range(2012,y),s) for s in ('A2','B2')]
            if all(x['n']>=100 and x['mean_R']>.02 and (x['pf'] or 0)>1.10 and x['positive_years']>=math.ceil(.65*(y-2012)) for x in fs):ranking.append((min(x['mean_R'] for x in fs),name))
        name=max(ranking)[1] if ranking else None;wallets={}
        rows=[]
        if name:
            matches=list(Path(root).rglob(f'ledger_{y}.jsonl.gz'));assert len(matches)==1
            with gzip.open(matches[0],'rt') as f:
                for line in f:
                    r=json.loads(line)
                    if r['config']==name:
                        r['net_usd_1oz']=r['net_usd_1000eur'];r['risk_per_oz']=r['risk_per_1000eur'];rows.append(r)
        for s in b.SCENARIOS:
            wallets[s]=r12.wallet([r for r in rows if r['scenario']==s],cash[s]);cash[s]=wallets[s]['ending_cash']
        walk.append(dict(year=y,past_only_selected=name,wallet=wallets))
    result=dict(study='R13_EURUSD_R12_REPLICATION',configurations=64,families=2,years=14,
        scenario_configuration_years=64*14*4,development_qualified=sum(x['development_pass'] for x in summary),validation_qualified=sum(x['validation_pass'] for x in summary),evaluation_qualified=sum(x['evaluation_pass'] for x in summary),
        positive_pooled_stress_expectancy_configurations=sum(all(fold(reports,n,range(2012,2026),s)['net_R']>0 for s in ('A2','B2')) for n in names),
        native_parity=False,production_changes=False,terminal_Frozen_balance_change=None,
        standalone_past_only_ending_cash=cash,walk_forward=walk,all_results=summary,
        annual_standalone={str(y):{n:reports[y][n]['standalone_annual_wallet'] for n in names} for y in reports},
        commit_sha=raw[0]['commit_sha'],run_url=raw[0]['run_url'],target_10_billion_verified=False,
        caveat='Reused history and related R12 hypotheses; hypothetical execution costs/specs. No2026, pristine OOS, significance, floating DD or native wallet claim.')
    b.dump(OUT/'aggregate.json',result)
    print('R13_AGGREGATE',json.dumps({k:v for k,v in result.items() if k not in ('all_results','annual_standalone','walk_forward')}),flush=True)

def selftest():
    r12.selftest()
    # A1000EUR block at1.10USD/EUR =1100USD notional, margin5.50USD at200x.
    import pandas as pd
    d=pd.DataFrame([[1.1,1.101,1.099,1.1,1.1001,1.1011,1.0991,1.1001]],columns=['bo','bh','bl','bc','ao','ah','al','ac'],index=pd.DatetimeIndex(['2024-01-02T10:00Z']))*1000
    m=pd.DataFrame({'atr':[1.]},index=d.index)
    rows,_=b.replay(d,m,[(0,1099.,0)],1,1,1.5,'A1');row=rows[0]
    assert abs(row['commission_usd']-.06)<1e-12 and abs(row['entry']-1100.15)<1e-9
    assert abs(row['net_usd_1oz']-((row['exit']-row['entry'])-.06))<1e-9
    assert rename(row)['symbol']=='EURUSD' and rename(row)['blocks_1000eur']==1.
    print('R13_DIMENSIONAL_SELFTEST_PASS 1000EUR price, fees, spread, USD PnL and labels')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--selftest',action='store_true');p.add_argument('--year',type=int);p.add_argument('--pilot',action='store_true');p.add_argument('--aggregate');a=p.parse_args()
    if a.selftest:selftest()
    elif a.aggregate:aggregate(a.aggregate)
    elif a.year in range(2012,2026):execute(a.year,a.pilot)
    else:p.error('Choose selftest, year2012-2025 or aggregate')
