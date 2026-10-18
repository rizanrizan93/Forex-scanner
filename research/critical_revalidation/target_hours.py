from pathlib import Path
import json,urllib.request,lzma,hashlib,struct,datetime as dt,time,concurrent.futures
r=Path(__file__).resolve().parent;out=r/'targeted_hour_recovery';out.mkdir(exist_ok=True)
# Four still-unavailable hours during an ordinary Friday trading session. Weekend and maintenance are not requested again.
def fetch(h):
 rel=f'XAUUSD/2025/09/17/{h:02}h_ticks.bi5';errors=[]
 for suffix in ['', '?download=1', '?audit=20261019']:
  for base in ['https://www.dukascopy.com/datafeed/','https://datafeed.dukascopy.com/datafeed/']:
   url=base+rel+suffix
   try:
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=15)as response:b=response.read()
    a=lzma.decompress(b)if b else b'';assert len(a)%20==0;records=list(struct.iter_unpack('>3I2f',a))
    assert all(ms<3600000 and ask>=bid>0 and av>=0 and bv>=0 for ms,ask,bid,av,bv in records)
    p=out/rel.replace('/','_');p.write_bytes(b)
    return{'hour_utc':f'2025-10-17T{h:02}:00:00Z','url':url,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'ticks':len(records),'status':'VERIFIED_DECODE'if records else'EMPTY_NO_TICKS','errors':errors}
   except Exception as e:errors.append({'url':url,'error':repr(e)});time.sleep(.5)
 return{'hour_utc':f'2025-10-17T{h:02}:00:00Z','status':'DATA_GAP_UNRESOLVED','errors':errors}
with concurrent.futures.ThreadPoolExecutor(max_workers=2)as ex:a=list(ex.map(fetch,[10,11,16,20]))
json.dump(a,open(out/'TARGETED_HOURS.json','w'),indent=2);print(json.dumps(a),flush=True)
