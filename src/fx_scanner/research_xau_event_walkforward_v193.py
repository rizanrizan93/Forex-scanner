from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Sequence

from .research_xau_event_reaction_v193 import build_reaction_atlas
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_event_reaction_v193_full"
ARTIFACT_CONTRACT = "XAU_EVENT_REACTION_V193_FULL_1"
TRAIN_MIN = 20
BIAS_UP = 0.60
BIAS_DOWN = 0.40


def _year(row: dict[str, Any]) -> int | None:
    raw = row.get("scheduled_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).year
    except ValueError:
        return None


def era_label(year: int) -> str:
    if year <= 2015:
        return "ERA_2012_2015"
    if year <= 2019:
        return "ERA_2016_2019"
    if year <= 2022:
        return "ERA_2020_2022"
    return "ERA_2023_CURRENT"


def _direction(row: dict[str, Any], field: str = "r15m_atr") -> str | None:
    value = row.get(field)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 0:
        return "UP"
    if number < 0:
        return "DOWN"
    return None


def _surprise(row: dict[str, Any]) -> str:
    return str(dict(row.get("surprise") or {}).get("sign") or "MISSING")


def _h1_structure(row: dict[str, Any]) -> str:
    conditioning = dict(row.get("conditioning") or {})
    mtf = dict(conditioning.get("mtf") or {})
    h1 = dict(mtf.get("H1") or {})
    return str(h1.get("market_structure") or "UNKNOWN")


def _h4_stack(row: dict[str, Any]) -> str:
    conditioning = dict(row.get("conditioning") or {})
    mtf = dict(conditioning.get("mtf") or {})
    h4 = dict(mtf.get("H4") or {})
    return str(h4.get("ema_stack") or "UNKNOWN")


def _sd_direction(row: dict[str, Any]) -> str:
    conditioning = dict(row.get("conditioning") or {})
    sd = dict(conditioning.get("supply_demand") or {})
    return str(sd.get("active_reaction_direction") or "NONE")


def _key(row: dict[str, Any], scheme: str) -> tuple[str, ...]:
    family = str(row.get("family") or "UNKNOWN")
    if scheme == "FAMILY":
        return (family,)
    if scheme == "FAMILY_SURPRISE":
        return (family, _surprise(row))
    if scheme == "FAMILY_SURPRISE_STRUCTURE":
        return (
            family,
            _surprise(row),
            _h1_structure(row),
            _h4_stack(row),
            _sd_direction(row),
        )
    raise ValueError(f"unknown V193 scheme: {scheme}")


def _fit_bias(
    rows: Sequence[dict[str, Any]],
    *,
    scheme: str,
) -> dict[tuple[str, ...], dict[str, Any]]:
    buckets: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for row in rows:
        direction = _direction(row)
        if direction is None:
            continue
        if scheme != "FAMILY" and str(row.get("attribution") or "") != "SINGLE_EVENT":
            continue
        buckets[_key(row, scheme)].append(direction)

    fitted: dict[tuple[str, ...], dict[str, Any]] = {}
    for key, directions in buckets.items():
        if len(directions) < TRAIN_MIN:
            continue
        up = sum(direction == "UP" for direction in directions)
        up_freq = up / len(directions)
        if up_freq >= BIAS_UP:
            predicted = "UP"
        elif up_freq <= BIAS_DOWN:
            predicted = "DOWN"
        else:
            predicted = "ABSTAIN"
        fitted[key] = {
            "n": len(directions),
            "up_frequency": up_freq,
            "predicted": predicted,
        }
    return fitted


def walk_forward(
    rows: Sequence[dict[str, Any]],
    *,
    scheme: str,
    first_test_year: int = 2017,
) -> dict[str, Any]:
    years = sorted({year for row in rows if (year := _year(row)) is not None})
    folds: list[dict[str, Any]] = []
    for test_year in years:
        if test_year < first_test_year:
            continue
        train = [row for row in rows if (_year(row) or 0) < test_year]
        test = [row for row in rows if _year(row) == test_year]
        fitted = _fit_bias(train, scheme=scheme)
        eligible = 0
        correct = 0
        abstain = 0
        no_model = 0
        for row in test:
            actual = _direction(row)
            if actual is None:
                continue
            if scheme != "FAMILY" and str(row.get("attribution") or "") != "SINGLE_EVENT":
                continue
            model = fitted.get(_key(row, scheme))
            if model is None:
                no_model += 1
                continue
            predicted = str(model["predicted"])
            if predicted == "ABSTAIN":
                abstain += 1
                continue
            eligible += 1
            correct += int(predicted == actual)

        denominator = sum(
            1
            for row in test
            if _direction(row) is not None
            and (scheme == "FAMILY" or str(row.get("attribution") or "") == "SINGLE_EVENT")
        )
        folds.append(
            {
                "test_year": test_year,
                "train_start": min((_year(row) for row in train if _year(row) is not None), default=None),
                "train_end": test_year - 1,
                "train_rows": len(train),
                "test_rows": len(test),
                "directional_test_rows": denominator,
                "eligible_predictions": eligible,
                "correct_predictions": correct,
                "directional_accuracy": None if eligible == 0 else correct / eligible,
                "prediction_coverage": None if denominator == 0 else eligible / denominator,
                "abstain": abstain,
                "no_model": no_model,
            }
        )

    total_eligible = sum(int(row["eligible_predictions"]) for row in folds)
    total_correct = sum(int(row["correct_predictions"]) for row in folds)
    total_directional = sum(int(row["directional_test_rows"]) for row in folds)
    return {
        "scheme": scheme,
        "train_min": TRAIN_MIN,
        "bias_up_threshold": BIAS_UP,
        "bias_down_threshold": BIAS_DOWN,
        "folds": folds,
        "total_eligible_predictions": total_eligible,
        "total_correct_predictions": total_correct,
        "aggregate_directional_accuracy": (
            None if total_eligible == 0 else total_correct / total_eligible
        ),
        "aggregate_prediction_coverage": (
            None if total_directional == 0 else total_eligible / total_directional
        ),
        "interpretation": (
            "Simple preregistered expanding-window directional benchmark. "
            "Accuracy is conditional on non-abstained eligible predictions and is not "
            "a production probability or promotion decision."
        ),
    }


def _era_summary(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        year = _year(row)
        if year is None:
            continue
        grouped[era_label(year)].append(row)

    output: list[dict[str, Any]] = []
    for era, subset in sorted(grouped.items()):
        atlas = build_reaction_atlas(subset, minimum_samples=10)
        directional = [row for row in subset if _direction(row) is not None]
        abs15 = [
            abs(float(row["r15m_atr"]))
            for row in directional
            if row.get("r15m_atr") is not None
        ]
        output.append(
            {
                "era": era,
                "n": len(subset),
                "directional_n": len(directional),
                "median_abs_r15m_atr": None if not abs15 else median(abs15),
                "atlas": atlas,
            }
        )
    return output


def load_year_artifacts(directory: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reactions: list[dict[str, Any]] = []
    shards: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("xau-event-reaction-v193-*.json")):
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        year = payload.get("year")
        shard_rows = list(payload.get("reactions") or [])
        reactions.extend(dict(row) for row in shard_rows)
        shards.append(
            {
                "year": year,
                "reaction_count": len(shard_rows),
                "event_count": payload.get("event_count"),
                "cluster_count": payload.get("cluster_count"),
                "skipped_no_price": payload.get("skipped_no_price"),
                "artifact": str(path),
            }
        )
    reactions.sort(key=lambda row: str(row.get("scheduled_at") or ""))
    return reactions, shards


def build_full_artifact(
    reactions: Sequence[dict[str, Any]],
    shards: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    years = sorted({year for row in reactions if (year := _year(row)) is not None})
    full_atlas = build_reaction_atlas(reactions, minimum_samples=30)
    walkforwards = [
        walk_forward(reactions, scheme=scheme)
        for scheme in (
            "FAMILY",
            "FAMILY_SURPRISE",
            "FAMILY_SURPRISE_STRUCTURE",
        )
    ]
    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "year_min": None if not years else min(years),
        "year_max": None if not years else max(years),
        "years_present": years,
        "reaction_count": len(reactions),
        "shards": list(shards),
        "atlas": full_atlas,
        "eras": _era_summary(reactions),
        "walk_forward": walkforwards,
        "decision": (
            "FULL_BACKFILL_RESEARCH_READY"
            if years and min(years) <= 2012 and max(years) >= datetime.now(tz=UTC).year
            and len(reactions) >= 1000
            else "BACKFILL_INCOMPLETE"
        ),
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    input_dir = Path(os.getenv("XAU_V193_SHARD_DIR", "artifacts/v193-shards"))
    output = Path(
        os.getenv(
            "XAU_V193_FULL_OUTPUT",
            "artifacts/xau-event-reaction-v193-full.json",
        )
    )
    reactions, shards = load_year_artifacts(input_dir)
    artifact = build_full_artifact(reactions, shards)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False, default=str)
        + "\n"
    )

    details = {
        key: value
        for key, value in artifact.items()
        if key not in {"atlas", "eras", "walk_forward"}
    }
    details["walk_forward_summary"] = [
        {
            "scheme": row["scheme"],
            "aggregate_directional_accuracy": row["aggregate_directional_accuracy"],
            "aggregate_prediction_coverage": row["aggregate_prediction_coverage"],
            "eligible": row["total_eligible_predictions"],
        }
        for row in artifact["walk_forward"]
    ]
    details["era_summary"] = [
        {
            "era": row["era"],
            "n": row["n"],
            "median_abs_r15m_atr": row["median_abs_r15m_atr"],
        }
        for row in artifact["eras"]
    ]

    healthy = artifact["decision"] == "FULL_BACKFILL_RESEARCH_READY"
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=healthy,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    print(
        "XAU_EVENT_REACTION_V193_FULL "
        f"years={artifact['year_min']}-{artifact['year_max']} "
        f"reactions={artifact['reaction_count']} shards={len(shards)} "
        f"decision={artifact['decision']} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
