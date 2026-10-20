from pathlib import Path
import sys,subprocess,os,gzip,json,hashlib,datetime,collections
r=Path(__file__).resolve().parent;root=r.parent.parent;w=r/'work';o=r/'results';o.mkdir(exist_ok=True);path=sys.argv[1];case='LF122_L200_'+path
for name,h in [('BTCUSD_M1.csv','c217e367a22cab5f157d6d8a38828b9ada249f5a2d0657f20d204fee881c9504'),('xau_2012_2026.csv','3fda8011082e2691b6ebe1a8a4da5fff8e4bf0fc07baf57506b7894d95fc1808'),('eur_2012_2026_recovered.csv','3c74ac5ccaeeac64f44693bc6bd4406e9225a9ef61dbb5f80756530f050506ec')]:assert hashlib.file_digest((root/'inputs'/name).open('rb'),'sha256').hexdigest()==h
p=o/(case+'.json');env=os.environ.copy();env.update({'BTC_INPUT':str(root/'inputs/BTCUSD_M1.csv'),'RESEARCH_PATH':path,'RESEARCH_CASE':case,'RESEARCH_BTC_LEVERAGE':'200','DOTNET_GCHeapHardLimit':'0xC0000000'})
with (o/(case+'.stdout.log')).open('w') as out,(o/(case+'.stderr.log')).open('w') as err:
 c=subprocess.run([str(root/'dotnet/dotnet'),str(w/'replay/Replay.dll'),str(root/'inputs/xau_2012_2026.csv'),str(root/'inputs/eur_2012_2026_recovered.csv'),str(p),'full','2019','2026'],env=env,stdout=out,stderr=err)
assert c.returncode==0,(case,c.returncode)
a=json.loads(p.read_text())['Reports'][0];s=a['Summary'];h=a['BrokerHistory'];res=100+sum(x['NetProfit'] for x in h)-s['EndingBalance'];assert abs(res)<1e-5
assert s['OpenPositions']==s['ErrorCount']==s['TerminalForcedCloses']==0 and not s['Quarantined'] and not s['AccountingBlock']
for v in h:
 if v['SymbolName']!='BTCUSD':continue
 t=datetime.datetime.fromisoformat(v['EntryTime'].replace('Z','+00:00'));end=datetime.datetime.fromisoformat(v['ClosingTime'].replace('Z','+00:00'));m=(t-datetime.timedelta(days=t.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
 assert t.weekday()<5 and end<=m+datetime.timedelta(days=4,hours=21,minutes=30,seconds=5)
with gzip.open(o/(case+'.json.gz'),'wt') as f:json.dump(a,f,separators=(',',':'))
(o/(case+'_SUMMARY.json')).write_text(json.dumps({'Summary':s,'cash_residual':res,'weekend_audit_pass':True},indent=2));print(json.dumps(s),flush=True)
