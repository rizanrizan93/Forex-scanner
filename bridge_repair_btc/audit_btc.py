"""Read-only BTC routing audit; never prints credentials or changes services."""
import ast,json,pathlib,re,subprocess,shlex,socket

def run(*args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=20);return p.returncode,p.stdout

def props(unit):
 code,out=run('systemctl','show',unit,'--no-pager','-p','ActiveState','-p','FragmentPath','-p','EnvironmentFiles','-p','ExecStart')
 return dict(x.split('=',1) for x in out.splitlines() if '=' in x)

def main():
 root=pathlib.Path('/home/Rizanrizan/Forex-scanner')
 out={'read_only':True,'services':{},'production_contracts':[],'routing':[],'listeners':{}}
 p=root/'cbot_bridge/server.py'
 if p.exists():
  for n in ast.walk(ast.parse(p.read_text())):
   if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CONTRACTS' for t in n.targets):out['production_contracts']=list(ast.literal_eval(n.value))
 code,units=run('systemctl','list-unit-files','--no-legend','--no-pager')
 for line in units.splitlines():
  unit=line.split()[0]
  if unit.endswith('.service') and re.search(r'rizan|btc',unit,re.I):
   d=props(unit);out['services'][unit]={'active':d.get('ActiveState'),'unit_path':d.get('FragmentPath'),'btc7d_mentioned':'btc7d' in d.get('ExecStart','').lower() or '7day' in d.get('ExecStart','').lower()}
 code,nginx=run('sudo','-n','nginx','-T')
 out['nginx_readable']=code==0
 if code==0:
  file='';lines=[]
  for line in nginx.splitlines():
   if line.startswith('# configuration file '):file=line.split('file ',1)[1].rstrip(':')
   if re.search(r'^\s*(listen|server_name|location|proxy_pass)\s',line):
    # Only allow directive values safe to disclose, never query strings/credentials.
    safe=line.strip()
    if '@' not in safe and '?' not in safe:lines.append({'file':file,'directive':safe})
  out['routing']=lines
 for port in [25345,25346,8130]:
  s=socket.socket();s.settimeout(1);out['listeners'][str(port)]=s.connect_ex(('127.0.0.1',port))==0;s.close()
 base=pathlib.Path('/home/Rizanrizan')
 out['btc_candidate_paths']=[str(p) for p in base.iterdir() if re.search(r'btc|7day',p.name,re.I)]
 print(json.dumps(out,indent=2))
if __name__=='__main__':main()
