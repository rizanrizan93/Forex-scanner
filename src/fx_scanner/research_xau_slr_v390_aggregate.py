from __future__ import annotations

import json
import os
import statistics
from pathlib import Path
from typing import Any, Sequence

from .research_xau_slr_v390 import (
    ARTIFACT_CONTRACT,
    BASE_COST_PRICE,
    RESEARCH_VERSION,
    STRESS_COST_PRICE,
    config_grid,
    summarize_trades,
    training_score,
)

STRICT_OOS_START = 2015
STRICT_OOS_END = 2025
PROVISIONAL_OOS_YEAR = 2026
TRAIN_YEARS = 3
MIN_TRAIN_TRADES = 45

ACCEPTANCE = {
    "oos_profit_factor_min": 1.50,
    "oos_expectancy_r_min": 0.20,
    "oos_trades_min": 150,
    "profitable_fold_ratio_min": 0.70,
    "median_fold_profit_factor_min": 1.30,
    "stress_profit_factor_min": 1.20,
    "max_drawdown_r_max": 15.0,
}


def _shard_dir() -> Path:
    path = Path(os.getenv("XAU_SLR_V390_SHARD_DIR", "/tmp/xau-slr-v390-shards"))
    if not path.exists():
        raise SystemExit(f"XAU_SLR_V390_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(os.getenv("XAU_SLR_V390_FULL_OUTPUT", "artifacts/xau-slr-raw-v390-full.json"))


def _load_shards(path: Path) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    for file in sorted(path.rglob("xau-slr-v390-*.json")):
        if "provenance" in file.name or file.name.endswith("-full.json"):
            continue
        payload = json.loads(file.read_text())
        if "year" not in payload or "configs" not in payload:
            continue
        output[int(payload["year"])] = payload
    return output


def _trades(shards: dict[int, dict[str, Any]], years: Sequence[int], config_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in years:
        shard = shards.get(int(year))
        if not shard:
            continue
        config_payload = dict(shard.get("configs") or {}).get(config_id) or {}
        rows.extend(dict(row) for row in list(config_payload.get("trades") or []))
    return rows


def _positive_year_ratio(shards: dict[int, dict[str, Any]], years: Sequence[int], config_id: str) -> float:
    flags: list[bool] = []
    for year in years:
        trades = _trades(shards, [year], config_id)
        metrics = summarize_trades(trades, cost_price=BASE_COST_PRICE)
        if int(metrics["completed"]) == 0:
            flags.append(False)
        else:
            flags.append(
                float(metrics["expectancy_r"]) > 0.0 and float(metrics["profit_factor_r"]) > 1.0
            )
    return float(sum(flags) / len(flags)) if flags else 0.0


def _select_config(shards: dict[int, dict[str, Any]], train_years: Sequence[int]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for config in config_grid():
        rows = _trades(shards, train_years, config.config_id)
        metrics = summarize_trades(rows, cost_price=BASE_COST_PRICE)
        positive_ratio = _positive_year_ratio(shards, train_years, config.config_id)
        admissible = bool(
            int(metrics["completed"]) >= MIN_TRAIN_TRADES
            and float(metrics["expectancy_r"]) > 0.0
            and float(metrics["profit_factor_r"]) > 1.05
            and positive_ratio >= (2.0 / 3.0)
        )
        candidates.append(
            {
                "config_id": config.config_id,
                "config": config.payload(),
                "metrics": metrics,
                "positive_year_ratio": positive_ratio,
                "admissible": admissible,
                "score": training_score(metrics, positive_year_ratio=positive_ratio),
            }
        )
    eligible = [row for row in candidates if row["admissible"]] or candidates
    eligible.sort(key=lambda row: (float(row["score"]), row["config_id"]), reverse=True)
    selected = dict(eligible[0])
    selected["fallback_selection"] = not any(row["admissible"] for row in candidates)
    return selected


def _fold(shards: dict[int, dict[str, Any]], oos_year: int) -> dict[str, Any]:
    train_years = list(range(oos_year - TRAIN_YEARS, oos_year))
    selected = _select_config(shards, train_years)
    rows = _trades(shards, [oos_year], str(selected["config_id"]))
    return {
        "oos_year": oos_year,
        "train_years": train_years,
        "selected_config_id": selected["config_id"],
        "selected_config": selected["config"],
        "train": selected["metrics"],
        "train_positive_year_ratio": selected["positive_year_ratio"],
        "train_admissible": selected["admissible"],
        "fallback_selection": selected["fallback_selection"],
        "base": summarize_trades(rows, cost_price=BASE_COST_PRICE),
        "stress": summarize_trades(rows, cost_price=STRESS_COST_PRICE),
        "trades": rows,
    }


def _acceptance(base: dict[str, Any], stress: dict[str, Any], strict_folds: Sequence[dict[str, Any]], integrity: bool) -> dict[str, Any]:
    fold_positive = [
        float(row["base"]["expectancy_r"]) > 0.0 and float(row["base"]["profit_factor_r"]) > 1.0
        for row in strict_folds
    ]
    profitable_ratio = float(sum(fold_positive) / len(fold_positive)) if fold_positive else 0.0
    fold_pfs = [float(row["base"]["profit_factor_r"]) for row in strict_folds]
    median_pf = float(statistics.median(fold_pfs)) if fold_pfs else 0.0
    checks = {
        "source_integrity": bool(integrity),
        "oos_profit_factor": float(base["profit_factor_r"]) >= ACCEPTANCE["oos_profit_factor_min"],
        "oos_expectancy": float(base["expectancy_r"]) >= ACCEPTANCE["oos_expectancy_r_min"],
        "oos_trade_count": int(base["completed"]) >= ACCEPTANCE["oos_trades_min"],
        "profitable_fold_ratio": profitable_ratio >= ACCEPTANCE["profitable_fold_ratio_min"],
        "median_fold_profit_factor": median_pf >= ACCEPTANCE["median_fold_profit_factor_min"],
        "stress_profit_factor": float(stress["profit_factor_r"]) > ACCEPTANCE["stress_profit_factor_min"],
        "max_drawdown": float(base["max_drawdown_r"]) <= ACCEPTANCE["max_drawdown_r_max"],
    }
    return {
        "thresholds": dict(ACCEPTANCE),
        "profitable_fold_ratio": profitable_ratio,
        "median_fold_profit_factor": median_pf,
        "checks": checks,
        "all_checks_met": all(checks.values()),
    }


def run() -> int:
    shards = _load_shards(_shard_dir())
    expected = set(range(2012, 2027))
    missing = sorted(expected - set(shards))
    if missing:
        raise SystemExit(f"XAU_SLR_V390_MISSING_SHARDS:{missing}")

    strict_folds = [_fold(shards, year) for year in range(STRICT_OOS_START, STRICT_OOS_END + 1)]
    provisional = _fold(shards, PROVISIONAL_OOS_YEAR)

    strict_trades: list[dict[str, Any]] = []
    for fold in strict_folds:
        strict_trades.extend(dict(row) for row in fold["trades"])
    provisional_trades = [dict(row) for row in provisional["trades"]]

    base = summarize_trades(strict_trades, cost_price=BASE_COST_PRICE)
    stress = summarize_trades(strict_trades, cost_price=STRESS_COST_PRICE)
    provisional_base = summarize_trades(provisional_trades, cost_price=BASE_COST_PRICE)
    provisional_stress = summarize_trades(provisional_trades, cost_price=STRESS_COST_PRICE)

    strict_integrity = all(
        bool(dict(shards[year].get("price_provenance") or {}).get("data_integrity_ok"))
        for year in range(2012, STRICT_OOS_END + 1)
    )
    acceptance = _acceptance(base, stress, strict_folds, strict_integrity)

    selection_counts: dict[str, int] = {}
    for fold in [*strict_folds, provisional]:
        key = str(fold["selected_config_id"])
        selection_counts[key] = selection_counts.get(key, 0) + 1

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_1",
        "research_version": RESEARCH_VERSION,
        "symbol": "XAUUSD",
        "source": "HISTDATA_XAUUSD_M1",
        "years": list(range(2012, 2027)),
        "strict_oos_years": [STRICT_OOS_START, STRICT_OOS_END],
        "provisional_oos_year": PROVISIONAL_OOS_YEAR,
        "method": {
            "parameter_grid_size": len(config_grid()),
            "rolling_train_years": TRAIN_YEARS,
            "selection": "ONLY_PRIOR_3_YEARS; CURRENT_OOS_YEAR_NEVER_USED_FOR_SELECTION",
            "minimum_train_trades": MIN_TRAIN_TRADES,
            "same_bar_policy": "STOP_FIRST",
            "base_cost_price_round_trip": BASE_COST_PRICE,
            "stress_cost_price_round_trip": STRESS_COST_PRICE,
            "strict_acceptance_excludes_partial_2026": True,
            "execution_authority": False,
        },
        "strict_oos": {
            "base": base,
            "stress": stress,
            "acceptance": acceptance,
            "folds": [{k: v for k, v in row.items() if k != "trades"} for row in strict_folds],
        },
        "provisional_2026": {
            "base": provisional_base,
            "stress": provisional_stress,
            "fold": {k: v for k, v in provisional.items() if k != "trades"},
            "partial": bool(shards[PROVISIONAL_OOS_YEAR].get("partial_current_year")),
        },
        "selection_frequency": selection_counts,
        "source_integrity": {
            "strict_complete": strict_integrity,
            "failed_periods_by_year": {
                str(year): list(dict(shards[year].get("price_provenance") or {}).get("failed_periods") or [])
                for year in sorted(shards)
                if list(dict(shards[year].get("price_provenance") or {}).get("failed_periods") or [])
            },
        },
        "limitations": [
            "HistData M1 is public secondary market data, not FP Markets historical bid/ask ticks.",
            "Historical spread is unavailable; fixed adverse price-cost proxies are applied in R-space.",
            "M5 intrabar sequence is unknown; ambiguous SL/TP bars are resolved STOP_FIRST.",
            "2026 is partial and excluded from strict acceptance.",
            "Passing this research gate would justify demo-forward validation, not a live-profit guarantee.",
        ],
        "execution_influence": False,
        "execution_authority": False,
        "live_execution_enabled": False,
    }

    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    print(
        "XAU_SLR_RAW_V390_FULL "
        f"oos_n={base['completed']} oos_pf={base['profit_factor_r']:.4f} "
        f"oos_exp={base['expectancy_r']:.4f} oos_wr={base['win_rate']:.4f} "
        f"oos_dd={base['max_drawdown_r']:.4f} stress_pf={stress['profit_factor_r']:.4f} "
        f"stress_exp={stress['expectancy_r']:.4f} folds_positive={acceptance['profitable_fold_ratio']:.4f} "
        f"median_fold_pf={acceptance['median_fold_profit_factor']:.4f} "
        f"gate={int(acceptance['all_checks_met'])} source_integrity={int(strict_integrity)} "
        f"y2026_n={provisional_base['completed']} y2026_pf={provisional_base['profit_factor_r']:.4f} "
        f"y2026_exp={provisional_base['expectancy_r']:.4f} execution_authority=0"
    )
    for fold in strict_folds:
        print(
            "XAU_SLR_RAW_V390_FOLD "
            f"year={fold['oos_year']} config={fold['selected_config_id']} "
            f"train_n={fold['train']['completed']} train_pf={fold['train']['profit_factor_r']:.4f} "
            f"oos_n={fold['base']['completed']} oos_pf={fold['base']['profit_factor_r']:.4f} "
            f"oos_exp={fold['base']['expectancy_r']:.4f} fallback={int(fold['fallback_selection'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
