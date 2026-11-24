from pathlib import Path
import shutil
root=Path(__file__).resolve().parent
shutil.copytree(root/'native',root/'native_diagnostics',ignore=shutil.ignore_patterns('obj','bin'))
p=root/'native_diagnostics/native_replay/Replay.cs';s=p.read_text()
needle=' void Observe(){host.Mark();'
assert s.count(needle)==1
s=s.replace(needle,' readonly ReplayDiagnostics diagnostics=new();\n void Observe(){host.Mark();diagnostics.Observe(host.Server.TimeInUtc,host.Account.Balance,host.Account.Equity,host.Account.Margin,host.Positions);')
needle='return new{AddonAudit=addon.Audit(),'
assert s.count(needle)==1
s=s.replace(needle,'return new{Diagnostics=diagnostics.Result(),AddonAudit=addon.Audit(),')
p.write_text(s)
