import zipfile,json,csv,io,hashlib,gzip,sys
from datetime import datetime,timedelta
z=zipfile.ZipFile(sys.argv[1]);m=json.loads(z.read('SHA256_MANIFEST.json'))
for n,h in m.items():assert hashlib.sha256(z.read(n)).hexdigest()==h,n
metrics=list(csv.DictReader(io.StringIO(z.read('METRICS.csv').decode())));assert len(metrics)==6
results=[]
for row in metrics:
 c=row['case'];x=json.loads(gzip.decompress(z.read(c+'_RAW.json.gz')));s=x['Summary'];h=x['BrokerHistory']
 assert abs(float(row['balance'])-s['EndingBalance'])<1e-8
 res=100+sum(p['GrossProfit']+p['Commissions']+p['ExitCommission']+p['Swap'] for p in h)-s['EndingBalance'];assert abs(res)<1e-5
 assert not x['Open'] and not x['Errors'] and not s['Quarantined'] and not s['AccountingBlock']
 pk=100;dd=0
 for p in x['CashEvents']:pk=max(pk,p['Balance']);dd=max(dd,(pk-p['Balance'])/pk)
 assert abs(dd*100-s['MaxClosedDDPct'])<1e-8
 btc=[p for p in h if p['SymbolName']=='BTCUSD'];assert len(btc)==s['BtcBaskets']
 assert sum(p['TradeType']==0 for p in btc)==s['BtcBuys'];assert sum(p['TradeType']==1 for p in btc)==s['BtcSells']
 for p in btc:
  a=datetime.fromisoformat(p['EntryTime'].replace('Z','+00:00'));b=datetime.fromisoformat(p['ClosingTime'].replace('Z','+00:00'));assert a.weekday()<5;assert b<=(a+timedelta(days=(4-a.weekday())%7)).replace(hour=21,minute=30,second=5,microsecond=0)
 pf=sum(max(0,p['Pnl']) for p in x['Ledger'])/-sum(min(0,p['Pnl']) for p in x['Ledger']);assert abs(pf-s['PF'])<1e-8
 results.append(dict(case=c,cash_residual=res,btc_positions=len(btc)))
print(json.dumps({'files_verified':len(m),'cases':results,'macro_vintage_certified':False,'live_changed':False},indent=2))
