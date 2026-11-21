"""Post-selection diagnostic for frozen R10 H1/H4 setups. Research only.
2024-2026 evaluation is NOT an untouched holdout.
"""
import json, glob
from pathlib import Path
import numpy as np
import pandas as pd
from r10_million import load, ohlc_indicators, align_context, predicates, unpack_rules, wilson

CHOSEN={'1h': {'BUY':73827,'SELL':1984866},'4h':{'BUY':892952,'SELL':1836969}}
OUT=Path('artifacts'); OUT.mkdir(exist_ok=True)

def estimate(profit,right,favorable,adverse):
    n=len(profit)
    if not n:return {'n':0}
    k=int(np.count_nonzero(right))
    return {'n':int(n),'accuracy':float(k/n),'wilson95_lower':float(wilson(k,n)),
            'gross_mean_usd_per_oz':float(np.mean(profit)),
            'gross_median_usd_per_oz':float(np.median(profit)),
            'break_even_roundtrip_friction_usd_per_oz':float(np.mean(profit)),
            'mfe_gte_10_ratio':float(np.mean(favorable>=10)),
            'avg_mfe_usd_per_oz':float(np.mean(favorable)),
            'avg_mae_usd_per_oz':float(np.mean(adverse))}

def run():
    provenance=[]
    for p in sorted(glob.glob('/tmp/r10/r10-provenance-*.json')):
        x=json.loads(Path(p).read_text())
        provenance.append({'year':x.get('year'),'input_rows':x.get('rows'),'failed_periods':len(x.get('failed_periods',[])),
                           'last_timestamp_utc':x.get('last_timestamp_utc'),'sha256':x.get('normalized_csv_sha256')})
    assert len(provenance)==8,'Missing source provenance'
    report={'research':'RIZAN R10.1 frozen candidate audit','selected_source':'R10 GitHub run 44901264975',
            'non_pristine_evaluation':True,'frozen_candidate_configs':CHOSEN,'provenance':provenance,'timeframes':{}}
    base=load('1h')
    for tf,choice in CHOSEN.items():
        d=load(tf);z=ohlc_indicators(d)
        align_context(z,base,'D','d1');align_context(z,base,'W','w1')
        hours=1 if tf=='1h' else 4
        contiguous=((d.index.to_series().shift(-1)-d.index.to_series())==pd.Timedelta(hours=hours)).to_numpy()
        entry=d.o.shift(-1).to_numpy();exit_=d.c.shift(-1).to_numpy()
        hi=d.h.shift(-1).to_numpy();lo=d.l.shift(-1).to_numpy()
        valid=contiguous & np.isfinite(z.d1_mom.to_numpy()) & np.isfinite(z.w1_mom.to_numpy()) & np.isfinite(entry) & np.isfinite(exit_) & (exit_!=entry)
        report['timeframes'][tf]={}
        for side,cfg in choice.items():
            s=1 if side=='BUY' else -1
            pred=predicates(z,side,tf)
            mask=unpack_rules(cfg,z,pred)&valid
            profit=s*(exit_-entry)
            favorable=(hi-entry) if s==1 else (entry-lo)
            adverse=(entry-lo) if s==1 else (hi-entry)
            right=profit>0
            result={'config_id':cfg,'side':side,'periods':{},'yearly':{},'session_utc':{},'monthly':{},'baseline_yearly':{}}
            for name,loy,hiy in [('train',2019,2022),('validation',2023,2023),('evaluation',2024,2026)]:
                ix=mask&(z.index.year>=loy)&(z.index.year<=hiy)
                result['periods'][name]=estimate(profit[ix],right[ix],favorable[ix],adverse[ix])
            for year in range(2019,2027):
                ix=mask&(z.index.year==year);baseix=valid&(z.index.year==year)
                result['yearly'][str(year)]=estimate(profit[ix],right[ix],favorable[ix],adverse[ix])
                result['baseline_yearly'][str(year)]=estimate(profit[baseix],right[baseix],favorable[baseix],adverse[baseix])
            for name,lohr,hihr in [('asia',0,8),('europe',8,16),('us',16,24)]:
                ix=mask&(z.index.hour>=lohr)&(z.index.hour<hihr)&(z.index.year>=2024)
                result['session_utc'][name]=estimate(profit[ix],right[ix],favorable[ix],adverse[ix])
            for month in range(1,13):
                ix=mask&(z.index.month==month)&(z.index.year>=2024)
                result['monthly'][str(month)]=estimate(profit[ix],right[ix],favorable[ix],adverse[ix])
            report['timeframes'][tf][side]=result
            print(json.dumps({'timeframe':tf,'side':side,'evaluation':result['periods']['evaluation'],'yearly':result['yearly']}),flush=True)
    (OUT/'r101-frozen-audit.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    print('AUDIT_COMPLETE: prior evaluation NOT a pristine holdout',flush=True)

if __name__=='__main__':run()
