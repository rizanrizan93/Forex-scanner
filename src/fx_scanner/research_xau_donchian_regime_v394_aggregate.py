from __future__ import annotations

import json
import os
import statistics
from pathlib import Path
from typing import Any, Sequence

from .research_xau_donchian_regime_v394 import (
    ARTIFACT_CONTRACT,
    BASE_COST_PRICE,
    RESEARCH_VERSION,
    STRESS_COST_PRICE,
    config_grid,
    summarize,
    training_score,
)

STRICT_OOS_START = 2015
STRICT_OOS_END = 2025
PROVISIONAL_OOS_YEAR = 2026
TRAIN_YEARS = 3
MIN_TRAIN_TRADES = 60
ACCEPTANCE = {
    "oos_profit_factor_min": 1.50,
    "oos_expectancy_r_min": 0.20,
    "oos_trades_min": 150,
    "profitable_fold_ratio_min": 0.70,
    "median_fold_profit_factor_min": 1.30,
    "stress_profit_factor_min": 1.20,
    "max_drawdown_r_max": 15.0,
}


def _dir() -> Path:
    path = Path(os.getenv("XAU_DONCHIAN_REGIME_V394_SHARD_DIR", "/tmp/xau-donchian-regime-v394-shards"))
    if not path.exists():
        raise SystemExit(f"XAU_DONCHIAN_REGIME_V394_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _load() -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for file in sorted(_dir().rglob("xau-donchian-regime-v394-*.json")):
        if "provenance" in file.name or file.name.endswith("-full.json"):
            continue
        payload = json.loads(file.read_text())
        if "year" in payload and "configs" in payload:
            out[int(payload["year"])] = payload
    return out


def _trades(shards: dict[int, dict[str, Any]], years: Sequence[int], config_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in years:
        c = dict((shards.get(int(year)) or {}).get("configs") or {}).get(config_id) or {}
        rows.extend(dict(row) for row in list(c.get("trades") or []))
    return rows


def _positive_ratio(shards: dict[int, dict[str, Any]], years: Sequence[int], config_id: str) -> float:
    flags = []
    for year in years:
        m = summarize(_trades(shards, [year], config_id), cost_price=BASE_COST_PRICE)
        flags.append(int(m["completed"]) > 0 and float(m["expectancy_r"]) > 0 and float(m["profit_factor_r"]) > 1)
    return float(sum(flags) / len(flags)) if flags else 0.0


def _select(shards: dict[int, dict[str, Any]], train_years: Sequence[int]) -> dict[str, Any]:
    rows = []
    for config in config_grid():
        metrics = summarize(_trades(shards, train_years, config.config_id), cost_price=BASE_COST_PRICE)
        positive = _positive_ratio(shards, train_years, config.config_id)
        admissible = bool(
            int(metrics["completed"]) >= MIN_TRAIN_TRADES
            and float(metrics["expectancy_r"]) > 0
            and float(metrics["profit_factor_r"]) > 1.05
            and positive >= (2 / 3)
        )
        rows.append({
            "config_id": config.config_id,
            "config": config.payload(),
            "metrics": metrics,
            "positive_year_ratio": positive,
            "admissible": admissible,
            "score": training_score(metrics, positive_year_ratio=positive),
        })
    eligible = [r for r in rows if r["admissible"]] or rows
    eligible.sort(key=lambda r: (float(r["score"]), r["config_id"]), reverse=True)
    selected = dict(eligible[0])
    selected["fallback_selection"] = not any(r["admissible"] for r in rows)
    return selected


def _fold(shards: dict[int, dict[str, Any]], year: int) -> dict[str, Any]:
    train_years = list(range(year - TRAIN_YEARS, year))
    selected = _select(shards, train_years)
    trades = _trades(shards, [year], str(selected["config_id"]))
    return {
        "oos_year": year,
        "train_years": train_years,
        "selected_config_id": selected["config_id"],
        "selected_config": selected["config"],
        "train": selected["metrics"],
        "train_positive_year_ratio": selected["positive_year_ratio"],
        "train_admissible": selected["admissible"],
        "fallback_selection": selected["fallback_selection"],
        "base": summarize(trades, cost_price=BASE_COST_PRICE),
        "stress": summarize(trades, cost_price=STRESS_COST_PRICE),
        "trades": trades,
    }


def run() -> int:
    shards = _load()
    missing = sorted(set(range(2012, 2027)) - set(shards))
    if missing:
        raise SystemExit(f"XAU_DONCHIAN_REGIME_V394_MISSING_SHARDS:{missing}")
    folds = [_fold(shards, y) for y in range(STRICT_OOS_START, STRICT_OOS_END + 1)]
    provisional = _fold(shards, PROVISIONAL_OOS_YEAR)
    trades = [dict(t) for fold in folds for t in fold["trades"]]
    ptrades = [dict(t) for t in provisional["trades"]]
    base = summarize(trades, cost_price=BASE_COST_PRICE)
    stress = summarize(trades, cost_price=STRESS_COST_PRICE)
    pbase = summarize(ptrades, cost_price=BASE_COST_PRICE)
    pstress = summarize(ptrades, cost_price=STRESS_COST_PRICE)
    integrity = all(bool(dict(shards[y].get("price_provenance") or {}).get("data_integrity_ok")) for y in range(2012, STRICT_OOS_END + 1))
    positives = [float(f["base"]["expectancy_r"]) > 0 and float(f["base"]["profit_factor_r"]) > 1 for f in folds]
    positive_ratio = float(sum(positives) / len(positives))
    median_pf = float(statistics.median(float(f["base"]["profit_factor_r"]) for f in folds))
    checks = {
        "source_integrity": integrity,
        "oos_profit_factor": float(base["profit_factor_r"]) >= ACCEPTANCE["oos_profit_factor_min"],
        "oos_expectancy": float(base["expectancy_r"]) >= ACCEPTANCE["oos_expectancy_r_min"],
        "oos_trade_count": int(base["completed"]) >= ACCEPTANCE["oos_trades_min"],
        "profitable_fold_ratio": positive_ratio >= ACCEPTANCE["profitable_fold_ratio_min"],
        "median_fold_profit_factor": median_pf >= ACCEPTANCE["median_fold_profit_factor_min"],
        "stress_profit_factor": float(stress["profit_factor_r"]) > ACCEPTANCE["stress_profit_factor_min"],
        "max_drawdown": float(base["max_drawdown_r"]) <= ACCEPTANCE["max_drawdown_r_max"],
    }
    acceptance = {"thresholds": ACCEPTANCE, "profitable_fold_ratio": positive_ratio, "median_fold_profit_factor": median_pf, "checks": checks, "all_checks_met": all(checks.values())}
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_1",
        "research_version": RESEARCH_VERSION,
        "symbol": "XAUUSD",
        "source": "HISTDATA_XAUUSD_M1",
        "method": {
            "parameter_grid_size": len(config_grid()),
            "rolling_train_years": TRAIN_YEARS,
            "selection": "ONLY_PRIOR_3_YEARS",
            "minimum_train_trades": MIN_TRAIN_TRADES,
            "same_bar_policy": "STOP_FIRST",
            "base_cost_price_round_trip": BASE_COST_PRICE,
            "stress_cost_price_round_trip": STRESS_COST_PRICE,
            "strict_acceptance_excludes_partial_2026": True,
            "calendar_year_not_used_as_regime_gate": True,
            "execution_authority": False,
        },
        "strict_oos": {"base": base, "stress": stress, "acceptance": acceptance, "folds": [{k: v for k, v in f.items() if k != "trades"} for f in folds]},
        "provisional_2026": {"base": pbase, "stress": pstress, "fold": {k: v for k, v in provisional.items() if k != "trades"}, "partial": bool(shards[2026].get("partial_current_year"))},
        "source_integrity": integrity,
        "execution_authority": False,
    }
    output = Path(os.getenv("XAU_DONCHIAN_REGIME_V394_FULL_OUTPUT", "artifacts/xau-donchian-regime-raw-v394-full.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_DONCHIAN_REGIME_RAW_V394_FULL "
        f"oos_n={base['completed']} oos_pf={base['profit_factor_r']:.4f} oos_exp={base['expectancy_r']:.4f} "
        f"oos_wr={base['win_rate']:.4f} oos_dd={base['max_drawdown_r']:.4f} stress_pf={stress['profit_factor_r']:.4f} "
        f"stress_exp={stress['expectancy_r']:.4f} folds_positive={positive_ratio:.4f} median_fold_pf={median_pf:.4f} "
        f"gate={int(all(checks.values()))} source_integrity={int(integrity)} y2026_n={pbase['completed']} "
        f"y2026_pf={pbase['profit_factor_r']:.4f} y2026_exp={pbase['expectancy_r']:.4f} execution_authority=0"
    )
    for f in folds:
        print(
            "XAU_DONCHIAN_REGIME_RAW_V394_FOLD "
            f"year={f['oos_year']} config={f['selected_config_id']} train_n={f['train']['completed']} "
            f"train_pf={f['train']['profit_factor_r']:.4f} oos_n={f['base']['completed']} "
            f"oos_pf={f['base']['profit_factor_r']:.4f} oos_exp={f['base']['expectancy_r']:.4f} fallback={int(f['fallback_selection'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
