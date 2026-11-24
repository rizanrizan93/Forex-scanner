"""Run missing same-path controls and finalist A1/A2/B2 cases, then audit gates."""
import json
import run_fast_batch as fast
r=fast.r;ROOT=r.ROOT
def cached(profile,path,cost):
 p=ROOT/'runs'/f'{profile["Id"]}_{path}{cost}'/'verified.json'
 return json.loads(p.read_text()) if p.exists() else None
def main():
 assert json.loads((ROOT/'INDEXED_BASELINE_PARITY.json').read_text())['passed']
 rows=[json.loads(p.read_text()) for p in (ROOT/'runs').glob('*/verified.json')]
 control=json.loads((ROOT/'v5/v7_priority_profiles.json').read_text())[0]
 choices=sorted([x for x in rows if x['Profile']['Year']==2019 and x['Profile'].get('EndYear')==2026 and x['Path']=='B' and x['Cost']==1 and 'CONTROL' not in x['Profile']['Id'] and x['Summary']['MaxEquityDDPct']<60 and x['Summary']['EndingBalance']>1662133293.0811067],key=lambda x:x['Summary']['EndingBalance'],reverse=True)[:3]
 if not choices:print('No completed B1 improvement eligible for additional stress');return
 for path,cost in [('A',1),('A',2),('B',2)]:
  needed=[]
  if cached(control,path,cost) is None:needed.append(control)
  needed += [x['Profile'] for x in choices if cached(x['Profile'],path,cost) is None]
  if needed:fast.batch(needed,f'finalists_{path}{cost}',path,cost)
 gates=[]
 for choice in choices:
  p=choice['Profile'];cases=[]
  for path,cost in [('B',1),('A',1),('A',2),('B',2)]:
   row=cached(p,path,cost);base=cached(control,path,cost)
   assert row is not None and base is not None
   s=row['Summary'];b=base['Summary']
   cases.append({'Path':path,'Cost':cost,'EndingBalance':s['EndingBalance'],'FloatingDDPct':s['MaxEquityDDPct'],'BaselineBalance':b['EndingBalance'],'BaselineFloatingDDPct':b['MaxEquityDDPct'],'OutperformsSameScenario':s['EndingBalance']>b['EndingBalance'],'DDUnder60':s['MaxEquityDDPct']<60,'ReceiptFile':row['File'],'ReceiptSHA256':row['ReceiptSHA256']})
  gates.append({'Profile':p,'Cases':cases,'FourCaseDDPass':all(x['DDUnder60'] for x in cases),'FourCaseBalanceImprovement':all(x['OutperformsSameScenario'] for x in cases),'TargetReachedB1':choice['Summary']['EndingBalance']>=1e10,'TargetReachedAllFour':all(x['EndingBalance']>=1e10 for x in cases),'AdditionalRobustnessPending':['explicit spread widening','separate slippage stress','delayed execution','Monte Carlo','walk-forward','start-date sensitivity','subperiod tests','broker capacity and market impact'],'LiveApproved':False})
 r.save(ROOT/'FOUR_CASE_VALIDATION.json',gates)
 print(json.dumps(gates))
if __name__=='__main__':main()
