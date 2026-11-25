"""User-authorized retirement of known obsolete RIZAN services only.
Keep the live Bootstrap125 service; no order API, deletion of data, or restart of V1.
"""
import json,os,re,sqlite3,subprocess,sys,time
from pathlib import Path
from datetime import datetime,timezone
KEEP="rizan-bootstrap125-bridge.service"
ROOT=Path("/var/lib/rizan-bootstrap125-bridge")
LEGACY={
 "rizan-buy050-bridge.service":("/var/lib/rizan-buy050-bridge",),
 "rizan-btc10-bridge.service":("/var/lib/rizan-btc10-bridge",),
 "rizan-disp1506-bridge.service":("/var/lib/rizan-disp1506-bridge",),
 "rizan-cbot-bridge.service":("/var/lib/rizan-r3-bridge","/var/lib/rizan-compression-bridge","/var/lib/rizan-tp500-bridge"),
}
# BTC7D130 may be an independent feed dependency; inventory only.
def run(args,check=True):
 return subprocess.run(args,capture_output=True,text=True,timeout=25,check=check).stdout.strip()
def prop(u,k):return run(["systemctl","show",u,"--value","-p",k],False)
def mem():
 d={}
 for l in Path("/proc/meminfo").read_text().splitlines():
  k,v=l.split(":",1)
  if k in {"MemTotal","MemAvailable","SwapTotal","SwapFree"}:d[k+"_MiB"]=round(int(v.split()[0])/1024,1)
 return d
def info(u):
 m=prop(u,"MemoryCurrent");p=prop(u,"MainPID")
 return {"unit":u,"active":prop(u,"ActiveState"),"enabled":prop(u,"UnitFileState"),"pid":int(p) if p.isdigit() else 0,"memory_MiB":round(int(m)/1048576,1) if m.isdigit() and int(m)<10**13 else None}
def inventory():
 names=set(LEGACY)|{KEEP,"rizan-btc7d130.service","rizan-v8frozen-bridge.service"}
 for l in run(["systemctl","list-units","--type=service","--state=active","--no-legend","--plain"]).splitlines():
  if l.split():names.add(l.split()[0])
 out=[info(u) for u in sorted(names)]
 return {"memory":mem(),"services":[u for u in out if u["unit"].startswith("rizan-") or (u["memory_MiB"] or 0)>=20],"top_processes":[l.strip() for l in run(["ps","-eo","pid,comm,rss","--sort=-rss"]).splitlines()[1:11]],"containers":run(["docker","ps","--format","{{.Names}} {{.Status}}"],False).splitlines()}
def ro(p):return sqlite3.connect(p.resolve().as_uri()+"?mode=ro",uri=True,timeout=4)
def healthy():
 if prop(KEEP,"ActiveState")!="active":return False
 try:
  h=json.loads((ROOT/"health.json").read_text())
  age=time.time()-datetime.fromisoformat(h["observed_utc"].replace("Z","+00:00")).timestamp()
  if not 0<=age<60 or h["btc"]!="ready":return False
  with ro(ROOT/"checkpoints.sqlite") as db:
   roles={k.split(":")[-1] for k,e,t in db.execute("SELECT key,expires_at,touched_at FROM bridge_leases") if e>time.time() and time.time()-t<30}
   return {"BOOTSTRAP","EURUSD","XAUUSD","BTCUSD"}<=roles
 except Exception:return False
def validate_old(dirs):
 paths=[Path(d)/"checkpoints.sqlite" for d in dirs]
 if not all(p.is_file() for p in paths):return None,"missing_checkpoint_inventory"
 for p in paths:
  with ro(p) as db:
   names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   if not {"checkpoints","bridge_leases"}<=names:return None,"schema_unknown"
   if db.execute("SELECT 1 FROM bridge_leases WHERE expires_at>?",(time.time(),)).fetchone():return None,"live_lease"
   for key,raw in db.execute("SELECT key,state FROM checkpoints"):
    if key.endswith(":PROBE"):continue
    s=json.loads(raw)
    if any(s.get(k) for k in ("Basket","PendingLabel","NativePendingLabel","Sending","ExitPending","BatchActive","BatchRemaining","OpenLabel","Intent","HandoffSignal","Fault","Quarantined")):return None,"open_or_uncertain_checkpoint"
 return paths,None
def main():
 before=inventory();print("V8_VPS_BEFORE "+json.dumps(before),flush=True)
 changes=[];skipped={}
 if not healthy():
  print("V8_VPS_RESULT "+json.dumps({"changed":changes,"blocker":"V1_FRESH_FOUR_ROLE_GUARD_FAILED","after":inventory()}),flush=True);return
 start=prop(KEEP,"ExecMainStartTimestampMonotonic")
 live_dep=prop(KEEP,"Requires").split()+prop(KEEP,"Wants").split()
 live_paths=[str((ROOT/"btc-m1.sqlite").resolve()),str(ROOT.resolve())]
 env=Path("/etc/rizan-bootstrap125-bridge.env")
 if env.exists():
  for l in env.read_text().splitlines():
   if l.startswith(("BOOT125_BTC_SEED=","BOOT125_STATE_DIR=")):
    live_paths.append(str(Path(l.split("=",1)[1].strip("'\"")).resolve()))
 for unit,dirs in LEGACY.items():
  old=info(unit)
  if old["active"]!="active" and old["enabled"]!="enabled":skipped[unit]="already_inactive_or_disabled";continue
  if unit in live_dep or prop(unit,"RequiredBy").strip() or prop(unit,"BoundBy").strip():skipped[unit]="dependency";continue
  if any(any(d in p or str(Path(d).name) in p for p in live_paths) for d in dirs):skipped[unit]="live_data_dependency";continue
  if old["pid"]:
   ss=run(["ss","-H","-tnp","state","established"],False)
   if re.search(r"pid="+str(old["pid"])+r"(?=[,)])",ss):skipped[unit]="established_socket";continue
  try:paths,why=validate_old(dirs)
  except Exception:paths,why=None,"checkpoint_unreadable"
  if why:skipped[unit]=why;continue
  backup=Path("/var/backups/rizan-retired-v8")/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")/unit
  backup.mkdir(parents=True,mode=0o700)
  for p in paths:
   with ro(p) as src,sqlite3.connect(backup/(p.parent.name+".sqlite")) as dst:src.backup(dst)
   (backup/(p.parent.name+".sqlite")).chmod(0o600)
  try:
   run(["systemctl","disable","--now",unit])
   if prop(unit,"ActiveState")!="inactive" or not healthy() or prop(KEEP,"ExecMainStartTimestampMonotonic")!=start:raise RuntimeError("retirement_guard")
  except Exception:
   if old["enabled"]=="enabled":run(["systemctl","enable",unit],False)
   if old["active"]=="active":run(["systemctl","start",unit],False)
   skipped[unit]="rolled_back";continue
  changes.append({"unit":unit,"memory_before_MiB":old["memory_MiB"],"after":info(unit),"checkpoint_backup_preserved":True})
 print("V8_VPS_RESULT "+json.dumps({"changed":changes,"skipped":skipped,"v1_healthy":healthy(),"v1_not_restarted":prop(KEEP,"ExecMainStartTimestampMonotonic")==start,"after":inventory(),"checkpoints_deleted":False,"orders":0}),flush=True)
if __name__=="__main__":main()
