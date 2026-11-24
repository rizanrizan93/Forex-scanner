"""Acquire pinned public XAU, no year-reset in later continuous wallet."""
import sys,json
from pathlib import Path
import numpy as np,pandas as pd
year=int(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(Path(sys.argv[3]).resolve()/"scripts"))
from snowball_s6_xau_grid import source
from snowball_s8_xau_2026_partial import acquire_2026
d,p=(acquire_2026(year) if year==2026 else source(year))
t=(d.index.asi8//60_000_000_000).astype("<i8")
t.tofile(out/"times.bin")
pd.DataFrame({"o":d.bo,"h":d.bh,"l":d.bl,"c":d.bc,"s":d.ao-d.bo}).to_numpy(dtype="<f8").tofile(out/"bars.bin")
(out/"provenance.json").write_text(json.dumps(p,indent=2))
print("DATA",year,len(t),d.index[0],d.index[-1],flush=True)
