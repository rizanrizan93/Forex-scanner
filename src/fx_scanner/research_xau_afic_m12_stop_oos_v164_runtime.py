from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path

import dukascopy_python
from dukascopy_python import instruments

from .models import Bar
from .research_xau_hierarchical_regime_router_v35_runtime import _normalize
from .research_xau_afic_m12_stop_oos_v164 import evaluate_v164

UTC=timezone.utc
START=datetime(2023,1,1,tzinfo=UTC)
END=datetime(2025,1,1,tzinfo=UTC)

def _fetch_m1(start:datetime,end:datetime):
    raw=dukascopy_python.fetch(
        instrument=instruments.INSTRUMENT_FX_METALS_XAU_USD,
        interval=dukascopy_python.INTERVAL_MIN_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=start.replace(tzinfo=None),
        end=end.replace(tzinfo=None),
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
    rows=_fetch_m1(START,END)
    d=evaluate_v164(rows)
    p=Path(os.getenv("V164_OUTPUT","artifacts/xau-afic-m12-stop-oos-v164.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    print("V164_ROWS "+json.dumps({"m1_rows":len(rows),"confirmations":d["confirmation_count"]},sort_keys=True))
    for variant,x in d["summary"].items():
        print("V164_STOP "+json.dumps({"variant":variant,**x},sort_keys=True,default=str))
    print("V164_DECISION "+json.dumps({"diagnostic_only":True,"promotion":False,"observer_change":False},sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(run())
