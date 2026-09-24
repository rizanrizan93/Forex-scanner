from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_event_conditioning_v193 import (
    build_conditioning_frames,
    event_conditioning_from_frames,
)
from .research_xau_event_reaction_v193_year_runtime import _load_price

ARTIFACT_CONTRACT = "XAU_EVENT_SD_CONDITION_V193_YEAR_1"


def _year() -> int:
    year = int(os.getenv("XAU_V193_YEAR", "0") or 0)
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V193_YEAR_INVALID:{year}")
    return year


def _required_path(name: str) -> Path:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise SystemExit(f"{name}_REQUIRED")
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"{name}_NOT_FOUND:{path}")
    return path


def _output_path(year: int) -> Path:
    raw = os.getenv(
        "XAU_V193_SD_YEAR_OUTPUT",
        f"artifacts/xau-event-sd-v193-{year}.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_V193_SD_YEAR_OUTPUT_REQUIRED")
    return Path(raw)


def _event_year(row: dict[str, Any]) -> int | None:
    raw = row.get("scheduled_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).year
    except ValueError:
        return None


def _valid_sd_state(state: Any) -> bool:
    value = str(state or "").upper()
    return value not in {
        "",
        "ATLAS_ERROR",
        "INSUFFICIENT_M15_FOR_ATLAS",
        "DEFERRED_POST_WALK_FORWARD",
    }


def run() -> int:
    year = _year()
    base_path = _required_path("XAU_V193_BASE_ARTIFACT")
    price_path = _required_path("XAU_V193_PRICE_CSV")
    output_path = _output_path(year)

    base = json.loads(base_path.read_text())
    if str(base.get("decision") or "") != "REACTION_BACKFILL_WALKFORWARD_READY":
        raise SystemExit(
            "XAU_V193_SD_BASE_NOT_READY:"
            + str(base.get("decision") or "MISSING")
        )

    reactions = [
        dict(row)
        for row in list(base.get("reactions") or [])
        if _event_year(dict(row)) == year
    ]
    if not reactions:
        raise SystemExit(f"XAU_V193_SD_NO_BASE_REACTIONS:{year}")

    price = _load_price(price_path)
    frames = build_conditioning_frames(price.reset_index())

    conditioned: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    valid_count = 0

    for row in reactions:
        raw_at = str(row.get("scheduled_at") or "")
        if not raw_at:
            continue
        event_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        if event_at.tzinfo is None:
            continue
        result = event_conditioning_from_frames(
            frames,
            event_at=event_at.astimezone(UTC),
            supply_demand_lookback_days=90,
            include_supply_demand=True,
        )
        sd = dict(result.get("supply_demand") or {})
        state = str(sd.get("state") or "UNKNOWN")
        state_counts[state] += 1
        if _valid_sd_state(state):
            valid_count += 1

        conditioned.append(
            {
                "cluster_id": row.get("cluster_id"),
                "scheduled_at": raw_at,
                "family": row.get("family"),
                "supply_demand": sd,
                "strategic_bias_proxy": result.get("strategic_bias_proxy"),
                "execution_influence": False,
                "execution_authority": False,
            }
        )

    coverage = 0.0 if not reactions else valid_count / len(reactions)
    payload = {
        "artifact_contract": ARTIFACT_CONTRACT,
        "year": year,
        "base_artifact_contract": base.get("artifact_contract"),
        "base_observed_at": base.get("observed_at"),
        "base_reaction_count": len(reactions),
        "conditioned_count": len(conditioned),
        "valid_supply_demand_count": valid_count,
        "supply_demand_coverage": coverage,
        "state_counts": dict(state_counts),
        "rows": conditioned,
        "decision": (
            "SD_YEAR_CONDITIONING_READY"
            if coverage >= 0.90
            else "SD_YEAR_CONDITIONING_INSUFFICIENT"
        ),
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str)
        + "\n"
    )
    healthy = payload["decision"] == "SD_YEAR_CONDITIONING_READY"
    print(
        "XAU_EVENT_SD_CONDITION_V193_YEAR "
        f"year={year} reactions={len(reactions)} conditioned={len(conditioned)} "
        f"valid={valid_count} coverage={coverage:.4f} "
        f"decision={payload['decision']} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
