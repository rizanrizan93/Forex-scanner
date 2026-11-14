"""Inspect only Bootstrap125/BUY050 health and research data metadata. No broker calls."""
import json,subprocess,os,re,sqlite3,shlex,sys
from pathlib import Path
from datetime import datetime,timezone

def run(a,**kw):return subprocess.run(a,capture_output=True,text=True,timeout=90,**kw)
def envparse(text):
 d={}
 for line in text.splitlines():
  if line.strip() and not line.lstrip().startswith('#') and '=' in line:
   k,v=line.split('=',1);p=shlex.split(v);d[k.strip()]=p[0] if len(p)==1 else v.strip()
 return d
report={'observed_utc':datetime.now(timezone.utc).isoformat(),'services':{},'checkpoint_summary':[],'research_locations':[],'execution_authority':'NONE','broker_orders':0}
for unit in ['rizan-bootstrap125-bridge.service','rizan-buy050-bridge.service']:
 props={}
 for name in ['ActiveState','SubState','NRestarts','MemoryCurrent','ExecMainStartTimestampMonotonic']:
  props[name]=run(['systemctl','show',unit,'--value','-p',name]).stdout.strip()
 report['services'][unit]=props
state=Path('/var/lib/rizan-bootstrap125-bridge')
if (state/'health.json').exists():report['health']=json.loads((state/'health.json').read_text())
if (state/'checkpoints.sqlite').exists():
 with sqlite3.connect((state/'checkpoints.sqlite').as_uri()+'?mode=ro',uri=True) as db:
  for key,version,data in db.execute('SELECT key,version,state FROM checkpoints'):
   s=json.loads(data);report['checkpoint_summary'].append({'symbol':key.split(':')[-1],'version':version,'phase':s.get('Phase'),'fault':s.get('Fault'),'quarantined':s.get('Quarantined'),'sending':s.get('Sending'),'intent':s.get('Intent') is not None,'open_label_present':bool(s.get('OpenLabel'))})
# Restrict discovery to known research/scanner directories; file bytes never printed.
locations=set()
for root in [Path('/home/Rizanrizan'),Path('/home'),Path('/opt'),Path('/var/lib')]:
 if not root.exists():continue
 for p in root.iterdir():
  if p.is_dir() and re.search('rizan|tick|replay|research|forex|ctrader',p.name,re.I):locations.add(p)
for home in Path('/home').iterdir():
 if not home.is_dir():continue
 for p in home.iterdir():
  if p.is_dir() and re.search('rizan|tick|replay|research|forex|ctrader',p.name,re.I):locations.add(p)
for root in sorted(locations):
 item={'directory':str(root),'selected_files':[],'subdirectories':[]};total=0
 for p in root.iterdir():
  if p.is_dir():item['subdirectories'].append(p.name)
 # Up to 3 levels only; ignore virtualenv/git and any credentials/config.
 for base,dirs,files in os.walk(root):
  depth=len(Path(base).relative_to(root).parts);dirs[:]=[d for d in dirs if not d.startswith('.') and d not in {'node_modules','__pycache__','venv','sdk','share','lib','include','site-packages'} and depth<3]
  for name in files:
   p=Path(base)/name
   if re.search(r'(tick|replay|seed|2019|2026|bootstrap|growth|\.parquet$|\.bi5$|\.bin$|\.tar\.xz$)',name,re.I) and not re.search(r'(env|key|credential|token)',name,re.I):
    item['selected_files'].append({'path':str(p),'bytes':p.stat().st_size});total+=1
    if total>=80:break
  if total>=80:break
 item['subdirectories']=item['subdirectories'][:40];report['research_locations'].append(item)
report['ctrader_cli_paths']={str(p):p.exists() for p in [Path('/opt/ctrader'),Path('/usr/local/bin/ctrader-cli'),Path('/usr/bin/docker')]}
# Re-use installed authenticated PROBE. Does not write trading checkpoints or send orders.
env=os.environ.copy();env.update(envparse(Path('/etc/rizan-bootstrap125-bridge.env').read_text()))
p=run(['/opt/rizan-bootstrap125-bridge/.venv/bin/python',sys.argv[1]],env=env) if len(sys.argv)>1 else None
if p:
 report['public_probe_exit']=p.returncode
 try:report['public_probe']=json.loads(p.stdout)
 except:report['public_probe']={'result':'unavailable'}
print(json.dumps(report,indent=2))
