"""Download only the exact archival bytes identified by the read-only VPS manifest."""
import csv,io,json,hashlib,pathlib,urllib.request,time
from concurrent.futures import ThreadPoolExecutor,as_completed
BASE=pathlib.Path(__file__).resolve().parents[1]
DATA=BASE/'data';DATA.mkdir(exist_ok=True)
d=json.loads((BASE/'audit/vps_inventory.json').read_text())
rows=list(csv.DictReader(io.StringIO(d['manifests']['.jobs/manifest_sha256.csv'])))
def get(row):
 p=DATA/row['filename']
 for attempt in range(3):
  try:
   if not p.exists() or p.stat().st_size!=int(row['bytes']):
    tmp=p.with_suffix('.partial');urllib.request.urlretrieve(row['source_url'],tmp);tmp.replace(p)
   digest=hashlib.sha256(p.read_bytes()).hexdigest()
   if digest!=row['sha256']: raise ValueError('SHA256_MISMATCH')
   return {'filename':p.name,'sha256':digest,'bytes':p.stat().st_size,'status':'MATCH_VPS_MANIFEST','source_url':row['source_url']}
  except Exception as e:
   if attempt==2:return {'filename':p.name,'status':'ERROR','error':str(e)}
   time.sleep(1+attempt)
if __name__=='__main__':
 selected=[r for r in rows if r['symbol']=='XAUUSD']
 out=[]
 with ThreadPoolExecutor(max_workers=4) as pool:
  for fut in as_completed([pool.submit(get,r) for r in selected]):
   out.append(fut.result());print(len(out),out[-1]['filename'],out[-1]['status'],flush=True)
 (BASE/'audit/acquisition.json').write_text(json.dumps(sorted(out,key=lambda x:x['filename']),indent=2))
