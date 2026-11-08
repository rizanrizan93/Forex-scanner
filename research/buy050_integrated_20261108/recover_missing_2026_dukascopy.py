#!/usr/bin/env python3
"""Research-only public Dukascopy 2026 gap recovery. No broker or VPS writes."""
import concurrent.futures as futures
import calendar,collections,csv,datetime as dt,gzip,hashlib,json,lzma,struct,sys,time,urllib.request,urllib.error,zipfile
from pathlib import Path
CONFIG={'XAUUSD':(1000,500,10000),'EURUSD':(100000,0.5,2.0)}
def fetch(task):
 sym,y,m,d,h=task
 url=f'https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m-1:02d}/{d:02d}/{h:02d}h_ticks.bi5'
 for k in range(3):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'RIZAN-Research/1.0'})
   with urllib.request.urlopen(req,timeout=45) as f:raw=f.read()
   if not raw:return task,'empty',b'',None
   data=lzma.decompress(raw)
   if len(data)%20:raise ValueError('INVALID_BI5_RECORD_ALIGNMENT')
   return task,'ok',raw,data
  except urllib.error.HTTPError as e:
   if e.code==404:return task,'404',b'',None
   if e.code in (429,500,502,503,504) and k<2:time.sleep(k+1);continue
   return task,'HTTP_'+str(e.code),b'',None
  except Exception as e:
   if k<2:time.sleep(k+1);continue
   return task,type(e).__name__,b'',None
 raise AssertionError('unreachable')
def main():
 sym=sys.argv[1].upper();y,m=map(int,sys.argv[2].split('-'));dest=Path(sys.argv[3])
 if sym not in CONFIG or y!=2026 or not 4<=m<=10:raise ValueError('2026_RESEARCH_SCOPE_ONLY')
 dest.mkdir(parents=True,exist_ok=True)
 divisor,pmin,pmax=CONFIG[sym];last=min(calendar.monthrange(y,m)[1],9 if m==10 else 31)
 tasks=[(sym,y,m,d,h) for d in range(1,last+1) for h in range(24)]
 bars={};states=collections.Counter();errors=[];ticks=0
 rawzip=dest/(f'{sym}_{y}-{m:02d}_RAW_HOURLY_BI5.zip')
 with zipfile.ZipFile(rawzip,'w',compression=zipfile.ZIP_STORED) as archive:
  with futures.ThreadPoolExecutor(max_workers=3) as pool:
   for key,state,raw,data in pool.map(fetch,tasks):
    states[state]+=1;_,_,_,day,hour=key
    if state!='ok':
     if state not in ('404','empty'):errors.append({'day':day,'hour':hour,'code':state})
     continue
    archive.writestr(f'{y}/{m-1:02d}/{day:02d}/{hour:02d}h_ticks.bi5',raw)
    count=len(data)//20;ticks+=count
    for i in range(count):
     ms,au,bu,_,_=struct.unpack_from('>IIIff',data,20*i)
     a=au/divisor;b=bu/divisor
     if ms>=3600000 or not (pmin<=b<=a<=pmax):raise ValueError('INVALID_2026_TICK_PRICE_OR_TIME_SCALE')
     index=(day,hour*60+ms//60000)
     record=bars.get(index)
     if record is None:bars[index]=[b,b,b,b,a,a,a,a,1]
     else:
      record[1]=max(record[1],b);record[2]=min(record[2],b);record[3]=b
      record[5]=max(record[5],a);record[6]=min(record[6],a);record[7]=a;record[8]+=1
 m1=dest/(f'{sym}_{y}-{m:02d}_BIDASK_M1.csv.gz')
 with gzip.open(m1,'wt',newline='') as f:
  w=csv.writer(f);w.writerow(['utc','bid_open','bid_high','bid_low','bid_close','ask_open','ask_high','ask_low','ask_close','tick_count'])
  for (day,minute),r in sorted(bars.items()):
   when=dt.datetime(y,m,day,tzinfo=dt.timezone.utc)+dt.timedelta(minutes=minute)
   w.writerow([when.strftime('%Y-%m-%dT%H:%M:%SZ'),*r])
 out={'source':'Dukascopy public .bi5 (not FP Markets)','symbol':sym,'month':f'{y}-{m:02d}',
      'point_divisor':divisor,'raw_tick_records':ticks,'minutes_with_ticks':len(bars),
      'hours':dict(states),'network_errors':errors,'complete_no_network_errors':not errors,
      'raw_zip_sha256':hashlib.sha256(rawzip.read_bytes()).hexdigest(),
      'm1_sha256':hashlib.sha256(m1.read_bytes()).hexdigest(),
      'no_interpolation':True,'orders_sent':0,'vps_modified':False}
 (dest/'PROVENANCE.json').write_text(json.dumps(out,indent=2)+'\n')
 print('DUKA_MONTH_RESULT='+json.dumps(out,sort_keys=True),flush=True)
if __name__=='__main__':main()
