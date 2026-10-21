"""Research exports only. Read datasets/checkpoints; never connect as cBot or trade."""
import csv,datetime,gzip,hashlib,json,os,pathlib,re,subprocess,sys,time
P=pathlib.Path;HOME=P('/home/Rizanrizan');base=HOME/'rizan-ticks'/'REPLAY_RESULTS'
out=P(sys.argv[1]);assert out.is_relative_to(base/'october-entry-audit-20261021');out.mkdir(parents=True,exist_ok=True)
start='2026-09-30T17:00:00';end='2026-10-20T17:00:00'
files=[];ledgers=[];dirs=[]
def tail(p):
 try:
  with p.open('rb') as f:f.seek(max(0,p.stat().st_size-16384));b=f.read()
  rows=b.decode(errors='replace').strip().splitlines();return rows[-1][:240] if rows else ''
 except OSError:return ''
for root,sub,names in os.walk(base):
 rel=P(root).relative_to(base)
 if len(rel.parts)>=7:sub[:]=[]
 sub[:]=[s for s in sub if not s.startswith('.') and s not in ['node_modules','vendor','dotnet','venv','.venv','october-entry-audit-20261021']]
 if len(rel.parts)<2:dirs.extend(str(P(root)/s) for s in sub)
 for name in names:
  p=P(root)/name;low=name.lower()
  if (low in {'xau_2012_2026.csv','eur_2012_2026_recovered.csv','btcusd_m1.csv'} or low.endswith('.csv') and ('2026' in low and ('xau' in low or 'eur' in low))):
   files.append({'path':str(p),'bytes':p.stat().st_size,'last_row':tail(p)})
  if ('7d130' in low or 'seven_day_l200' in low or 'frozen_7day' in low) and low.endswith(('.json.gz','.json','.zip')):ledgers.append(str(p))
result={'period_wib':'2026-10-01 00:00 to2026-10-21 00:00 exclusive','period_utc':[start+'Z',end+'Z'],'start_live_reported_wib':'2026-10-10; exact start time and versions not certified','read_only_production':True,'directories':dirs[:160],'input_files':files[:180],'candidate_ledgers':ledgers[:100]}
(out/'INVENTORY.json').write_text(json.dumps(result,indent=2))
print('INVENTORY',json.dumps(result),flush=True)
# Source Feed is loaded from the exact running release, without opening its DB/lease.
wd=subprocess.run(['systemctl','show','rizan-btc7d130.service','--value','-p','WorkingDirectory'],capture_output=True,text=True,check=True).stdout.strip()
sys.path.insert(0,wd);from server import Feed
seed=P(wd)/'BITSTAMP_H1_SEED.csv';f=Feed(seed);f.update(time.time());wire=json.loads(f.wire(time.time()))
with (out/'BTC_H1.csv').open('w',newline='') as z:
 w=csv.writer(z);w.writerow(['unix','open','high','low','close','count']);w.writerows(wire['bars'])
result['btc_export']={'rows':len(wire['bars']),'through_unix':wire['through'],'seed_csv_sha256':hashlib.sha256(seed.read_bytes()).hexdigest(),'csv_sha256':hashlib.sha256((out/'BTC_H1.csv').read_bytes()).hexdigest(),'source_release':wd}
# Cached replay results are evidence only; do not relabel their coverage as through20Oct.
extracted=[]
for name in ledgers:
 p=P(name)
 if not p.name.endswith('.json.gz') or p.stat().st_size>80_000_000:continue
 try:
  with gzip.open(p,'rt') as h:d=json.load(h)
  if isinstance(d,dict) and 'Reports' in d:d=d['Reports'][0]
  if not isinstance(d,dict) or 'BrokerHistory' not in d:continue
  rows=d['BrokerHistory'];octrows=[r for r in rows if start<=str(r.get('EntryTime','')).replace('Z','')<end]
  key=hashlib.sha256(str(p).encode()).hexdigest()[:12]
  rec={'source':str(p),'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'summary':d.get('Summary',{}),'history_total_rows':len(rows),'period_entry_rows':octrows}
  (out/('CACHED_'+key+'.json')).write_text(json.dumps(rec,indent=2));extracted.append({'source':str(p),'file':'CACHED_'+key+'.json','entries_in_requested_period':len(octrows)})
 except (OSError,ValueError,KeyError,TypeError):continue
result['cached_extracts']=extracted
(out/'INVENTORY.json').write_text(json.dumps(result,indent=2))
print('EXPORT_DONE',json.dumps({'btc_export':result['btc_export'],'cached_extracts':extracted}),flush=True)
