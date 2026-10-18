from pathlib import Path
import os,json,shutil,hashlib,difflib,subprocess,sys
import numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
r=Path(__file__).resolve().parent;old=Path('/tmp/previous');engine=r/'engine';engine.mkdir(exist_ok=True)
for p in old.iterdir():
 if p.is_file() and p.suffix in ['.cs','.py','.gz','.json']:shutil.copy2(p,engine/p.name)
for n in ['source','tests','validation']:shutil.copytree(old/n,engine/n,dirs_exist_ok=True)
# The uploaded bundle overlays adapter files only. Source hashes must remain identical.
import tarfile
with tarfile.open(r/'critical-engine.tgz') as t:t.extractall(engine,filter='data')
for n,sha in json.load(open(old/'SOURCE_SHA256.json')).items():assert hashlib.sha256((engine/'source'/n).read_bytes()).hexdigest()==sha
(engine/'ADAPTER_SOURCE_DIFF.patch').write_text(''.join(difflib.unified_diff((old/'TickReplay.cs').read_text().splitlines(True),(engine/'TickReplay.cs').read_text().splitlines(True),fromfile='8fdfe44/TickReplay.cs',tofile='critical-revalidation/TickReplay.cs')))
# Correct EUR persist-before-queue to source Cycle ordering. Add observation only.
p=engine/'TickReplay.cs';s=p.read_text();s=s.replace('readonly List<object> monthly=new(),','readonly List<object> decisions=new();readonly List<object> monthly=new(),')
s=s.replace('l.Call("PrepareBasket",sp.Signal,Now);','var cashBefore=host.Account.Balance;var equityBefore=host.Account.Equity;var marginBefore=host.Account.Margin;l.Call("PrepareBasket",sp.Signal,Now);decisions.Add(new{At=Now,SignalAt=at,Symbol=l.Symbol,Signal=JsonSerializer.SerializeToElement(sp.Signal,sp.Signal.GetType()),sp.Fast,sp.Slow,Balance=cashBefore,Equity=equityBefore,Margin=marginBefore,Basket=JsonSerializer.SerializeToElement((object?)l.Basket),Status=l.Type.GetField("_status",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(l.Context)});')
s=s.replace('Ledger=host.History,','Decisions=decisions,Ledger=host.History,');p.write_text(s)
# Small sampling fixture records all intents and protection modifications without changing execution.
p=engine/'ApiStubs.cs';s=p.read_text().replace('Requests++;BeforeMarketFill?.Invoke();','Requests++;OrderEvents.Add(new{At=Server.TimeInUtc,Symbol=symbol,Side=side.ToString(),Volume=volume,Label=label,Status="REQUEST",RequestId=Requests});BeforeMarketFill?.Invoke();');p.write_text(s)
# Allow deterministic overlay of verified recovered ticks during monthly read. Always verify originals first.
p=engine/'run_ticks.py';s=p.read_text();s=s.replace("d=pf.read(columns=['timestamp','bid','ask']).to_pandas();t=", "d=pf.read(columns=['timestamp','bid','ask']).to_pandas();\n  if os.environ.get('RIZAN_GAP_PATCH') and sym=='XAUUSD' and ym=='2025-10':\n   patch=pq.read_table(os.environ['RIZAN_GAP_PATCH']).to_pandas()[['timestamp','bid','ask']]\n   patch['timestamp']=pd.to_datetime(patch.timestamp,utc=True);d['timestamp']=pd.to_datetime(d.timestamp,utc=True)\n   assert not d.timestamp.isin(patch.timestamp).any()\n   d=pd.concat([d,patch],ignore_index=True).sort_values('timestamp',kind='stable').reset_index(drop=True)\n   print('VERIFIED_GAP_OVERLAY',len(patch),flush=True)\n  t=")
p.write_text(s)
# Financial reports use the corrected count for the patched scenario set, but provenance retains original manifest.
for name in ['control_audit','patched_audit']:
 dest=r/name;shutil.copytree(old/'data_audit',dest,dirs_exist_ok=True)
patchpath=r/'gap_repair/XAUUSD_gap_patch.parquet';summary=json.load(open(r/'gap_repair/GAP_REPAIR_SUMMARY.json'))
if patchpath.exists() and summary.get('ticks_added',0)>0:
 p=pq.read_table(patchpath).to_pandas();assert len(p)==summary['ticks_added'];assert int(pq.read_metadata(patchpath).metadata[b'point'])==1000
 assert (p.bid>0).all() and (p.ask>=p.bid).all() and p.timestamp.is_monotonic_increasing
 # Calibration: only recovered original BI5 ticks; no price rescaling by fitted market moves.
 original=pd.read_csv(old/'data_audit/XAUUSD_m1.csv');original['timestamp']=pd.to_datetime(original.timestamp,utc=True)
 q=p.copy();q['bid']=q.bid/1000;q['spread']=(p.ask-p.bid)/1000;q=q.set_index('timestamp').resample('1min').agg({'bid':['first','max','min','last'],'spread':['mean']}).dropna();q.columns=['open','high','low','close','spread'];q=q.reset_index();q['roll']=0;q['buy_ok']=0;q['sell_ok']=0
 assert not original.timestamp.isin(q.timestamp).any()
 corrected=pd.concat([original,q]).sort_values('timestamp',kind='stable');corrected.to_csv(r/'patched_audit/XAUUSD_m1.csv',index=False,float_format='%.10f')
 qa=json.load(open(r/'patched_audit/data_quality.json'));qa['original_total_ticks']=qa['total_ticks'];qa['total_ticks']+=len(p);qa['status']='PARTIAL_DATA_GAP_UNRESOLVED_WITH_VERIFIED_PARTIAL_RECOVERY';qa['patch_ticks']=len(p)
 for f in qa['files']:
  if f['file']=='XAUUSD_2025-10.parquet':f['original_ticks']=f['ticks'];f['ticks']+=len(p);f['overlay_sha256']=summary['parquet_sha256']
 json.dump(qa,open(r/'patched_audit/data_quality.json','w'),indent=2)
 summary['minutes_recovered']=len(q);summary['full_gap_resolved']=False
 json.dump(summary,open(r/'gap_repair/GAP_REPAIR_SUMMARY.json','w'),indent=2)
print('PREPARED',summary,flush=True)
