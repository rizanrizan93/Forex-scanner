"""Replay locked finalists; hourly estimates and calendar-month block bootstrap."""
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
spec=importlib.util.spec_from_file_location("search",Path(__file__).with_name("research_reversal_10m.py"))
search=importlib.util.module_from_spec(spec); spec.loader.exec_module(search)
from fx_scanner.reversal_zones import normalize_bars, closed_features, base_events, thin_events, matches


def year_profile(csv, year, result, output):
    m1=normalize_bars(pd.read_csv(csv)); features=closed_features(m1)
    ledger=[]
    for winner in result["selected_by_side"]:
        cfg=winner["config"]
        base=thin_events(base_events(features,cfg["side"],cfg["lookback_h1"],cfg["half_width_atr"]).query("year == @year"))
        # Verify exact research/runtime filter and labels parity, including
        # observations outside selected session for the time-of-day baseline.
        filtered=base.loc[(base.wick_bin>=search.GRID['wick_fraction'].index(cfg['wick_fraction'])) &
            (base.approach_bin>=search.GRID['approach_atr'].index(cfg['approach_atr'])) &
            (base.age_bin<=search.GRID['max_age_hours'].index(cfg['max_age_hours'])) &
            ((base.trend_bin==['ALIGNED','OPPOSED','FLAT'].index(cfg['trend'])) if cfg['trend']!='ANY' else True)]
        filtered, labels=search.labels_for(m1,filtered,cfg['side'])
        values=labels[:,search.GRID['invalidation_atr'].index(cfg['invalidation_atr']),
            search.GRID['reaction_atr'].index(cfg['reaction_atr']),search.GRID['horizon_minutes'].index(cfg['horizon_minutes'])]
        for stamp, value in zip(filtered.index, values):
            if value==-2: continue
            ledger.append({"index":winner['index'],"year":year,"at_utc":stamp.isoformat(),
                "month":stamp.strftime('%Y-%m'),"hour_utc":stamp.hour,"outcome":int(value)})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(ledger)+"\n")


def aggregate_profiles(folder,result,output):
    rows=[]
    files=sorted(folder.rglob('profile-*.json'))
    if {int(p.stem.split('-')[-1]) for p in files}!=set(range(2016,2026)):
        raise ValueError('TEN_PROFILES_REQUIRED')
    for p in files: rows.extend(json.loads(p.read_text()))
    data=pd.DataFrame(rows)
    for winner in result['selected_by_side']:
        f=data[data['index']==winner['index']]
        cfg=winner['config']; session=f[(f.hour_utc>=cfg['session_utc'])&(f.hour_utc<cfg['session_utc']+6)]
        profiles={}
        for phase, lo, hi in [('train',2016,2021),('validation',2022,2023),('holdout',2024,2025)]:
            g=session[(session.year>=lo)&(session.year<=hi)]
            actual=search.metric((g.outcome==1).sum(),len(g),(g.outcome==-1).sum())
            assert actual==winner[phase], ('REPLAY_SEARCH_PARITY_FAILURE',phase,actual,winner[phase])
            hours=[]
            for hour in range(24):
                g=f[(f.year>=lo)&(f.year<=hi)&(f.hour_utc==hour)]
                hours.append({'hour_utc':hour,'hour_wib':(hour+7)%24,
                    **search.metric((g.outcome==1).sum(),len(g),(g.outcome==-1).sum())})
            all_hours=f[(f.year>=lo)&(f.year<=hi)]
            profiles[phase]={'hours':hours,'all_hours_baseline':search.metric((all_hours.outcome==1).sum(),
                 len(all_hours),(all_hours.outcome==-1).sum())}
        # Choose explanatory best hour by TRAIN+VALIDATION only, requiring 30
        # samples in validation. Never use holdout to choose the displayed hour.
        valid_hours=[r for r in profiles['validation']['hours'] if r['n']>=30
            and cfg['session_utc']<=r['hour_utc']<cfg['session_utc']+6]
        best=max(valid_hours,key=lambda r:(r['wilson_lower_95'],-r['hour_utc'])) if valid_hours else None
        profiles['best_hour_selected_before_holdout']=best
        if best: profiles['best_hour_holdout']=profiles['holdout']['hours'][best['hour_utc']]
        g=session[session.year>=2024]
        blocks=g.groupby('month').outcome.agg(n='size',wins=lambda x:(x==1).sum()).to_numpy()
        rng=np.random.default_rng(20261013)
        samples=rng.integers(0,len(blocks),size=(10000,len(blocks)))
        sums=blocks[samples].sum(axis=1)
        rates=sums[:,1]/sums[:,0]
        profiles['holdout_month_block_bootstrap_95']=[float(x) for x in np.quantile(rates,[.025,.975])]
        profiles['year_metrics']={str(year):search.metric(((session.year==year)&(session.outcome==1)).sum(),
            (session.year==year).sum(),((session.year==year)&(session.outcome==-1)).sum()) for year in range(2016,2026)}
        winner['timing_profile']=profiles
    result['status']='VALIDATED' if result['selected']['qualified'] else 'RESEARCH_ONLY'
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--csv',type=Path);p.add_argument('--year',type=int)
    p.add_argument('--shards',type=Path);p.add_argument('--result',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=json.loads(args.result.read_text())
    if args.shards: aggregate_profiles(args.shards,result,args.output)
    else: year_profile(args.csv,args.year,result,args.output)
