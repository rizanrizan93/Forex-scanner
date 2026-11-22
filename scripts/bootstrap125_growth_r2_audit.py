"""RIZAN Bootstrap125 Snowball R2: read-only audit of existing matched replay.
This DOES NOT run a new native portfolio backtest or modify V1/cBots.
Do not promote any candidate from replay development-year selection.
"""
import json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'research/bootstrap125_growth_r2_existing_replay_evidence.json'

def audit(e):
    annual=sorted(e['annual'],key=lambda r:r['year'])
    assert [r['year'] for r in annual]==list(range(2019,2027))
    assert e['research_only'] and not e['execution_authority']
    assert e['archive_sha256']=='1e7de884d7fcf839a3f4ab45f1affba64831bf8cb0e0ef6440dda69c6c684c00'
    families=e['growth_challenger_policies']
    assert len(families)==9
    for a in annual:
        assert a['v1']>0 and a['addon']>0
        assert a['v1_baskets']>0 and a['addon_baskets']>0
        assert 0<=a['v1_dd']<100 and 0<=a['addon_dd']<100
    # Fail closed: cannot infer earlier handoff from post-handoff growth addon.
    handoff_faster_on_verified_records=False
    enhanced=[a for a in annual if a['addon']>a['v1']+1e-9]
    worse=[a for a in annual if a['addon']<a['v1']-1e-9]
    lost_with_more_baskets=[a for a in annual if a['addon_baskets']>a['v1_baskets'] and a['addon']<a['v1']]
    finalists=[p for p in families if p['min_ratio']>=1 and p['max_dd']<60]
    assert len(enhanced)==5 and len(worse)==3
    assert [a['year'] for a in lost_with_more_baskets]==[2020,2023,2024]
    assert not finalists
    assert max(annual,key=lambda a:a['days_to_125'])['year']==2024
    total= sum(a['addon_baskets']-a['v1_baskets'] for a in annual)
    assert total==sum(a['addon_baskets'] for a in annual)-sum(a['v1_baskets'] for a in annual)
    # This ratio is scale arithmetic, NOT achieved or extrapolated portfolio balance.
    factor=e['goal_scenario_only_usd']/e['frozen_v1_continuous_model_usd']
    return {
      'study':'RIZAN bootstrap125 matched archive audit R2',
      'status':'NO_QUALIFIED_FULL_YEAR_CHALLENGER',
      'new_native_backtests_this_run':0,
      'existing_annual_reset_cases_evaluated':len(annual),
      'existing_growth_variants_checked':len(families),
      'years_balance_improved':len(enhanced),
      'years_balance_degraded':len(worse),
      'years_balance_degraded_despite_extra_baskets':[a['year'] for a in lost_with_more_baskets],
      'additional_baskets_all_eight_reset_runs':total,
      'fastest_graduation_year':min(annual,key=lambda a:a['days_to_125'])['year'],
      'slowest_graduation_year':2024,
      'slowest_graduation_days':next(a['days_to_125'] for a in annual if a['year']==2024),
      'post_handoff_addon_improves_seed':handoff_faster_on_verified_records,
      'goal_10b_to_frozen_1_662b_ratio':factor,
      'ten_billion_backtest_verified':False,
      'live_or_broker_authority':False,
      'required_next_replay':'Matched original native core + changed EUR seed, 8 resets and continuous 2019–2026, 2 intrabar paths, base and 2x costs, monthly and 100→125 handoff metrics. Reject if 2024 stress seed fails.',
      'caveat':'Input is existing replay summary derived from immutable library archive SHA256; no new broker or candidate replay executed.'
    }

if __name__=='__main__':
    evidence=json.loads(SRC.read_text())
    report=audit(evidence)
    dest=ROOT/'artifacts/bootstrap125_growth_r2_audit.json'
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(report,indent=2,allow_nan=False))
