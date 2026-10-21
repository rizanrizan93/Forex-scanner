"""Read-only production adapter + isolated as-of reconstruction. Never opens trading/bridge sessions."""
import csv,datetime,hashlib,io,json,os,pathlib,re,subprocess,sys,zipfile,gzip
P=pathlib.Path;UTC=datetime.timezone.utc;out=P(sys.argv[1]);assert str(out).startswith('/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/october-macro-audit/');out.mkdir(parents=True,exist_ok=True)
base=P('/home/Rizanrizan/Forex-scanner');sys.path.insert(0,str(base/'cbot_bridge'));import feeds
now=datetime.datetime.now(UTC);times=[datetime.datetime(2026,10,20,h,m,tzinfo=UTC) for h,m in [(12,5),(12,40),(13,55)]]
report={'observed_utc':now.isoformat(),'read_only_production':True,'historical_delivery_proven':False,'running_adapter_path':str(P(feeds.__file__)),'running_adapter_sha256':hashlib.sha256(P(feeds.__file__).read_bytes()).hexdigest(),'lag_rule':'exact running macro_point: two US federal business days at America/New_York midnight','sources':[],'asof_points':[],'vintage_checks':[],'archive_scan':{}}
raw={}
def get(url,name,kind):
 try:
  b=feeds.fetch(url,now,datetime.timedelta(0));p=out/name;p.write_bytes(b);rec={'name':name,'kind':kind,'url':url,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'status':'downloaded'};report['sources'].append(rec);return b
 except Exception as e:report['sources'].append({'name':name,'kind':kind,'url':url,'status':'unavailable','error_type':type(e).__name__});return None
def details(body,series,at):
 import pandas as pd
 from pandas.tseries.offsets import CustomBusinessDay
 from pandas.tseries.holiday import USFederalHolidayCalendar
 frame=pd.read_csv(io.StringIO(body.decode())).rename(columns={'observation_date':'DATE'});num=pd.to_numeric(frame[series],errors='coerce');f=frame.loc[num.notna(),['DATE']].copy();f[series]=num[num.notna()].astype(float).to_numpy();assert f.DATE.is_unique and f.DATE.is_monotonic_increasing
 days=CustomBusinessDay(calendar=USFederalHolidayCalendar());dates=pd.to_datetime(f.DATE).dt.normalize();available=pd.DatetimeIndex([d+2*days for d in dates]).tz_localize('America/New_York').tz_convert('UTC');eligible=[i for i,t in enumerate(available) if t<=at];i=eligible[-1];assert i>0
 return {'observation_date':f.iloc[i].DATE,'value':float(f.iloc[i][series]),'previous_observation_date':f.iloc[i-1].DATE,'previous_value':float(f.iloc[i-1][series]),'available_utc':available[i].isoformat(),'native_adapter_point':feeds.macro_point(body,series,at)}
for series in ['DGS10','DFII10']:
 b=get(feeds.FRED.format(series),series+'_CURRENT.csv','FRED_CURRENT_NOT_CERTIFIED_VINTAGE')
 if b:raw[series]=b
 # Explicitly request ALFRED vintage; reject ambiguous column names rather than assuming vintage applied.
 url='https://alfred.stlouisfed.org/graph/alfredgraph.csv?id='+series+'&vintage_date=2026-10-20'
 b=get(url,series+'_ALFRED_VINTAGE_20261020.csv','ALFRED_REQUESTED_VINTAGE')
 if b:
  try:
   import pandas as pd
   f=pd.read_csv(io.StringIO(b.decode()));columns=list(f.columns);expected=series+'_20261020';verified=expected in columns
   check={'series':series,'requested_vintage':'2026-10-20','columns':columns,'vintage_header_verified':verified}
   if verified:
    body=f.rename(columns={expected:series}).to_csv(index=False).encode();check['points']=[{'signal_utc':t.isoformat(),**details(body,series,t)} for t in times]
   report['vintage_checks'].append(check)
  except Exception as e:report['vintage_checks'].append({'series':series,'vintage_header_verified':False,'error_type':type(e).__name__})
for t in times:
 row={'signal_utc':t.isoformat(),'signal_wib':t.astimezone(datetime.timezone(datetime.timedelta(hours=7))).isoformat(),'points':{},'scope':'AS_OF_RECONSTRUCTION_FROM_NEWLY_DOWNLOADED_DATA_NOT_TERMINAL_DELIVERY_LOG'}
 for series,b in raw.items():row['points'][series]=details(b,series,t)
 report['asof_points'].append(row)
ff=get(feeds.FF,'FF_THISWEEK_AT_AUDIT.json','CALENDAR_RETRIEVED_AFTER_SIGNAL');bls=get(feeds.BLS,'BLS_ICS_AT_AUDIT.ics','CALENDAR_RETRIEVED_AFTER_SIGNAL')
cases=[]
for row,t in zip(report['asof_points'],times):
 snap={'ProducedUtc':feeds.utc_text(t),'CoverageFromUtc':feeds.utc_text(t),'CoverageToUtc':feeds.utc_text(t),'ForexFactoryOk':False,'BlsOk':False,'Dgs10':row['points'].get('DGS10',{}).get('native_adapter_point'),'Dfii10':row['points'].get('DFII10',{}).get('native_adapter_point'),'Events':[]};errors=[]
 try:
  assert ff is not None;events,start,end=feeds.ff_events(ff,t);snap.update(ForexFactoryOk=True,CoverageFromUtc=feeds.utc_text(start),CoverageToUtc=feeds.utc_text(end),Events=events)
  assert bls is not None;snap['Events']+=feeds.bls_events(bls,start,end);snap['BlsOk']=True
 except Exception as e:errors.append(type(e).__name__)
 row['calendar_reconstruction']={'ff_ok':snap['ForexFactoryOk'],'bls_ok':snap['BlsOk'],'events_in_hold_window':[v for v in snap['Events'] if t-datetime.timedelta(minutes=30)<=feeds.parse_utc(v['AtUtc'])<=t+datetime.timedelta(minutes=495)],'errors':errors}
 cases.append({'name':'FULL_CURRENT_DATA_RECONSTRUCTION','signal_utc':t.isoformat(),'scope':'RECONSTRUCTION_NOT_DELIVERY_PROOF','snapshot':snap})
 iso=dict(snap);iso.update(ForexFactoryOk=True,BlsOk=True,CoverageFromUtc=feeds.utc_text(t-datetime.timedelta(minutes=30)),CoverageToUtc=feeds.utc_text(t+datetime.timedelta(minutes=495)),Events=[])
 cases.append({'name':'YIELD_ONLY_CALENDAR_ALLOWED_CONTROL','signal_utc':t.isoformat(),'scope':'SYNTHETIC_CALENDAR_CONTROL_WITH_RECONSTRUCTED_YIELD','snapshot':iso})
 positive=json.loads(json.dumps(iso));positive['Dgs10']={'Delta':.01,'AvailableUtc':feeds.utc_text(t)}
 cases.append({'name':'POSITIVE_YIELD_CONTROL','signal_utc':t.isoformat(),'scope':'SYNTHETIC_POSITIVE_CONTROL_NOT_HISTORICAL_DATA','snapshot':positive})
(out/'MACRO_GATE_INPUT.json').write_text(json.dumps(cases,indent=2))
# Bounded known-source archive inventory. Export only whitelisted macro values, never arbitrary JSON/env data.
found=[];candidates=[];visited=0
roots=[base/'state',base/'cbot_bridge',P('/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS')]
skip={'.git','.venv','venv','node_modules','vendor','raw','ticks','data','sdk','packs','shared','proxy_raw'}
def inspect(data,path,member=None):
 try:obj=json.loads(data)
 except Exception:return
 stack=[(obj,0)]
 while stack:
  v,depth=stack.pop()
  if not isinstance(v,dict):continue
  if 'ProducedUtc' in v and ('Dgs10' in v or 'Dfii10' in v):
   found.append({'path':str(path),'member':member,'snapshot':{k:v.get(k) for k in ['ProducedUtc','CoverageFromUtc','CoverageToUtc','ForexFactoryOk','BlsOk','Dgs10','Dfii10']}})
  if depth<2:stack.extend((x,depth+1) for x in v.values() if isinstance(x,dict))
for root in roots:
 if not root.exists():continue
 for folder,dirs,names in os.walk(root):
  rel=P(folder).relative_to(root);dirs[:]=[d for d in dirs if d not in skip and not d.startswith('.')]
  if len(rel.parts)>=5:dirs[:]=[]
  for name in names:
   visited+=1
   if visited>20000:break
   p=P(folder)/name;low=name.lower()
   try:size=p.stat().st_size
   except OSError:continue
   if size>15_000_000:continue
   if any(k in low for k in ['macro','snapshot','readonly']) and not low.endswith(('.py','.cs','.dll','.algo')):
    candidates.append({'path':str(p),'bytes':size})
    if size<=8_000_000:
     try:inspect(gzip.decompress(p.read_bytes()) if low.endswith('.gz') else p.read_bytes(),p)
     except Exception:pass
   if low.endswith('.zip'):
    try:
     with zipfile.ZipFile(p) as z:
      for n in z.infolist():
       if n.file_size<=1_000_000 and n.filename.lower().endswith('.json') and any(k in n.filename.lower() for k in ['macro','snapshot','readonly','audit']):inspect(z.read(n),p,n.filename)
    except Exception:pass
  if visited>20000:break
report['archive_scan']={'roots':[str(x) for x in roots],'files_visited':visited,'bounded_cap_hit':visited>20000,'candidate_files':candidates[:150],'macro_snapshots_found':found[:150],'signal_day_snapshots':[v for v in found if str(v['snapshot'].get('ProducedUtc','')).startswith('2026-10-20')]}
(out/'MACRO_RECONSTRUCTION_AUDIT.json').write_text(json.dumps(report,indent=2));print('MACRO_AUDIT_RESULT',json.dumps(report),flush=True)
