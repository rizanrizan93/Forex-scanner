"""Publish isolated manual market and compact news files atomically."""
import json,os,subprocess,sys
from pathlib import Path
from datetime import UTC,datetime
APP=Path('/opt/rizan-manual-r3');OUT=Path('/var/lib/rizan-manual-r3')

def atomic(path,data):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w') as f:json.dump(data,f,separators=(',',':'),allow_nan=False);f.flush();os.fsync(f.fileno())
    tmp.chmod(0o644);os.replace(tmp,path)

def main():
    from fx_scanner.manual_r3_feed import read_public,calendar_from_snapshot,PRE_NEWS_URL,NEWS_CONTRACT
    credentials=json.loads(Path('/etc/rizan-bootstrap125-monitor-broker.json').read_text())
    env=dict(os.environ,**{k:credentials[k] for k in ['CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCESS_TOKEN']})
    path=OUT/'market.json'
    subprocess.run([sys.executable,str(APP/'scripts/collect_manual_r3.py'),str(path)],env=env,cwd=APP,check=True,timeout=160,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    now=datetime.now(UTC)
    try:calendar=calendar_from_snapshot(read_public(PRE_NEWS_URL+'?r3='+str(int(now.timestamp()//60)),timeout=5,limit=512*1024),now=now)
    except (OSError,ValueError,TypeError,KeyError):calendar={'contract':NEWS_CONTRACT,'observed_at':None,'events':None,'execution_authority':False}
    data=json.loads(path.read_text());data['calendar']=calendar
    atomic(path,data);atomic(OUT/'news.json',calendar)
    print('MANUAL_R3_PUBLISHED',data['as_of'],len(data['m1']),'calendar='+str(calendar['observed_at']),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as e:print('MANUAL_R3_PUBLISH_FAILED:'+type(e).__name__);raise SystemExit(1)
