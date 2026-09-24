from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .research_xau_event_conditioning_v193 import (
    build_conditioning_frames,
    event_conditioning_from_frames,
)
from .research_xau_event_walkforward_v193 import (
    _direction,
    _fit_bias,
    _key,
    _year,
)

CONTRACT = "XAU_EVENT_SD_POST_WALKFORWARD_V193_1"
SCHEME = "FAMILY_SURPRISE_MARKET_STRUCTURE"
FIRST_TEST_YEAR = 2017


def oos_signal_rows(
    rows: Sequence[dict[str, Any]],
    *,
    scheme: str = SCHEME,
    first_test_year: int = FIRST_TEST_YEAR,
) -> list[dict[str, Any]]:
    years = sorted({year for row in rows if (year := _year(row)) is not None})
    output: list[dict[str, Any]] = []
    for test_year in years:
        if test_year < first_test_year:
            continue
        train = [row for row in rows if (_year(row) or 0) < test_year]
        test = [row for row in rows if _year(row) == test_year]
        fitted = _fit_bias(train, scheme=scheme)
        for row in test:
            if scheme != "FAMILY" and str(row.get("attribution") or "") != "SINGLE_EVENT":
                continue
            model = fitted.get(_key(row, scheme))
            if model is None:
                continue
            predicted = str(model.get("predicted") or "ABSTAIN")
            if predicted == "ABSTAIN":
                continue
            output.append(
                {
                    "cluster_id": row.get("cluster_id"),
                    "scheduled_at": row.get("scheduled_at"),
                    "test_year": test_year,
                    "family": row.get("family"),
                    "surprise_sign": dict(row.get("surprise") or {}).get("sign"),
                    "predicted_direction": predicted,
                    "actual_direction": _direction(row),
                    "model_n": model.get("n"),
                    "model_up_frequency": model.get("up_frequency"),
                    "conditioning_key": row.get("conditioning_key"),
                }
            )
    output.sort(key=lambda row: str(row.get("scheduled_at") or ""))
    return output


def _load_full_artifact(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if str(payload.get("decision") or "") != "REACTION_BACKFILL_WALKFORWARD_READY":
        raise RuntimeError(
            "V193 base artifact is not REACTION_BACKFILL_WALKFORWARD_READY"
        )
    rows = list(payload.get("reactions") or [])
    if not rows:
        raise RuntimeError("V193 base artifact contains no reaction rows")
    return payload


def _load_price(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"V193 SD price CSV missing columns: {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if frame.empty:
        raise RuntimeError("V193 SD price CSV parsed empty")
    return frame


def _compact_zone(value: Any) -> dict[str, Any]:
    zone = dict(value or {})
    if not zone:
        return {}
    keep = (
        "zone_id",
        "timeframe",
        "direction",
        "low",
        "high",
        "proximal",
        "distal",
        "pattern",
        "zone_class",
        "research_score",
        "distance_atr",
        "status",
        "age_bucket",
    )
    output = {key: zone.get(key) for key in keep if key in zone}
    lifecycle = dict(zone.get("lifecycle") or {})
    if lifecycle:
        output["lifecycle"] = {
            key: lifecycle.get(key)
            for key in (
                "active",
                "freshness",
                "touch_count",
                "mitigation_depth",
                "invalidated_at",
            )
            if key in lifecycle
        }
    liquidity = dict(zone.get("liquidity") or {})
    if liquidity:
        output["liquidity"] = {
            "confluence_count": liquidity.get("confluence_count"),
            "sources": list(liquidity.get("sources") or []),
        }
    return output


def _alignment(predicted: str, sd_direction: str | None) -> str:
    mapping = {"UP": "LONG", "DOWN": "SHORT"}
    predicted_side = mapping.get(str(predicted or "").upper())
    sd_side = str(sd_direction or "").upper()
    if predicted_side not in {"LONG", "SHORT"}:
        return "PREDICTION_UNKNOWN"
    if sd_side not in {"LONG", "SHORT"}:
        return "NO_ACTIVE_SD_DIRECTION"
    return "ALIGNED" if predicted_side == sd_side else "OPPOSED"


def evaluate_year(
    *,
    full_artifact: dict[str, Any],
    price: pd.DataFrame,
    year: int,
) -> dict[str, Any]:
    reactions = [dict(row) for row in full_artifact.get("reactions") or []]
    signals = [
        row
        for row in oos_signal_rows(reactions)
        if int(row.get("test_year") or 0) == int(year)
    ]
    frames = build_conditioning_frames(price)
    evaluated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for signal in signals:
        raw_at = str(signal.get("scheduled_at") or "")
        try:
            event_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
            if event_at.tzinfo is None:
                raise ValueError("naive event timestamp")
            event_at = event_at.astimezone(UTC)
            context = event_conditioning_from_frames(
                frames,
                event_at=event_at,
                supply_demand_lookback_days=90,
                include_supply_demand=True,
            )
            sd = dict(context.get("supply_demand") or {})
            active_direction = sd.get("active_reaction_direction")
            actual = signal.get("actual_direction")
            predicted = signal.get("predicted_direction")
            evaluated.append(
                {
                    **signal,
                    "sd_state": sd.get("state"),
                    "sd_active_reaction_direction": active_direction,
                    "sd_source_timeframe": sd.get("source_timeframe"),
                    "sd_source_freshness": sd.get("source_freshness"),
                    "sd_alignment": _alignment(str(predicted), active_direction),
                    "nearest_demand": _compact_zone(sd.get("nearest_demand")),
                    "nearest_supply": _compact_zone(sd.get("nearest_supply")),
                    "active_source_zone": _compact_zone(sd.get("active_source_zone")),
                    "prediction_correct": (
                        None
                        if actual not in {"UP", "DOWN"}
                        else str(predicted) == str(actual)
                    ),
                    "execution_influence": False,
                    "execution_authority": False,
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "scheduled_at": raw_at,
                    "cluster_id": signal.get("cluster_id"),
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )

    return {
        "contract": CONTRACT,
        "year": year,
        "scheme": SCHEME,
        "signal_count": len(signals),
        "evaluated_count": len(evaluated),
        "error_count": len(errors),
        "coverage": None if not signals else len(evaluated) / len(signals),
        "rows": evaluated,
        "errors": errors,
        "policy_effect": "POST_WALK_FORWARD_DIAGNOSTIC_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    year = int(os.getenv("XAU_V193_YEAR", "0") or 0)
    if year < FIRST_TEST_YEAR or year > datetime.now(tz=UTC).year:
        raise SystemExit(f"XAU_V193_SD_YEAR_INVALID:{year}")

    full_path = Path(
        os.getenv(
            "XAU_V193_FULL_ARTIFACT",
            "/tmp/v193-base/xau-event-reaction-v193-full.json",
        )
    )
    price_path = Path(os.getenv("XAU_V193_PRICE_CSV", "").strip())
    output = Path(
        os.getenv(
            "XAU_V193_SD_OUTPUT",
            f"artifacts/xau-event-sd-v193-{year}.json",
        )
    )
    if not full_path.exists():
        raise SystemExit(f"XAU_V193_FULL_ARTIFACT_NOT_FOUND:{full_path}")
    if not price_path.exists():
        raise SystemExit(f"XAU_V193_PRICE_CSV_NOT_FOUND:{price_path}")

    artifact = _load_full_artifact(full_path)
    price = _load_price(price_path)
    result = evaluate_year(full_artifact=artifact, price=price, year=year)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False, default=str)
        + "\n"
    )

    healthy = (
        result["signal_count"] == 0
        or (
            result["evaluated_count"] > 0
            and float(result["coverage"] or 0.0) >= 0.90
        )
    )
    print(
        "XAU_EVENT_SD_POST_WF_V193 "
        f"year={year} signals={result['signal_count']} "
        f"evaluated={result['evaluated_count']} errors={result['error_count']} "
        f"coverage={result['coverage']} healthy={int(healthy)} "
        "execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
