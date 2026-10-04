from __future__ import annotations

"""V385 research-only parallel adaptive C4 replay harness.

V385 preserves the V384 causal state-machine and frozen V376 C4 selector.  The
change is computational only:

Layer 1 -- Structural C4 provider
    Loads/resamples the 2025 M1 shard once per job and owns the canonical C4
    forecast cache for the timestamps required by that configuration.

Layer 2 -- Adaptive configuration simulator
    Runs exactly one V384 invalidation challenger per process.  The four
    challengers are intended to run as four independent GitHub Actions jobs.

This prevents one Python process from carrying four divergent adaptive paths
serially.  It does not grant execution authority and does not retrain C4.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fx_scanner.research_xau_sd_liquidity_v345 import load_price_frame

from xau_v384_adaptive_c4_reforecast_cached import (
    CONFIGS,
    Config,
    _arrays,
    _bar_cache,
    _m15_arrays,
    _run_config,
)

SCHEMA = "XAU_V385_ADAPTIVE_C4_PARALLEL_TWO_LAYER_V1"
CONFIG_MAP = {config.name: config for config in CONFIGS}


@dataclass
class StructuralLayer:
    arrays: dict[str, Any]
    bars: dict[str, Any]
    completed: dict[str, list[datetime]]
    m15: dict[str, Any]
    forecast_cache: dict[datetime, dict[str, Any] | None]
    cache_stats: dict[str, int]

    @classmethod
    def from_csv(cls, csv_path: Path) -> "StructuralLayer":
        price = load_price_frame(csv_path)
        arrays = _arrays(price)
        bars, completed, frames = _bar_cache(price)
        return cls(
            arrays=arrays,
            bars=bars,
            completed=completed,
            m15=_m15_arrays(frames["M15"]),
            forecast_cache={},
            cache_stats={"hits": 0, "evaluations": 0},
        )

    def run_config(self, *, year: int, config: Config) -> dict[str, Any]:
        return _run_config(
            year=year,
            config=config,
            arrays=self.arrays,
            bars=self.bars,
            completed=self.completed,
            m15=self.m15,
            forecast_cache=self.forecast_cache,
            cache_stats=self.cache_stats,
        )

    def cache_summary(self) -> dict[str, Any]:
        total = self.cache_stats["hits"] + self.cache_stats["evaluations"]
        return {
            "entries": len(self.forecast_cache),
            "hits": self.cache_stats["hits"],
            "evaluations": self.cache_stats["evaluations"],
            "hit_rate": None if not total else self.cache_stats["hits"] / total,
        }


def run(*, year: int, csv_path: Path, config_name: str, output: Path) -> dict[str, Any]:
    if config_name not in CONFIG_MAP:
        raise SystemExit(f"Unknown config {config_name!r}; expected one of {sorted(CONFIG_MAP)}")

    structural = StructuralLayer.from_csv(csv_path)
    config = CONFIG_MAP[config_name]
    result = structural.run_config(year=year, config=config)

    payload = {
        "schema": SCHEMA,
        "year": year,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "source": "HISTDATA_XAUUSD_M1_PUBLIC_SECONDARY",
        "causal": True,
        "execution_authority": False,
        "execution_influence": False,
        "champion_selector": "V376_C4_NEXT_ZONE_PATH_FROZEN",
        "methodology_parent": "XAU_V384_ADAPTIVE_C4_REFORECAST_CACHED_V1",
        "two_layer_contract": {
            "layer_1": "STRUCTURAL_C4_PROVIDER_WITH_CAUSAL_TIMESTAMP_CACHE",
            "layer_2": "SINGLE_ADAPTIVE_INVALIDATION_CONFIG_STATE_MACHINE",
            "selection_logic_changed": False,
            "state_machine_changed": False,
        },
        "config": result,
        "forecast_cache": structural.cache_summary(),
        "limitations": [
            "Public M1 OHLC plus completed M15 structural invalidation; not bid/ask tick execution replay.",
            "C4 zone-selection parameters remain frozen; V385 changes replay orchestration only.",
            "2025 is configuration selection; the existing successful V384 2026 result remains holdout.",
            "Path metrics are not trade PnL; costs, news, SL/TP and execution gates are outside V385.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("V385_CONFIG=" + config_name)
    print("V385_CACHE=" + json.dumps(payload["forecast_cache"], sort_keys=True))
    print("V385_SUMMARY=" + json.dumps(result["summary"], sort_keys=True))
    print(f"OUTPUT={output}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--config", choices=sorted(CONFIG_MAP), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(year=args.year, csv_path=args.csv, config_name=args.config, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
