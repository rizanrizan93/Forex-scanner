from pathlib import Path
import hashlib,json,sys,zipfile
p=Path(sys.argv[1])
with zipfile.ZipFile(p) as z:
 names=z.namelist();assert len(names)==len(set(names));m=json.loads(z.read('SHA256_MANIFEST.json'))
 assert set(names)==set(m)|{'SHA256_MANIFEST.json'}
 for n,h in m.items():assert hashlib.sha256(z.read(n)).hexdigest()==h,n
 status=json.loads(z.read('FROZEN_STATUS.json'));assert not status['trading_enabled_default'];assert not status['dd56_qualified'];assert not status['live_deployed']
 print(json.dumps({'Pass':True,'members':len(names),'zip_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'binary_sha256':hashlib.sha256(z.read(status['binary'])).hexdigest(),'dd56_qualified':False,'default_off':True},indent=2))
