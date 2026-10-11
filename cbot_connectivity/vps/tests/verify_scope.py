from pathlib import Path
import hashlib,json,re
r=Path.cwd(); out=r/'cbot_connectivity/vps'; mappings=[('xau-v1.0.1','cbot_sources/archive/migration-20261010/v1.0.1'),('eur-batch-v1.1.0','cbot_sources/archive/eur-releases/v1.1.0')]
allowed={'OnStart','ConnectBridge','ReceiveBridge','Persist','Cycle','OnStop','BridgeOffline','ServiceBridge'}
def methods(s):
 # Source uses expression-bodied helpers too; compare remaining source after replacing allowed method bodies.
 for name in allowed:
  pattern=re.compile(r'(?m)^    (?:private|protected override) void '+name+r'\([^\n]*?\)\s*\{')
  match=pattern.search(s)
  if not match:continue
  begin=match.start();pos=match.end();depth=1;quoted=False;esc=False
  while depth:
   c=s[pos];pos+=1
   if quoted:
    if esc:esc=False
    elif c=='\\':esc=True
    elif c=='"':quoted=False
   elif c=='"':quoted=True
   elif c=='{':depth+=1
   elif c=='}':depth-=1
  s=s[:begin]+s[pos:]
 s=s.replace('    private DateTime _handshakeDeadline, _saveDeadline;\n    private int _bridgeGeneration;\n    private bool _connecting, _stopping;\n','')
 return re.sub(r"\n{2,}","\n",s)
rows=[]
for target,original in mappings:
 for p in sorted((out/target).rglob('*')):
  if not p.is_file():continue
  rel=p.relative_to(out/target);o=r/original/rel
  a=o.read_bytes();b=p.read_bytes();unchanged=a==b
  if p.name=='RizanRobot.cs':
   assert methods(a.decode())==methods(b.decode()),'non-connectivity code changed'
   for text in [a.decode(),b.decode()]:
    tail=text[text.index('        ManagePositions(now);'):text.index('    private bool ExternalOk')]
    if text==a.decode(): original_tail=tail
    else: assert tail==original_tail,'Cycle strategy changed'
  else:assert unchanged,str(rel)
  rows.append(dict(path=str(p.relative_to(r)),original=str(o.relative_to(r)),original_sha256=hashlib.sha256(a).hexdigest(),adapted_sha256=hashlib.sha256(b).hexdigest(),byte_identical=unchanged))
assert (out/'bridge/feeds.py').read_bytes()==(r/mappings[0][1]/'bridge/feeds.py').read_bytes()
(out/'provenance.json').write_text(json.dumps({'base_commit':'adb5c1c718d3ecef0c36231f48a66eab02dcc6d9','scope':'Connectivity only; original archives unchanged','unchanged_methods':'All methods except OnStart, ConnectBridge, ReceiveBridge, Persist, Cycle connectivity preamble, OnStop; added BridgeOffline and ServiceBridge','files':rows},indent=2)+'\n')
print(f'{len(rows)} source/project files checked; frozen cores, batch execution and robot projects byte-identical; non-connectivity robot code identical')
