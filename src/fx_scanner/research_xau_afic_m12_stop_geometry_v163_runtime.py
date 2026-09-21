from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
import dukascopy_python
from dukascopy_python import instruments

from .models import Bar
from .research_xau_hierarchical_regime_router_v35_runtime import _normalize
from .research_xau_afic_m12_stop_geometry_v163 import evaluate_v163

UTC=timezone.utc
FETCH_START=datetime(2024,12,1,tzinfo=UTC)
END=datetime(2026,9,20,tzinfo=UTC)

def _fetch_m1():
    raw=dukascopy_python.fetch(
        instrument=instruments.INSTRUMENT_FX_METALS_XAU_USD,
        interval=dukascopy_python.INTERVAL_MIN_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=FETCH_START.replace(tzinfo=None),
        end=END.replace(tzinfo=None),
        max_retries=3,
    )
    df=_normalize(raw)
    return tuple(
        Bar(
            symbol="XAUUSD",timeframe="M1",
            timestamp=r.time.to_pydatetime(),
            open=float(r.open),high=float(r.high),low=float(r.low),close=float(r.close),
            tick_count=1,spread_avg=0.0,spread_max=0.0,
        ) for r in df.itertuples(index=False)
    )

def run():
    rows=_fetch_m1()
    d=evaluate_v163(rows,evaluation_end=END)
    p=Path(os.getenv("V163_OUTPUT","artifacts/xau-afic-m12-stop-geometry-v163.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    print("V163_ROWS "+json.dumps({"m1_rows":len(rows),"confirmations":d["confirmation_count"]},sort_keys=True))
    for window,variants in d["windows"].items():
        for variant,x in variants.items():
            print("V163_STOP "+json.dumps({"window":window,"variant":variant,**x},sort_keys=True,default=str))
    print("V163_DECISION "+json.dumps({"diagnostic_only":True,"promotion":False},sort_keys=True))
    return 0

if __name__=="__main__":raise SystemExit(run())
