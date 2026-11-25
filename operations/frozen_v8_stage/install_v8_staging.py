"""Isolated staging bridge on the existing VPS. Test account only, no broker API.
Use V1's pinned public BTC seed and read-only cache snapshot; never copy live checkpoints.
"""
import asyncio,contextlib,hashlib,json,os,re,shlex,shutil,socket,sqlite3,subprocess,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
import importlib.util
root=Path(sys.argv[1]).resolve()
source=root/"bridge"
fixture=root/"native_startup_wires.json"
reference=root/"v1_provision.py"
spec=importlib.util.spec_from_file_location("v1_provision",reference)
oldcode=importlib.util.module_from_spec(spec);spec.loader.exec_module(oldcode)
UNIT="rizan-v8frozen-bridge.service";USER="rizan-v8frozen";PORT=25357
APP=Path("/opt/rizan-v8frozen-bridge");STATE=Path("/var/lib/rizan-v8frozen-bridge");ENV=Path("/etc/rizan-v8frozen-bridge.env")
UNITPATH=Path("/etc/systemd/system")/UNIT
SNIPPET=Path("/etc/nginx/snippets/rizan-v8frozen-locations.conf")
V1ENV=Path("/etc/rizan-bootstrap125-bridge.env")
V1APP=Path("/opt/rizan-bootstrap125-bridge")
V1UNIT="rizan-bootstrap125-bridge.service"
ACCOUNT="9000000000000000002"
URL="wss://rizan-bridge.duckdns.org:25345/v8frozen/"
def run(args,timeout=60):
 p=subprocess.run(args,check=True,text=True,capture_output=True,timeout=timeout)
 return p.stdout
def active(unit):return subprocess.run(["systemctl","is-active","--quiet",unit],capture_output=True).returncode==0
def services():
 names=[x.split()[0] for x in run(["systemctl","list-units","--type=service","--state=active","--no-legend","--plain"]).splitlines() if x.split()]
 return {u:run(["systemctl","show",u,"--value","-p","ExecMainStartTimestampMonotonic"]).strip() for u in names if u.startswith("rizan-") and u!=UNIT}
def envparse(s):return oldcode.envparse(s)
def portfree():
 with socket.socket() as s:s.bind(("127.0.0.1",PORT))
def existing_route():
 nginx=run(["nginx","-T"])
 found=[]
 for p in {Path(p).resolve() for p in re.findall(r"^# configuration file ([^:]+):$",nginx,re.M)}:
  if p.is_file():
   s=p.read_text();end=oldcode.server_close(s)
   if end is not None:found.append((p,s,end))
 if len(found)!=1:raise RuntimeError("NGINX_TLS_SERVER_NOT_UNIQUE")
 if "/v8frozen" in nginx or SNIPPET.exists():raise RuntimeError("V8_ROUTE_ALREADY_PRESENT")
 return found[0]
def install():
 assert os.geteuid()==0
 if not active(V1UNIT):raise RuntimeError("V1_BRIDGE_NOT_ACTIVE")
 before=services()
 avail=int(re.search(r"MemAvailable:\s+(\d+)",Path("/proc/meminfo").read_text()).group(1))
 if avail<400*1024:raise RuntimeError("INSUFFICIENT_RAM_FOR_CAPPED_STAGE")
 if shutil.disk_usage("/var/lib").free<1024**3:raise RuntimeError("INSUFFICIENT_FREE_DISK")
 if any(p.exists() for p in (APP,STATE,ENV,UNITPATH,SNIPPET)):raise RuntimeError("V8_STAGE_EXISTS_REVIEW_REQUIRED")
 portfree()
 old=envparse(V1ENV.read_text());token=old["BOOT125_BRIDGE_TOKEN"]
 assert len(token)>=32
 # Only an explicitly synthetic test account is allowed in the staging service.
 # A separate handoff is required before admitting any actual trading account.
 seed=Path(old["BOOT125_BTC_SEED"]);cache=Path(old["BOOT125_STATE_DIR"])/"btc-m1.sqlite"
 if not seed.is_file() or not cache.is_file():raise RuntimeError("V1_PUBLIC_FEED_ASSETS_MISSING")
 if hashlib.sha256(seed.read_bytes()).hexdigest()!="210b1855ac5ffab2b628a7b4d301290427dc04e86a4a6042599d6d0ac8b873f2":raise RuntimeError("BTC_SEED_BYTES_MISMATCH")
 py=V1APP/".venv/bin/python"
 if not py.is_file():raise RuntimeError("V1_PINNED_PYTHON_MISSING")
 run([str(py),"-c","import websockets,icalendar,pandas"])
 conf,original,end=existing_route()
 changed=False;started=False
 try:
  if subprocess.run(["id","-u",USER],capture_output=True).returncode:
   run(["useradd","--system","--user-group","--home-dir",str(STATE),"--shell","/usr/sbin/nologin",USER])
  APP.mkdir(mode=0o755);STATE.mkdir(mode=0o700)
  for p in source.iterdir():
   if p.is_file() and (p.suffix==".py" or p.name=="requirements.txt"):shutil.copyfile(p,APP/p.name)
  shutil.copyfile(seed,APP/"BTC_SEED_PACKET.json")
  with sqlite3.connect(cache.resolve().as_uri()+"?mode=ro",uri=True,timeout=10) as db:
   with sqlite3.connect(STATE/"btc-m1.sqlite") as dst:db.backup(dst)
  shutil.chown(STATE,user=USER,group=USER);shutil.chown(STATE/"btc-m1.sqlite",user=USER,group=USER)
  (STATE/"btc-m1.sqlite").chmod(0o600)
  with ENV.open("x") as f:f.write("BOOT125_HOST=127.0.0.1\nBOOT125_PORT="+str(PORT)+"\nBOOT125_STATE_DIR="+str(STATE)+"\nBOOT125_BTC_SEED="+str(APP/"BTC_SEED_PACKET.json")+"\nBOOT125_ALLOWED_ACCOUNTS="+ACCOUNT+"\nBOOT125_BRIDGE_TOKEN="+token+"\n")
  ENV.chmod(0o600)
  UNITPATH.write_text("[Unit]\nDescription=RIZAN Frozen V8 staging bridge (synthetic account only)\nAfter=network-online.target\n[Service]\nType=simple\nUser="+USER+"\nGroup="+USER+"\nWorkingDirectory="+str(APP)+"\nEnvironmentFile="+str(ENV)+"\nExecStart="+str(py)+" "+str(APP/"server.py")+"\nRestart=no\nUMask=0077\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=true\nReadWritePaths="+str(STATE)+"\nMemoryHigh=192M\nMemoryMax=256M\nMemorySwapMax=128M\nCPUQuota=40%\nOOMScoreAdjust=500\nNice=10\n[Install]\nWantedBy=multi-user.target\n")
  run(["systemctl","daemon-reload"]);run(["systemctl","start",UNIT]);started=True
  for _ in range(30):
   try:
    with socket.create_connection(("127.0.0.1",PORT),timeout=1):break
   except OSError:time.sleep(1)
  else:raise RuntimeError("V8_LOCAL_LISTENER_UNAVAILABLE")
  if not active(UNIT):raise RuntimeError("V8_SERVICE_NOT_ACTIVE")
  if conf.read_text()!=original:raise RuntimeError("NGINX_CHANGED_CONCURRENTLY")
  SNIPPET.write_text("location ^~ /v8frozen/ {\n    proxy_pass http://127.0.0.1:"+str(PORT)+";\n    proxy_http_version 1.1;\n    proxy_set_header Upgrade $http_upgrade;\n    proxy_set_header Connection \"upgrade\";\n    proxy_set_header Host $host;\n    proxy_read_timeout 90s;\n    proxy_send_timeout 90s;\n    proxy_buffering off;\n}\nlocation = /v8frozen { return 308 /v8frozen/; }\n")
  conf.write_text(original[:end]+"\n    include "+str(SNIPPET)+";\n"+original[end:]);changed=True
  run(["nginx","-t"]);run(["systemctl","reload","nginx"])
  # Probe in existing pinned Python, with credentials kept on VPS. All
  # remote account keys are synthetic and in a separate checkpoint database.
  p=subprocess.run([str(py),str(root/"probe_v8.py"),str(fixture),str(ENV)],capture_output=True,text=True,timeout=120)
  if p.returncode:raise RuntimeError("V8_PUBLIC_PROTOCOL_PROBE_FAILED")
  report=json.loads(p.stdout)
  if not report["all_four_roles"] or not report["durable_reconnect"] or not report["btc_feed_fresh"]:raise RuntimeError("V8_PUBLIC_PROBE_INCOMPLETE")
  after=services()
  if any(after.get(k)!=v for k,v in before.items()):raise RuntimeError("LEGACY_SERVICE_RESTART_DETECTED")
  if not active(V1UNIT):raise RuntimeError("V1_NOT_ACTIVE_AFTER_STAGE")
  health=json.loads((Path(old["BOOT125_STATE_DIR"])/"health.json").read_text())
  age=time.time()-datetime.fromisoformat(health["observed_utc"].replace("Z","+00:00")).timestamp()
  if not 0<=age<60 or health["btc"]!="ready":raise RuntimeError("V1_HEALTH_AFTER_STAGE_FAILED")
  with sqlite3.connect((Path(old["BOOT125_STATE_DIR"])/"checkpoints.sqlite").resolve().as_uri()+"?mode=ro",uri=True,timeout=4) as db:
   roles={k.split(":")[-1] for k,e,t in db.execute("SELECT key,expires_at,touched_at FROM bridge_leases") if e>time.time() and time.time()-t<30}
  if not {"BOOTSTRAP","XAUUSD","EURUSD","BTCUSD"}<=roles:raise RuntimeError("V1_LEASES_AFTER_STAGE_FAILED")
  remaining=int(re.search(r"MemAvailable:\s+(\d+)",Path("/proc/meminfo").read_text()).group(1))
  if remaining<128*1024:raise RuntimeError("POST_STAGE_RAM_RESERVE_INSUFFICIENT")
  stage_mem=run(["systemctl","show",UNIT,"--value","-p","MemoryCurrent"])
  report.update(memory_before_MiB=round(avail/1024,1),memory_after_MiB=round(remaining/1024,1),stage_memory_MiB=round(int(stage_mem)/1048576,1) if stage_mem.isdigit() else None,memory_high_MiB=192,memory_max_MiB=256,v1_fresh_leases=True)
  pass # temporary synthetic staging only, no autostart
  report.update(service=UNIT,stage_active=True,old_services_unchanged=True,production_account_allowed=False,execution_authority="NONE",observed_utc=datetime.now(timezone.utc).isoformat())
  print(json.dumps(report))
 except BaseException:
  # Rollback only our own route and service. Never touch old V1 checkpoints.
  if changed:
   # If another writer touched NGINX, do not overwrite its changes.
   expected=original[:end]+"\n    include "+str(SNIPPET)+";\n"+original[end:]
   if conf.read_text()==expected:
    conf.write_text(original);SNIPPET.unlink(missing_ok=True)
    subprocess.run(["nginx","-t"],capture_output=True)
    subprocess.run(["systemctl","reload","nginx"],capture_output=True)
  if started:subprocess.run(["systemctl","stop",UNIT],capture_output=True)
  raise
if __name__=="__main__":
 try:install()
 except Exception as e:
  print(json.dumps({"stage_active":False,"error":str(e) if isinstance(e,RuntimeError) else type(e).__name__,"broker_orders":0,"production_account_allowed":False}))
  sys.exit(1)
