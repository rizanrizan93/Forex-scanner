import datetime,hashlib,io,json,os,pathlib,sqlite3,sys,time,zipfile
import lease_audit
P=pathlib.Path;HOME=P('/home/Rizanrizan');BASE=HOME/'Forex-scanner'
def resolved(env,name,default):
 p=P(env.get(name,default));return p if p.is_absolute() else BASE/p

def main():
 env=lease_audit.env('rizan-cbot-bridge.service');b=lease_audit.env('rizan-btc7d130.service');now=time.time()
 con=sqlite3.connect(resolved(env,'RIZAN_STATE_DB','state/rizan-checkpoints.sqlite').resolve().as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');states=[]
 fields=['EpochUtc','LastBarUtc','LastSignalUtc','LastRealExitUtc','PeakEquity','XauResumeUtc','Quarantined','QuarantineReason','PendingChildren','XauDaySignals','LastSignal','Fault','ExitPending','Sending','WeekendLockUntil']
 for key,ver,raw in con.execute('SELECT key,version,state FROM checkpoints'):
  if ':2147903:' not in key:continue
  s=json.loads(raw);states.append({'namespace':key.split(':')[0],'symbol':key.split(':')[-1],'server_revision':ver,'state':{k:s[k] for k in fields if k in s},'has_basket':s.get('Basket') is not None,'pending_intent':bool(s.get('PendingLabel'))})
 con.close();bc=sqlite3.connect(P(b['RZ7D_STATE_DB']).resolve().as_uri()+'?mode=ro',uri=True)
 for key,ver,raw in bc.execute('SELECT key,version,state FROM checkpoints'):
  s=json.loads(raw);states.append({'namespace':'RZBTC7D130','symbol':'BTCUSD','server_revision':ver,'state':{k:s[k] for k in fields if k in s}})
 bc.close()
 out={'observed_unix':now,'read_only':True,'native_state':states}
 for label,path in [('bridge_health',resolved(env,'RIZAN_HEALTH_PATH','state/cbot_bridge_health.json')),('macro_snapshot',resolved(env,'RIZAN_SNAPSHOT_PATH','state/xau_macro_event_snapshot.json'))]:
  if not path.exists():out[label]={'exists':False};continue
  d=json.loads(path.read_text())
  if label=='bridge_health':out[label]={k:d.get(k) for k in ['observed_at_unix','streams','execution_authority','turso']}
  else:out[label]={k:d.get(k) for k in ['ProducedUtc','CoverageFromUtc','CoverageToUtc','ForexFactoryOk','BlsOk','Dgs10','Dfii10']};out[label]['event_count']=len(d.get('Events',[]));out[label]['error_count']=len(d.get('Errors',[]))
 # Research files can be outside archived result folders. Bounded walk; skip SDKs and caches.
 dirs=[];files=[];archives=[]
 roots=[HOME,P('/tmp')]
 skip={'node_modules','.git','.cache','venv','.venv','vendor','dotnet','sdk','packs','shared','raw','ticks','.npm','.local'}
 for base in roots:
  for root,sub,names in os.walk(base):
   rel=P(root).relative_to(base)
   if len(rel.parts)>=6:sub[:]=[]
   sub[:]=[s for s in sub if s not in skip and not s.startswith('.')]
   if base==P('/tmp') and len(rel.parts)==0:sub[:]=[s for s in sub if any(k in s.lower() for k in ['rizan','research','replay','frozen','portfolio','btc','weekend','seven','lf122'])]
   if len(rel.parts)<2:dirs.extend(str(P(root)/s) for s in sub)
   for name in names:
    p=P(root)/name;low=name.lower()
    if low.endswith(('.csv','.csv.gz','.json.gz','.zip')) and any(k in low for k in ['xau','eur','7d130','seven_day','7day','settlement']):
     try:size=p.stat().st_size
     except OSError:continue
     item={'path':str(p),'bytes':size}
     if low.endswith('.csv'):
      try:
       with p.open('rb') as f:f.seek(max(0,size-4096));item['last_row']=f.read().decode(errors='replace').strip().splitlines()[-1][:240]
      except Exception:pass
     if low.endswith('.zip'):
      if len(archives)<70:
       try:
        with zipfile.ZipFile(p) as z:item['relevant_members']=[n for n in z.namelist() if any(k in n.upper() for k in ['LEDGER','MONTHLY','RAW.JSON','SEVEN_DAY','7D130'])][:25]
       except Exception:pass
       archives.append(item)
     elif len(files)<160:files.append(item)
 out['directories']=dirs[:160];out['candidate_files']=files;out['candidate_archives']=archives
 print(json.dumps(out,indent=2))
if __name__=='__main__':main()
