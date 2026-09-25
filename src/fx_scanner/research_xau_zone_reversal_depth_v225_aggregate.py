from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_zone_reversal_depth_v225 import (
    ARTIFACT_CONTRACT,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    RESEARCH_VERSION,
    deserialize_episode,
    grouped_report,
    hierarchy_report,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "research_xau_zone_reversal_depth_v225"
ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


def _shard_dir() -> Path:
    raw = os.getenv("XAU_V225_SHARD_DIR", "/tmp/v225-shards").strip()
    if not raw:
        raise SystemExit("XAU_V225_SHARD_DIR_REQUIRED")
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"XAU_V225_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    raw = os.getenv(
        "XAU_V225_FULL_OUTPUT",
        "artifacts/xau-zone-reversal-depth-v225-full.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_V225_FULL_OUTPUT_REQUIRED")
    return Path(raw)


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows = []
    for file in sorted(path.rglob("xau-zone-reversal-depth-v225-*.json")):
        payload = json.loads(file.read_text())
        if "year" not in payload:
            continue
        rows.append(payload)
    rows.sort(key=lambda item: int(item["year"]))
    return rows


def _top_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for timeframe in ("H4", "H1", "M15"):
        tf = dict(report.get(timeframe) or {})
        for direction in ("ALL", "LONG", "SHORT"):
            summary = dict(tf.get(direction) or {})
            top = list(summary.get("highest_hazard_bands_min_n") or [])
            if not top:
                continue
            best = dict(top[0])
            internal = dict(summary.get("internal_geometry") or {})
            internal_top = list(internal.get("highest_hazard_bands_min_n") or [])
            internal_best = dict(internal_top[0]) if internal_top else {}
            output.append(
                {
                    "timeframe": timeframe,
                    "direction": direction,
                    "touches": summary.get("touches"),
                    "hold_rate": summary.get("hold_rate"),
                    "hold_wilson_lower_95": summary.get("hold_wilson_lower_95"),
                    "depth_coordinate": summary.get("coordinate"),
                    "depth_median": summary.get("depth_median"),
                    "depth_p25": summary.get("depth_p25"),
                    "depth_p75": summary.get("depth_p75"),
                    "highest_hazard_band": best.get("band"),
                    "band_hazard": best.get("hazard"),
                    "band_wilson_lower_95": best.get("wilson_lower_95"),
                    "band_at_risk": best.get("at_risk"),
                    "band_reversals": best.get("reversals"),
                    "internal_coordinate": internal.get("coordinate"),
                    "internal_depth_median": internal.get("depth_median"),
                    "internal_highest_hazard_band": internal_best.get("band"),
                    "internal_band_hazard": internal_best.get("hazard"),
                    "internal_band_at_risk": internal_best.get("at_risk"),
                }
            )
    return output


def run() -> int:
    observed_at = datetime.now(tz=UTC)
    shards = _load_shards(_shard_dir())
    if not shards:
        raise SystemExit("XAU_V225_NO_SHARDS")

    episodes = []
    yearly: dict[str, Any] = {}
    for shard in shards:
        year = int(shard["year"])
        yearly[str(year)] = {
            "zone_count": shard.get("zone_count"),
            "episode_count": shard.get("episode_count"),
            "summary": shard.get("summary"),
            "hierarchy": shard.get("hierarchy"),
        }
        for raw in list(shard.get("episodes") or []):
            episodes.append(deserialize_episode(dict(raw)))

    overall = grouped_report(episodes)
    hierarchy = hierarchy_report(episodes)
    eras: dict[str, Any] = {}
    for name, (start, end) in ERAS.items():
        selected = [
            row for row in episodes
            if start <= row.touch_at.year <= end
        ]
        eras[name] = {
            "years": [start, end],
            "episodes": len(selected),
            "summary": grouped_report(selected),
            "hierarchy": hierarchy_report(selected),
        }

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "contains_secrets": False,
        "observed_at": observed_at.isoformat(),
        "years": [int(shard["year"]) for shard in shards],
        "year_count": len(shards),
        "episode_count": len(episodes),
        "label_contract": {
            "full_zone_depth_zero": "NEAR_OUTER_EDGE:H4_H1_M15_DEMAND_HIGH_OR_SUPPLY_LOW",
            "full_zone_depth_one": "FAR_OUTER_EDGE:H4_H1_M15_DEMAND_LOW_OR_SUPPLY_HIGH",
            "internal_depth_zero": "ATLAS_PROXIMAL_BODY_EDGE",
            "internal_depth_one": "ATLAS_DISTAL_EDGE",
            "primary_coordinate": "FULL_ZONE_NEAR_EDGE_TO_FAR_EDGE",
            "secondary_coordinate": "ATLAS_PROXIMAL_BODY_EDGE_TO_DISTAL",
            "reaction": "0.50_ATR_FAVORABLE_MOVE_BEFORE_CLOSE_BEYOND_DISTAL",
            "turning_point": (
                "DEEPEST_ADVERSE_M1_EXTREME_RECORDED_BEFORE_FIRST_REACTION_TARGET; "
                "TARGET_BAR_NEW_ADVERSE_EXTREME_EXCLUDED_FOR_CONSERVATIVE_INTRABAR_ORDERING"
            ),
            "hazard": (
                "REVERSALS_IN_10PCT_DEPTH_BAND / EPISODES_THAT_REACHED_BAND_LOWER_BOUND"
            ),
            "timeframes": ["H4", "H1", "M15"],
            "hierarchy": (
                "SUCCESSFUL_H4_REVERSAL_POINT_MAPPED_INTO_PRE_EXISTING_SAME_DIRECTION "
                "H1_CHILD_THEN_M15_CHILD_IF_AVAILABLE"
            ),
        },
        "overall": overall,
        "hierarchy": hierarchy,
        "eras": eras,
        "yearly": yearly,
        "key_findings": _top_findings(overall),
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V225.2 is historical research only. M15 zones are causal only after the departure candle closes. The primary full-zone coordinate matches "
            "the user-facing supply/demand range: 0% is the near outer edge and 100% the "
            "far outer edge. Internal proximal-to-distal geometry is retained separately "
            "for diagnosis. Highest-hazard bands are conditional on price reaching that "
            "depth and have no entry authority until parity/prospective validation."
        ),
    }

    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=len(shards) >= 15,
            lag_seconds=0.0,
            details={
                "contract": payload["artifact_contract"],
                "research_version": RESEARCH_VERSION,
                "years": payload["years"],
                "year_count": len(shards),
                "episode_count": len(episodes),
                "key_findings": payload["key_findings"],
                "hierarchy": hierarchy,
                "eras": {
                    name: {
                        "episodes": item["episodes"],
                        "summary": item["summary"],
                        "hierarchy": item["hierarchy"],
                    }
                    for name, item in eras.items()
                },
                "policy_effect": POLICY_EFFECT,
                "execution_influence": False,
                "execution_authority": False,
                "promotion_authority": False,
                "artifact_path": str(output),
                "observed_at": observed_at.isoformat(),
                "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            },
        )
    except Exception as exc:
        print(f"V225_HEARTBEAT_WRITE_WARNING:{type(exc).__name__}:{exc}")

    print(
        "XAU_ZONE_REVERSAL_DEPTH_V225_FULL "
        f"years={len(shards)} episodes={len(episodes)} "
        f"h4={overall['H4']['ALL']['touches']} "
        f"h1={overall['H1']['ALL']['touches']} "
        f"m15={overall['M15']['ALL']['touches']} "
        f"artifact={output} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
