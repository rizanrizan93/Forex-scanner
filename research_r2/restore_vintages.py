"""Restore and hash-check the exact ALFRED responses bundled as a compact archive."""
import pathlib,json,tarfile,gzip,hashlib,re
ROOT=pathlib.Path(__file__).resolve().parents[1];manifest=json.loads((ROOT/'r2_audit/alfred_manifest.json').read_text());expected={x['vintage_date']:x['sha256_uncompressed'] for x in manifest};dest=ROOT/'r2_raw/alfred';dest.mkdir(parents=True,exist_ok=True)
with tarfile.open(ROOT/'r2_raw/ALFRED_EXACT_RESPONSES.tar.xz','r:xz') as archive:
 for member in archive:
  if not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.csv',member.name):raise ValueError('Unexpected archive member')
  day=member.name[:-4];raw=archive.extractfile(member).read()
  if hashlib.sha256(raw).hexdigest()!=expected[day]:raise ValueError('Vintage checksum mismatch')
  p=dest/(day+'.csv.gz')
  if not p.exists():p.write_bytes(gzip.compress(raw))
print('Verified',len(expected),'exact dated ALFRED responses')
