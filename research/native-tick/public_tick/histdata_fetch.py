"""Public Generic ASCII bid/ask download; timestamps are fixed EST, not DST."""
import urllib.request,urllib.parse,http.cookiejar,html.parser,zipfile,io,datetime,hashlib,os,math
class Form(html.parser.HTMLParser):
 def __init__(self):super().__init__();self.fields={}
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag=='input' and d.get('id') in ['tk','date','datemonth','platform','timeframe','fxpair']:self.fields[d['id']]=d.get('value','')
def fetch(symbol,year=2019,month=1):
 url=f'https://www.histdata.com/download-free-forex-historical-data/?/ascii/tick-data-quotes/{symbol.lower()}/{year}/{month}'
 jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar));ua={'User-Agent':'Mozilla/5.0'}
 body=opener.open(urllib.request.Request(url,headers=ua),timeout=30).read();form=Form();form.feed(body.decode(errors='replace'))
 if not form.fields.get('tk'):raise RuntimeError('PUBLIC_DOWNLOAD_FORM_UNAVAILABLE')
 fields=form.fields
 if fields.get('fxpair','').upper()!=symbol or fields.get('timeframe')!='T':raise RuntimeError('PUBLIC_FILE_IDENTITY_MISMATCH')
 req=urllib.request.Request('https://www.histdata.com/get.php',data=urllib.parse.urlencode(fields).encode(),headers={**ua,'Referer':url,'Origin':'https://www.histdata.com','Content-Type':'application/x-www-form-urlencoded'})
 raw=opener.open(req,timeout=90).read();z=zipfile.ZipFile(io.BytesIO(raw));data=[];names=[]
 begin=datetime.datetime.fromisoformat(os.environ.get('RIZAN_PUBLIC_START','2019-01-07')).replace(tzinfo=datetime.timezone.utc);finish=datetime.datetime.fromisoformat(os.environ.get('RIZAN_PUBLIC_END','2019-01-12')).replace(tzinfo=datetime.timezone.utc)
 for name in z.namelist():
  if name.lower().endswith('.csv'):
   names.append(name)
   for line in z.read(name).decode('utf-8-sig').splitlines():
    if not line.strip():continue
    p=line.replace(';',',').split(',');stamp=p[0].strip()
    try:at=datetime.datetime.strptime(stamp,'%Y%m%d %H%M%S%f').replace(tzinfo=datetime.timezone(datetime.timedelta(hours=-5))).astimezone(datetime.timezone.utc)
    except ValueError:raise ValueError('UNEXPECTED_PUBLIC_TICK_TIMESTAMP:'+stamp[:40])
    bid=float(p[1]);ask=float(p[2]);
    if not math.isfinite(bid) or not math.isfinite(ask) or bid<=0 or ask<bid:raise ValueError('INVALID_PUBLIC_BID_ASK')
    if begin<=at<finish:data.append((int(at.timestamp()*1000),0 if symbol=='EURUSD' else 1,bid,ask))
 if not data:raise RuntimeError('NO_QUOTES_IN_REQUESTED_WINDOW')
 return data,{'symbol':symbol,'provider':'HistData Generic ASCII tick quotes, millisecond timestamps','source_url':url,'zip_sha256':hashlib.sha256(raw).hexdigest(),'csv_names':names,'count_in_window':len(data),'timezone_conversion':'fixed EST UTC-5 to UTC, no DST'}
