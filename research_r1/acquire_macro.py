"""Official daily histories for descriptive analysis, never intraday PIT inputs."""
import pathlib,json,hashlib,urllib.request,datetime,concurrent.futures
from xml.etree import ElementTree as ET
import pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];RAW=ROOT/'macro_raw';RAW.mkdir(exist_ok=True)
END=pd.Timestamp('2026-11-15',tz='UTC')
def task(year,kind):
 dataset='daily_treasury_yield_curve' if kind=='nominal' else 'daily_treasury_real_yield_curve'
 url=f'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data={dataset}&field_tdr_date_value={year}'
 path=RAW/f'treasury_{kind}_{year}.xml'
 try:
  if not path.exists():
   req=urllib.request.Request(url,headers={'User-Agent':'RIZAN-Research-R1/1.0'})
   path.write_bytes(urllib.request.urlopen(req,timeout=45).read())
  raw=path.read_bytes();root=ET.fromstring(raw);rows=[]
  fields={'BC_2YEAR':'US2Y','BC_5YEAR':'US5Y','BC_10YEAR':'US10Y'} if kind=='nominal' else {'TC_5YEAR':'REAL5Y','TC_10YEAR':'REAL10Y'}
  for e in root.iter():
   if e.tag.split('}')[-1]!='properties':continue
   d={x.tag.split('}')[-1]:x.text for x in e};date=(d.get('NEW_DATE') or '')[:10]
   if not date or date<'2019-01-01' or date>'2026-11-15':continue
   row={'date':date}
   for k,v in fields.items():
    try:row[v]=float(d[k])
    except (ValueError,KeyError,TypeError):row[v]=None
   rows.append(row)
  return rows,{'url':url,'file':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(raw).hexdigest(),'rows':len(rows),'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'historical_available_at':None,'kind':kind}
 except Exception as e:return [],{'url':url,'error':str(e),'kind':kind}
if __name__=='__main__':
 allrows=[];manifest=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
  for rows,meta in ex.map(lambda x:task(*x),[(y,k) for y in range(2019,2027) for k in ['nominal','real']]):
   allrows.extend(rows);manifest.append(meta);print(meta,flush=True)
 df=pd.DataFrame(allrows)
 if len(df):
  df=df.groupby('date').first().sort_index();df['SPREAD10Y2Y']=df.US10Y-df.US2Y;df['BE5Y']=df.US5Y-df.REAL5Y;df['BE10Y']=df.US10Y-df.REAL10Y
  df.to_csv(ROOT/'audit/treasury_daily_descriptive.csv')
 (ROOT/'audit/macro_manifest.json').write_text(json.dumps(manifest,indent=2))
