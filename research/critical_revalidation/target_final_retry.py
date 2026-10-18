from pathlib import Path
import json,urllib.request,lzma,hashlib,struct,datetime as dt,time,concurrent.futures
r=Path(__file__).resolve().parent;out=r/'extended_hour_recovery';out.mkdir(exist_ok=True)
jobs=[dt.datetime(2025,10,17,h,tzinfo=dt.timezone.utc)for h in[10,11,16,20]]+[dt.datetime(2025,12,31,h,tzinfo=dt.timezone.utc)for h in range(24)]
def fetch(t):
 rel=f'XAUUSD/{t.year}/{t.month-1:02}/{t.day:02}/{t.hour:02}h_ticks.bi5';errors=[];p=out/rel.replace('/','_')
 for suffix in ['', '?download=1', '?audit=20261019']:
  for base in ['https://www.dukascopy.com/datafeed/','https://datafeed.dukascopy.com/datafeed/']:
   url=base+rel+suffix+('&' if suffix else '?')+'retry_nonce='+str(time.time_ns())
   try:
    if p.exists():b=p.read_bytes()
    else:
     req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Cache-Control':'no-cache'})
     with urllib.request.urlopen(req,timeout=12)as response:b=response.read()
    a=lzma.decompress(b)if b else b'';assert len(a)%20==0;records=list(struct.iter_unpack('>3I2f',a));assert all(ms<3600000 and ask>=bid>0 and av>=0 and bv>=0 for ms,ask,bid,av,bv in records)
    p.write_bytes(b);return{'hour_utc':t.isoformat(),'url':url,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'ticks':len(records),'status':'VERIFIED_DECODE'if records else'EMPTY_NO_TICKS','errors':errors}
   except Exception as e:errors.append({'url':url,'error':repr(e)});time.sleep(.3)
 return{'hour_utc':t.isoformat(),'status':'DATA_GAP_UNRESOLVED','errors':errors}
a=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4)as ex:
 for x in ex.map(fetch,jobs):a.append(x);json.dump(a,open(out/'EXTENDED_HOURS.json','w'),indent=2);print(x['hour_utc'],x['status'],x.get('ticks'),flush=True)
