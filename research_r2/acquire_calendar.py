"""Original BLS archive release dates; no fabricated future consensus/actuals."""
import pathlib,re,json,hashlib,urllib.request,concurrent.futures,datetime
import pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];RAW=ROOT/'r2_raw/calendar';RAW.mkdir(parents=True,exist_ok=True);AUDIT=ROOT/'r2_audit';AUDIT.mkdir(exist_ok=True)
def task(series):
 url='https://www.bls.gov/bls/news-release/'+series+'.htm';path=RAW/(series+'.html')
 try:
  raw=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RIZAN-Research-R2/1.0'}),timeout=30).read();path.write_bytes(raw);text=raw.decode(errors='replace')
  # Dated release archive names, not reference-month headings or guessed first Fridays.
  matches=set(re.findall(r'(?:https://www.bls.gov)?/news.release/archives/'+series+r'_(\d{8})\.(?:htm|pdf)',text));records=[]
  for stamp in matches:
   day=pd.to_datetime(stamp,format='%m%d%Y',errors='coerce')
   if pd.isna(day) or not pd.Timestamp('2019-01-01')<=day<=pd.Timestamp('2026-03-31'):continue
   et=day.tz_localize('America/New_York')+pd.Timedelta(hours=10 if series=='jolts' else 8,minutes=0 if series=='jolts' else 30)
   records.append({'series':series,'release_et':et.isoformat(),'release_utc':et.tz_convert('UTC').isoformat(),'available_after_buffer':(et+pd.Timedelta(hours=1)).tz_convert('UTC').isoformat(),'archive_url':f'https://www.bls.gov/news.release/archives/{series}_{stamp}.pdf','timestamp_basis':'DATED_ORIGINAL_ARCHIVE_PLUS_REGULAR_RELEASE_TIME_1H_BUFFER'})
  return records,{'series':series,'url':url,'file':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'events':len(records),'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 except Exception as e:return [],{'series':series,'url':url,'error':str(e)}
if __name__=='__main__':
 events=[];manifest=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
  for rows,meta in ex.map(task,['cpi','ppi','empsit','jolts']):events+=rows;manifest.append(meta)
 pd.DataFrame(events).sort_values('release_utc').to_csv(AUDIT/'bls_release_calendar.csv',index=False);(AUDIT/'calendar_manifest.json').write_text(json.dumps(manifest,indent=2));print(manifest)
