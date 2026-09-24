from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Sequence

from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_reaction_v193_full"
PARITY_WORKER = "ctrader_xau_event_parity_v193"
ARTIFACT_CONTRACT = "XAU_EVENT_REACTION_V193_FINAL_1"

MIN_SD_COVERAGE = 0.90


def _required_path(name: str) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise SystemExit(f"{name}_REQUIRED")
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"{name}_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    raw = os.getenv(
        "XAU_V193_FINAL_OUTPUT",
        "artifacts/xau-event-reaction-v193-final.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_V193_FINAL_OUTPUT_REQUIRED")
    return Path(raw)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _load_sd_rows(directory: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_cluster: dict[str, dict[str, Any]] = {}
    shards: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("xau-event-sd-v193-*.json")):
        payload = json.loads(path.read_text())
        year = payload.get("year")
        rows = list(payload.get("rows") or [])
        for raw in rows:
            row = dict(raw)
            cluster_id = str(row.get("cluster_id") or "")
            if cluster_id:
                by_cluster[cluster_id] = row
        shards.append(
            {
                "year": year,
                "decision": payload.get("decision"),
                "base_reaction_count": payload.get("base_reaction_count"),
                "conditioned_count": payload.get("conditioned_count"),
                "valid_supply_demand_count": payload.get("valid_supply_demand_count"),
                "supply_demand_coverage": payload.get("supply_demand_coverage"),
                "state_counts": payload.get("state_counts"),
                "artifact": str(path),
            }
        )
    return by_cluster, shards


def _valid_sd_state(state: Any) -> bool:
    value = str(state or "").upper()
    return value not in {
        "",
        "ATLAS_ERROR",
        "INSUFFICIENT_M15_FOR_ATLAS",
        "DEFERRED_POST_WALK_FORWARD",
    }


def _directional_stats(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        conditioning = dict(row.get("conditioning") or {})
        sd = dict(conditioning.get("supply_demand") or {})
        direction = str(sd.get("active_reaction_direction") or "NONE")
        source_timeframe = str(sd.get("source_timeframe") or "NONE")
        freshness = str(sd.get("source_freshness") or "NONE")
        value = row.get("r15m_atr")
        if value is None:
            continue
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            continue
        grouped[(direction, source_timeframe, freshness)].append(normalized)

    segments = []
    for key, values in sorted(grouped.items()):
        if not values:
            continue
        up = sum(v > 0 for v in values)
        down = sum(v < 0 for v in values)
        directional = up + down
        segments.append(
            {
                "active_reaction_direction": key[0],
                "source_timeframe": key[1],
                "source_freshness": key[2],
                "n": len(values),
                "historical_up_frequency_15m": (
                    None if directional == 0 else up / directional
                ),
                "historical_down_frequency_15m": (
                    None if directional == 0 else down / directional
                ),
                "median_r15m_atr": median(values),
                "median_abs_r15m_atr": median(abs(v) for v in values),
            }
        )
    return {
        "segments": segments,
        "interpretation": (
            "Post-walk-forward Supply/Demand conditioning diagnostics only. "
            "These frequencies are descriptive historical evidence, not calibrated "
            "probabilities and not execution authority."
        ),
    }


def _latest_parity(store: SupabaseOperationalStore) -> tuple[datetime | None, dict[str, Any]]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", PARITY_WORKER)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None, {}
    row = dict(rows[0])
    return _parse_dt(row.get("observed_at")), dict(row.get("details") or {})


def run() -> int:
    base_path = _required_path("XAU_V193_BASE_ARTIFACT")
    sd_dir = _required_path("XAU_V193_SD_SHARD_DIR")
    output = _output_path()

    base = json.loads(base_path.read_text())
    base_decision = str(base.get("decision") or "")
    reactions = [dict(row) for row in list(base.get("reactions") or [])]
    by_cluster, sd_shards = _load_sd_rows(sd_dir)

    merged: list[dict[str, Any]] = []
    matched = 0
    valid = 0
    state_counts: Counter[str] = Counter()
    missing_cluster_ids: list[str] = []

    for reaction in reactions:
        cluster_id = str(reaction.get("cluster_id") or "")
        sd_row = by_cluster.get(cluster_id)
        if sd_row is None:
            if cluster_id and len(missing_cluster_ids) < 50:
                missing_cluster_ids.append(cluster_id)
            merged.append(reaction)
            continue

        matched += 1
        conditioning = dict(reaction.get("conditioning") or {})
        sd = dict(sd_row.get("supply_demand") or {})
        conditioning["supply_demand"] = sd
        conditioning["strategic_bias_proxy"] = sd_row.get("strategic_bias_proxy")
        reaction["conditioning"] = conditioning
        state = str(sd.get("state") or "UNKNOWN")
        state_counts[state] += 1
        if _valid_sd_state(state):
            valid += 1
        merged.append(reaction)

    total = len(reactions)
    match_coverage = 0.0 if total == 0 else matched / total
    valid_coverage = 0.0 if total == 0 else valid / total

    store = SupabaseOperationalStore.from_env()
    parity_at, parity_details = _latest_parity(store)
    parity_result = dict(parity_details.get("result") or {})
    parity_decision = str(parity_result.get("decision") or "PARITY_MISSING")
    base_at = _parse_dt(base.get("observed_at"))
    parity_current = bool(
        parity_at is not None
        and base_at is not None
        and parity_at >= base_at
    )

    all_years = sorted(
        {
            int(shard["year"])
            for shard in sd_shards
            if shard.get("year") is not None
        }
    )
    expected_years = list(range(2012, datetime.now(tz=UTC).year + 1))
    years_complete = all_years == expected_years

    base_ready = base_decision == "REACTION_BACKFILL_WALKFORWARD_READY"
    sd_ready = (
        years_complete
        and match_coverage >= MIN_SD_COVERAGE
        and valid_coverage >= MIN_SD_COVERAGE
    )
    parity_ready = parity_current and parity_decision == "PARITY_DESCRIPTIVE_AVAILABLE"

    if not base_ready:
        decision = "BASE_REACTION_BACKFILL_NOT_READY"
    elif not sd_ready:
        decision = "SUPPLY_DEMAND_CONDITIONING_INCOMPLETE"
    elif not parity_ready:
        decision = "AWAIT_CURRENT_PARITY"
    else:
        decision = "FULL_BACKFILL_RESEARCH_READY"

    artifact = {
        **base,
        "artifact_contract": ARTIFACT_CONTRACT,
        "base_artifact_contract": base.get("artifact_contract"),
        "base_decision": base_decision,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "reactions": merged,
        "supply_demand_conditioning": {
            "shard_years": all_years,
            "expected_years": expected_years,
            "years_complete": years_complete,
            "matched_count": matched,
            "valid_count": valid,
            "reaction_count": total,
            "match_coverage": match_coverage,
            "valid_coverage": valid_coverage,
            "minimum_required_coverage": MIN_SD_COVERAGE,
            "state_counts": dict(state_counts),
            "missing_cluster_ids_sample": missing_cluster_ids,
            "shards": sd_shards,
            "diagnostics": _directional_stats(merged),
        },
        "parity_gate": {
            "worker": PARITY_WORKER,
            "observed_at": None if parity_at is None else parity_at.isoformat(),
            "current_for_base": parity_current,
            "decision": parity_decision,
            "coverage": parity_result.get("coverage"),
            "horizons": parity_result.get("horizons"),
        },
        "research_stage": "POST_WALK_FORWARD_SD_AND_PARITY_FINAL_GATE",
        "decision": decision,
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False, default=str)
        + "\n"
    )

    operationally_healthy = base_ready and sd_ready
    heartbeat = {
        "artifact_contract": ARTIFACT_CONTRACT,
        "observed_at": artifact["observed_at"],
        "decision": decision,
        "base_decision": base_decision,
        "reaction_count": total,
        "year_min": base.get("year_min"),
        "year_max": base.get("year_max"),
        "sd_match_coverage": match_coverage,
        "sd_valid_coverage": valid_coverage,
        "sd_years_complete": years_complete,
        "parity_decision": parity_decision,
        "parity_current_for_base": parity_current,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    store.write_heartbeat(
        WORKER_NAME,
        healthy=operationally_healthy,
        lag_seconds=0.0,
        details=heartbeat,
    )
    print(
        "XAU_EVENT_REACTION_V193_FINAL "
        f"base={base_decision} reactions={total} "
        f"sd_match={match_coverage:.4f} sd_valid={valid_coverage:.4f} "
        f"parity={parity_decision} current={int(parity_current)} "
        f"decision={decision} execution_authority=0"
    )
    # A parity insufficiency should not discard completed SD work. The final
    # decision remains fail-closed for prospective activation.
    return 0 if operationally_healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
