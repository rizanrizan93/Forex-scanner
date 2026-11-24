"""One-variable native ablation and indexed diagnostic recheck of the new best."""
import json,gzip,hashlib
from pathlib import Path
import run_fast_batch as fast
r=fast.r;ROOT=r.ROOT
def main():
 previous=json.loads((ROOT/'runs/V7_LOCK_BTC18_ALL_B1/verified.json').read_text())
 parent=previous['Profile']
 no_adaptive={**parent,'Id':'V8_BTC18_ALL_NO_ADAPTIVE','EarlyRiskMask':0}
 r.save(ROOT/'PAIRED_ABLATION_PROTOCOL.json',{'Control':no_adaptive,'Challenger':parent,'OnlyEconomicParameterChanged':'EarlyRiskMask2 versus0','Scenario':'continuous2019-2026 B1 USD100','NoLiveChanges':True,'Status':'queued, no result inferred'})
 rows=fast.batch([parent,no_adaptive],'paired_adaptive_ablation')
 byid={x['Profile']['Id']:x for x in rows};candidate=byid[parent['Id']];control=byid[no_adaptive['Id']]
 with gzip.open(previous['File'],'rt') as f:a=json.load(f)
 with gzip.open(candidate['File'],'rt') as f:b=json.load(f)
 equality={k:a[k]==b[k] for k in ['Ledger','OrderLedger','CashLedger','EquityCurve']}
 assert all(equality.values()),equality
 s=candidate['Summary'];c=control['Summary']
 r.save(ROOT/'PAIRED_ADAPTIVE_ABLATION.json',{'Control':control,'Challenger':candidate,'IsolatedAdaptiveEffectUSD':s['EndingBalance']-c['EndingBalance'],'FloatingDDChangePoints':s['MaxEquityDDPct']-c['MaxEquityDDPct'],'IndexedBestRecheckExactStreams':equality,'Diagnostics':b.get('Diagnostics'),'Status':'completed native paired experiment; no causal attribution to other changed parameters','LiveApproved':False})
if __name__=='__main__':main()
