import concurrent.futures,datetime,hashlib,json,lzma,pathlib,struct,urllib.request,urllib.error
P=pathlib.Path;out=P('publish');out.mkdir(exist_ok=True)
def get(job):
 symbol,day=job;d=datetime.date.fromisoformat(day);url=f'https://datafeed.dukascopy.com/datafeed/{symbol}/{d.year}/{d.month-1:02d}/{d.day:02d}/BID_candles_min_1.bi5'
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RIZAN-research-data-audit'}),timeout=25) as r:b=r.read(2_000_001)
  assert len(b)<=2_000_000;raw=lzma.decompress(b);assert len(raw)%24==0
  rows=list(struct.iter_unpack('>5If',raw));scale=1000 if symbol=='XAUUSD' else 100000
  valid=[a for a in rows if a[1]>0 and a[3]>0 and a[4]>=max(a[1],a[2]) and a[3]<=min(a[1],a[2]) and a[0]<86400 and a[0]%60==0]
  return {'symbol':symbol,'day':day,'url':url,'status':'OK','bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'records':len(rows),'valid_records':len(valid),'first':[[*a[:1],*[v/scale for v in a[1:5]],a[5]] for a in valid[:2]]}
 except urllib.error.HTTPError as e:return {'symbol':symbol,'day':day,'url':url,'status':'HTTP_'+str(e.code)}
 except Exception as e:return {'symbol':symbol,'day':day,'url':url,'status':type(e).__name__}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:rows=list(ex.map(get,[(s,d) for s in ['XAUUSD','EURUSD'] for d in ['2026-10-01','2026-10-20']]))
(out/'FX_PUBLIC_DATA_PROBE.json').write_text(json.dumps(rows,indent=2));print('FX_PUBLIC_PROBE',json.dumps(rows),flush=True)
