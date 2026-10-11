#!/usr/bin/env python3
"""Immutable contract/source pins and field mapping only; never broker calls."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FIELDS=['Symbol','Hash','Stages','Depths','Confirmed','AddMinutes','InitialFraction','WeightPower','RiskFraction','MarginFraction','TargetR','HoldMinutes','Slip','ChildUnits','CommissionPerSide','ReferenceLeverage']
def hash_bytes(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def parse_contract(text,name):
 raw=re.search(r'public static FrozenContract '+name+r' => new\((.*?)\);',text,re.S).group(1)
 array=re.search(r'new\[\] \{([^}]*)\}',raw);depths=[float(x.strip().rstrip('d')) for x in array.group(1).split(',')]
 raw=raw[:array.start()]+'DEPTHS'+raw[array.end():]
 values=[]
 for part in raw.split(','):
  p=part.strip()
  if p=='DEPTHS':value=depths
  elif p.startswith('"'):value=json.loads(p)
  elif p in ('true','false'):value=p=='true'
  else:value=float(p.rstrip('d'))
  values.append(value)
 assert len(values)==len(FIELDS)
 return dict(zip(FIELDS,values))
def main():
 pins=json.loads((ROOT/'config/cbots/frozen_parity_v1.json').read_text());result={}
 for symbol,name,folder,key in [('XAUUSD','Xau','migration-20261010/v1.0.1','xauusd'),('EURUSD','Eur','eur-releases/v1.1.0','eurusd')]:
  archive=ROOT/'cbot_sources/archive'/folder
  frozen=json.loads((ROOT/('config/frozen/xauusd_raw_selected_v1.json' if name=='Xau' else 'config/frozen/eurusd_raw_selected_v3.json')).read_text());c=frozen['contract']
  digest=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  assert digest==frozen['contract_sha256']==pins[key]['contract_sha256']
  for path,expected in pins[key]['current_cbot']['source_hashes'].items():assert hash_bytes(archive/path)==expected,path
  compiled='compiled/RizanXAU.algo' if name=='Xau' else 'compiled/RizanEURBatch_v1.1.0.algo'
  assert hash_bytes(archive/compiled)==pins[key]['current_cbot']['sha256']
  layer=c['layering'];p=dict(zip(c['policy_vector_columns'],c['policy_vector'])) if name=='Xau' else c['policy']
  expected={'Symbol':symbol,'Hash':digest,'Stages':layer['stages'],'Depths':layer['depths_r'],'Confirmed':layer['confirmed'],'AddMinutes':layer['expiry_minutes'] if name=='Xau' else layer['add_expiry_minutes'],'InitialFraction':p['initial_fraction'],'WeightPower':p['depth_weight_power'],'RiskFraction':p['risk_ceiling'],'MarginFraction':p['margin_ceiling'],'TargetR':c['target_r'] if name=='Xau' else c['full_reference_policy']['target_r'],'HoldMinutes':c['hold_minutes'] if name=='Xau' else c['full_reference_policy']['hold_minutes'],'Slip':c['execution_cost_model']['xau_slippage_per_side'] if name=='Xau' else c['full_reference_policy']['virtual_slip'],'ChildUnits':layer['child_units_oz'] if name=='Xau' else c['sizing']['child_units'],'CommissionPerSide':(c['execution_cost_model']['commission_per_001lot_per_side_usd'] if name=='Xau' else c['execution_cost_model']['commission_usd_per_001lot_per_side']),'ReferenceLeverage':c['leverage_policy']['reference'] if name=='Xau' else c['reference_leverage']}
  actual=parse_contract((archive/'Common/FrozenCore.cs').read_text(),name)
  assert actual==expected,[f for f in FIELDS if actual.get(f)!=expected.get(f)]
  result[symbol]={'frozen_hash':'PASS','archived_source_pins':'PASS','archived_algo_pin':'PASS','contract_fields':len(FIELDS),'field_mapping':'PASS','full_behavioral_parity':'NOT_CLAIMED_BY_STATIC_TEST'}
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
