from pathlib import Path
import os,sys,subprocess,json,gzip,hashlib,datetime
r=Path(__file__).resolve().parent;root=r.parent;out=r/'results';out.mkdir(exist_ok=True);path=sys.argv[1];case='SEVEN_DAY_L200_'+path
checks=json.loads((r/'INPUT_SHA256.json').read_text())
for n,h in checks.items():assert hashlib.file_digest((root/'inputs'/n).open('rb'),'sha256').hexdigest()==h
p=out/(case+'.json');env=os.environ.copy();env.update({'BTC_INPUT':str(root/'inputs/BTCUSD_M1.csv'),'RESEARCH_PATH':path,'RESEARCH_CASE':case,'RESEARCH_BTC_LEVERAGE':'200','BTC_FULL_INDICATORS':'1','DOTNET_GCHeapHardLimit':'0x100000000'})
with (out/(case+'.stdout.log')).open('w') as f,(out/(case+'.stderr.log')).open('w') as e:
 c=subprocess.run([str(root/'dotnet/dotnet'),str(r/'work/replay/Replay.dll'),str(root/'inputs/xau_2012_2026.csv'),str(root/'inputs/eur_2012_2026_recovered.csv'),str(p),'full','2019','2026'],env=env,stdout=f,stderr=e)
assert c.returncode==0
v=json.loads(p.read_text())['Reports'][0];s=v['Summary'];h=v['BrokerHistory'];res=100+sum(x['NetProfit'] for x in h)-s['EndingBalance'];assert abs(res)<1e-5
assert s['OpenPositions']==s['ErrorCount']==s['TerminalForcedCloses']==0 and not s['Quarantined'] and not s['AccountingBlock'];assert s['BtcLeverage']==200 and not s['BtcWeekendBarsFiltered']
for x in h:
 if x['SymbolName']!='BTCUSD':continue
 t=datetime.datetime.fromisoformat(x['EntryTime'].replace('Z','+00:00'));e=datetime.datetime.fromisoformat(x['ClosingTime'].replace('Z','+00:00'));m=(t-datetime.timedelta(days=t.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
 assert t.weekday()<5 and t<=m+datetime.timedelta(days=4,hours=21,seconds=5) and e<=m+datetime.timedelta(days=4,hours=21,minutes=30,seconds=5)
with gzip.open(out/(case+'.json.gz'),'wt') as f:json.dump(v,f,separators=(',',':'))
(out/(case+'_SUMMARY.json')).write_text(json.dumps({'summary':s,'cash_residual':res,'weekend_audit_pass':True},indent=2));print(json.dumps(s),flush=True)
