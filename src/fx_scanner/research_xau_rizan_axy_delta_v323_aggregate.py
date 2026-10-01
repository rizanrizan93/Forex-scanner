from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from .research_xau_rizan_axy_delta_v323 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_AUTHORITY,
    RESEARCH_VERSION,
    combine_candidate_stats,
)

TRAIN_END_YEAR = 2024
OOS_START_YEAR = 2025
MIN_TRAIN_FILLS = 150
MIN_TRAIN_RESOLVED = 100


def _load_shards(root: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for path in sorted(root.rglob("xau-rizan-axy-delta-v323-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "year" not in payload:
            continue
        output.append(payload)
    output.sort(key=lambda row: int(row["year"]))
    return output


def _candidate_index(shards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for shard in shards:
        year = int(shard["year"])
        for raw in list(shard.get("candidates") or []):
            row = dict(raw or {})
            row["year"] = year
            output[str(row.get("candidate_key") or "")].append(row)
    return dict(output)


def _combine(
    rows: list[dict[str, Any]],
    *,
    years: set[int] | None = None,
) -> dict[str, Any]:
    selected = rows if years is None else [
        row for row in rows if int(row.get("year") or 0) in years
    ]
    return combine_candidate_stats(selected)


def _score_train(stats: dict[str, Any]) -> float | None:
    fills = int(stats.get("fills") or 0)
    resolved = int(stats.get("resolved") or 0)
    expectancy = stats.get("expectancy_r_all_fills")
    pf = stats.get("profit_factor_gross_r")
    fill_rate = stats.get("fill_rate_of_anchors")
    entry_error = stats.get("mean_entry_error_atr")
    if (
        fills < MIN_TRAIN_FILLS
        or resolved < MIN_TRAIN_RESOLVED
        or expectancy is None
        or pf is None
    ):
        return None
    stability_weight = min(1.0, fills / 500.0)
    return (
        float(expectancy) * stability_weight
        + 0.08 * float(fill_rate or 0.0)
        + 0.03 * min(float(pf), 5.0)
        - 0.04 * float(entry_error or 0.0)
    )


def _candidate_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = dict(rows[0]) if rows else {}
    return {
        "candidate_key": first.get("candidate_key"),
        "delta_fraction": first.get("delta_fraction"),
        "entry_tier": first.get("entry_tier"),
        "target_multiple": first.get("target_multiple"),
    }


def run() -> int:
    root = Path(os.getenv("XAU_V323_SHARD_DIR", "/tmp/v323-shards"))
    output = Path(
        os.getenv(
            "XAU_V323_FULL_OUTPUT",
            "artifacts/xau-rizan-axy-delta-v323-full.json",
        )
    )
    shards = _load_shards(root)
    if not shards:
        raise SystemExit("XAU_V323_NO_SHARDS")

    years = sorted(int(row["year"]) for row in shards)
    train_years = {year for year in years if year <= TRAIN_END_YEAR}
    oos_years = {year for year in years if year >= OOS_START_YEAR}
    index = _candidate_index(shards)

    candidates: list[dict[str, Any]] = []
    for key, rows in index.items():
        train = _combine(rows, years=train_years)
        oos = _combine(rows, years=oos_years)
        full = _combine(rows)
        score = _score_train(train)
        candidates.append(
            {
                **_candidate_meta(rows),
                "train_2012_2024": train,
                "oos_2025_2026": oos,
                "full_2012_2026": full,
                "train_selection_score": score,
                "train_eligible": score is not None,
            }
        )

    eligible = [row for row in candidates if row["train_selection_score"] is not None]
    eligible.sort(
        key=lambda row: (
            -float(row["train_selection_score"]),
            -float(row["train_2012_2024"].get("expectancy_r_all_fills") or -999.0),
            -int(row["train_2012_2024"].get("fills") or 0),
            float(row["train_2012_2024"].get("mean_entry_error_atr") or 999.0),
        )
    )
    selected = dict(eligible[0]) if eligible else {}

    era_definitions = {
        "2012_2018": set(range(2012, 2019)),
        "2019_2024": set(range(2019, 2025)),
        "2025_2026_OOS": set(range(2025, 2027)),
    }
    selected_eras: dict[str, Any] = {}
    if selected:
        selected_rows = index[str(selected["candidate_key"])]
        for name, era_years in era_definitions.items():
            selected_eras[name] = _combine(selected_rows, years=era_years)

    oos = dict(selected.get("oos_2025_2026") or {})
    oos_pf = oos.get("profit_factor_gross_r")
    oos_expectancy = oos.get("expectancy_r_all_fills")
    oos_fills = int(oos.get("fills") or 0)
    oos_pass = bool(
        selected
        and oos_fills >= 100
        and oos_pf is not None
        and float(oos_pf) >= 1.20
        and oos_expectancy is not None
        and float(oos_expectancy) >= 0.10
    )

    top_train = [
        {
            "candidate_key": row["candidate_key"],
            "delta_fraction": row["delta_fraction"],
            "entry_tier": row["entry_tier"],
            "target_multiple": row["target_multiple"],
            "train_selection_score": row["train_selection_score"],
            "train_fills": row["train_2012_2024"].get("fills"),
            "train_expectancy_r": row["train_2012_2024"].get("expectancy_r_all_fills"),
            "train_profit_factor": row["train_2012_2024"].get("profit_factor_gross_r"),
            "train_win_rate": row["train_2012_2024"].get("win_rate_resolved"),
            "train_entry_error_atr": row["train_2012_2024"].get("mean_entry_error_atr"),
            "oos_fills": row["oos_2025_2026"].get("fills"),
            "oos_expectancy_r": row["oos_2025_2026"].get("expectancy_r_all_fills"),
            "oos_profit_factor": row["oos_2025_2026"].get("profit_factor_gross_r"),
            "oos_win_rate": row["oos_2025_2026"].get("win_rate_resolved"),
            "oos_entry_error_atr": row["oos_2025_2026"].get("mean_entry_error_atr"),
        }
        for row in eligible[:12]
    ]

    payload = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "years": years,
        "year_count": len(years),
        "train_years": sorted(train_years),
        "oos_years": sorted(oos_years),
        "candidate_count": len(candidates),
        "selection_contract": {
            "fit_only_on": "2012-2024",
            "oos_never_used_for_selection": True,
            "minimum_train_fills": MIN_TRAIN_FILLS,
            "minimum_train_resolved": MIN_TRAIN_RESOLVED,
            "score": (
                "expectancy_R_all_fills*min(1,fills/500) "
                "+0.08*fill_rate_of_anchors +0.03*min(PF,5) "
                "-0.04*mean_entry_error_ATR"
            ),
            "friction": "NOT_INCLUDED_GROSS_RESEARCH",
        },
        "selected_train_candidate": selected,
        "selected_candidate_by_era": selected_eras,
        "top_train_candidates": top_train,
        "oos_gate": {
            "status": "HISTORICAL_OOS_PASS_FORWARD_DEMO_REQUIRED" if oos_pass
            else "HISTORICAL_OOS_NOT_READY",
            "minimum_oos_fills": 100,
            "minimum_oos_profit_factor_gross_r": 1.20,
            "minimum_oos_expectancy_r_all_fills": 0.10,
            "pass": oos_pass,
            "forward_demo_required": True,
            "automatic_runtime_promotion": False,
        },
        "all_candidates": candidates,
        "interpretation": (
            "V323 calibrates the reconstructed A/X/Y spacing without using 2025-2026 "
            "to choose the model. Anchor A is formed causally from post-touch M5 reclaim, "
            "impulse and the first confirmed pullback pivot. Entry fill requires a later "
            "M1 touch of A/X/Y. Same-M1 SL/TP ambiguity is resolved STOP_FIRST. Results "
            "exclude spread/commission/slippage and therefore are gross research evidence, "
            "not a production profitability claim. Runtime V320/V322 delta must not be "
            "changed automatically from this artifact; forward DEMO validation is required."
        ),
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        "XAU_RIZAN_AXY_DELTA_V323 "
        f"years={len(years)} candidates={len(candidates)} "
        f"selected={selected.get('candidate_key','NONE')} "
        f"oos_pass={int(oos_pass)} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
