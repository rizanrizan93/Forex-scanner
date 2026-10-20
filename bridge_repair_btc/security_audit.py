"""VPS read-only safety and native-connectivity audit. Never acquires a lease."""
import asyncio,contextlib,datetime,hashlib,io,json,os,pathlib,re,socket,ssl,stat,subprocess,sys,time
import lease_audit
P=pathlib.Path

def command(*args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=20);return p.returncode,p.stdout

def props(unit):
 code,out=command('systemctl','show',unit,'--no-pager','-p','ActiveState','-p','MainPID','-p','NRestarts','-p','WorkingDirectory','-p','NoNewPrivileges','-p','ProtectSystem','-p','ProtectHome')
 return dict(x.split('=',1) for x in out.splitlines() if '=' in x)

def snapshot():
 out=io.StringIO()
 with contextlib.redirect_stdout(out):lease_audit.main()
 return json.loads(out.getvalue())

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def permissions(path):
 p=P(path);s=p.stat();return {'mode':oct(stat.S_IMODE(s.st_mode)),'uid':s.st_uid,'group_or_other_access':bool(s.st_mode&0o077),'is_symlink':p.is_symlink()}

async def auth_checks(token):
 from websockets.asyncio.client import connect
 url='wss://rizan-bridge.duckdns.org:25345/btc7d130';results=[]
 for case,key,contract,value,expected in [
  ('invalid_token','RZBTC7D130:0:BTCUSD','RZ-7D130-BTC8500283-LFOLLOW-WEEKEND','RIZAN_AUDIT_INVALID_TOKEN_NOT_A_SECRET','AUTH_FAILED'),
  ('correct_token_wrong_account','RZBTC7D130:0:BTCUSD','RZ-7D130-BTC8500283-LFOLLOW-WEEKEND',token,'IDENTITY_INVALID'),
  ('correct_token_wrong_contract','RZBTC7D130:2147903:BTCUSD','AUDIT_INVALID_CONTRACT',token,'IDENTITY_INVALID')]:
  async with connect(url,max_size=32000,open_timeout=15) as ws:
   await ws.send(json.dumps({'type':'hello','key':key,'lease':'0'*32,'contract':contract,'token':value}))
   reply=json.loads(await asyncio.wait_for(ws.recv(),10));code=reply.get('code')
   # Fixed codes only. No token/key/lease/payload echoed to reports.
   results.append({'case':case,'expected':expected,'received':code if code in {'AUTH_FAILED','IDENTITY_INVALID'} else 'UNEXPECTED','pass':reply.get('type')=='error' and code==expected})
 return results

def main():
 before=snapshot();a=lease_audit.env('rizan-cbot-bridge.service');b=lease_audit.env('rizan-btc7d130.service')
 units={u:props(u) for u in ['rizan-cbot-bridge.service','rizan-btc7d130.service']}
 wd=P(units['rizan-btc7d130.service']['WorkingDirectory'])
 source={n:digest(wd/n) for n in ['server.py','store_base.py','timestamps.py','BITSTAMP_H1_SEED.csv']}
 envsec=permissions('/home/Rizanrizan/rizan-btc7d130/bridge.env');dbsec=permissions(b['RZ7D_STATE_DB'])
 code,ss=command('ss','-H','-ltn');listeners=[]
 for line in ss.splitlines():
  fields=line.split()
  if len(fields)>3 and any(fields[3].endswith(':'+str(p)) for p in [8130,25346,25345]):listeners.append(fields[3])
 private=[x for x in listeners if x.endswith(':8130') or x.endswith(':25346')]
 loopback=bool(private) and all(x.rsplit(':',1)[0] in {'127.0.0.1','[::1]','::1'} for x in private)
 context=ssl.create_default_context()
 with socket.create_connection(('rizan-bridge.duckdns.org',25345),timeout=15) as tcp:
  with context.wrap_socket(tcp,server_hostname='rizan-bridge.duckdns.org') as tls:
   cert=tls.getpeercert();tls_result={'hostname_and_chain_valid':True,'protocol':tls.version(),'expires':cert['notAfter'],'expires_in_days':round((ssl.cert_time_to_seconds(cert['notAfter'])-time.time())/86400,2)}
 auth=asyncio.run(auth_checks(a['RIZAN_BRIDGE_TOKEN']))
 # Independent reconstruction verifies feed source + catch-up. It does NOT assert native FeedReady.
 feed={}
 try:
  sys.path.insert(0,str(wd));from server import Feed
  f=Feed(b['RZ7D_SEED_CSV']);f.update(time.time());wire=json.loads(f.wire(time.time()))
  feed={'independent_reconstruction_current':True,'source':wire['source'],'contract':wire['contract'],'rows':len(wire['bars']),'through_unix':wire['through']}
 except Exception as exc:feed={'independent_reconstruction_current':False,'failure_type':type(exc).__name__}
 time.sleep(15)
 after=snapshot();nowunits={u:props(u) for u in units}
 unchanged={u:units[u]['MainPID']==nowunits[u]['MainPID'] for u in units}
 con=__import__('sqlite3').connect(P(b['RZ7D_STATE_DB']).resolve().as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');integrity=con.execute('PRAGMA quick_check').fetchone()[0];con.close()
 out={'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'read_only':True,'native_before':before,'native_after':after,'units':nowunits,'service_pids_unchanged':unchanged,'btc_source_sha256':source,'btc_env_permissions':envsec,'btc_db_permissions':dbsec,'btc_sqlite_quick_check':integrity,'listeners':listeners,'private_backends_loopback_only':loopback,'public_tls':tls_result,'public_btc_auth_checks':auth,'feed_reconstruction':feed,'probe_lease_acquisitions':0,'probe_checkpoint_writes':0,'production_changes':False,'orders_sent':False,'native_entry_readiness_observed':False}
 print(json.dumps(out,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'audit_complete':False,'error_type':type(e).__name__,'production_changes':False,'orders_sent':False}));sys.exit(1)
