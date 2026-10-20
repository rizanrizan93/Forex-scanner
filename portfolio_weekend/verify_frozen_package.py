from pathlib import Path
import zipfile,json,gzip,hashlib,datetime,sys,zlib
p=Path(sys.argv[1]);z=zipfile.ZipFile(p);assert z.testzip() is None
manifest=json.loads(z.read('SHA256_MANIFEST.json'))
for name,sha in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==sha,name
results=[]
for n in z.namelist():
 if not n.endswith('_RAW.json.gz'):continue
 r=json.loads(gzip.decompress(z.read(n)));s=r['Summary'];h=r['BrokerHistory'];assert s['ErrorCount']==0 and s['OpenPositions']==0 and not s['AccountingBlock'] and not s['Quarantined']
 net=sum(x['GrossProfit']+x['Commissions']+x['ExitCommission']+x['Swap'] for x in h);assert abs(100+net-s['EndingBalance'])<1e-5
 peak=100;dd=0
 for e in r['CashEvents']:peak=max(peak,e['Balance']);dd=max(dd,100*(peak-e['Balance'])/peak)
 assert abs(dd-s['MaxClosedDDPct'])<1e-8
 btc=[x for x in h if x['SymbolName']=='BTCUSD']
 for x in btc:
  a=datetime.datetime.fromisoformat(x['EntryTime'].replace('Z','+00:00'));b=datetime.datetime.fromisoformat(x['ClosingTime'].replace('Z','+00:00'));m=(a-datetime.timedelta(days=a.weekday())).replace(hour=0,minute=0,second=0,microsecond=0);close=m+datetime.timedelta(days=4,hours=22)
  assert a.weekday()<5 and b.weekday()<5 and a<=close-datetime.timedelta(minutes=60)+datetime.timedelta(seconds=5) and b<=close-datetime.timedelta(minutes=30)+datetime.timedelta(seconds=5)
 results.append({'case':s['cfg']['Name'],'balance':s['EndingBalance'],'floating_dd':s['MaxEquityDDPct'],'cash_residual':100+net-s['EndingBalance'],'btc_positions_checked':len(btc),'weekend_violations':0})
assert len(results)==2 and sum(x['btc_positions_checked'] for x in results)==191
algo=z.read('RizanXauEurBtcPortfolio_FROZEN_WEEKEND_V1_2_1.algo');d=zlib.decompressobj(31);meta=json.loads(d.decompress(algo[9:]));t=meta['Types'][0];params={x['PropertyName']:x for x in t['Parameters']};assert 'Version=1.2.1.0' in t['AssemblyName'] and params['EnableTrading']['DefaultValue']==False and params['PortfolioRiskPercent']['MinValue']==params['PortfolioRiskPercent']['MaxValue']==20.75
print(json.dumps({'Pass':True,'SHA256':hashlib.sha256(p.read_bytes()).hexdigest(),'Members':len(manifest),'Checks':results,'NativeMetadataPass':True,'DD56Qualified':False},indent=2))
