from pathlib import Path
import subprocess,os,json,gzip,hashlib,collections,csv,time
r=Path(__file__).resolve().parent;root=r.parent.parent;inp=root/'inputs';out=r/'results';out.mkdir(exist_ok=True)
sdk=root/'dotnet';x=inp/'xau_2012_2026.csv';e=inp/'eur_2012_2026_recovered.csv';btc=inp/'BTCUSD_M1.csv'
for p,h in [(x,'3fda8011082e2691b6ebe1a8a4da5fff8e4bf0fc07baf57506b7894d95fc1808'),(e,'3c74ac5ccaeeac64f44693bc6bd4406e9225a9ef61dbb5f80756530f050506ec'),(btc,'c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504')]:assert hashlib.file_digest(p.open('rb'),'sha256').hexdigest()==h
cases=[('NORMAL',{}),('CONTROL',{'RESEARCH_CONTROL':'1'}),('COST_15',{'RESEARCH_COST':'1.5'}),('COST_20',{'RESEARCH_COST':'2'}),('NEXT_M1',{'RESEARCH_NEXT_M1':'1'}),('BTC_L2',{'RESEARCH_BTC_LEVERAGE':'2'}),('BTC_L5',{'RESEARCH_BTC_LEVERAGE':'5'}),('FULL_INDICATORS',{'BTC_FULL_INDICATORS':'1'}),('LEGACY_7D',{'BTC_FULL_INDICATORS':'1','BTC_SEVEN_DAY':'1'})]
# Run the independent reference before any cost or execution variant.
for path in ['A','B']:
 for name,extra in cases:
  case=name+'_'+path;p=out/(case+'.json');packed=out/(case+'.json.gz')
  if packed.exists():continue
  w=r/('legacy_work' if name=='LEGACY_7D' else 'work')
  env=os.environ.copy();env.update(extra);env.update({'BTC_INPUT':str(btc),'RESEARCH_PATH':path,'RESEARCH_CASE':case,'DOTNET_GCHeapHardLimit':'0xC0000000'})
  start=time.time();print('START',case,flush=True)
  with (out/(case+'.stdout.log')).open('w') as f,(out/(case+'.stderr.log')).open('w') as g:
   cp=subprocess.run([str(sdk/'dotnet'),str(w/'replay/Replay.dll'),str(x),str(e),str(p),'full','2019','2026'],env=env,stdout=f,stderr=g)
  if cp.returncode:raise RuntimeError((case,cp.returncode,(out/(case+'.stderr.log')).read_text()[-3000:]))
  d=json.loads(p.read_text());a=d['Reports'][0];s=a['Summary'];h=a['BrokerHistory'];res=100+sum(v['NetProfit'] for v in h)-s['EndingBalance']
  assert abs(res)<1e-5,(case,res)
  assert s['ErrorCount']==0 and not s['Quarantined'] and not s['AccountingBlock'],case
  if name=='NORMAL':
   original=json.load(gzip.open(root/'frozen'/('WEEKEND_PATH_'+path+'_RAW.json.gz')))
   for k in ['EndingBalance','MaxEquityDDPct','MaxClosedDDPct','Baskets','PF']:assert abs(s[k]-original['Summary'][k])<1e-7,(case,k,s[k],original['Summary'][k])
   assert h==original['BrokerHistory'],case+' exact ledger parity'
  with gzip.open(packed,'wt') as f:json.dump(d,f,separators=(',',':'))
  p.unlink() # removes only this script's temporary uncompressed output after verified packing
  print('DONE',case,'seconds',round(time.time()-start,1),'balance',s['EndingBalance'],'DD',s['MaxEquityDDPct'],'open',s['OpenPositions'],flush=True)
