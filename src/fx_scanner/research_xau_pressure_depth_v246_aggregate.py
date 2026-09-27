from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .research_xau_pressure_depth_v246 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    PressureDepthEpisode,
    pressure_depth_report,
)

ERA_BOUNDS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


def _load_rows(root: Path) -> tuple[PressureDepthEpisode, ...]:
    rows: list[PressureDepthEpisode] = []
    for path in sorted(root.rglob("xau-pressure-depth-v246-*.json")):
        payload = json.loads(path.read_text())
        for row in list(payload.get("episodes") or []):
            rows.append(PressureDepthEpisode(**dict(row)))
    rows.sort(key=lambda r: (r.touch_at, r.timeframe, r.zone_id))
    return tuple(rows)


def _year(row: PressureDepthEpisode) -> int:
    return int(str(row.touch_at)[:4])


def run() -> int:
    root = Path(os.getenv("XAU_V246_SHARD_DIR", "/tmp/v246-shards"))
    output = Path(
        os.getenv(
            "XAU_V246_FULL_OUTPUT",
            "artifacts/xau-pressure-depth-v246-full.json",
        )
    )
    rows = _load_rows(root)
    if not rows:
        raise SystemExit("XAU_V246_NO_SHARDS")

    eras: dict[str, Any] = {}
    for era, (start, end) in ERA_BOUNDS.items():
        selected = [row for row in rows if start <= _year(row) <= end]
        eras[era] = pressure_depth_report(selected)

    yearly = {
        str(year): pressure_depth_report([row for row in rows if _year(row) == year])
        for year in range(2012, 2027)
    }

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_1",
        "research_version": RESEARCH_VERSION,
        "episode_count": len(rows),
        "historical_dom_available": False,
        "historical_pressure_source": "CAUSAL_M1_OHLC_PROXY",
        "summary": pressure_depth_report(rows),
        "eras": eras,
        "yearly": yearly,
        "research_question": (
            "Conditional on buyer/seller pressure immediately before first touch, "
            "how deep does XAUUSD penetrate an H4/H1/M15 supply-demand zone before "
            "a 0.50 ATR reaction or invalidation?"
        ),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_PRESSURE_DEPTH_V246_AGGREGATE "
        f"episodes={len(rows)} eras={len(eras)} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
