"""Original Fed statements: use only already published decisions, no future dates."""
import pathlib,re,json,urllib.request,hashlib,concurrent.futures,html
from html.parser import HTMLParser
import pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];RAW=ROOT/'r2_raw/fomc';RAW.mkdir(parents=True,exist_ok=True);OUT=ROOT/'r2_audit';OUT.mkdir(exist_ok=True)
class Links(HTMLParser):
 def __init__(self):super().__init__();self.href=None;self.text=[];self.links=[]
 def handle_starttag(self,t,a):
  if t=='a':self.href=dict(a).get('href');self.text=[]
 def handle_data(self,d):
  if self.href:self.text.append(d)
 def handle_endtag(self,t):
  if t=='a' and self.href:self.links.append((self.href,' '.join(self.text).strip()));self.href=None
def request(url):return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RIZAN-Research-R2/1.0'}),timeout=25).read()
def statement(url):
 try:
  day=re.search(r'monetary(\d{8})',url).group(1);p=RAW/(day+'_'+url.rsplit('/',1)[1]);raw=p.read_bytes() if p.exists() else request(url);text=re.sub('<[^>]+>',' ',raw.decode(errors='replace'));text=html.unescape(text)
  m=re.search(r'For release at\s+(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?',text,re.I)
  if not m:raise ValueError('NO_VERIFIED_RELEASE_TIME')
  hour=int(m.group(1))%12+(12 if m.group(3).lower()=='p' else 0);minute=int(m.group(2) or 0)
  dt=pd.to_datetime(day).tz_localize('America/New_York')+pd.Timedelta(hours=hour,minutes=minute)
  p.write_bytes(raw)
  return {'series':'FOMC','release_utc':dt.tz_convert('UTC').isoformat(),'available_after_buffer':(dt+pd.Timedelta(hours=1)).tz_convert('UTC').isoformat(),'archive_url':url,'sha256':hashlib.sha256(raw).hexdigest(),'file':str(p.relative_to(ROOT)),'verified_time_text':m.group(0)}
 except Exception as e:return {'archive_url':url,'error':str(e)}
if __name__=='__main__':
 urls=set();indexmeta=[]
 for year in range(2019,2027):
  url=f'https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm'
  try:
   raw=request(url);(RAW/f'index_{year}.html').write_bytes(raw);parser=Links();parser.feed(raw.decode(errors='replace'))
   for href,label in parser.links:
    if label.lower()=='statement' and re.search(r'/pressreleases/monetary\d{8}[a-z]\.htm',href):urls.add('https://www.federalreserve.gov'+href if href.startswith('/') else href)
   indexmeta.append({'year':year,'url':url,'sha256':hashlib.sha256(raw).hexdigest()})
  except Exception as e:indexmeta.append({'year':year,'url':url,'error':str(e)})
 # Calendar page carries recent years when historical year pages are not published.
 url='https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
 try:
  raw=request(url);(RAW/'calendar.html').write_bytes(raw);parser=Links();parser.feed(raw.decode(errors='replace'))
  for href,label in parser.links:
   m=re.search(r'/pressreleases/monetary(\d{8})[a-z]\.htm',href)
   if m and (label.lower()=='statement' or (label.lower()=='html' and href.endswith('a.htm'))) and '20190101'<=m.group(1)<='20260331':urls.add('https://www.federalreserve.gov'+href if href.startswith('/') else href)
 except Exception as e:indexmeta.append({'url':url,'error':str(e)})
 urls=sorted(u for u in urls if '20190101'<=re.search(r'monetary(\d{8})',u).group(1)<='20260331')
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:result=list(ex.map(statement,urls))
 (OUT/'fomc_manifest.json').write_text(json.dumps({'indexes':indexmeta,'statements':result},indent=2));pd.DataFrame([x for x in result if 'error' not in x]).to_csv(OUT/'fomc_releases.csv',index=False)
 print('statements',len(result),'verified',sum('error' not in x for x in result),flush=True)
