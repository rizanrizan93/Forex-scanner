"""Read-only search for original research files. Writes copies only beneath the supplied temporary output."""
from pathlib import Path
import os,re,json,hashlib,zipfile,gzip,shutil,sys,datetime
EXACT={'RIZAN_XAU_COMPRESSION_FROZEN_20261030.zip','RIZAN_XAU_TARGET_2B_DD60_RESULTS.zip'}
NEEDLES=['1114218301','63.66304388135381','COMP_R3','RIZAN_XAU_TARGET_2B_DD60_RESULTS','RIZAN_XAU_COMPRESSION_FROZEN_20261030']
PRUNE={'.git','.ssh','.cache','.local','.venv','venv','node_modules','rizan-ticks','ticks','__pycache__','site-packages','bin','obj'}
def main():
 out=Path(sys.argv[1]);assert re.fullmatch(r'/tmp/rizan-compression-recovery\.[A-Za-z0-9]+/evidence',str(out));out.mkdir(mode=0o700)
 roots=[Path('/home/Rizanrizan')]+list(Path('/opt').glob('rizan*'))+list(Path('/var/backups').glob('rizan*'))+list(Path('/tmp').glob('rizan*'))
 hits=[];copied=[];scanned=0;total=0;limited=False
 for root in roots:
  if not root.is_dir() or out.parent==root or str(root)=='/opt/rizan-compression-bridge':continue
  for folder,dirs,files in os.walk(root,followlinks=False):
   dirs[:]=[d for d in dirs if d not in PRUNE and not d.startswith('.') and len(Path(folder).relative_to(root).parts)<7]
   for name in files:
    p=Path(folder)/name;scanned+=1
    if scanned>150000:limited=True;break
    low=str(p).lower()
    if any(v in name.lower() for v in ['token','secret','credential','password','.env','.pem','private_key','known_hosts']):continue
    if p.is_symlink():continue
    if not any(v in low for v in ['research','replay','compression','frozen','backup','20261030','xau_entry']):continue
    if not (name in EXACT or re.search(r'\.(zip|json|json\.gz|py|cs|md|log|txt|bak|old)$',name,re.I)):continue
    try:
     stat=p.stat();match=[];members=[]
     if name in EXACT:match.append('EXACT_ORIGINAL_FILENAME')
     if name.lower().endswith('.zip') and stat.st_size<150*1024**2:
      with zipfile.ZipFile(p) as z:
       members=[n for n in z.namelist() if n.rsplit('/',1)[-1] in EXACT or ('20261030' in n and any(v in n.lower() for v in ['compression','comp_r3','target_2b']))]
      if members:match.append('ARCHIVE_MEMBER_NAME')
     elif stat.st_size<8*1024**2:
      text=(gzip.open(p,'rt',errors='replace').read(512*1024) if name.endswith('.gz') else p.read_text(errors='replace'));match.extend(n for n in NEEDLES if n in text)
      if not match and p.suffix in ['.py','.cs'] and 'compression' in text.lower() and stat.st_mtime>=1793232000:match.append('RECENT_COMPRESSION_SOURCE_UNVERIFIED')
     if not match:continue
     h=hashlib.file_digest(p.open('rb'),'sha256').hexdigest();item=dict(path=str(p),bytes=stat.st_size,sha256=h,mtime_utc=datetime.datetime.fromtimestamp(stat.st_mtime,datetime.timezone.utc).isoformat(),matches=match,members=members[:30],original_identity_verified=False)
     hits.append(item)
     # The unchanged original archives or small source/config candidates can be reviewed privately.
     if stat.st_size<=64*1024**2 and total+stat.st_size<=128*1024**2 and (name in EXACT or p.suffix in ['.py','.cs','.json']):
      if p.suffix in ['.py','.cs','.json']:
       text=p.read_text(errors='replace')
       if re.search(r'(?:token|secret|password|private_key)[\"\x27]?\s*[=:]\s*[\"\x27][A-Za-z0-9_\-]{24,}',text,re.I):item['copy_withheld']='CREDENTIAL_ASSIGNMENT_DETECTED';continue
      dst=out/(str(len(copied)).zfill(3)+'_'+name);shutil.copyfile(p,dst);copied.append(dict(source=str(p),file=dst.name,sha256=h));total+=stat.st_size
    except (OSError,ValueError,zipfile.BadZipFile):continue
   if limited:break
  if limited:break
 report=dict(read_only=True,live_services_changed=False,original_strategy_activated=False,roots=[str(p) for p in roots],scanned_files=scanned,scan_limit_reached=limited,hits=hits,copied=copied)
 (out/'RECOVERY_REPORT.json').write_text(json.dumps(report,indent=2));print('RECOVERY_REPORT='+json.dumps(report,separators=(',',':')))
if __name__=='__main__':main()
