from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import dukascopy_python
import pandas as pd
from dukascopy_python import instruments

from .models import Bar
from .research_xau_hierarchical_regime_router_v35 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v35,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import BrokerLotSpec
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_hierarchical_regime_router_v35"

ERAS = {
    "2012_2018": {
        "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
        "start": datetime(2012, 1, 1, tzinfo=UTC),
        "end": datetime(2019, 1, 1, tzinfo=UTC),
    },
    "2019_2024": {
        "fetch_start": datetime(2018, 1, 1, tzinfo=UTC),
        "start": datetime(2019, 1, 1, tzinfo=UTC),
        "end": datetime(2025, 1, 1, tzinfo=UTC),
    },
    "2025_2026YTD": {
        "fetch_start": datetime(2024, 1, 1, tzinfo=UTC),
        "start": datetime(2025, 1, 1, tzinfo=UTC),
        "end": datetime(2026, 9, 20, tzinfo=UTC),
    },
}

BROKER_SPEC = BrokerLotSpec(
    lot_size_cents=10000,
    min_volume_cents=100,
    max_volume_cents=200000,
    step_volume_cents=100,
    expected_margin_001_usd=145.94,
    margin_money_digits=2,
    reference_price=4377.83,
)
LEVERAGE_TIERS = (LeverageTier(max_usd_volume=100000.0, leverage=500.0),)

# Cost sensitivity requested after V31. Values are total round-trip entry friction
# in XAU pips before swap: ~17, 35, 37.4 and 46.75.
COST_SCENARIOS = {
    "LOW_1700": M15ResearchCosts(
        spread_pips=16.6,
        slippage_pips=0.2,
        commission_pips_round_trip=0.2,
        swap_pips_per_day=0.0,
    ),
    "MID_3500": M15ResearchCosts(
        spread_pips=34.6,
        slippage_pips=0.2,
        commission_pips_round_trip=0.2,
        swap_pips_per_day=0.0,
    ),
    "V24_BASE_3740": M15ResearchCosts(
        spread_pips=37.0,
        slippage_pips=0.2,
        commission_pips_round_trip=0.2,
        swap_pips_per_day=0.0,
    ),
    "V24_STRESS_4675": M15ResearchCosts(
        spread_pips=37.0,
        slippage_pips=0.2,
        commission_pips_round_trip=0.2,
        swap_pips_per_day=0.0,
        spread_multiplier=1.25,
        slippage_multiplier=1.50,
    ),
}


def _normalize(raw):
    x = raw.copy().reset_index()
    cols = {str(c).lower(): c for c in x.columns}
    tcol = cols.get("timestamp") or cols.get("time") or x.columns[0]
    out = pd.DataFrame()
    out["time"] = pd.to_datetime(x[tcol], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        out[c] = pd.to_numeric(x[cols[c]], errors="coerce")
    return (
        out.dropna()
        .drop_duplicates("time")
        .sort_values("time")
        .reset_index(drop=True)
    )


def _fetch(era):
    raw = dukascopy_python.fetch(
        instrument=instruments.INSTRUMENT_FX_METALS_XAU_USD,
        interval=dukascopy_python.INTERVAL_MIN_15,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=era["fetch_start"].replace(tzinfo=None),
        end=era["end"].replace(tzinfo=None),
        max_retries=3,
    )
    df = _normalize(raw)
    return tuple(
        Bar(
            symbol="XAUUSD",
            timeframe="M15",
            timestamp=row.time.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            tick_count=1,
            spread_avg=0.0,
            spread_max=0.0,
        )
        for row in df.itertuples(index=False)
    )


def _metric_line(metric: dict) -> str:
    gp = float(metric.get("gross_profit_r") or 0.0)
    gl = float(metric.get("gross_loss_r") or 0.0)
    return (
        f"n={metric.get('completed_trades')} "
        f"pf={metric.get('profit_factor')} "
        f"exp={metric.get('expectancy_r')} "
        f"netr={gp-gl} "
        f"wr={metric.get('win_rate')} "
        f"ddr={metric.get('max_drawdown_r')}"
    )


def run() -> int:
    era_id = os.environ.get("V35_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V35_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)

    decision = evaluate_v35(
        bars,
        era_id=era_id,
        era_start=era["start"],
        era_end=era["end"],
        pip_size=0.01,
        cost_scenarios=COST_SCENARIOS,
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "PUBLIC_HISTORY_PLUS_BROKER_SNAPSHOT",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "promotion_eligible": False,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "data_source": "Dukascopy Bank public BID M15 via dukascopy-python",
        "decision": decision,
    }

    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            f"{WORKER_NAME}_{era_id}",
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(
        os.getenv(
            "V35_EVIDENCE_OUTPUT",
            f"artifacts/xau-hierarchical-regime-router-v35-{era_id}.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": details,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )

    print(
        f"V35_RESULT era={era_id} rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, scenario in decision["scenario_results"].items():
        print(
            f"V35_COST era={era_id} cost={cost_id} "
            f"m15_raw={scenario['m15_raw_trades']} "
            f"annotated={scenario['m15_context_annotated']}"
        )
        for portfolio_id, payload in scenario["portfolio_results"].items():
            line = _metric_line(payload["metrics"])
            cash = payload.get("cash_fixed_001")
            cash_text = ""
            if cash is not None:
                cash_text = (
                    f" ending={cash.get('ending_balance_usd')} "
                    f"ddpct={cash.get('max_realized_drawdown_pct')} "
                    f"opened={cash.get('opened_trades')}"
                )
            print(
                f"V35_PORTFOLIO era={era_id} cost={cost_id} "
                f"id={portfolio_id} {line}{cash_text}"
            )
        counter = scenario["diagnostics"]["countertrend_extended_h1_strict"]
        print(
            f"V35_COUNTERTREND era={era_id} cost={cost_id} "
            f"trades={counter['trades']} {_metric_line(counter['metrics'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
