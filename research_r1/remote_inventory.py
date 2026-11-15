"""Read-only bounded inventory: never imports the trading repository."""
import json, pathlib, datetime
root=pathlib.Path('/home/Rizanrizan/rizan-ticks').resolve()
out={'root':str(root),'audited_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':[],'manifests':{}}
try:
 import pyarrow.parquet as pq
except ImportError:
 pq=None
for symbol in ['XAUUSD','EURUSD','USDJPY']:
 folder=root/symbol
 for p in sorted(folder.rglob('*.parquet')) if folder.exists() else []:
  if len(out['files'])>=500: break
  if not p.resolve().is_relative_to(root): continue
  item={'path':str(p.relative_to(root)),'bytes':p.stat().st_size}
  if pq:
   try:
    f=pq.ParquetFile(p);item.update(rows=f.metadata.num_rows,schema=str(f.schema_arrow))
    if len(out['files'])<3:
     b=next(f.iter_batches(batch_size=2));item['sample']=b.to_pydict()
   except Exception as e: item['error']=type(e).__name__
  out['files'].append(item)
for name in ['.jobs/archive_status.json','.jobs/manifest_sha256.csv','manifest_sha256.csv']:
 p=root/name
 if p.is_file() and p.stat().st_size<500000: out['manifests'][name]=p.read_text()
print(json.dumps(out,default=str))
