"""R14 actual archived basket screening. Not a native counterfactual wallet."""
from pathlib import Path
import argparse,hashlib,heapq,itertools,json,math,datetime as dt,os
ROOT=Path(__file__).resolve().parent

def stamp(s):return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
def key(scope,symbol):return symbol if scope=='symbol' else 'ALL'
def admit(rows,scope,loss_limit,days):
    pending=[];streak={};pause={};chosen=[];sequence=0
    for row in sorted(rows,key=lambda r:(r[0],r[2],r[1])):
        now=stamp(row[0])
        while pending and pending[0][0]<=now:
            end,seq,r=heapq.heappop(pending);k=key(scope,r[2]);loss=streak.get(k,0)
            if r[3]<0:
                loss+=1
                if loss>=loss_limit:pause[k]=max(pause.get(k,end),end+dt.timedelta(days=days));loss=0
            elif r[3]>0:loss=0
            streak[k]=loss
        k=key(scope,row[2])
        if now<pause.get(k,dt.datetime.min.replace(tzinfo=dt.timezone.utc)):continue
        chosen.append(row);heapq.heappush(pending,(stamp(row[1]),sequence,row));sequence+=1
    return chosen

def metric(rows,years):
    a=[r for r in rows if stamp(r[1]).year in years]
    returns=[r[3]/r[4] for r in a]
    gain=sum(v for v in returns if v>0);loss=-sum(v for v in returns if v<0)
    annual={str(y):sum(r[3]/r[4] for r in a if stamp(r[1]).year==y) for y in years}
    return dict(n=len(a),sum_normalized_return=sum(returns),mean_normalized_return=sum(returns)/len(a) if a else None,pf_normalized=gain/loss if loss else None,positive_years=sum(v>0 for v in annual.values()),annual_additive_normalized=annual)

def run():
    manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text());data={}
    for name,entry in manifest['files'].items():
        p=ROOT/'data'/f'{name}.json';assert hashlib.sha256(p.read_bytes()).hexdigest()==entry['derived_file_sha256']
        obj=json.loads(p.read_text());assert obj['member_sha256']==entry['compressed_member_sha256']
        assert not obj['cashflows'] and not obj['errors']
        assert len(obj['rows'])==obj['summary']['Baskets']==entry['rows']
        assert all(r[4]>0 and math.isfinite(r[3]/r[4]) and stamp(r[1])>=stamp(r[0]) for r in obj['rows'])
        assert abs(100+math.fsum(r[3] for r in obj['rows'])-obj['summary']['EndingBalance'])<.01
        data[name]=obj
    periods={'development':range(2019,2023),'validation':range(2023,2026),'partial2026':[2026]}
    controls={n:{label:metric(o['rows'],years) for label,years in periods.items()} for n,o in data.items()}
    summaries=[]
    for scope,limit,days in itertools.product(('global','symbol'),(2,3,4),(1,7,30)):
        candidate={}
        for name,obj in data.items():
            chosen=admit(obj['rows'],scope,limit,days)
            candidate[name]={label:metric(chosen,years) for label,years in periods.items()}
        def passed(label,minn,pos):
            for name in ('incumbent_A1','incumbent_B1','incumbent_B2'):
                c=candidate[name][label];u=controls[name][label]
                if not(c['n']>=max(minn,.5*u['n']) and c['positive_years']>=pos and c['mean_normalized_return']>u['mean_normalized_return'] and c['sum_normalized_return']>u['sum_normalized_return']):return False
            return True
        dev=passed('development',50,3);val=dev and passed('validation',30,2)
        lift=min(candidate[n]['development']['sum_normalized_return']-controls[n]['development']['sum_normalized_return'] for n in ('incumbent_A1','incumbent_B1','incumbent_B2'))
        summaries.append(dict(scope=scope,loss_limit=limit,pause_days=days,development_pass=dev,validation_pass=val,development_min_sum_lift=lift,diagnostics=candidate))
    selected=max(summaries,key=lambda c:(c['development_pass'],c['development_min_sum_lift'],c['scope'],c['loss_limit'],c['pause_days']))
    risk={name:{'archived_ending_balance':o['summary']['EndingBalance'],'archived_max_floating_DD_pct':o['summary']['MaxEquityDDPct'],'observed_open_risk_pct':o['summary']['MaxObservedOpenRiskPct'],'observed_margin_pct':o['summary']['MaxObservedMarginPct'],'planned_cap_observation_pass':o['summary']['MaxObservedOpenRiskPct']<=20.75 and o['summary']['MaxObservedMarginPct']<=50} for name,o in data.items()}
    report=dict(study='R14_CAUSAL_GROWTH_GUARD_DIAGNOSTIC',policies=18,archived_native_records=sum(len(o['rows']) for o in data.values()),archive_risk_observations=risk,controls=controls,development_qualified=sum(c['development_pass'] for c in summaries),validation_qualified=sum(c['validation_pass'] for c in summaries),selected_on_development_only=selected,all_policies=summaries,attachment=manifest['attachment'],native_counterfactual_replay=False,new_terminal_balance=None,new_floating_DD=None,production_changes=False,promotion_allowed=False,target10B_verified=False,run_url=f"https://github.com/{os.getenv('GITHUB_REPOSITORY','rizanrizan93/Forex-scanner')}/actions/runs/{os.getenv('GITHUB_RUN_ID','LOCAL')}",commit_sha=os.getenv('GITHUB_SHA'))
    out=Path('artifacts/r14');out.mkdir(parents=True,exist_ok=True);(out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('R14_RESULT',json.dumps({k:v for k,v in report.items() if k not in ('all_policies','controls','selected_on_development_only')}),flush=True)
    print('R14_DEVELOPMENT_SELECTED',json.dumps({k:v for k,v in selected.items() if k!='diagnostics'}),flush=True)
    return report

def selftest():
    def row(e,x,p,s='XAUUSD'):return [f'2020-01-{e:02d}T00:00:00Z',f'2020-01-{x:02d}T00:00:00Z',s,p,100.,100.,None]
    rows=[row(1,2,-1),row(2,3,-1),row(3,4,100),row(5,6,1)]
    chosen=admit(rows,'global',2,1);assert [r[0] for r in chosen]==[rows[0][0],rows[1][0],rows[3][0]]
    # A future settlement must never pause an earlier entry.
    rows2=[row(1,10,-1),row(2,3,-1),row(3,4,100)]
    assert len(admit(rows2,'global',2,7))==3
    for scope in ('global','symbol'):
        for cut in range(1,len(rows)+1):assert admit(rows[:cut],scope,2,1)==[r for r in admit(rows,scope,2,1) if r[0]<=rows[cut-1][0]]
    rows3=[row(1,2,-1),row(2,3,-1),row(3,4,100,'EURUSD')]
    assert len(admit(rows3,'symbol',2,7))==3
    print('R14_SELFTEST_PASS settlement-first, no future settlement leakage, prefix and per-symbol isolation')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--selftest',action='store_true');a=p.parse_args()
    if a.selftest:selftest()
    else:run()
