from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import dukascopy_python
import pandas as pd
from dukascopy_python import instruments

from .models import Bar
from .research_xau_crossasset_leadlag_v39 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SOURCE_EUR,
    SOURCE_XAG,
    evaluate_v39,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    ERAS,
    LEVERAGE_TIERS,
    _fetch,
    _metric_line,
    _normalize,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_crossasset_leadlag_v39"


def _fetch_h1(era, *, instrument: str, symbol: str) -> tuple[Bar, ...]:
    raw = dukascopy_python.fetch(
        instrument=instrument,
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=era["fetch_start"].replace(tzinfo=None),
        end=era["end"].replace(tzinfo=None),
        max_retries=3,
    )
    df = _normalize(raw)
    return tuple(
        Bar(
            symbol=symbol,
            timeframe="H1",
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


def run() -> int:
    era_id = os.environ.get("V39_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V39_ERA_INVALID:{era_id}")
    era = ERAS[era_id]

    xau = _fetch(era)
    xag = _fetch_h1(
        era,
        instrument=instruments.INSTRUMENT_FX_METALS_XAG_USD,
        symbol=SOURCE_XAG,
    )
    eur = _fetch_h1(
        era,
        instrument=instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
        symbol=SOURCE_EUR,
    )
    decision = evaluate_v39(
        xau,
        xag_h1=xag,
        eur_h1=eur,
        era_id=era_id,
        era_start=era["start"],
        era_end=era["end"],
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
        "data_source": {
            "target": "Dukascopy Bank XAUUSD BID M15 via dukascopy-python",
            "xag_source": "Dukascopy Bank XAGUSD BID H1 via dukascopy-python",
            "eur_source": "Dukascopy Bank EURUSD BID H1 via dukascopy-python",
        },
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
            "V39_EVIDENCE_OUTPUT",
            f"artifacts/xau-crossasset-leadlag-v39-{era_id}.json",
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
        ) + "\n"
    )

    print(
        f"V39_RESULT era={era_id} xau={len(xau)} xag_h1={len(xag)} "
        f"eur_h1={len(eur)} trading_days={decision['trading_days']} "
        f"artifact={path} policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, scenario in decision["scenario_results"].items():
        for variant_id, payload in scenario["variants"].items():
            print(
                f"V39_VARIANT era={era_id} cost={cost_id} id={variant_id} "
                f"{_metric_line(payload['metrics'])} "
                f"tpd={payload['trades_per_day']} "
                f"loss_streak={payload['max_losing_streak']}"
            )
        if cost_id == "V24_STRESS_4675":
            for variant_id, payload in scenario["variants"].items():
                for bucket, diag in payload["diagnostics"]["source_strength"].items():
                    print(
                        f"V39_DIAG_STRENGTH era={era_id} id={variant_id} "
                        f"bucket={bucket} {_metric_line(diag['metrics'])} "
                        f"tpd={diag['trades_per_day']}"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
