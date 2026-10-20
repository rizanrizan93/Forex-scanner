"""Recompute cash-month balances and classify actual fills and basket groups."""
from pathlib import Path
import gzip,json,csv,collections,datetime,hashlib,zipfile
r=Path(__file__).resolve().parent;f=r.parent.parent/'frozen';out=r/'analysis';out.mkdir(exist_ok=True)
def save(name,rows):
 with (out/name).open('w',newline='') as q:
  w=csv.DictWriter(q,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
monthly=[];directions=[];basketstats=[];cutoffs=[];cashproof=[]
for path in ['A','B']:
 a=json.load(gzip.open(f/f'WEEKEND_PATH_{path}_RAW.json.gz'));h=a['BrokerHistory'];g=collections.defaultdict(list)
 for x in h:g[tuple(x['Label'].split('|')[:2])].append(x)
 for symbol in ['XAUUSD','EURUSD','BTCUSD']:
  for side in [0,1]:
   q=[x for x in h if x['SymbolName']==symbol and x['TradeType']==side];groups=[x for x in g.values() if x[0]['SymbolName']==symbol and x[0]['TradeType']==side];p=[sum(v['NetProfit'] for v in group) for group in groups]
   directions.append(dict(path=path,symbol=symbol,side=['BUY','SELL'][side],baskets=len(groups),fills=len(q),gross_winning_net_fills=sum(max(0,x['NetProfit']) for x in q),gross_losing_net_fills=sum(min(0,x['NetProfit']) for x in q),net_pnl=sum(x['NetProfit'] for x in q),winning_basket_net=sum(max(0,x) for x in p),losing_basket_net=sum(min(0,x) for x in p),win_rate_basket_pct=100*sum(x>0 for x in p)/len(p)))
  groups=[x for x in g.values() if x[0]['SymbolName']==symbol]
  stages=[{int(v['Label'].split('|')[2]) for v in group} if symbol!='BTCUSD' else {0} for group in groups]
  basketstats.append(dict(path=path,symbol=symbol,baskets=len(groups),multi_fill_baskets=sum(len(x)>1 for x in groups),baskets_with_later_stage=sum(any(i>0 for i in x) for x in stages),max_stage_index=max(max(x) for x in stages),max_fills_per_basket=max(map(len,groups)),max_total_units_per_basket=max(sum(v['VolumeInUnits'] for v in x) for x in groups)))
 prev=100;events=a['CashEvents'];ei=0;bal=100
 for year in range(2019,2027):
  for month in range(1,13):
   key=f'{year:04d}-{month:02d}'
   if key>'2026-10':break
   while ei<len(events) and events[ei]['At'][:7]<=key:bal=events[ei]['Balance'];ei+=1
   q=[v for v in h if v['ClosingTime'][:7]==key];row=dict(path=path,month=key,start_balance=prev,cash_change=bal-prev,end_balance=bal,closed_fill_net=sum(v['NetProfit'] for v in q))
   for sym,side,label in [('XAUUSD',0,'xau_buy'),('XAUUSD',1,'xau_sell'),('EURUSD',0,'eur_buy'),('EURUSD',1,'eur_sell'),('BTCUSD',0,'btc_buy'),('BTCUSD',1,'btc_sell')]:row[label]=sum(v['NetProfit'] for v in q if v['SymbolName']==sym and v['TradeType']==side)
   row['cash_minus_closed_fill_net']=row['cash_change']-row['closed_fill_net'];monthly.append(row);prev=bal
 btc=[x for x in h if x['SymbolName']=='BTCUSD'];flat=[x for x in btc if datetime.datetime.fromisoformat(x['ClosingTime'].replace('Z','+00:00')).weekday()==4 and x['ClosingTime'][11:16]=='21:30']
 for x in flat:cutoffs.append(dict(path=path,**x))
 cashproof.append(dict(path=path,cash_residual=100+sum(x['NetProfit'] for x in h)-a['Summary']['EndingBalance'],monthly_cash_residual=100+sum(x['cash_change'] for x in monthly if x['path']==path)-a['Summary']['EndingBalance'],cutoff_timed_btc_closes=len(flat),cutoff_net=sum(x['NetProfit'] for x in flat),cutoff_buys=sum(x['TradeType']==0 for x in flat),cutoff_sells=sum(x['TradeType']==1 for x in flat),note='Cutoff-timed exits identified by Friday 21:30 UTC timestamp, not proof of exit reason alone.'))
save('MONTHLY_CASH_AND_CONTRIBUTIONS.csv',monthly);save('DIRECTION_BASKET_AND_FILL.csv',directions);save('LAYERING_ACTUAL.csv',basketstats);save('BTC_CUTOFF_TIMED_EXITS.csv',cutoffs)
(out/'LEDGER_RECONCILIATION.json').write_text(json.dumps(cashproof,indent=2))
print(json.dumps({'cashproof':cashproof,'layering':basketstats},indent=2))
