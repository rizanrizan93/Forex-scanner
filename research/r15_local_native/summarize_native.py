"""Summarize completed same-wallet native pilots; never invent unfinished balances."""
from pathlib import Path
import argparse,gzip,json,hashlib

def read(p):return json.loads(gzip.decompress(p.read_bytes()))
def stats(a):
 s=a['Summary'];return {k:s[k] for k in ('EndingBalance','MaxEquityDDPct','MaxClosedDDPct','Baskets','PF','MaxObservedMarginPct','MaxObservedOpenRiskPct','ErrorCount','OpenPositions','ActualCutoff','Orders')}
def key(t):return (t['Entry'],t['Symbol'])
def summarize(root):
 root=Path(root);cases=root/'native_runs/cases'
 paths={'baseline':cases/'r15_indexed_baseline_B_cost1.json.gz','guard4_24h':cases/'r15_indexed_guard4_24h_B_cost1.json.gz','addon_r3':cases/'r15_indexed_addon_r3_B_cost1.json.gz'}
 if not all(p.exists() for p in paths.values()):raise RuntimeError('Native pilots incomplete')
 data={k:read(p) for k,p in paths.items()};b=data['baseline'];core={key(t) for t in b['Ledger'] if t['Origin']!='SEED'}
 result={'stage':'R15_COMPLETED_CONTINUOUS_B1_LOCAL_NATIVE_PILOT','model':'Original synthetic M1 execution engine, exact restored inputs and reconstructed seed tapes; indexed history adapter matched controls. Not FP Markets real ticks.','baseline_matches_archived_terminal_cent':round(b['Summary']['EndingBalance'],2)==1662133293.08,'baseline_matches_archived_baskets':b['Summary']['Baskets']==1047,'cases':{},'cost_path':'B1 only; A/2x/annual tests still required','new_pristine_OOS':False,'live_changes':False,'promotion_allowed':False}
 for n,a in data.items():
  s=stats(a);other={key(t) for t in a['Ledger'] if t['Origin'] not in ('SEED','ADDON')}
  s.update(terminal_change_vs_baseline=s['EndingBalance']-b['Summary']['EndingBalance'],terminal_ratio=s['EndingBalance']/b['Summary']['EndingBalance'],floating_DD_change_pp=s['MaxEquityDDPct']-b['Summary']['MaxEquityDDPct'],original_core_keys_missing=len(core-other),new_core_keys=len(other-core),addon_filled_baskets=sum(t['Origin']=='ADDON' for t in a['Ledger']),planned_caps_observation_pass=s['MaxObservedMarginPct']<=50 and s['MaxObservedOpenRiskPct']<=20.75,guard_audit=a.get('GrowthGuardAudit'),addon_audit=a.get('AddonAudit'),seed_audit=a.get('SeedAudit'),sha256=hashlib.sha256(paths[n].read_bytes()).hexdigest(),trace=a['TraceAudit'])
  result['cases'][n]=s
 original=cases/'r15_continuous_baseline_B_cost1.json.gz'
 if original.exists():
  old=read(original);fields=('Ledger','OrderLedger','CashLedger','EquityCurve');result['indexed_vs_original_continuous_stream_equality']={f:old[f]==b[f] for f in fields}
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True);a=p.parse_args();r=summarize(a.root);Path(a.output).write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
