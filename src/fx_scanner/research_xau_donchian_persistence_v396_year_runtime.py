from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .research_xau_donchian_persistence_v396 import (
    ARTIFACT_CONTRACT,
    BASE_COST_PRICE,
    MIN_BREAKOUT_DISTANCE_ATR,
    RESEARCH_VERSION,
    STRESS_COST_PRICE,
    SYMBOL,
    config_grid,
    prepare_m15,
    simulate_config,
    summarize,
)
from .research_xau_donchian_regime_v394_year_runtime import _download


def _year() -> int:
    value = int(os.getenv("XAU_DONCHIAN_PERSIST_V396_YEAR", "0") or 0)
    current = datetime.now(tz=UTC).year
    if value < 2012 or value > current:
        raise SystemExit(f"XAU_DONCHIAN_PERSIST_V396_YEAR_INVALID:{value}")
    return value


def run() -> int:
    year = _year()
    csv_path = Path(os.getenv("XAU_DONCHIAN_PERSIST_V396_PRICE_CSV", f"/tmp/histdata/xau-donchian-persist-v396-{year}.csv"))
    provenance_path = Path(os.getenv("XAU_DONCHIAN_PERSIST_V396_PROVENANCE", f"artifacts/xau-donchian-persist-v396-provenance-{year}.json"))
    output_path = Path(os.getenv("XAU_DONCHIAN_PERSIST_V396_OUTPUT", f"artifacts/xau-donchian-persist-v396-{year}.json"))

    provenance = _download(year, csv_path, provenance_path)
    price = pd.read_csv(csv_path)
    price["timestamp"] = pd.to_datetime(price["timestamp"], utc=True)
    for column in ("open", "high", "low", "close"):
        price[column] = pd.to_numeric(price[column], errors="raise")
    m15 = prepare_m15(price)

    configs = {}
    total = 0
    for config in config_grid():
        trades = simulate_config(m15, config, target_year=year)
        total += len(trades)
        configs[config.config_id] = {
            "config": config.payload(),
            "trades": trades,
            "base": summarize(trades, cost_price=BASE_COST_PRICE),
            "stress": summarize(trades, cost_price=STRESS_COST_PRICE),
        }

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "year": year,
        "partial_current_year": bool(provenance["partial_current_year"]),
        "price_provenance": provenance,
        "price_rows": len(price),
        "m15_rows": len(m15),
        "config_count": len(configs),
        "method": {
            "pattern": "M15_DONCHIAN_RETEST_REGIME_COST_GATE_PLUS_PRIOR_SIGNED_MOMENTUM_AND_BREAKOUT_DISTANCE",
            "parameter_grid_size": len(config_grid()),
            "signed_momentum_uses_prior_bars_only": True,
            "min_breakout_distance_atr": MIN_BREAKOUT_DISTANCE_ATR,
            "future_retest_entry_only": True,
            "pretrade_cost_gate": True,
            "same_bar_policy": "STOP_FIRST",
            "base_cost_price_round_trip": BASE_COST_PRICE,
            "stress_cost_price_round_trip": STRESS_COST_PRICE,
            "execution_authority": False,
        },
        "configs": configs,
        "execution_authority": False,
        "live_execution_enabled": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    best = max(configs.values(), key=lambda row: (float(row["base"]["expectancy_r"]), float(row["base"]["profit_factor_r"])))
    print(
        "XAU_DONCHIAN_PERSIST_RAW_V396_YEAR "
        f"year={year} rows={len(price)} m15={len(m15)} configs={len(configs)} records={total} "
        f"best={best['config']['config_id']} best_n={best['base']['completed']} "
        f"best_pf={best['base']['profit_factor_r']:.4f} best_exp={best['base']['expectancy_r']:.4f} "
        f"failed_periods={len(provenance['failed_periods'])} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
