"""Read exact running BTC feed implementation/seed; extend a separate in-memory instance only."""
import csv,hashlib,json,pathlib,subprocess,sys,time
out=pathlib.Path(sys.argv[1]);assert str(out).startswith('/home/Rizanrizan/rizan-ticks/REPLAY_RESULTS/october-order-readiness/');out.mkdir(parents=True,exist_ok=True)
wd=subprocess.run(['systemctl','show','rizan-btc7d130.service','--value','-p','WorkingDirectory'],capture_output=True,text=True,check=True).stdout.strip();sys.path.insert(0,wd)
from server import Feed
seed=pathlib.Path(wd)/'BITSTAMP_H1_SEED.csv';sha=hashlib.sha256(seed.read_bytes()).hexdigest();assert sha=='b8cc6dece79c77a2ad92c85f32cb37f45f5c003cc91910fe442c350fe7def4f4'
f=Feed(seed);f.update(time.time());wire=json.loads(f.wire(time.time()));dest=out/'BTC_H1.csv'
with dest.open('w',newline='') as z:w=csv.writer(z);w.writerow(['unix','open','high','low','close','count']);w.writerows(wire['bars'])
m={'read_only_production':True,'source_release':wd,'seed_csv_sha256':sha,'rows':len(wire['bars']),'through_unix':wire['through'],'csv_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()};(out/'BTC_FRESH_SEED_MANIFEST.json').write_text(json.dumps(m,indent=2));print(json.dumps(m))
