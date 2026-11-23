"""Compare completed native account replays, retaining all core interference."""
from pathlib import Path
import argparse, gzip, hashlib, json
def read(p):return json.loads(gzip.decompress(p.read_bytes()))
def key(t):return (t['Entry'],t['Symbol'])
def run(root):
    root=Path(root).resolve();repo=root/'Forex-scanner/research/r16_no_pause';cases=root/'native_runs/cases'
    status=json.loads((repo/'run_status.json').read_text());assert status['exit_code']==0 and status['complete']
    basepath=cases/'r15_indexed_baseline_B_cost1.json.gz';b=read(basepath)
    core={key(t) for t in b['Ledger'] if t['Origin']!='SEED'}
    seed=[t for t in b['Ledger'] if t['Origin']=='SEED']
    fields=('EndingBalance','MaxEquityDDPct','MaxClosedDDPct','Baskets','Orders','PF',
            'MaxObservedMarginPct','MaxObservedOpenRiskPct','ErrorCount','OpenPositions','ActualCutoff')
    output={'stage':'R16_COMPLETED_NATIVE_B1_PILOT','initial_balance':100,
        'baseline':{f:b['Summary'][f] for f in fields},'cases':{},'new_pristine_OOS':False,
        'execution_model':'Synthetic M1 path B with original costs and native cash/order/fee/volume accounting',
        'extra_24h_pause':False,'live_changes':False,'promotion_allowed':False,
        'limitations':['Historical selection reused; no new OOS evidence',
            'Not FP Markets real ticks or proven billion-dollar liquidity',
            'Inherited macro snapshots and direction flags not point-in-time certified',
            'Path A, 2x costs and annual reset not tested in this batch',
            'Baseline already exceeds intended margin/open-risk caps']}
    for name in ['r16_quality_all','r16_quality_asia']:
        path=cases/f'{name}_B_cost1.json.gz';a=read(path);s=a['Summary']
        assert a['GrowthGuardAudit']['Enabled'] is False
        assert s['ErrorCount']==0 and s['OpenPositions']==0
        assert s['ActualCutoff']==b['Summary']['ActualCutoff']
        own={key(t) for t in a['Ledger'] if t['Origin'] not in ('SEED','ADDON')}
        addon=[t for t in a['Ledger'] if t['Origin']=='ADDON']
        missing=sorted(core-own);new=sorted(own-core)
        result={f:s[f] for f in fields}
        result.update(terminal_change_vs_baseline=s['EndingBalance']-b['Summary']['EndingBalance'],
            terminal_change_pct=100*(s['EndingBalance']/b['Summary']['EndingBalance']-1),
            floating_DD_change_pp=s['MaxEquityDDPct']-b['Summary']['MaxEquityDDPct'],
            addon_filled_baskets=len(addon),addon_winning_baskets=sum(t['Pnl']>0 for t in addon),
            original_core_keys_missing=len(missing),new_core_keys=len(new),
            seed_ledger_identical=[t for t in a['Ledger'] if t['Origin']=='SEED']==seed,
            missing_core_entries=missing,new_core_entries=new,
            guard_audit=a['GrowthGuardAudit'],addon_audit=a['AddonAudit'],trace=a['TraceAudit'],
            planned_exposure_caps_pass=s['MaxObservedMarginPct']<=50 and s['MaxObservedOpenRiskPct']<=20.75,
            raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        output['cases'][name]=result
    (repo/'results.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);run(p.parse_args().root)
