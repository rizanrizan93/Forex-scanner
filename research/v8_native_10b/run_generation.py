"""Deferred adaptive search using actual annual native screens and full finalists.
Never claims the nominal search space has been executed. No broker access.
"""
import concurrent.futures,fcntl,json,math,random,time
from pathlib import Path
import run_fast_batch as fast
r=fast.r;ROOT=r.ROOT
SPACE={
 'EarlyMask':[5,7], 'EarlyRiskLook':[4,6,8,12,16],
 'EarlyRiskThreshold':[.4,.5,.6,.7], 'EarlyRiskFactor':[.125,.25,.5,.75],
 'EarlyRiskLimit':[500,1000,1500,2500,5000],
 'BtcBuyTarget':[12,18,24,30,40], 'BtcBuyHours':[24,48,72,96,160,240],
 'BtcSellTarget':[2,3,4,6,8,10,15], 'BtcSellHours':[4,8,16,24,48,72],
 'BtcBatchOrders':[16,32,64,128], 'BtcBatchSeconds':[60,180,300,600,1200,1800],
 'BtcBatchRisk':[.01,.015,.02,.025], 'BtcBatchMargin':[.025,.05,.075,.1],
 'BtcBuyRsiMax':[75,80,85,90,100], 'BtcBuyEfficiencyMin':[.2,.25,.3,.4],
 'BtcSellRsiMin':[30,35,40,45], 'AddBtcBullCompression':[False,True],
 'XauTarget':[2,3,4.5,5.5,7,9,12,15], 'XauStop':[1,1.8,2.4,3,4,5],
 'XauRisk':[1,1.3,1.65], 'EurTarget':[4,6,8,10,12,15,20,25],
 'EurBE':[1,2,3,4,6,8], 'EurStop':[.5,.65,.845,1,1.25,1.5],
 'EurRisk':[.4,.6,.8], 'GrowthRisk':[12,16,18,20.75]}
def loadrows():
 return [json.loads(p.read_text()) for p in (ROOT/'runs').glob('*/verified.json')]
def main():
 lock=(ROOT/'adaptive_search.lock').open('w')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:print('Another adaptive worker holds the lock');return
 priority=json.loads((ROOT/'v5/v7_priority_profiles.json').read_text());ids={p['Id'] for p in priority[1:]}
 while True:
  rows=loadrows();completed={x['Profile']['Id'] for x in rows if x['Path']=='B' and x['Cost']==1}
  pending=ids-completed
  if not pending:break
  r.save(ROOT/'ADAPTIVE_STATUS.json',{'stage':'WAITING_FOR_PRIORITY_NATIVE','priority_challengers_completed':len(ids)-len(pending),'priority_challengers_total':len(ids)})
  time.sleep(10)
 assert json.loads((ROOT/'INDEXED_BASELINE_PARITY.json').read_text())['passed']
 rng=random.Random(20261124);control=priority[0]
 # These annual native runs are diagnostics, not the continuous objective.
 annualcontrols=[]
 for year in [2019,2020,2022]:
  p={**control,'Id':f'V8_ANNUAL_CONTROL_{year}','Year':year,'EndYear':year};annualcontrols.append(p)
 fast.batch(annualcontrols,'annual_controls')
 used={json.dumps({k:v for k,v in row['Profile'].items() if k!='Id'},sort_keys=True) for row in loadrows()}
 generation=0
 while not (ROOT/'STOP_RESEARCH').exists():
  allrows=loadrows();full=[x for x in allrows if x['Profile']['Year']==2019 and x['Profile'].get('EndYear')==2026 and x['Path']=='B' and x['Cost']==1]
  good=sorted([x for x in full if x['Summary']['MaxEquityDDPct']<60],key=lambda x:x['Summary']['EndingBalance'],reverse=True)
  target=[x for x in good if x['Summary']['EndingBalance']>=1e10]
  if target:
   r.save(ROOT/'TARGET_B1_FOUND.json',{'status':'B1_TARGET_FOUND_REQUIRES_STRESS_AND_CAPACITY_VALIDATION','candidate':target[0]});return
  parents=[x['Profile'] for x in good[:3]] or [control]
  children=[]
  while len(children)<24:
   p=json.loads(json.dumps(rng.choice(parents)))
   for k in rng.sample(list(SPACE),rng.choice([1,2,3])):p[k]=rng.choice(SPACE[k])
   if p.get('EarlyRiskMask',0)==2 and not (p.get('EarlyMask',7)&2) and p.get('EarlyRiskLimit',1000)<=p.get('EarlyThreshold',1000):p['EarlyRiskMask']=0
   key=json.dumps({k:v for k,v in p.items() if k!='Id'},sort_keys=True)
   if key in used:continue
   used.add(key);p['Id']=f'V8_G{generation:03d}_{len(children):03d}';children.append(p)
  r.save(ROOT/f'GENERATION_{generation:03d}_PROFILES.json',children)
  trials=[]
  for p in children:
   for year in [2019,2020,2022]:trials.append({**p,'Id':p['Id']+f'_ANNUAL{year}','Year':year,'EndYear':year})
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   jobs=[pool.submit(fast.batch,trials[i::2],f'g{generation:03d}_annual_worker{i}') for i in range(2)]
   for f in concurrent.futures.as_completed(jobs):f.result()
  annual={x['Profile']['Id']:x for x in loadrows()}
  scores=[]
  for p in children:
   tests=[annual[p['Id']+f'_ANNUAL{year}'] for year in [2019,2020,2022]]
   failures=sum(not x.get('BootstrapAudit',{}).get('GrowthEnabled',False) or x['Summary']['EndingBalance']<100 for x in tests)
   maxdd=max(x['Summary']['MaxEquityDDPct'] for x in tests)
   score=sum(math.log(max(1,x['Summary']['EndingBalance'])) for x in tests)/len(tests)
   scores.append({'Id':p['Id'],'BootstrapFailures':failures,'Starts':3,'WorstAnnualDDPct':maxdd,'RankingLogBalance':score,'Eligible':failures==0 and maxdd<60})
  r.save(ROOT/f'GENERATION_{generation:03d}_ANNUAL_SCORES.json',scores)
  scoreby={x['Id']:x for x in scores}
  finalists=sorted([p for p in children if scoreby[p['Id']]['Eligible']],key=lambda p:scoreby[p['Id']]['RankingLogBalance'],reverse=True)[:8]
  if finalists:
   with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    jobs=[pool.submit(fast.batch,finalists[i::2],f'g{generation:03d}_full_worker{i}') for i in range(2) if finalists[i::2]]
    for f in concurrent.futures.as_completed(jobs):f.result()
  r.save(ROOT/'ADAPTIVE_STATUS.json',{'stage':'GENERATION_COMPLETE','generation':generation,'annual_native_cases':len(trials),'full_native_finalists':len(finalists),'target_usd':1e10,'production_changes':False})
  generation+=1
if __name__=='__main__':main()
