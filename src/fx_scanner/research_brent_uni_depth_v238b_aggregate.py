from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ensure_utc
from .research_brent_uni_depth_v238b_metrics import grouped_excursion_report
from .research_xau_zone_reversal_depth_v225 import (
    deserialize_episode,
    grouped_report,
    hierarchy_report,
)

RESEARCH_VERSION = "BRENT_UNI_DEPTH_V238B_1"
ARTIFACT_CONTRACT = "BRENT_UNI_DEPTH_V238B_1_EVIDENCE_1"
ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


def _shard_dir() -> Path:
    path = Path(os.getenv("BRENT_V238B_SHARD_DIR", "/tmp/brent-v238b-shards").strip())
    if not path.exists():
        raise SystemExit(f"BRENT_V238B_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(
        os.getenv(
            "BRENT_V238B_FULL_OUTPUT",
            "artifacts/brent-uni-depth-v238b-full.json",
        ).strip()
    )


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file in sorted(path.rglob("brent-uni-depth-v238b-*.json")):
        payload = dict(json.loads(file.read_text()) or {})
        if "year" in payload:
            rows.append(payload)
    rows.sort(key=lambda item: int(item["year"]))
    return rows


def _depth_headline(report: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for timeframe in ("H4", "H1", "M15"):
        row = dict(dict(report.get(timeframe) or {}).get("ALL") or {})
        p25 = row.get("depth_p25")
        p75 = row.get("depth_p75")
        top = list(row.get("highest_hazard_bands_min_n") or [])
        best = dict(top[0]) if top else {}
        output[timeframe] = {
            "touches": row.get("touches"),
            "reaction_rate_050": row.get("hold_rate"),
            "reaction_wilson_lower_95_050": row.get("hold_wilson_lower_95"),
            "depth_median": row.get("depth_median"),
            "depth_p25": p25,
            "depth_p75": p75,
            "depth_iqr": (
                None if p25 is None or p75 is None else float(p75) - float(p25)
            ),
            "highest_hazard_band": best.get("band"),
            "band_hazard": best.get("hazard"),
            "band_at_risk": best.get("at_risk"),
        }
    return output


def _excursion_headline(report: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for timeframe in ("H4", "H1", "M15"):
        row = dict(dict(report.get(timeframe) or {}).get("ALL") or {})
        output[timeframe] = {
            "episodes": row.get("episodes"),
            "reaction_rates": row.get("reaction_rates"),
            "mfe_atr_median": row.get("mfe_atr_median"),
            "mae_atr_median": row.get("mae_atr_median"),
            "candidate_to_first_touch_minutes_median": row.get(
                "candidate_to_first_touch_minutes_median"
            ),
            "time_to_reaction_minutes_median": row.get(
                "time_to_reaction_minutes_median"
            ),
            "break_before_horizon_rate": row.get("break_before_horizon_rate"),
        }
    return output


def _excursion_year(row: dict[str, Any]) -> int:
    return ensure_utc(
        datetime.fromisoformat(str(row["touch_at"]).replace("Z", "+00:00"))
    ).year


def run() -> int:
    shards = _load_shards(_shard_dir())
    if not shards:
        raise SystemExit("BRENT_V238B_NO_SHARDS")

    episodes = []
    excursions: list[dict[str, Any]] = []
    yearly: dict[str, Any] = {}
    available_years: list[int] = []
    unavailable_years: list[int] = []

    for shard in shards:
        year = int(shard["year"])
        available = bool(shard.get("available"))
        if available:
            available_years.append(year)
        else:
            unavailable_years.append(year)
        yearly[str(year)] = {
            "available": available,
            "price_rows": shard.get("price_rows"),
            "zone_count": shard.get("zone_count"),
            "episode_count": shard.get("episode_count"),
            "depth_headline": _depth_headline(dict(shard.get("summary") or {})),
            "excursion_headline": _excursion_headline(
                dict(shard.get("excursion_summary") or {})
            ),
            "price_provenance": shard.get("price_provenance"),
        }
        for raw in list(shard.get("episodes") or []):
            episodes.append(deserialize_episode(dict(raw)))
        excursions.extend(dict(row) for row in list(shard.get("excursions") or []))

    overall_depth = grouped_report(episodes)
    overall_excursion = grouped_excursion_report(excursions)
    eras: dict[str, Any] = {}
    for name, (start, end) in ERAS.items():
        selected_episodes = [
            row for row in episodes if start <= ensure_utc(row.touch_at).year <= end
        ]
        selected_excursions = [
            row for row in excursions if start <= _excursion_year(row) <= end
        ]
        depth_report = grouped_report(selected_episodes)
        excursion_report = grouped_excursion_report(selected_excursions)
        eras[name] = {
            "years": [start, end],
            "episodes": len(selected_episodes),
            "depth_headline": _depth_headline(depth_report),
            "excursion_headline": _excursion_headline(excursion_report),
            "depth_summary": depth_report,
            "excursion_summary": excursion_report,
            "hierarchy": hierarchy_report(selected_episodes),
        }

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "instrument": "BRENT",
        "histdata_pair": "BCOUSD",
        "method_source": "XAU_ZONE_REVERSAL_DEPTH_V225_2_CAUSAL_GEOMETRY",
        "requested_years": [2012, 2026],
        "available_years": available_years,
        "unavailable_years": unavailable_years,
        "year_count_available": len(available_years),
        "episode_count": len(episodes),
        "overall_depth_headline": _depth_headline(overall_depth),
        "overall_excursion_headline": _excursion_headline(overall_excursion),
        "overall_depth": overall_depth,
        "overall_excursion": overall_excursion,
        "hierarchy": hierarchy_report(episodes),
        "eras": eras,
        "yearly": yearly,
        "metric_scope": {
            "implemented": [
                "candidate_to_first_touch",
                "penetration_depth_percentiles",
                "reaction_025_atr",
                "reaction_050_atr",
                "reaction_075_atr",
                "reaction_100_atr",
                "mae_atr",
                "mfe_atr",
                "time_to_reaction",
                "break_before_horizon_rate",
                "era_stability",
            ],
            "deferred_to_execution_stage": [
                "m15_h1_h4_structural_target_hit_rate",
                "spread_slippage_normalized_atr",
                "event_conditioned_failure",
                "expectancy_after_costs",
                "profit_factor",
                "drawdown",
                "walk_forward_oos_execution",
            ],
        },
        "interpretation": (
            "Brent V238B is a causal, first-touch Uni Depth geometry benchmark. "
            "It reuses the frozen XAU V225.2 zone construction without fitting thresholds "
            "to Brent. Reaction ladders use STOP_FIRST on same-M1 break/target ambiguity. "
            "It is not an execution backtest and cannot grant broker authority."
        ),
        "broker_symbol_status": "UNRESOLVED_FP_MARKETS_CTRADER",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "live_execution_enabled": False,
    }
    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "BRENT_UNI_DEPTH_V238B_FULL "
        f"available_years={len(available_years)} unavailable_years={len(unavailable_years)} "
        f"episodes={len(episodes)} artifact={output} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
