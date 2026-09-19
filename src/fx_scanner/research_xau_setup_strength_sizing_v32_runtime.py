from __future__ import annotations

import json,os
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd
import dukascopy_python
from dukascopy_python import instruments

from .models import Bar
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_setup_strength_sizing_v32 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v32
from .storage.supabase_operational import SupabaseOperationalStore

UTC=timezone.utc
WORKER_NAME="dukascopy_xau_setup_strength_sizing_v32"
ERAS={
    "2012_2018":{"fetch_start":datetime(2010,1,1),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2019,1,1,tzinfo=UTC)},
    "2019_2024":{"fetch_start":datetime(2017,1,1),"start":datetime(2019,1,1,tzinfo=UTC),"end":datetime(2025,1,1,tzinfo=UTC)},
    "2025_2026":{"fetch_start":datetime(2023,1,1),"start":datetime(2025,1,1,tzinfo=UTC),"end":datetime(2026,9,1,tzinfo=UTC)},
}

BROKER_SPEC=BrokerLotSpec(
    lot_size_cents=10000,min_volume_cents=100,max_volume_cents=200000,
    step_volume_cents=100,expected_margin_001_usd=145.94,
    margin_money_digits=2,reference_price=4377.83,
)
LEVERAGE_TIERS=(LeverageTier(max_usd_volume=100000.0,leverage=500.0),)
CURRENT_STRESS_COSTS=M15ResearchCosts(
    spread_pips=37.0,slippage_pips=0.2,
    commission_pips_round_trip=0.2,swap_pips_per_day=0.0,
).stressed(spread_multiplier=1.25,slippage_multiplier=1.50)


def _normalize(raw):
    x=raw.copy().reset_index()
    cols={str(c).lower():c for c in x.columns}
    tcol=cols.get("timestamp") or cols.get("time") or x.columns[0]
    out=pd.DataFrame()
    out["time"]=pd.to_datetime(x[tcol],utc=True,errors="coerce")
    for c in ("open","high","low","close"):
        out[c]=pd.to_numeric(x[cols[c]],errors="coerce")
    return out.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)


def _fetch(era):
    raw=dukascopy_python.fetch(
        instrument=instruments.INSTRUMENT_FX_METALS_XAU_USD,
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=era["fetch_start"],
        end=era["end"].replace(tzinfo=None),
        max_retries=3,
    )
    df=_normalize(raw)
    return tuple(
        Bar(
            symbol="XAUUSD",timeframe="H1",timestamp=row.time.to_pydatetime(),
            open=float(row.open),high=float(row.high),low=float(row.low),close=float(row.close),
            tick_count=1,spread_avg=0.0,spread_max=0.0,
        )
        for row in df.itertuples(index=False)
    )


def run()->int:
    era_id=os.environ.get("V32_ERA","").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V32_ERA_INVALID:{era_id}")
    era=ERAS[era_id]
    bars=_fetch(era)
    decision=evaluate_v32(
        bars,era_id=era_id,era_start=era["start"],era_end=era["end"],
        costs=CURRENT_STRESS_COSTS,pip_size=0.01,
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,
    )
    details={
        "research_version":RESEARCH_VERSION,
        "environment":"PUBLIC_HISTORY_PLUS_BROKER_SNAPSHOT",
        "policy_effect":"SHADOW_ONLY",
        "execution_influence":False,
        "observed_at":datetime.now(tz=UTC).isoformat(),
        "data_source":"Dukascopy Bank public BID H1 via dukascopy-python",
        "decision":decision,
    }
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            f"{WORKER_NAME}_{era_id}",healthy=True,lag_seconds=0.0,details=details
        )
    except Exception as exc:
        details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"

    path=Path(os.getenv("V32_EVIDENCE_OUTPUT",f"artifacts/xau-setup-strength-sizing-v32-{era_id}.json"))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},
                               indent=2,sort_keys=True,default=str)+"\n")
    diag=decision["score_diagnostics"]
    print(
        "V32_RESULT "
        f"era={era_id} trades={decision['scored_trades']} monotonic={int(diag['monotonic_expectancy'])} "
        f"high_low_delta={diag['high_minus_low_expectancy_r']} "
        f"flex_supported={int(decision['decision_gate']['flexible_sizing_supported'])} artifact={path}"
    )
    for label,b in diag["buckets"].items():
        print(
            "V32_BUCKET "
            f"era={era_id} bucket={label} n={b['trades']} pf={b['profit_factor']} "
            f"exp={b['expectancy_r']} netr={b['net_r']}"
        )
    for map_id,p in decision["cash_paths"].items():
        print(
            "V32_PATH "
            f"era={era_id} map={map_id} opened={p['opened_trades']} skipped={p['skipped_margin_guard']} "
            f"ending={p['ending_balance_usd']} minbal={p['minimum_realized_balance_usd']} "
            f"ddpct={p['max_realized_drawdown_pct']} hit1000={int(p['hit_1000'])} "
            f"hit1000at={p['hit_1000_at']} ruin={int(p['ruin'])} "
            f"desired={json.dumps(p['desired_lot_distribution'],sort_keys=True)} "
            f"actual={json.dumps(p['actual_lot_distribution'],sort_keys=True)}"
        )
    return 0


if __name__=="__main__": raise SystemExit(run())
