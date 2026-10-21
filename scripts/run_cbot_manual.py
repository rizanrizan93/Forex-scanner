"""One read-only publisher; no order credentials, execution dispatch or DB writes."""
import base64,hashlib,json,os,subprocess,sys,time
from datetime import datetime,UTC
from pathlib import Path
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from fx_scanner.cbot_manual import project,validate
from run_reversal_feed import github_api
FOLDER=ROOT/'artifacts/cbot_manual';BRANCH='cbot-manual-snapshots'
def verify():
 manifest=json.loads((ROOT/'cbot_manual/SOURCE_MANIFEST.json').read_text())
 for path,sha in manifest['files'].items():
  if hashlib.sha256((ROOT/'cbot_manual'/path).read_bytes()).hexdigest()!=sha:raise ValueError('FROZEN_SOURCE_HASH_MISMATCH')
def publish(payload):
 p=validate(payload)
 if not p['fresh']:raise ValueError('SNAPSHOT_NOT_FRESH')
 raw=json.dumps(p,allow_nan=False)
 if len(raw)>900000:raise ValueError('SNAPSHOT_TOO_LARGE')
 try:parent=github_api('GET','git/ref/heads/'+BRANCH)['object']['sha'];exists=True
 except HTTPError as e:
  if e.code!=404:raise
  parent=os.environ['GITHUB_SHA'];exists=False
 tree=github_api('GET','git/commits/'+parent)['tree']['sha']
 t=github_api('POST','git/trees',{'base_tree':tree,'tree':[{'path':'runtime/cbot_manual_snapshot.json','mode':'100644','type':'blob','content':raw}]})
 c=github_api('POST','git/commits',{'message':'Refresh read-only cBot manual monitor','tree':t['sha'],'parents':[parent]})
 if exists:github_api('PATCH','git/refs/heads/'+BRANCH,{'sha':c['sha'],'force':False})
 else:github_api('POST','git/refs',{'ref':'refs/heads/'+BRANCH,'sha':c['sha']})
def loop():
 verify();FOLDER.mkdir(parents=True,exist_ok=True);last_hour=None;btc=None;start=time.monotonic();failures=0
 while time.monotonic()-start<float(os.environ.get('CBOT_MONITOR_SECONDS','19800')):
  tick=time.monotonic()
  try:
   hour=int(time.time()//3600);options=['-i',os.environ['CBOT_SSH_KEY'],'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+os.environ['CBOT_SSH_HOSTS'],'-o','ConnectTimeout=15']
   remote=os.environ['CBOT_READER_PATH']
   if not remote.startswith('/tmp/rizan-monitor.') or not remote.endswith('/read_cbot_native.py') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-' for c in remote):raise ValueError('REMOTE_READER_PATH_INVALID')
   result=subprocess.run(['ssh',*options,'Rizanrizan@202.74.74.172','sudo -n /usr/bin/python3 '+remote+(' --btc' if hour!=last_hour else '')],capture_output=True,text=True,timeout=150,check=True)
   native=json.loads(result.stdout)
   if 'btc_feed' in native:btc=native.pop('btc_feed');last_hour=hour
   if btc:native['btc_feed']=btc
   (FOLDER/'native.json').write_text(json.dumps(native,allow_nan=False))
   subprocess.run([sys.executable,str(ROOT/'scripts/collect_cbot_manual.py'),str(FOLDER/'market.json')],check=True,timeout=180,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   market=json.loads((FOLDER/'market.json').read_text());combined={**market,'native':native};(FOLDER/'input.json').write_text(json.dumps(combined,allow_nan=False))
   subprocess.run(['dotnet',str(ROOT/'cbot_manual/bin/Release/net8.0/Monitor.dll'),str(FOLDER/'input.json'),str(FOLDER/'calculations.json')],check=True,timeout=45,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   p=project(json.loads((FOLDER/'calculations.json').read_text()),market,native);publish(p);(FOLDER/'snapshot.json').write_text(json.dumps(p,allow_nan=False));failures=0
   print('CBOT_MANUAL_PUBLISHED '+p['as_of']+' '+','.join(r['symbol']+':'+r['status'] for r in p['symbols']),flush=True)
  except Exception as e:
   failures+=1;print('CBOT_MANUAL_UNAVAILABLE '+type(e).__name__,flush=True)
   if failures>=3:raise RuntimeError('REPEATED_MONITOR_FAILURE') from None
  remaining=min(30-(time.monotonic()-tick),float(os.environ.get('CBOT_MONITOR_SECONDS','19800'))-(time.monotonic()-start))
  if remaining>0:time.sleep(remaining)
if __name__=='__main__':loop()
