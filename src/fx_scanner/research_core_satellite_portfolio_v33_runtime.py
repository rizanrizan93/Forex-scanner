from __future__ import annotations

import json,os
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd
import dukascopy_python
from dukascopy_python import instruments

from .models import Bar
from .research_core_satellite_portfolio_v33 import ARTIFACT_CONTRACT,RESEARCH_VERSION,SPECS,evaluate_v33
from .storage.supabase_operational import SupabaseOperationalStore

UTC=timezone.utc
WORKER_NAME="dukascopy_core_satellite_portfolio_v33"

ERAS={
    "2012_2018":{"fetch_start":datetime(2010,1,1),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2019,1,1,tzinfo=UTC)},
    "2019_2024":{"fetch_start":datetime(2017,1,1),"start":datetime(2019,1,1,tzinfo=UTC),"end":datetime(2025,1,1,tzinfo=UTC)},
    "2025_2026":{"fetch_start":datetime(2023,1,1),"start":datetime(2025,1,1,tzinfo=UTC),"end":datetime(2026,9,1,tzinfo=UTC)},
}

INSTRUMENTS={
    "XAUUSD":instruments.INSTRUMENT_FX_METALS_XAU_USD,
    "AUDJPY":instruments.INSTRUMENT_FX_CROSSES_AUD_JPY,
    "GBPJPY":instruments.INSTRUMENT_FX_CROSSES_GBP_JPY,
    "CADJPY":instruments.INSTRUMENT_FX_CROSSES_CAD_JPY,
    "USDCAD":instruments.INSTRUMENT_FX_MAJORS_USD_CAD,
}


def _normalize(raw):
    x=raw.copy().reset_index(); cols={str(c).lower():c for c in x.columns}
    tcol=cols.get("timestamp") or cols.get("time") or x.columns[0]
    out=pd.DataFrame(); out["time"]=pd.to_datetime(x[tcol],utc=True,errors="coerce")
    for c in ("open","high","low","close"):
        out[c]=pd.to_numeric(x[cols[c]],errors="coerce")
    return out.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)


def _fetch(symbol,era):
    raw=dukascopy_python.fetch(
        instrument=INSTRUMENTS[symbol],interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,start=era["fetch_start"],
        end=era["end"].replace(tzinfo=None),max_retries=3,
    )
    df=_normalize(raw)
    return tuple(
        Bar(symbol=symbol,timeframe="H1",timestamp=row.time.to_pydatetime(),
            open=float(row.open),high=float(row.high),low=float(row.low),close=float(row.close),
            tick_count=1,spread_avg=0.0,spread_max=0.0)
        for row in df.itertuples(index=False)
    )


def run()->int:
    era_id=os.environ.get("V33_ERA","").strip()
    if era_id not in ERAS: raise SystemExit(f"V33_ERA_INVALID:{era_id}")
    era=ERAS[era_id]
    datasets={symbol:_fetch(symbol,era) for symbol in SPECS}
    decision=evaluate_v33(
        datasets,era_id=era_id,era_start=era["start"],era_end=era["end"]
    )
    details={
        "research_version":RESEARCH_VERSION,"environment":"PUBLIC_HISTORY",
        "policy_effect":"SHADOW_ONLY","execution_influence":False,
        "observed_at":datetime.now(tz=UTC).isoformat(),
        "data_source":"Dukascopy Bank public BID H1 via dukascopy-python",
        "coverage":{s:{"rows":len(v),"start":v[0].timestamp.isoformat(),"end":v[-1].timestamp.isoformat()} for s,v in datasets.items()},
        "decision":decision,
    }
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            f"{WORKER_NAME}_{era_id}",healthy=True,lag_seconds=0.0,details=details
        )
    except Exception as exc:
        details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"

    path=Path(os.getenv("V33_EVIDENCE_OUTPUT",f"artifacts/core-satellite-portfolio-v33-{era_id}.json"))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},
                               indent=2,sort_keys=True,default=str)+"\n")
    print(f"V33_RESULT era={era_id} artifact={path} promotion_eligible=0")
    for symbol,p in decision["symbol_results"].items():
        m=p["metrics"]
        print(
            "V33_SYMBOL "
            f"era={era_id} symbol={symbol} strategy={p['strategy_id']} n={m['trades']} "
            f"pf={m['profit_factor']} exp={m['expectancy_r']} netr={m['net_r']} dd={m['max_dd_r']}"
        )
    for pid,p in decision["portfolio_results"].items():
        m=p["metrics"]; f=p["frequency"]
        print(
            "V33_PORTFOLIO "
            f"era={era_id} id={pid} n={m['trades']} pf={m['profit_factor']} "
            f"exp={m['expectancy_r']} netr={m['net_r']} dd={m['max_dd_r']} "
            f"mean_day={f['mean_trades_per_day']} ge1={f['days_ge_1_fraction']} "
            f"max_active={p['max_active_positions']}"
        )
    return 0


if __name__=="__main__": raise SystemExit(run())
