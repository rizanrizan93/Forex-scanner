"""Bounded VPS memory recovery. No broker API, credentials or strategy changes."""
import fcntl,json,os,re,shutil,sqlite3,subprocess,sys,time
from pathlib import Path
from datetime import datetime,timezone

OLD_UNITS=('rizan-r3-bridge.service','rizan-compression-bridge.service','rizan-tp500-bridge.service')
def emit(label,value):print(label+'='+json.dumps(value,allow_nan=False),flush=True)
def run(args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=30).stdout.strip()
def memory():
 values={k:int(v.strip().split()[0]) for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())}
 return {k:values[k] for k in ['MemTotal','MemAvailable','SwapTotal','SwapFree']}
def prop(unit,name):return run(['systemctl','show',unit,'--value','-p',name])
def idle_evidence(folder,now=None):
 now=time.time() if now is None else now
 report={'eligible':False,'folder':str(folder)}
 try:
  folder=Path(folder)
  if folder.is_symlink():raise ValueError('STATE_SYMLINK')
  h=json.loads((folder/'health.json').read_text());at=datetime.fromisoformat(h['observed_utc'].replace('Z','+00:00')).timestamp()
  report.update(health_age_seconds=round(now-at,2),connected=h.get('connected'))
  if not 0<=now-at<=90 or type(h.get('connected')) is not int or h['connected']!=0:raise ValueError('CONNECTED_OR_HEALTH_NOT_FRESH')
  with sqlite3.connect((folder/'checkpoints.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
   leases=db.execute('SELECT expires_at,touched_at FROM bridge_leases').fetchall()
   report['last_lease_age_seconds']=round(min((now-t for _,t in leases),default=1e9),2)
   if any(expiry>now or now-touched<120 for expiry,touched in leases):raise ValueError('RECENT_CLIENT_LEASE')
   count=0
   for raw, in db.execute('SELECT state FROM checkpoints'):
    state=json.loads(raw);count+=1
    if state.get('Basket') is not None or state.get('PendingLabel') or any(state.get(k,0) for k in ['PendingChildren','BatchRemaining','NativePendingSequence','Sending','ExitPending']):raise ValueError('RECORDED_EXPOSURE_OR_PENDING_INTENT')
   report['checkpoint_count']=count
  report.update(eligible=True,reason='FRESH_ZERO_PEERS_NO_RECENT_LEASE_NO_RECORDED_EXPOSURE')
 except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as e:report['reason']=str(e) if isinstance(e,ValueError) else type(e).__name__
 return report
def ensure_swap():
 before=memory();emit('MEMORY_BEFORE_KIB',before)
 target=Path('/var/lib/rizan-maintenance/swapfile')
 active={line.split()[0] for line in Path('/proc/swaps').read_text().splitlines()[1:]}
 created=False
 if before['SwapTotal']==0:
  if shutil.disk_usage('/var/lib').free<4*2**30:raise RuntimeError('INSUFFICIENT_DISK_FOR_SWAP')
  fs=run(['findmnt','-n','-o','FSTYPE','/'])
  if fs not in ['ext4','xfs']:raise RuntimeError('SWAP_FILESYSTEM_REQUIRES_REVIEW')
  if target.parent.is_symlink() or target.exists() or target.is_symlink():raise RuntimeError('EXISTING_SWAP_PATH_PRESERVED_REVIEW_REQUIRED')
  target.parent.mkdir(mode=0o700,exist_ok=True)
  fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
  run(['fallocate','-l','2G',str(target)])
  run(['mkswap',str(target)])
  run(['swapon',str(target)])
  active={line.split()[0] for line in Path('/proc/swaps').read_text().splitlines()[1:]}
  if str(target) not in active:raise RuntimeError('SWAP_ACTIVATION_NOT_CONFIRMED')
  created=True
 if str(target) in active:
  fstab=Path('/etc/fstab')
  if fstab.is_symlink():raise RuntimeError('FSTAB_SYMLINK_REQUIRES_REVIEW')
  text=fstab.read_text()
  if not any(line.split() and line.split()[0]==str(target) for line in text.splitlines() if not line.lstrip().startswith('#')):
   backup=Path('/var/lib/rizan-maintenance')/('fstab.before-swap-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
   shutil.copy2(fstab,backup)
   with fstab.open('a') as f:f.write(('' if not text or text.endswith('\n') else '\n')+str(target)+' none swap sw 0 0\n');f.flush();os.fsync(f.fileno())
 emit('SWAP_RECOVERY',{'created':created,'active':str(target) in active,'swap_kib':memory()['SwapTotal'],'existing_swap_preserved':not created})
def retire_idle():
 protected=['rizan-btc10-bridge.service','rizan-cbot-bridge.service','rizan-btc7d130.service','nginx.service']
 starts={u:prop(u,'ExecMainStartTimestampMonotonic') for u in protected}
 retired=[];record=[]
 for unit in OLD_UNITS:
  state_dir=prop(unit,'StateDirectory')
  if not re.fullmatch(r'rizan-[a-z0-9-]+',state_dir):emit('RETIRE_SKIPPED',{'unit':unit,'reason':'UNKNOWN_STATE_DIRECTORY'});continue
  evidence=idle_evidence(Path('/var/lib')/state_dir)
  if not evidence['eligible']:emit('RETIRE_SKIPPED',{'unit':unit,**evidence});continue
  enabled=subprocess.run(['systemctl','is-enabled',unit],text=True,capture_output=True,timeout=10).stdout.strip()
  item={'unit':unit,'enabled_before':enabled,'active_before':prop(unit,'ActiveState'),'evidence':evidence}
  record.append(item)
  receipt=Path('/var/lib/rizan-maintenance')/('retired-bridge-'+unit+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
  with receipt.open('x') as f:json.dump(item,f,indent=2);f.flush();os.fsync(f.fileno())
  run(['systemctl','stop',unit])
  if prop(unit,'ActiveState')!='inactive':raise RuntimeError('LEGACY_STOP_NOT_CONFIRMED')
  run(['systemctl','disable',unit]);retired.append(unit)
  emit('LEGACY_RETIRED',{'unit':unit,'checkpoint_files_preserved':True,'receipt':str(receipt),'active':prop(unit,'ActiveState')})
 for unit in protected:
  if prop(unit,'ExecMainStartTimestampMonotonic')!=starts[unit]:raise RuntimeError('PROTECTED_SERVICE_START_CHANGED')
 emit('PROTECTED_SERVICES_PRESERVED',{'units':protected,'starts_unchanged':True})
 return retired
def cpu_sample():
 def sample():return [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
 a=sample();time.sleep(1);b=sample();diff=[y-x for x,y in zip(a,b)];total=sum(diff)
 return {'busy_pct':round(100*(total-diff[3]-diff[4])/max(total,1),2),'iowait_pct':round(100*diff[4]/max(total,1),2)}
def main():
 if os.geteuid()!=0:raise RuntimeError('ROOT_REQUIRED')
 with open('/run/lock/rizan-memory-recovery.lock','w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  ensure_swap()
  for unit in OLD_UNITS:
   state_dir=prop(unit,'StateDirectory')
   report={'unit':unit,'active':prop(unit,'ActiveState'),'memory_current_bytes':prop(unit,'MemoryCurrent')}
   if re.fullmatch(r'rizan-[a-z0-9-]+',state_dir):report.update(idle_evidence(Path('/var/lib')/state_dir))
   else:report.update(eligible=False,reason='STATE_DIRECTORY_NOT_RECOGNIZED')
   emit('LEGACY_INVENTORY',report)
  retired=retire_idle() if '--retire-idle' in sys.argv[1:] else []
  emit('MEMORY_AFTER_KIB',memory());emit('CPU_SAMPLE',cpu_sample());emit('RECOVERY_COMPLETE',{'utc':datetime.now(timezone.utc).isoformat(),'strategy_changed':False,'broker_orders':0,'services_stopped':retired})
if __name__=='__main__':main()
