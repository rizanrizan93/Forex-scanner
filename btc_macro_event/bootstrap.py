from pathlib import Path
import shutil,hashlib,json
r=Path(__file__).resolve().parent;b=r.parent/'portfolio_weekend'
for folder in ['source','tests']:shutil.copytree(b/folder,r/folder,dirs_exist_ok=True)
for f in ['xau-tape.json','eur-tape.json']:
 if (b/f).is_file():shutil.copy2(b/f,r/f)
assert all((r/'source'/p.relative_to(b/'source')).read_bytes()==p.read_bytes() for p in (b/'source').rglob('*.cs'))
print('Frozen source unchanged; macro/event filter is in replay adapter only.')
