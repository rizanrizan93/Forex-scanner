from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch, _metric_line
from .research_xau_v47_gvz_implied_vol_v75 import (
    ARTIFACT_CONTRACT,
    FULL_END,
    FULL_START,
    RESEARCH_VERSION,
    availability_timestamp,
    evaluate_v75,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_v47_gvz_implied_vol_v75"
GVZ_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GVZCLS"
FULL_ERA = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": FULL_START,
    "end": FULL_END,
}


def _fetch_gvz() -> tuple[list[tuple[datetime, float]], str, int]:
    request = Request(
        GVZ_URL,
        headers={"User-Agent": "ForexScannerResearch-V75/1.0"},
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[tuple[datetime, float]] = []
    for row in reader:
        date_raw = row.get("DATE") or row.get("observation_date")
        value_raw = row.get("GVZCLS")
        if not date_raw or value_raw in (None, "", "."):
            continue
        day = datetime.strptime(str(date_raw), "%Y-%m-%d").replace(tzinfo=UTC)
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            continue
        if value <= 0.0:
            continue
        rows.append((availability_timestamp(day), value))
    if not rows:
        raise RuntimeError("V75_GVZ_DOWNLOAD_EMPTY")
    rows.sort(key=lambda x: x[0])
    return rows, digest, len(raw)


def run() -> int:
    bars = _fetch(FULL_ERA)
    gvz_rows, gvz_sha256, gvz_bytes = _fetch_gvz()
    decision = evaluate_v75(
        bars,
        gvz_rows=gvz_rows,
        pip_size=0.01,
        cost_scenarios=COST_SCENARIOS,
    )
    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "PUBLIC_HISTORY",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "promotion_eligible": False,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "price_data_source": "Dukascopy Bank public BID M15 via dukascopy-python",
        "gvz_source": GVZ_URL,
        "gvz_source_sha256": gvz_sha256,
        "gvz_source_bytes": gvz_bytes,
        "decision": decision,
    }
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(os.getenv("V75_EVIDENCE_OUTPUT", "artifacts/xau-v47-gvz-implied-vol-v75.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    print(
        f"V75_RESULT bars={len(bars)} gvz_rows={len(gvz_rows)} "
        f"gvz_sha256={gvz_sha256} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, payload in decision["scenarios"].items():
        print(
            f"V75_COST cost={cost_id} "
            f"satellite={_metric_line(payload['satellite']['metrics'])}"
        )
        for window, row in payload["diagnostic_windows"].items():
            print(
                f"V75_WINDOW cost={cost_id} window={window} "
                f"all={_metric_line(row['all']['metrics'])} "
                f"geometry={row['winner_loser_geometry']}"
            )
            for state, stats in row["gvz_states"].items():
                if int(stats["trades"]) > 0:
                    print(
                        f"V75_GVZ cost={cost_id} window={window} state={state} "
                        f"{_metric_line(stats['metrics'])}"
                    )
            for bucket, stats in row["stop_to_implied_1d"].items():
                if int(stats["trades"]) > 0:
                    print(
                        f"V75_STOP_IV cost={cost_id} window={window} bucket={bucket} "
                        f"{_metric_line(stats['metrics'])}"
                    )
            for bucket, stats in row["target_to_implied_1d"].items():
                if int(stats["trades"]) > 0:
                    print(
                        f"V75_TARGET_IV cost={cost_id} window={window} bucket={bucket} "
                        f"{_metric_line(stats['metrics'])}"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
