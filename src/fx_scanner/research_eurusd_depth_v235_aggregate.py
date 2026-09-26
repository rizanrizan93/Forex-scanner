from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .research_xau_zone_reversal_depth_v225 import (
    deserialize_episode,
    grouped_report,
    hierarchy_report,
)

RESEARCH_VERSION = "EURUSD_DEPTH_TRANSFER_V235_1"
ARTIFACT_CONTRACT = "EURUSD_DEPTH_TRANSFER_V235_1_EVIDENCE_1"
ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


def _shard_dir() -> Path:
    path = Path(os.getenv("EURUSD_V235_SHARD_DIR", "/tmp/eurusd-v235-shards").strip())
    if not path.exists():
        raise SystemExit(f"EURUSD_V235_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(
        os.getenv(
            "EURUSD_V235_FULL_OUTPUT",
            "artifacts/eurusd-depth-v235-full.json",
        ).strip()
    )


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows = []
    for file in sorted(path.rglob("eurusd-depth-v235-*.json")):
        payload = json.loads(file.read_text())
        if "year" in payload:
            rows.append(payload)
    rows.sort(key=lambda item: int(item["year"]))
    return rows


def _headline(report: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for timeframe in ("H4", "H1", "M15"):
        row = dict(dict(report.get(timeframe) or {}).get("ALL") or {})
        top = list(row.get("highest_hazard_bands_min_n") or [])
        best = dict(top[0]) if top else {}
        p25 = row.get("depth_p25")
        p75 = row.get("depth_p75")
        output[timeframe] = {
            "touches": row.get("touches"),
            "hold_rate_050": row.get("hold_rate"),
            "hold_wilson_lower_95": row.get("hold_wilson_lower_95"),
            "depth_median": row.get("depth_median"),
            "depth_p25": p25,
            "depth_p75": p75,
            "depth_iqr": (
                None if p25 is None or p75 is None else float(p75) - float(p25)
            ),
            "highest_hazard_band": best.get("band"),
            "band_hazard": best.get("hazard"),
            "band_at_risk": best.get("at_risk"),
            "band_wilson_lower_95": best.get("wilson_lower_95"),
        }
    return output


def run() -> int:
    shards = _load_shards(_shard_dir())
    if not shards:
        raise SystemExit("EURUSD_V235_NO_SHARDS")

    episodes = []
    yearly: dict[str, Any] = {}
    for shard in shards:
        year = int(shard["year"])
        yearly[str(year)] = {
            "zone_count": shard.get("zone_count"),
            "episode_count": shard.get("episode_count"),
            "headline": _headline(dict(shard.get("summary") or {})),
        }
        for raw in list(shard.get("episodes") or []):
            episodes.append(deserialize_episode(dict(raw)))

    overall = grouped_report(episodes)
    hierarchy = hierarchy_report(episodes)
    eras: dict[str, Any] = {}
    for name, (start, end) in ERAS.items():
        selected = [row for row in episodes if start <= row.touch_at.year <= end]
        report = grouped_report(selected)
        eras[name] = {
            "years": [start, end],
            "episodes": len(selected),
            "headline": _headline(report),
            "summary": report,
            "hierarchy": hierarchy_report(selected),
        }

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "pair": "EURUSD",
        "method_source": "XAU_ZONE_REVERSAL_DEPTH_V225_2_IDENTICAL_GEOMETRY",
        "years": [int(shard["year"]) for shard in shards],
        "year_count": len(shards),
        "episode_count": len(episodes),
        "overall_headline": _headline(overall),
        "overall": overall,
        "hierarchy": hierarchy,
        "eras": eras,
        "yearly": yearly,
        "interpretation": (
            "Cross-asset transfer benchmark only. The XAU V225.2 causal H4/H1/M15 "
            "supply-demand and first-touch depth geometry is applied unchanged to EURUSD. "
            "Reaction means >=0.50 ATR favorable move before a close beyond the distal edge. "
            "This does not yet reproduce the full V229 four-child broker execution path."
        ),
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
        "EURUSD_DEPTH_V235_FULL "
        f"years={len(shards)} episodes={len(episodes)} "
        f"h4={overall['H4']['ALL']['touches']} "
        f"h1={overall['H1']['ALL']['touches']} "
        f"m15={overall['M15']['ALL']['touches']} "
        f"artifact={output} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
