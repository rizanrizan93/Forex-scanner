import hashlib,json
from pathlib import Path
p=Path(__file__).resolve().parent
frozen=json.loads((p/'FROZEN_SOURCE_SHA256.json').read_text())
rename={'RizanPortfolioBTC10Frozen.csproj':'RizanPortfolioBTC10FullFix.csproj'}
changed=[name for name,digest in frozen.items() if hashlib.sha256((p/'source'/rename.get(name,name)).read_bytes()).hexdigest()!=digest]
assert set(changed)=={'BtcEngine.cs','RizanXauEurPortfolio.cs','RizanPortfolioBTC10Frozen.csproj'},changed
actual={str(x.relative_to(p/'source')) for x in (p/'source').rglob('*.cs') if 'obj' not in x.parts and 'bin' not in x.parts}
assert actual=={n for n in frozen if n.endswith('.cs')}|{'BtcWeekendRecovery.cs'},actual
print(json.dumps({'pass':True,'original_files':len(frozen),'unchanged':len(frozen)-len(changed),'changed':changed,'added':['BtcWeekendRecovery.cs'],'strategy_profile_preserved':hashlib.sha256((p/'source/FrozenR3.cs').read_bytes()).hexdigest()==frozen['FrozenR3.cs']}))
