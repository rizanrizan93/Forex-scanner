import sys,json,csv
from pathlib import Path
r=Path(__file__).resolve().parent;sys.path.insert(0,str(r/'bridge'))
from server import Feed,SEED_END
f=Feed(r/'bootstrap/BITSTAMP_H1_SEED.csv');(r/'checks/feed.json').write_text(f.wire(SEED_END))
print("feed bytes", (r/"checks/feed.json").stat().st_size)
