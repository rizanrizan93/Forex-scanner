import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
old=json.loads((root/'FROZEN_SOURCE_SHA256.json').read_text())
changed=[]
for name,digest in old.items():
 p=root/'source'/name
 if hashlib.sha256(p.read_bytes()).hexdigest()!=digest: changed.append(name)
assert changed==['BtcEngine.cs'], changed
s=(root/'source/BtcEngine.cs').read_text()
fixed='''// A five-minute cache must never cross the UTC weekly boundary. A stale
            // Friday close would make MustFlatten true on Monday and renew the lock.
            if(now>=nextSchedule||(weekClose.HasValue&&weekClose.Value<=BtcWeekendPolicy.Monday(now))){weekClose='''
legacy=s.replace(fixed,'if(now>=nextSchedule){weekClose=')
assert hashlib.sha256(legacy.encode()).hexdigest()==old['BtcEngine.cs']
print(json.dumps({'pass':True,'source_files':len(old),'changed':changed,'exact_patch_only':True}))
if '--legacy' in __import__('sys').argv: (root/'source/BtcEngine.cs').write_text(legacy)
