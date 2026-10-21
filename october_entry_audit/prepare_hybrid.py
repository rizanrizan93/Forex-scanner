"""Separate Dukascopy FX / Bitstamp BTC price proxy. Never replaces frozen inputs."""
import concurrent.futures,csv,datetime,hashlib,json,gzip,lzma,pathlib,struct,time,urllib.request,urllib.error
P=pathlib.Path;out=P('publish');raw=out/'proxy_raw';raw.mkdir(parents=True,exist_ok=True);UTC=datetime.timezone.utc
START=datetime.datetime(2026,9,30,17,tzinfo=UTC);END=datetime.datetime(2026,10,20,17,tzinfo=UTC)
days=[];d=datetime.date(2026,10,10)
while d<=datetime.date(2026,10,20):days.append(d);d+=datetime.timedelta(days=1)
def fetch(url):
 for n in range(3):
  try:
   request_url=url
   with urllib.request.urlopen(urllib.request.Request(request_url,headers={'User-Agent':'RIZAN-research-data-audit'}),timeout=25) as r:b=r.read(2_000_001)
   assert len(b)<=2_000_000
   if '.bi5' in url:
    test=lzma.decompress(b) if b else b'';assert len(test)%24==0
   return b
  except urllib.error.HTTPError as e:
   if e.code==404:raise
   if n==2:raise
  except Exception:
   if n==2:raise
  time.sleep(n+1)
def get(job):
 sym,day,side=job;url=f'https://datafeed.dukascopy.com/datafeed/{sym}/{day.year}/{day.month-1:02d}/{day.day:02d}/{side}_candles_min_1.bi5';name=f'{sym}_{day}_{side}.bi5';path=raw/name
 try:b=path.read_bytes() if path.exists() else fetch(url)
 except urllib.error.HTTPError as e:
  return {'symbol':sym,'day':str(day),'side':side,'status':e.code,'url':url},[]
 except Exception as e:
  return {'symbol':sym,'day':str(day),'side':side,'status':type(e).__name__,'url':url},[]
 path.write_bytes(b)
 decom=lzma.decompress(b) if b else b'';assert len(decom)%24==0
 scale=1000 if sym=='XAUUSD' else 100000;rows=[];invalid=0
 for sec,o,c,l,h,vol in struct.iter_unpack('>5If',decom):
  assert sec<86400 and sec%60==0
  if o==c==l==h==0:invalid+=1;continue
  assert o>0 and l>0 and h>=max(o,c) and l<=min(o,c) and l<=h
  at=datetime.datetime.combine(day,datetime.time(tzinfo=UTC))+datetime.timedelta(seconds=sec)
  if at<END:rows.append((at,o/scale,h/scale,l/scale,c/scale,vol))
 return {'symbol':sym,'day':str(day),'side':side,'status':200,'url':url,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'valid_records':len(rows),'zero_price_rows_excluded':invalid},rows
jobs=[(s,d,side) for s in ['XAUUSD','EURUSD'] for d in days for side in ['BID','ASK']]
values=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
 for i,result in enumerate(ex.map(get,jobs),1):
  values.append(result)
  if i%40==0:print('FX_FETCH_PROGRESS',i,'of',len(jobs),flush=True)
manifest=[x[0] for x in values];(out/'PROXY_FX_INPUT_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
quality={};data={}
PREFIX_HASH={'XAUUSD':'f9572d805936bd51c9728d42802a84dd774ad47e74f5652778ff4e80782daeec','EURUSD':'a75ecbe71806778e4849c7183aa1c432769181a3a5b49c0712662cc35f68fcf0'}

for sym in ['XAUUSD','EURUSD']:
 bids={r[0]:r for (m,rr) in values if m['symbol']==sym and m['side']=='BID' for r in rr};asks={r[0]:r for (m,rr) in values if m['symbol']==sym and m['side']=='ASK' for r in rr}
 missing=[m for m in manifest if m['symbol']==sym and datetime.date.fromisoformat(m['day']).weekday()<5 and (m['status']!=200 or m.get('valid_records',0)==0)]
 assert not missing,('FX_MISSING_WEEKDAY',sym,missing[:3])
 assert set(bids)==set(asks),('BID_ASK_TIME_MISMATCH',sym)
 seq=sorted(bids);assert seq and seq[-1]>=END-datetime.timedelta(minutes=2)
 prefixfile=P('october_entry_audit/verified_inputs')/('xau' if sym=='XAUUSD' else 'eur')
 prefixfile=prefixfile.with_name(prefixfile.name+'_2012_2026.csv.gz')
 pb=prefixfile.read_bytes();assert hashlib.sha256(pb).hexdigest()==PREFIX_HASH[sym]
 prefix=list(csv.DictReader(gzip.decompress(pb).decode().splitlines()))
 assert prefix[0]['timestamp'].startswith('2026-09-01') and prefix[-1]['timestamp'].startswith('2026-10-09')
 rolls={};count=int(prefix[-1]['roll']) if sym=='XAUUSD' else 0
 for day in days:
  if day.weekday()<5:count+=3 if day.weekday()==2 else 1
  rolls[day]=count
 with (out/(sym+'_PROXY.csv')).open('w',newline='') as f:
  w=csv.writer(f);w.writerow(['utc','open','high','low','close','spread','roll','buy_ok','sell_ok'])
  for r in prefix:
   w.writerow([r['timestamp'],r['open'],r['high'],r['low'],r['close'],r['spread'] if sym=='XAUUSD' else '.00001',r['roll'] if sym=='XAUUSD' else 0,1,1])
  for at in seq:
   b=bids[at];a=asks[at];spread=a[1]-b[1];assert spread>=-1e-9
   w.writerow([at.isoformat(),*b[1:5],max(0,spread),rolls[at.date()],1,1])
 quality[sym]={'original_prefix_rows':len(prefix),'prefix_gzip_sha256':PREFIX_HASH[sym],'splice_note':'Verified original HistData prefix Sept1-Oct9; Dukascopy BID/ASK Oct10-Oct20. All XAU macro flags overwritten to 1 only for TECH_ALLOWED control; strict no-macro separately. Not native parity.','rows':len(seq)+len(prefix),'start':prefix[0]['timestamp'],'end':seq[-1].isoformat(),'missing_weekday_files':len(missing),'weekend_404_files':sum(m['symbol']==sym and m['status']==404 for m in manifest),'sha256':hashlib.sha256((out/(sym+'_PROXY.csv')).read_bytes()).hexdigest()}
# BTC execution candles, independent of the immutable full H1 indicator seed.
btc=[];next_at=int(START.timestamp());target=int(END.timestamp());bm=[]
while next_at<target:
 last=min(target-60,next_at+999*60);url=f'https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=60&limit=1000&start={next_at}&end={last}&exclude_current_candle=true'
 b=fetch(url);body=json.loads(b);assert body['data']['pair'].lower().replace('/','')=='btcusd'
 rows=sorted(body['data']['ohlc'],key=lambda x:int(x['timestamp']));before=next_at
 for r in rows:
  at=int(r['timestamp'])
  if at<next_at or at>=target:continue
  assert at==next_at,('BTC_M1_GAP',next_at,at)
  vals=[float(r[k]) for k in ['open','high','low','close']];assert min(vals)>0 and vals[1]>=max(vals[0],vals[3]) and vals[2]<=min(vals[0],vals[3])
  btc.append([datetime.datetime.fromtimestamp(at,UTC).isoformat(),*vals]);next_at+=60
 assert next_at>before,'BTC_NO_PROGRESS';bm.append({'url':url,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)})
with (out/'BTC_EXECUTION_PROXY.csv').open('w',newline='') as f:w=csv.writer(f);w.writerow(['utc','open','high','low','close']);w.writerows(btc)
(out/'PROXY_BTC_INPUT_MANIFEST.json').write_text(json.dumps(bm,indent=2));quality['BTCUSD']={'rows':len(btc),'start':btc[0][0],'end':btc[-1][0],'sha256':hashlib.sha256((out/'BTC_EXECUTION_PROXY.csv').read_bytes()).hexdigest()}
(out/'PROXY_DATA_QUALITY.json').write_text(json.dumps(quality,indent=2));print('PROXY_DATA_READY',json.dumps(quality),flush=True)
