import pathlib,zipfile,hashlib,csv,io,json,shutil
src=pathlib.Path('input');out=pathlib.Path('dd_results');out.mkdir()
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
old=src/'RIZAN_BTC_DD50_55_AUDIT.zip'
for l in (src/'PACKAGE_SHA256.txt').read_text().splitlines():
 h,n=l.split('  ',1);assert sha(src/n)==h
work=pathlib.Path('corrected');work.mkdir()
with zipfile.ZipFile(old) as z:
 assert z.testzip() is None
 expected=list(csv.DictReader(io.TextIOWrapper(z.open('MANIFEST_SHA256.csv'))))
 for r in expected:assert hashlib.sha256(z.read(r['path'])).hexdigest()==r['sha256']
 z.extractall(work)
changed=[]
for p in work.glob('*/raw_validation/RAW_VALIDATION_PROOF.json'):
 before=sha(p);v=json.loads(p.read_text());original=v['selection']
 v['selection']='Frozen selected top5 DD<50 and top5 50<=DD<=55 from6million prior full-table rows plus7488 targeted sizing cases; actual list SELECTED_BEFORE_STRESS.csv'
 p.write_text(json.dumps(v,indent=2));changed.append({'path':str(p.relative_to(work)),'before_sha256':before,'after_sha256':sha(p),'original_label':original})
assert changed
allowed={x['path'] for x in changed}
for r in expected:
 if r['path'] not in allowed:assert sha(work/r['path'])==r['sha256'],r['path']
proof={'financial_files_byte_identical':True,'execution_sources_byte_identical':True,'reason':'Correct inherited generic shortlist wording in metadata only; actual DD constrained selection was already correct in CSV/report.','changed':changed,'original_archive_sha256':sha(old),'financial_run':39243543774}
(work/'METADATA_CORRECTION.json').write_text(json.dumps(proof,indent=2))
with open(work/'MANIFEST_SHA256.csv','w') as f:
 w=csv.writer(f);w.writerow(['path','sha256','bytes'])
 for p in sorted(work.rglob('*')):
  if p.is_file() and p.name!='MANIFEST_SHA256.csv':w.writerow([str(p.relative_to(work)),sha(p),p.stat().st_size])
with zipfile.ZipFile(out/old.name,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
 for p in work.rglob('*'):
  if p.is_file():z.write(p,str(p.relative_to(work)))
with zipfile.ZipFile(out/old.name) as z:
 assert z.testzip() is None
 for r in csv.DictReader(io.TextIOWrapper(z.open('MANIFEST_SHA256.csv'))):assert hashlib.sha256(z.read(r['path'])).hexdigest()==r['sha256']
for p in src.iterdir():
 if p.is_file() and p.suffix in ['.json','.md','.csv','.txt'] and p.name not in ['PACKAGE_SHA256.txt','VPS_VERIFICATION.txt']:shutil.copy2(p,out/p.name)
shutil.copy2(work/'METADATA_CORRECTION.json',out)
(out/'PACKAGE_SHA256.txt').write_text(sha(out/old.name)+'  '+old.name+'\n')
print(json.dumps(proof,indent=2))
