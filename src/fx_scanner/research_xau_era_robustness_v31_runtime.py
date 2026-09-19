from __future__ import annotations

import json,os
from datetime import datetime,timezone
from pathlib import Path

import pandas as pd
import dukascopy_python
from dukascopy_python import instruments

from .models import Bar
from .research_xau_era_robustness_v31 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_era
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .storage.supabase_operational import SupabaseOperationalStore

UTC=timezone.utc
WORKER_NAME="dukascopy_xau_era_robustness_v31"

ERAS={
    "2012_2018":{
        "fetch_start":datetime(2011,1,1,tzinfo=UTC),
        "start":datetime(2012,1,1,tzinfo=UTC),
        "end":datetime(2019,1,1,tzinfo=UTC),
    },
    "2019_2024":{
        "fetch_start":datetime(2018,1,1,tzinfo=UTC),
        "start":datetime(2019,1,1,tzinfo=UTC),
        "end":datetime(2025,1,1,tzinfo=UTC),
    },
}

# Snapshot verified by V24 broker evidence on 2026-09-19.
BROKER_SPEC=BrokerLotSpec(
    lot_size_cents=10000,
    min_volume_cents=100,
    max_volume_cents=200000,
    step_volume_cents=100,
    expected_margin_001_usd=145.94,
    margin_money_digits=2,
    reference_price=4377.83,
)
LEVERAGE_TIERS=(LeverageTier(max_usd_volume=100000.0,leverage=500.0),)

# Mirrors the V24 current-broker cost proxy: 37 pips spread + configured
# slippage/commission; stressed spread 1.25x and slippage 1.50x.
BASE_COSTS=M15ResearchCosts(
    spread_pips=37.0,
    slippage_pips=0.2,
    commission_pips_round_trip=0.2,
    swap_pips_per_day=0.0,
)
STRESSED_COSTS=BASE_COSTS.stressed(spread_multiplier=1.25,slippage_multiplier=1.50)


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
        interval=dukascopy_python.INTERVAL_MIN_15,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=era["fetch_start"].replace(tzinfo=None),
        end=era["end"].replace(tzinfo=None),
        max_retries=3,
    )
    df=_normalize(raw)
    return tuple(
        Bar(
            symbol="XAUUSD",timeframe="M15",timestamp=row.time.to_pydatetime(),
            open=float(row.open),high=float(row.high),low=float(row.low),close=float(row.close),
            tick_count=1,spread_avg=0.0,spread_max=0.0,
        )
        for row in df.itertuples(index=False)
    )


def run()->int:
    era_id=os.environ.get("V31_ERA","").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V31_ERA_INVALID:{era_id}")
    era=ERAS[era_id]
    bars=_fetch(era)
    decision=evaluate_era(
        bars,era_id=era_id,era_start=era["start"],era_end=era["end"],
        pip_size=0.01,base_costs=BASE_COSTS,stressed_costs=STRESSED_COSTS,
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,
    )
    details={
        "research_version":RESEARCH_VERSION,
        "environment":"PUBLIC_HISTORY_PLUS_BROKER_SNAPSHOT",
        "policy_effect":"SHADOW_ONLY",
        "execution_influence":False,
        "observed_at":datetime.now(tz=UTC).isoformat(),
        "data_source":"Dukascopy Bank public BID M15 via dukascopy-python",
        "cost_contract":{
            "base_total_pips_at_entry_ex_swap":37.4,
            "stress_total_pips_at_entry_ex_swap":46.75,
        },
        "decision":decision,
    }
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            f"{WORKER_NAME}_{era_id}",healthy=True,lag_seconds=0.0,details=details
        )
    except Exception as exc:
        details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"

    path=Path(os.getenv("V31_EVIDENCE_OUTPUT",f"artifacts/xau-era-robustness-v31-{era_id}.json"))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},
                               indent=2,sort_keys=True,default=str)+"\n")

    print(f"V31_RESULT era={era_id} rows={len(bars)} artifact={path} promotion_eligible=0")
    for pid,p in decision["portfolio_results"].items():
        m=p["metrics"]; c=p["cash_fixed_001"]
        lm=p["direction_metrics"]["long"]; sm=p["direction_metrics"]["short"]
        print(
            "V31_PORTFOLIO "
            f"era={era_id} id={pid} available={p['available_trades']} "
            f"pf={m['profit_factor']} exp={m['expectancy_r']} netr={m['gross_profit_r']-m['gross_loss_r']} "
            f"long_n={lm['completed_trades']} long_pf={lm['profit_factor']} long_exp={lm['expectancy_r']} "
            f"short_n={sm['completed_trades']} short_pf={sm['profit_factor']} short_exp={sm['expectancy_r']} "
            f"opened={c['opened_trades']} ending={c['ending_balance_usd']} minbal={c['minimum_realized_balance_usd']} "
            f"ddpct={c['max_realized_drawdown_pct']} hit1000={int(c['hit_1000'])} hit1000at={c['hit_1000_at']} "
            f"mean_day={c['mean_accepted_trades_per_day']} margin_skip={c['margin_skips']} guard_skip={c['stopout_guard_skips']}"
        )
    return 0


if __name__=="__main__": raise SystemExit(run())
