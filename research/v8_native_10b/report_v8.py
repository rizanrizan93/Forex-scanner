"""Build a status report from completed native receipts, never from estimates."""
import csv,gzip,hashlib,json,math
import run_v8
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
 receipts={};seenprofiles={}
 auditdir=ROOT/'receipt_audits';auditdir.mkdir(exist_ok=True)
 for p in list((ROOT/'runs').rglob('verified.json'))+list((ROOT/'diagnostic_runs').rglob('verified.json')):
  row=json.loads(p.read_text());receipts[row['File']]=row
 for folder in ['runs','diagnostic_runs']:
  for p in (ROOT/folder).rglob('*.metrics.json'):
   try:metrics=json.loads(p.read_text())
   except json.JSONDecodeError:continue
   for row in metrics:
    if row['File'] in receipts:continue
    key=hashlib.sha256(row['File'].encode()).hexdigest();cache=auditdir/(key+'.json')
    if cache.exists():row=json.loads(cache.read_text())
    else:
     row=run_v8.verify(row);cache.write_text(json.dumps(row,indent=2))
    receipts[row['File']]=row
 for row in receipts.values():
  key=(row['Profile']['Id'],row['Path'],row['Cost'])
  if key not in seenprofiles or ('diagnostic_runs' in row['File'] and 'diagnostic_runs' not in seenprofiles[key]['File']):seenprofiles[key]=row
 allrows=list(seenprofiles.values())
 rows=[r for r in allrows if r['Profile']['Year']==2019 and r['Profile'].get('EndYear')==2026]
 annualrows=[r for r in allrows if r['Profile']['Year']==r['Profile'].get('EndYear')]
 fullreceipts=[r for r in receipts.values() if r['Profile']['Year']==2019 and r['Profile'].get('EndYear')==2026]
 baseline=next((r for r in rows if r['Profile']['Id']=='V7_CONTROL' and r['Path']=='B' and r['Cost']==1),None)
 # Prefer the simpler identifier when two native receipts are financially exact.
 # This keeps a proven no-op policy from being promoted as part of the lock.
 ranked=sorted([r for r in rows if r['Path']=='B' and r['Cost']==1 and 'CONTROL' not in r['Profile']['Id']],key=lambda r:(r['Summary']['EndingBalance'],-len(r['Profile']['Id'])),reverse=True)
 eligible=[r for r in ranked if r['Summary']['MaxEquityDDPct']<60 and baseline is not None and r['Summary']['EndingBalance']>baseline['Summary']['EndingBalance']]
 selected=([baseline] if baseline else [])+ranked
 details={}
 detaildir=ROOT/'detail_cache';detaildir.mkdir(exist_ok=True)
 for row in ([baseline] if baseline else [])+ranked:
  detailfile=detaildir/(row['ReceiptSHA256']+'.json')
  if detailfile.exists():
   details[row['Profile']['Id']]=json.loads(detailfile.read_text());continue
  with gzip.open(row['File'],'rt') as f:raw=json.load(f)
  by=defaultdict(lambda:{'Baskets':0,'Wins':0,'NetPnlUSD':0})
  streak=worst=0
  for t in sorted(raw['Ledger'],key=lambda t:t['Exit']):
   z=by[t['Symbol']];z['Baskets']+=1;z['Wins']+=t['Pnl']>0;z['NetPnlUSD']+=t['Pnl']
   streak=streak+1 if t['Pnl']<0 else 0;worst=max(worst,streak)
  details[row['Profile']['Id']]={'BySymbol':dict(by),'WorstLosingBasketStreak':worst,'SeedAudit':raw['SeedAudit'],'Diagnostics':raw.get('Diagnostics'),'LedgerCashResidualUSD':100+math.fsum(t['Pnl'] for t in raw['Ledger'])-row['Summary']['EndingBalance'],'ReceiptSHA256':row['ReceiptSHA256']}
  if row['Profile']['Id']=='V7_CONTROL' and details[row['Profile']['Id']]['Diagnostics'] is None and (ROOT/'FULL_STREAM_EQUALITY.json').exists():details[row['Profile']['Id']]['Diagnostics']=json.loads((ROOT/'FULL_STREAM_EQUALITY.json').read_text())['Diagnostics']
  detailfile.write_text(json.dumps(details[row['Profile']['Id']],indent=2))
 stamp=datetime.now(timezone(timedelta(hours=7))).isoformat()
 previous={'Id':'R1_FOCUS_EURBTC_TO1000_BTC_BUY18_H72','EndingBalance':1838731373.8353884,'MaxEquityDDPct':58.90845697509444,'PF':2.2022752933425127,'Baskets':1040,'Orders':212102,'Status':'previous B1 native benchmark; robustness incomplete'}
 configs={json.dumps({k:v for k,v in row['Profile'].items() if k!='Id'},sort_keys=True) for row in rows}
 data={'AsOfWIB':stamp,'TargetUSD':1e10,'FloatingDDLimitExclusivePct':60,'CompletedFullNativeReplays':len(fullreceipts),'UniqueProfilePathCostCases':len(rows),'UniqueCompletedParameterConfigurationsExcludingId':len(configs),'UniqueB1Challengers':len(ranked),'NewModuleScreenConfigurations':0,'NewAnnualResetSimulations':len(annualrows),'Rows':rows,'AnnualRows':annualrows,'Details':details,'BestB1Below60':eligible[0]['Profile']['Id'] if eligible else None,'PreviousNativeBestB1Below60':previous,'TargetReachedB1':bool(eligible and eligible[0]['Summary']['EndingBalance']>=1e10),'ProductionChanges':False}
 (ROOT/'RESULTS_V8.json').write_text(json.dumps(data,indent=2))
 if eligible:
  best=eligible[0];s=best['Summary']
  lock={
   'Id':f'V8_B1_{round(s["EndingBalance"])}_RESEARCH_LOCK_20261124',
   'Status':'PROVISIONAL_B1_BENCHMARK_ONLY','NativeReplayed':True,
   'FullRobustnessValidated':False,'LiveApproved':False,'GoalUSD':1e10,
   'GoalReached':s['EndingBalance']>=1e10,'InitialBalanceUSD':100,
   'EndingBalanceUSD':s['EndingBalance'],'MaxFloatingDDPct':s['MaxEquityDDPct'],
   'MaxClosedDDPct':s['MaxClosedDDPct'],'PF':s['PF'],'Baskets':s['Baskets'],
   'OrderRequests':s['Orders'],'Parameters':best['Profile'],
   'NativeSourceCommit':'26bf8396b6e703d650e703fca48d556252782f03',
   'BuildSHA256':'30e50338cb624a823a1fc35b37648d3b9a73f700e9fbd63288770ad021e3dd63',
   'DatasetHashes':{'xau_2012_2026.csv':'defcbd64ab625156f7594f8a357591bc3d2fea2a0e8deb4c9144ae88e4e8fea7','eur_2012_2026.csv':'710f10ed97e709f48e284e79511981e4e85638deca6958a668908d6f418285c5','BTCUSD_M1.csv':'9257332636450a0c93d20c45757016ae359feb208d7b91ac82fac173a64f8c51'},
   'ReceiptFile':best['File'],'ReceiptSHA256':best['ReceiptSHA256'],
   'ComparedToPreviousB1BestUSD':previous['EndingBalance'],
   'GainVsPreviousBestUSD':s['EndingBalance']-previous['EndingBalance'],
   'DDChangeVsPreviousBestPoints':s['MaxEquityDDPct']-previous['MaxEquityDDPct'],
   'BaselineBalanceUSD':baseline['Summary']['EndingBalance'] if baseline else None,
   'GainVsBaselinePct':(s['EndingBalance']/baseline['Summary']['EndingBalance']-1)*100 if baseline else None,
   'AccountingErrors':s['ErrorCount'],'AdditionalCapitalUSD':s['TotalContributions']-100,
   'RemainingValidation':['A1/A2/B2 with matched controls','explicit spread/slippage/delay','Monte Carlo','walk-forward and start-date','2012-2018 causal strategy gates','broker capacity and impact'],
   'PreviousBenchmarkPreserved':True}
  (ROOT/'BEST_B1_RESEARCH_LOCK.json').write_text(json.dumps(lock,indent=2))
 pipeline={'AsOfWIB':stamp,'CompletedFullNativeReplays':len(fullreceipts),
  'CompletedPriorityChallengers':len(ranked),'PriorityChallengersTotal':45,
  'UniqueCompletedParameterConfigurationsExcludingId':len(configs),
  'CompletedAnnualNativeCases':len(annualrows),'CompletedNewModuleScreens':0,
  'BestB1':eligible[0]['Profile']['Id'] if eligible else None,
  'Robustness':'not complete; only actual verified receipts count',
  'PairedAblation':'not complete; only actual verified receipts count',
  'FullTargetReached':bool(eligible and eligible[0]['Summary']['EndingBalance']>=1e10),
  'ArtifactPersistence':'Library quota full; Drive auto-review rejected external private upload; complete ZIPs remain workspace-only','NoLiveChanges':True}
 (ROOT/'PIPELINE_STATUS.json').write_text(json.dumps(pipeline,indent=2))
 columns=['Candidate','Path','Cost','InitialUSD','EndingUSD','FloatingDDPct','ClosedDDPct','PF','Baskets','OrderRequests','MinEquity','MaxMarginPct','MaxOpenRiskPct','Status']
 table=[]
 for r in rows:
  s=r['Summary'];accept=r in eligible
  status='B1_IMPROVEMENT_ROBUSTNESS_PENDING' if accept else ('CONTROL' if 'CONTROL' in r['Profile']['Id'] else ('REJECT_DD' if s['MaxEquityDDPct']>=60 else 'NO_B1_IMPROVEMENT_OR_STRESS_REVIEW'))
  table.append([r['Profile']['Id'],r['Path'],r['Cost'],100,s['EndingBalance'],s['MaxEquityDDPct'],s['MaxClosedDDPct'],s['PF'],s['Baskets'],s['Orders'],s['MinimumEquity'],s['MaxObservedMarginPct'],s['MaxObservedOpenRiskPct'],status])
 with (ROOT/'NATIVE_RESULTS_V8.csv').open('w') as f:
  w=csv.writer(f);w.writerow(columns);w.writerows(table)
 lines=['# RIZAN V8 — actual native replay evidence',f'As of {stamp}. Research in progress; target USD10 billion remains unchanged.','',f'Completed full continuous native replays: {len(fullreceipts)}. Unique B1 challengers: {len(ranked)}. New module screens: 0. New annual-reset simulations: {len(annualrows)}.','', '| Candidate | Initial USD | Ending USD | Floating DD | PF | Baskets | Requests | Status |','|---|---:|---:|---:|---:|---:|---:|---|']
 for r in selected:
  s=r['Summary'];status='B1 improvement; robustness pending' if r in eligible else ('REJECT: floating DD >=60%' if s['MaxEquityDDPct']>=60 else 'REJECT: no balance improvement')
  if 'CONTROL' in r['Profile']['Id']:status='CONTROL'
  lines.append(f'| {r["Profile"]["Id"]} | 100 | {s["EndingBalance"]:,.2f} | {s["MaxEquityDDPct"]:.6f}% | {s["PF"]:.4f} | {s["Baskets"]} | {s["Orders"]} | {status} |')
 if ranked:
  best=ranked[0];s=best['Summary'];lines+=['',f'Highest completed B1 ending balance: USD{s["EndingBalance"]:,.2f}, floating DD {s["MaxEquityDDPct"]:.6f}%.']
  if baseline:lines.append(f'Change against same-path/same-cost baseline: {(s["EndingBalance"]/baseline["Summary"]["EndingBalance"]-1)*100:.6f}%.')
  if eligible:lines.append(f'Best ending balance below 60% floating DD: {eligible[0]["Profile"]["Id"]}, USD{eligible[0]["Summary"]["EndingBalance"]:,.2f}.')
  lines.append(f'Target reached in B1: {data["TargetReachedB1"]}. Four-scenario validation is separate and is not inferred from B1.')
 lines+=['',f'Previous B1 native benchmark below60% is retained: USD{previous["EndingBalance"]:,.2f}, floating DD{previous["MaxEquityDDPct"]:.6f}%. It is not counted as a newly completed V8 replay. The prior highest balance USD1,867,121,354.86 failed DD60.386930%.','', '| Candidate | Closed DD | Minimum equity USD | Max margin | Max open risk | Worst losing basket streak |','|---|---:|---:|---:|---:|---:|']
 for row in selected:
  s=row['Summary'];d=details.get(row['Profile']['Id'],{})
  lines.append(f'| {row["Profile"]["Id"]} | {s["MaxClosedDDPct"]:.6f}% | {s["MinimumEquity"]:.2f} | {s["MaxObservedMarginPct"]:.6f}% | {s["MaxObservedOpenRiskPct"]:.6f}% | {d.get("WorstLosingBasketStreak","unknown")} |')
 lines+=['','| Candidate | XAU net PnL USD | EUR net PnL USD | BTC net PnL USD |','|---|---:|---:|---:|']
 for name,d in details.items():
  by=d['BySymbol'];lines.append(f'| {name} | {by["XAUUSD"]["NetPnlUSD"]:,.2f} | {by["EURUSD"]["NetPnlUSD"]:,.2f} | {by["BTCUSD"]["NetPnlUSD"]:,.2f} |')
 lines+=['','Contributions describe the executed shared wallet, not additive standalone alpha.','', '| Candidate | Peak equity USD | Max-DD recovery days | Longest underwater days | Max simultaneous positions | Minimum margin level |','|---|---:|---:|---:|---:|---:|']
 for name,d in details.items():
  obs=d.get('Diagnostics')
  if obs:lines.append(f'| {name} | {obs["PeakEquity"]:,.2f} | {obs["MaxDDRecoveryDays"]:.6f} | {obs["LongestObservedUnderwaterDays"]:.6f} | {obs["MaximumSimultaneousPositions"]} | {obs["MinimumMarginLevelPct"]:.6f}% |')
 lines+=['','Milestones require both balance and floating equity to reach the level. Times below are WIB.','', '| Candidate | Milestone USD | First reached WIB | Floating DD before milestone |','|---|---:|---|---:|']
 for name,d in details.items():
  for level,mark in (d.get('Diagnostics') or {}).get('Milestones',{}).items():
   at=datetime.fromisoformat(mark['At'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=7)))
   lines.append(f'| {name} | {float(level):,.0f} | {at.isoformat()} | {mark["MaxFloatingDDPct"]:.6f}% |')
 if (ROOT/'P0_NATIVE_COMPARISON.json').exists():
  p0=json.loads((ROOT/'P0_NATIVE_COMPARISON.json').read_text())
  lines+=['',f'P0 actual comparison: USD{p0["ChangeUSD"]:,.2f} /{p0["ChangePct"]:.6f}% against control; all1047 core entry keys retained, {p0["CommonKeysWithChangedChildren"]} common baskets have changed integer units and {p0["CommonKeysWithChangedPnl"]} changed PnL. Native-minus-fixed-ledger reference: USD{p0["NativeMinusFixedLedgerUSD"]:,.2f}. The cash gate rejects this upgrade. No V5 estimate is promoted as native.']
 if (ROOT/'NATIVE_ATTEMPT_FAILURES.json').exists():
  failures=json.loads((ROOT/'NATIVE_ATTEMPT_FAILURES.json').read_text());data['InterruptedNativeAttempts']=failures
  (ROOT/'RESULTS_V8.json').write_text(json.dumps(data,indent=2))
  lines+=['',f'Interrupted startup attempts: {len(failures)}; these are not completed financial replays. One direct process received SIGKILL (OS cause unconfirmed); three indexed batch starts ran out of managed memory before market replay. A resource-only gateway now preserves the exact parity-verified DLL bytes, serializes input loading and limits gated native children to2 with3GiB heaps and a4GiB pre-load available-memory reserve. Retry status must be read from logs, not inferred from queue configuration.']
 if (ROOT/'BEST_B1_RESEARCH_LOCK.json').exists():
  lock=json.loads((ROOT/'BEST_B1_RESEARCH_LOCK.json').read_text())
  lines+=['',f'Provisional B1 research lock: {lock["Id"]}; cash USD{lock["EndingBalanceUSD"]:,.2f}, floating DD{lock["MaxFloatingDDPct"]:.6f}%. Prior-best gain USD{lock["GainVsPreviousBestUSD"]:,.2f}, DD change {lock["DDChangeVsPreviousBestPoints"]:.6f}points. A1/A2/B2 validation and one-parameter EarlyRiskMask paired ablation are incomplete; only completed receipts are financial results. No LIVE approval.']
 lines+=['','Complete private input/runtime and full native receipts are available as workspace ZIPs. Durable Library save failed because account storage quota is full. Google Drive upload was rejected by automatic approval review because that external destination has not been authorized for private archives. No private CSV or archive was uploaded to GitHub.']
 lines+=['','Baseline parity, exact dataset hashes and original commit verification are retained. Receipts include full order/basket ledgers, equity curve and accounting. Total contributions include the original USD100; additional deposits are zero. Each accepted receipt has no open positions, BTC fault/pending state, quarantines or accounting errors. Cash residual tolerance is USD0.05.','', 'Floating DD is the full synthetic native equity peak-to-trough metric, not closed-balance DD or scaled ledger sensitivity. Milestone and recovery data are available in instrumented receipts; absent diagnostic fields are unknown, not zero. Minimum equity and observed risk/margin are included in CSV/JSON.','', 'The inherited model uses original C# strategy sources with synthetic M1 price paths and API stubs. It is not execution of the original .algo on broker ticks. Synthetic admission macro snapshots and heartbeats are not certified historical vintages. Cost factor 2 changes modeled fees, slippage and funding; spread multiplier stays 1. Broker stop-out and nonlinear market impact are not implemented. Results do not certify broker capacity or LIVE profitability.','', '2012–2018 trading remains unvalidated because inherited entry/seed gates exclude earlier activity. Full A1/B1/A2/B2, explicit spread/slippage/delay stress, walk-forward, Monte Carlo, start-date and capacity validation remain pending until actual receipts exist. No production, main, VPS or cTrader instance changes.','', 'Code and evidence branch: research/v8-native-10b-accelerated-growth. This execution uses Work, not GitHub Actions; no new Actions run is claimed.']
 (ROOT/'REPORT_V8.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps({'completed':len(fullreceipts),'annual_native_cases':len(annualrows),'unique_B1_challengers':len(ranked),'best':eligible[0]['Profile']['Id'] if eligible else None,'target':data['TargetReachedB1']}))
if __name__=='__main__':main()
