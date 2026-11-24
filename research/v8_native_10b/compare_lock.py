"""Native locked-policy versus native control, including entry interference."""
import gzip,json,math
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
 p=ROOT/'runs/V7_LOCK_B1/verified.json'
 if not p.exists():print('P0 native receipt pending');return
 control=json.loads((ROOT/'runs/V7_CONTROL_B1/verified.json').read_text());challenger=json.loads(p.read_text())
 def load(r):
  with gzip.open(r['File'],'rt') as f:return json.load(f)
 a=load(control);b=load(challenger)
 key=lambda x:(x['Symbol'],x['Entry'])
 aa={key(t):t for t in a['Ledger']};bb={key(t):t for t in b['Ledger']}
 common=aa.keys()&bb.keys();by=defaultdict(lambda:{'BasketCount':0,'Wins':0,'NetPnlUSD':0})
 for t in b['Ledger']:
  z=by[t['Symbol']];z['BasketCount']+=1;z['Wins']+=t['Pnl']>0;z['NetPnlUSD']+=t['Pnl']
 xau=sorted([t for t in b['Ledger'] if t['Symbol']=='XAUUSD'],key=lambda t:t['Exit'])
 low=[]
 for t in xau:
  if not 0<t['ReferenceBalance']<1500:continue
  past=[q for q in xau if q['Exit']<t['Entry']][-8:]
  low.append({'Entry':t['Entry'],'NativeEntryBalance':t['ReferenceBalance'],'ClosedXauBasketsBeforeNominalSignal':len(past),'Prior8WinRate':sum(q['Pnl']>0 for q in past)/8 if len(past)==8 else None,'NativeChildren':t['Children'],'NativePnl':t['Pnl'],'Note':'descriptive audit at nominal signal timestamp; actual policy uses native PrepareBasket time'})
 s=b['Summary'];base=a['Summary']
 result={'Policy':{k:challenger['Profile'][k] for k in ['EarlyRiskMask','EarlyRiskLook','EarlyRiskThreshold','EarlyRiskFactor','EarlyRiskLimit']},'ControlEndingUSD':base['EndingBalance'],'NativeEndingUSD':s['EndingBalance'],'NativeFloatingDDPct':s['MaxEquityDDPct'],'NativeClosedDDPct':s['MaxClosedDDPct'],'ChangeUSD':s['EndingBalance']-base['EndingBalance'],'ChangePct':100*(s['EndingBalance']/base['EndingBalance']-1),'FixedLedgerReferenceUSD':2091130955.0952506,'NativeMinusFixedLedgerUSD':s['EndingBalance']-2091130955.0952506,'CoreEntryKeysRetained':len(common),'MissingControlKeys':[list(k) for k in sorted(aa.keys()-bb.keys())],'ExtraKeys':[list(k) for k in sorted(bb.keys()-aa.keys())],'CommonKeysWithChangedChildren':sum(aa[k]['Children']!=bb[k]['Children'] for k in common),'CommonKeysWithChangedPnl':sum(aa[k]['Pnl']!=bb[k]['Pnl'] for k in common),'BySymbol':dict(by),'EarlyXauNativeAudit':low,'MeetsB1ImprovementGate':s['EndingBalance']>base['EndingBalance'] and s['MaxEquityDDPct']<60,'ReceiptSHA256':challenger['ReceiptSHA256'],'AccountingResidualUSD':100+math.fsum(t['Pnl'] for t in b['Ledger'])-s['EndingBalance'],'Explanation':'Native sizing uses current balance/equity, integer units, balance-step sizing, staged allocation, margin, broker min/max volume and order-capacity constraints. A proportional fixed-ledger multiplier cannot preserve these nonlinear decisions. All downstream fills and settlements were replayed.'}
 (ROOT/'P0_NATIVE_COMPARISON.json').write_text(json.dumps(result,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k not in ['EarlyXauNativeAudit','MissingControlKeys','ExtraKeys']}))
if __name__=='__main__':main()
