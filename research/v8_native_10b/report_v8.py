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
  key=(row['Profile']['Id'],row['Path'],row['Cost']);seenprofiles[key]=row
 rows=list(seenprofiles.values());baseline=next((r for r in rows if r['Profile']['Id']=='V7_CONTROL' and r['Path']=='B' and r['Cost']==1),None)
 ranked=sorted([r for r in rows if r['Path']=='B' and r['Cost']==1 and 'CONTROL' not in r['Profile']['Id']],key=lambda r:r['Summary']['EndingBalance'],reverse=True)
 eligible=[r for r in ranked if r['Summary']['MaxEquityDDPct']<60]
 selected=([baseline] if baseline else [])+ranked
 details={}
 for row in ([baseline] if baseline else [])+ranked[:3]:
  with gzip.open(row['File'],'rt') as f:raw=json.load(f)
  by=defaultdict(lambda:{'Baskets':0,'Wins':0,'NetPnlUSD':0})
  streak=worst=0
  for t in sorted(raw['Ledger'],key=lambda t:t['Exit']):
   z=by[t['Symbol']];z['Baskets']+=1;z['Wins']+=t['Pnl']>0;z['NetPnlUSD']+=t['Pnl']
   streak=streak+1 if t['Pnl']<0 else 0;worst=max(worst,streak)
  details[row['Profile']['Id']]={'BySymbol':dict(by),'WorstLosingBasketStreak':worst,'SeedAudit':raw['SeedAudit'],'Diagnostics':raw.get('Diagnostics'),'LedgerCashResidualUSD':100+math.fsum(t['Pnl'] for t in raw['Ledger'])-row['Summary']['EndingBalance'],'ReceiptSHA256':row['ReceiptSHA256']}
 stamp=datetime.now(timezone(timedelta(hours=7))).isoformat()
 data={'AsOfWIB':stamp,'TargetUSD':1e10,'FloatingDDLimitExclusivePct':60,'CompletedFullNativeReplays':len(receipts),'UniqueProfilePathCostCases':len(rows),'UniqueB1Challengers':len(ranked),'NewModuleScreenConfigurations':0,'NewAnnualResetSimulations':0,'Rows':rows,'Details':details,'BestB1Below60':eligible[0]['Profile']['Id'] if eligible else None,'TargetReachedB1':bool(eligible and eligible[0]['Summary']['EndingBalance']>=1e10),'ProductionChanges':False}
 (ROOT/'RESULTS_V8.json').write_text(json.dumps(data,indent=2))
 columns=['Candidate','Path','Cost','InitialUSD','EndingUSD','FloatingDDPct','ClosedDDPct','PF','Baskets','OrderRequests','MinEquity','MaxMarginPct','MaxOpenRiskPct','Status']
 table=[]
 for r in rows:
  s=r['Summary'];table.append([r['Profile']['Id'],r['Path'],r['Cost'],100,s['EndingBalance'],s['MaxEquityDDPct'],s['MaxClosedDDPct'],s['PF'],s['Baskets'],s['Orders'],s['MinimumEquity'],s['MaxObservedMarginPct'],s['MaxObservedOpenRiskPct'],'B1_ACCEPTABLE_RESEARCH_ONLY' if r['Path']=='B' and r['Cost']==1 and s['MaxEquityDDPct']<60 else 'DD_OR_STRESS_REVIEW'])
 with (ROOT/'NATIVE_RESULTS_V8.csv').open('w') as f:
  w=csv.writer(f);w.writerow(columns);w.writerows(table)
 lines=['# RIZAN V8 — actual native replay evidence',f'As of {stamp}. Research in progress; target USD10 billion remains unchanged.','',f'Completed full continuous native replays: {len(receipts)}. Unique B1 challengers: {len(ranked)}. New module screens: 0. New annual-reset simulations: 0.','', '| Candidate | Initial USD | Ending USD | Floating DD | PF | Baskets | Requests | Status |','|---|---:|---:|---:|---:|---:|---:|---|']
 for r in selected:
  s=r['Summary'];status='B1 DD PASS; robustness pending' if s['MaxEquityDDPct']<60 else 'REJECT: floating DD >=60%'
  if 'CONTROL' in r['Profile']['Id']:status='CONTROL'
  lines.append(f'| {r["Profile"]["Id"]} | 100 | {s["EndingBalance"]:,.2f} | {s["MaxEquityDDPct"]:.6f}% | {s["PF"]:.4f} | {s["Baskets"]} | {s["Orders"]} | {status} |')
 if ranked:
  best=ranked[0];s=best['Summary'];lines+=['',f'Highest completed B1 ending balance: USD{s["EndingBalance"]:,.2f}, floating DD {s["MaxEquityDDPct"]:.6f}%.']
  if baseline:lines.append(f'Change against same-path/same-cost baseline: {(s["EndingBalance"]/baseline["Summary"]["EndingBalance"]-1)*100:.6f}%.')
  if eligible:lines.append(f'Best ending balance below 60% floating DD: {eligible[0]["Profile"]["Id"]}, USD{eligible[0]["Summary"]["EndingBalance"]:,.2f}.')
  lines.append(f'Target reached in B1: {data["TargetReachedB1"]}. Four-scenario validation is separate and is not inferred from B1.')
 lines+=['','Baseline parity, exact dataset hashes and original commit verification are retained. Receipts include full order/basket ledgers, equity curve and accounting. Total contributions include the original USD100; additional deposits are zero. Each accepted receipt has no open positions, BTC fault/pending state, quarantines or accounting errors. Cash residual tolerance is USD0.05.','', 'Floating DD is the full synthetic native equity peak-to-trough metric, not closed-balance DD or scaled ledger sensitivity. Milestone and recovery data are available in instrumented receipts; absent diagnostic fields are unknown, not zero. Minimum equity and observed risk/margin are included in CSV/JSON.','', 'The inherited model uses original C# strategy sources with synthetic M1 price paths and API stubs. It is not execution of the original .algo on broker ticks. Synthetic admission macro snapshots and heartbeats are not certified historical vintages. Cost factor 2 changes modeled fees, slippage and funding; spread multiplier stays 1. Broker stop-out and nonlinear market impact are not implemented. Results do not certify broker capacity or LIVE profitability.','', '2012–2018 trading remains unvalidated because inherited entry/seed gates exclude earlier activity. Full A1/B1/A2/B2, explicit spread/slippage/delay stress, walk-forward, Monte Carlo, start-date and capacity validation remain pending until actual receipts exist. No production, main, VPS or cTrader instance changes.','', 'Code and evidence branch: research/v8-native-10b-accelerated-growth. This execution uses Work, not GitHub Actions; no new Actions run is claimed.']
 (ROOT/'REPORT_V8.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps({'completed':len(receipts),'unique_B1_challengers':len(ranked),'best':eligible[0]['Profile']['Id'] if eligible else None,'target':data['TargetReachedB1']}))
if __name__=='__main__':main()
