"""Fail-closed parity gate for unapproved Bootstrap125 seed proxy research."""
import json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
d=json.loads((R/'research/bootstrap125_seed_r2_proxy_rejected_parity.json').read_text())
assert d['status']=='REJECTED_BASELINE_NATIVE_PARITY_FAILED'
assert d['research_only'] and not d['execution_authority']
assert d['source_is_older_and_incompatible']
assert d['eur_m1_sha256']!=d['actual_frozen_v1_required_eur_sha256']
assert len(d['annual_checks'])==8
errors=[r for r in d['annual_checks'] if r['proxy_days_to_125'] is None
  or abs(r['proxy_days_to_125']-r['frozen_days_to_125'])>1.0]
assert len(errors)>=4,errors
assert d['prototype_candidate_count']==10
assert d['prototype_cost_scenarios']==2
assert d['prototype_annual_reset_trials']==160
assert all(v['base_cost']<8 and v['stress_cost']<8 for v in d['proxy_only_graduations_out_of_8'].values())
print(json.dumps({'gate':'REJECT_PROXY_FOR_V1_PROMOTION','failed_native_parity_years':[v['year'] for v in errors],
 'source_verified_but_not_native':True,'new_native_seed_candidate_validated':False,'live_permission':False}))
