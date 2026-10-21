"""Read-only lease/configuration audit. No sessions acquired, no credentials printed."""
import contextlib,io,json,pathlib,re,shlex,sqlite3,subprocess,time
import audit_btc
P=pathlib.Path

def run(args):return subprocess.run(args,capture_output=True,text=True,timeout=20).stdout

def env(unit):
 def prop(n):return run(['systemctl','show',unit,'--value','-p',n]).strip()
 data=dict(x.split('=',1) for x in shlex.split(prop('Environment')) if '=' in x)
 for f in re.findall(r'(\S+) \(ignore_errors=(?:yes|no)\)',prop('EnvironmentFiles')):
  for line in P(f).read_text().splitlines():
   if '=' not in line or line.lstrip().startswith('#'):continue
   k,_,v=line.partition('=');k=k.strip().removeprefix('export ')
   if re.fullmatch('[A-Z_][A-Z0-9_]*',k):
    val=shlex.split(v,comments=True);data[k]=val[0] if val else ''
 return data

def database(path):
 if not path.exists():return {'exists':False}
 con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');now=time.time()
 leases=[];states=[]
 for key,expiry,touched in con.execute('SELECT key,expires_at,touched_at FROM bridge_leases'):
  leases.append({'namespace':key.split(':')[0],'symbol':key.split(':')[-1],'account_matches_expected':':2147903:' in key,'active':expiry>now,'last_touch_age_s':round(now-touched,2),'expires_in_s':round(expiry-now,2)})
 for key,version,raw in con.execute('SELECT key,version,state FROM checkpoints'):
  s=json.loads(raw);states.append({'namespace':key.split(':')[0],'symbol':key.split(':')[-1],'server_revision':version,'client_revision':s.get('Revision'),'quarantined':s.get('Quarantined',s.get('Fault')),'exit_pending':bool(s.get('ExitPending')),'sending':bool(s.get('Sending'))})
 con.close();return {'exists':True,'leases':leases,'checkpoints':states}

def main():
 buf=io.StringIO()
 with contextlib.redirect_stdout(buf):audit_btc.main()
 a=env('rizan-cbot-bridge.service');b=env('rizan-btc7d130.service')
 path=P(a.get('RIZAN_STATE_DB','state/rizan-checkpoints.sqlite'));path=path if path.is_absolute() else P('/home/Rizanrizan/Forex-scanner')/path
 out={'observed_unix':time.time(),'read_only':True,'infrastructure':json.loads(buf.getvalue()),'tokens_match':bool(a.get('RIZAN_BRIDGE_TOKEN')) and a.get('RIZAN_BRIDGE_TOKEN')==b.get('RZ7D_TOKEN'),'btc_account_matches_expected':b.get('RZ7D_ACCOUNT')=='2147903','main_database':database(path),'btc_database':database(P(b['RZ7D_STATE_DB']))}
 text=run(['journalctl','-u','rizan-btc7d130.service','--since','1 hour ago','--no-pager','-o','cat'])
 out['btc_fixed_error_counts']={c:text.count(c) for c in ['AUTH_FAILED','IDENTITY_INVALID','LEASE_BUSY','FEED_NOT_CURRENT','M1_GAP','Traceback','Main process exited']}
 print(json.dumps(out,indent=2))
if __name__=='__main__':main()
