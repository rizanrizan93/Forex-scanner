from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_event_supply_demand_post_v193 import oos_signal_rows
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_reaction_v193_full"
CONTRACT = "XAU_EVENT_REACTION_V193_FINAL_1"

MIN_SD_COVERAGE = 0.90
MIN_EVALUATED = 100


def _load_base(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if str(payload.get("decision") or "") != "REACTION_BACKFILL_WALKFORWARD_READY":
        raise RuntimeError(
            "V193 finalizer requires REACTION_BACKFILL_WALKFORWARD_READY base artifact"
        )
    return payload


def _load_sd_shards(directory: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    shards: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("xau-event-sd-v193-*.json")):
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        shard_rows = [dict(row) for row in payload.get("rows") or []]
        rows.extend(shard_rows)
        shards.append(
            {
                "year": payload.get("year"),
                "signal_count": payload.get("signal_count"),
                "evaluated_count": payload.get("evaluated_count"),
                "error_count": payload.get("error_count"),
                "coverage": payload.get("coverage"),
                "artifact": str(path),
            }
        )
    rows.sort(key=lambda row: str(row.get("scheduled_at") or ""))
    return rows, shards


def _accuracy(rows: list[dict[str, Any]]) -> float | None:
    eligible = [
        bool(row["prediction_correct"])
        for row in rows
        if row.get("prediction_correct") is not None
    ]
    if not eligible:
        return None
    return sum(eligible) / len(eligible)


def finalize(
    *,
    base: dict[str, Any],
    sd_rows: list[dict[str, Any]],
    shards: list[dict[str, Any]],
) -> dict[str, Any]:
    reactions = [dict(row) for row in base.get("reactions") or []]
    signals = oos_signal_rows(reactions)
    expected = len(signals)
    evaluated = len(sd_rows)
    coverage = None if expected == 0 else evaluated / expected

    state_counts = Counter(str(row.get("sd_alignment") or "UNKNOWN") for row in sd_rows)
    aligned = [row for row in sd_rows if row.get("sd_alignment") == "ALIGNED"]
    opposed = [row for row in sd_rows if row.get("sd_alignment") == "OPPOSED"]
    no_path = [
        row for row in sd_rows
        if row.get("sd_alignment") == "NO_ACTIVE_SD_DIRECTION"
    ]

    years_expected = sorted(
        {
            int(row.get("test_year"))
            for row in signals
            if row.get("test_year") is not None
        }
    )
    years_present = sorted(
        {
            int(row.get("test_year"))
            for row in sd_rows
            if row.get("test_year") is not None
        }
    )

    parity_gate = dict(base.get("parity_gate") or {})
    parity_ok = bool(parity_gate.get("passed"))

    decision = (
        "FULL_BACKFILL_RESEARCH_READY"
        if str(base.get("decision") or "") == "REACTION_BACKFILL_WALKFORWARD_READY"
        and expected > 0
        and evaluated >= MIN_EVALUATED
        and coverage is not None
        and coverage >= MIN_SD_COVERAGE
        and years_present == years_expected
        and parity_ok
        else "POST_WALKFORWARD_SD_OR_PARITY_INCOMPLETE"
    )

    return {
        **base,
        "artifact_contract": CONTRACT,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "research_stage": "REACTION_WALKFORWARD_PLUS_POST_SD_PLUS_PARITY",
        "supply_demand_conditioning": "POST_WALK_FORWARD_DIAGNOSTIC_COMPLETE",
        "sd_diagnostic": {
            "scheme": "FAMILY_SURPRISE_MARKET_STRUCTURE",
            "expected_oos_signals": expected,
            "evaluated_oos_signals": evaluated,
            "coverage": coverage,
            "years_expected": years_expected,
            "years_present": years_present,
            "state_counts": dict(sorted(state_counts.items())),
            "baseline_accuracy_on_evaluated": _accuracy(sd_rows),
            "aligned_accuracy": _accuracy(aligned),
            "opposed_accuracy": _accuracy(opposed),
            "no_active_path_accuracy": _accuracy(no_path),
            "aligned_n": len(aligned),
            "opposed_n": len(opposed),
            "no_active_path_n": len(no_path),
            "interpretation": (
                "Post-walk-forward Supply/Demand is diagnostic only. "
                "It was attached after an OOS historical prior existed and is not "
                "promotion-eligible evidence. Prospective shadow validation remains required."
            ),
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        },
        "sd_shards": shards,
        "decision": decision,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    base_path = Path(
        os.getenv(
            "XAU_V193_FULL_ARTIFACT",
            "/tmp/v193-base/xau-event-reaction-v193-full.json",
        )
    )
    shard_dir = Path(os.getenv("XAU_V193_SD_SHARD_DIR", "/tmp/v193-sd"))
    output = Path(
        os.getenv(
            "XAU_V193_FINAL_OUTPUT",
            "artifacts/xau-event-reaction-v193-final.json",
        )
    )
    if not base_path.exists():
        raise SystemExit(f"XAU_V193_FULL_ARTIFACT_NOT_FOUND:{base_path}")

    base = _load_base(base_path)
    sd_rows, shards = _load_sd_shards(shard_dir)
    artifact = finalize(base=base, sd_rows=sd_rows, shards=shards)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False, default=str)
        + "\n"
    )

    summary = {
        "contract": CONTRACT,
        "observed_at": artifact["observed_at"],
        "decision": artifact["decision"],
        "year_min": artifact.get("year_min"),
        "year_max": artifact.get("year_max"),
        "reaction_count": artifact.get("reaction_count"),
        "walk_forward_summary": artifact.get("walk_forward_summary"),
        "era_summary": artifact.get("era_summary"),
        "parity_gate": artifact.get("parity_gate"),
        "sd_diagnostic": artifact.get("sd_diagnostic"),
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    healthy = artifact["decision"] == "FULL_BACKFILL_RESEARCH_READY"
    SupabaseOperationalStore.from_env().write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=summary,
    )
    print(
        "XAU_EVENT_REACTION_V193_FINAL "
        f"decision={artifact['decision']} "
        f"reactions={artifact.get('reaction_count')} "
        f"sd_evaluated={artifact['sd_diagnostic']['evaluated_oos_signals']} "
        f"sd_coverage={artifact['sd_diagnostic']['coverage']} "
        f"parity_passed={int(bool(dict(artifact.get('parity_gate') or {}).get('passed')))} "
        "execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
