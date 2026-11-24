from pathlib import Path
from datetime import datetime,timezone
import json,csv,hashlib,gzip

root=Path(__file__).resolve().parent
continuous=[];annual=[]
for p in sorted((root/'results').glob('*/summary.json.metrics.json')):
 for x in json.loads(p.read_text()):
  s=x['Summary'];pr=x['Profile']
  r=dict(series=p.parent.name,id=pr['Id'],start_year=pr['Year'],end_year=pr.get('EndYear') or pr['Year'],path=x['Path'],cost=x.get('Cost',1),ending_balance=s['EndingBalance'],max_floating_dd_pct=s['MaxEquityDDPct'],max_closed_dd_pct=s['MaxClosedDDPct'],pf=s['PF'],baskets=s['Baskets'],orders=s['Orders'],errors=s['ErrorCount'],first_balance_equity_1000=s.get('FirstBalanceEquity1000'),open_positions=s['OpenPositions'],cutoff=s['ActualCutoff'],profile=pr)
  (continuous if r['end_year']>r['start_year'] else annual).append(r)
completion={n:(root/f'results/{n}/summary.json').exists() for n in ['capacity','filterF1_A','filterF1_cost2']}
module={}
for name,goal in [('screen1000',1000),('screen125',125)]:
 p=root/f'results/{name}.csv'
 count=sum(1 for _ in p.open())-1
 module[name]=dict(goal=goal,annual_screens=count,configurations=count//16,costs=2,years=8,portfolio_replay=False)
baseA=1392645692.9378428;baseADD=57.89042022425832
baseB=1662133293.0811067;baseDD=56.67209330213908
caseB=[r for r in continuous if r['path']=='B' and r['cost']==1]
best=max(caseB,key=lambda r:r['ending_balance'])
result=dict(status='COMPLETE_R1' if all(completion.values()) else 'VALIDATION_PENDING',goal_usd=10000000000,starting_cash=100,observed_utc=datetime.now(timezone.utc).isoformat(),baseline_A=dict(ending_balance=baseA,max_floating_dd_pct=baseADD),baseline_B=dict(ending_balance=baseB,max_floating_dd_pct=baseDD),module_screens=module,annual_cases=len(annual),continuous_cases=len(continuous),completion=completion,best_cost1_B=best,best_improvement_pct=100*(best['ending_balance']/baseB-1),goal_reached_in_completed_runs=any(r['ending_balance']>=1e10 for r in continuous),continuous=continuous,production_changes=False,real_ticks=False)
(root/'RESULTS_R1.json').write_text(json.dumps(result,indent=2))
(root/'BEST_MODEL_PROFILE.json').write_text(json.dumps(best['profile'],indent=2))
fields=[k for k in best if k!='profile']
for name,rows in [('CONTINUOUS_R1.csv',continuous),('ANNUAL_R1.csv',annual)]:
 with (root/name).open('w') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
lines=['# RIZAN 10B — research R1 results','',f"Status: {result['status']}. Goal USD 10 billion reached: {result['goal_reached_in_completed_runs']}.",'','Initial cash USD100, no additional deposits. Continuous shared wallet, model leverage 1:200. Historical cutoff 13 November 2026 03:00 UTC / 10:00 WIB.','', '| Variant | M1 path | Cost factor | Ending balance USD | Max floating equity DD | Baskets | Errors |','|---|---|---:|---:|---:|---:|---:|',f'| Frozen V1 baseline | A | 1 | {baseA:,.2f} | {baseADD:.4f}% | 1,040 | 0 |',f'| Frozen V1 baseline | B | 1 | {baseB:,.2f} | {baseDD:.4f}% | 1,047 | 0 |']
for r in continuous:
 lines.append(f"| {r['id']} | {r['path']} | {r['cost']} | {r['ending_balance']:,.2f} | {r['max_floating_dd_pct']:.4f}% | {r['baskets']:,} | {r['errors']} |")
lines+=['','## Scope and interpretation','',f"Highest completed cost-1 path-B candidate: USD {best['ending_balance']:,.2f}, {result['best_improvement_pct']:.3f}% above the baseline in the same path/cost. This is a provisional scenario result, not a claim of dominance across paths or costs.",'',f"Module screens: {sum(x['configurations'] for x in module.values()):,} configurations including the goal parameter, {sum(x['annual_screens'] for x in module.values()):,} annual module simulations. These are not full portfolio replays. Completed annual C# cases: {len(annual)}, including repeated controls. Completed continuous C# cases: {len(continuous)}.",'','The synthetic M1 C# model inherits API stubs, synthetic reliable heartbeat/ACK handling, and synthetic XAU admission snapshots from the recovered original research. It does not execute the uploaded .algo binary in cTrader or certify broker tick execution, historical macro vintages, market impact or large-capacity live fills. No LIVE strategy, service, checkpoint or order was changed.','', 'Cost factor 2 stresses modeled fees, slippage and funding; the reported spread multiplier remains 1. It is not a guarantee that all real-world costs have been captured. MaxEquityDDPct is peak-to-trough equity drawdown, including open positions; it is not closed-balance drawdown.','', 'The standalone screen column dd_upper is a module screening statistic. It is not a mathematical bound on the C# portfolio drawdown because entry timing and subsequent position sequences can differ. Candidates were rejected when the portfolio validation contradicted the screen.','', 'The experiment is exploratory. The historical periods were already used in prior research; there is no pristine holdout or live profitability certification.','', 'The early target is recorded only when both balance and equity reach USD1,000. Baseline path B reaches it on 2 April 2019 05:19:25 UTC. The RSI80/BUY18R/72h candidate reaches it on 3 April 2019 20:22:10 UTC, about 1.63 days later. Higher terminal balance therefore has not proved a faster early phase.','', 'Seed 5R/8h and its alternatives improved some reset cases but failed others, including higher-cost cases. A flat-only EUR/BTC add-on did not improve the portfolio consistently. The H1 BTC compression add-on failed to improve its five-year pilot consistently. These variants are not promoted.','', 'The capacity variant changes only BTC maximum batch order count 32→128 and batch window 180→600 seconds. The batch planned risk fraction remains 2.5%, batch margin fraction remains 10%, shared planned risk cap remains 20.75%, shared entry margin cap remains 50%, leverage and per-order broker model limits remain unchanged. Those entry controls are not hard bounds on observed floating risk/margin ratios after equity changes.','', 'Source hashes and exact input restoration hashes are retained in CURRENT_SOURCE_AUDIT.json and the baseline restoration records. All scenario definitions are retained as JSON files. Full local order/equity artifacts remain under results/; compact summaries and source are committed to the research branch.']
(root/'REPORT_R1.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'status':result['status'],'annual_cases':len(annual),'continuous_cases':len(continuous),'best_balance':best['ending_balance'],'best_float_dd':best['max_floating_dd_pct'],'completion':completion}))
