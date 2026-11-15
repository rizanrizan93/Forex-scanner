"""Current-vintage reference archive only. NEVER historical trading features."""
import pathlib,urllib.request,json,hashlib,datetime,io
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];RAW=ROOT/'macro_raw/fred_latest_vintage';RAW.mkdir(parents=True,exist_ok=True)
SERIES={'SOFR':'secured overnight financing rate','DFF':'effective fed funds daily','CPIAUCSL':'CPI all items seasonally adjusted','CPILFESL':'core CPI seasonally adjusted','PPIFIS':'PPI final demand','PPIFES':'PPI final demand less foods and energy','PAYEMS':'nonfarm payrolls','UNRATE':'unemployment rate','ICSA':'initial claims','JTSJOL':'JOLTS job openings','DCOILWTICO':'EIA WTI Cushing spot USD/barrel','DCOILBRENTEU':'EIA Brent Europe spot USD/barrel','VIXCLS':'CBOE VIX daily close','DTWEXBGS':'Federal Reserve broad dollar index, NOT ICE DXY','DEXUSEU':'EURUSD daily reference, NOT tick','DEXJPUS':'USDJPY daily reference, NOT tick'}
def get(item):
 series,label=item;url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2019-01-01&coed=2026-11-15';meta={'series':series,'label':label,'url':url,'historical_feature_eligible':False,'vintage':'LATEST_AT_RETRIEVAL_NOT_HISTORICAL_PIT','available_at_historical':None}
 try:
  raw=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RIZAN-Research/1.0'}),timeout=35).read();df=pd.read_csv(io.BytesIO(raw))
  if series not in df or len(df)==0:raise ValueError('Missing series payload')
  p=RAW/(series+'.csv');p.write_bytes(raw);meta.update(file=str(p.relative_to(ROOT)),sha256=hashlib.sha256(raw).hexdigest(),rows=len(df),retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
 except Exception as e:meta['error']=str(e)
 return meta
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=4) as pool:
  result=list(pool.map(get,SERIES.items()))
 (ROOT/'audit/fred_reference_manifest.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
