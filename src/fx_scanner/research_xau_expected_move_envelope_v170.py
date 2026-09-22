from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Sequence

import numpy as np

from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars

RESEARCH_VERSION = "XAU_EXPECTED_MOVE_ENVELOPE_V170"
ARTIFACT_CONTRACT = "XAU_EXPECTED_MOVE_ENVELOPE_V170_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

LOOKBACK_MATCHES = 60
VALIDATION_POINTS = 400
HORIZONS = {
    "1h": 4,
    "4h": 16,
    "8h": 32,
}
QUANTILES = (0.50, 0.75, 0.90)


@dataclass(frozen=True, slots=True)
class MoveOutcome:
    index: int
    slot: int
    timestamp: Any
    price: float
    up_points: dict[str, float]
    down_points: dict[str, float]
    abs_close_points: dict[str, float]


def _slot(row: Bar) -> int:
    stamp = ensure_utc(row.timestamp)
    return int(stamp.hour * 4 + stamp.minute // 15)


def _move_outcome(rows: Sequence[Bar], index: int) -> MoveOutcome | None:
    max_horizon = max(HORIZONS.values())
    if index < 0 or index + max_horizon >= len(rows):
        return None
    anchor = float(rows[index].close)
    up_points: dict[str, float] = {}
    down_points: dict[str, float] = {}
    abs_close_points: dict[str, float] = {}
    for label, bars_ahead in HORIZONS.items():
        window = rows[index + 1 : index + bars_ahead + 1]
        up_points[label] = max(
            0.0, max(float(row.high) - anchor for row in window)
        )
        down_points[label] = max(
            0.0, max(anchor - float(row.low) for row in window)
        )
        abs_close_points[label] = abs(
            float(rows[index + bars_ahead].close) - anchor
        )
    return MoveOutcome(
        index=index,
        slot=_slot(rows[index]),
        timestamp=ensure_utc(rows[index].timestamp),
        price=anchor,
        up_points=up_points,
        down_points=down_points,
        abs_close_points=abs_close_points,
    )


def _quantile_payload(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {
        "q50": float(np.quantile(arr, 0.50)),
        "q75": float(np.quantile(arr, 0.75)),
        "q90": float(np.quantile(arr, 0.90)),
        "mean": float(np.mean(arr)),
    }


def _prior_matches(
    outcomes: Sequence[MoveOutcome],
    *,
    target_index: int,
    target_slot: int,
    max_horizon: int,
) -> tuple[MoveOutcome, ...]:
    eligible = [
        row
        for row in outcomes
        if row.slot == target_slot
        and row.index <= target_index - max_horizon
    ]
    return tuple(eligible[-LOOKBACK_MATCHES:])


def _forecast_from_matches(
    matches: Sequence[MoveOutcome],
    *,
    price: float,
) -> dict[str, Any] | None:
    if len(matches) < LOOKBACK_MATCHES:
        return None
    horizons: dict[str, Any] = {}
    for label in HORIZONS:
        up = _quantile_payload([row.up_points[label] for row in matches])
        down = _quantile_payload([row.down_points[label] for row in matches])
        close_abs = _quantile_payload(
            [row.abs_close_points[label] for row in matches]
        )
        if up is None or down is None or close_abs is None:
            return None
        horizons[label] = {
            "up_points": up,
            "down_points": down,
            "abs_close_points": close_abs,
            "levels": {
                "up_q50": float(price + up["q50"]),
                "up_q75": float(price + up["q75"]),
                "up_q90": float(price + up["q90"]),
                "down_q50": float(price - down["q50"]),
                "down_q75": float(price - down["q75"]),
                "down_q90": float(price - down["q90"]),
            },
        }
    return {
        "lookback_matches": len(matches),
        "horizons": horizons,
        "oldest_match_at": ensure_utc(matches[0].timestamp).isoformat(),
        "newest_match_at": ensure_utc(matches[-1].timestamp).isoformat(),
    }


def _coverage(
    *,
    actual: MoveOutcome,
    forecast: dict[str, Any],
) -> dict[str, Any]:
    rows = {}
    for label in HORIZONS:
        f = forecast["horizons"][label]
        rows[label] = {}
        for side, actual_value in (
            ("up", actual.up_points[label]),
            ("down", actual.down_points[label]),
            ("abs_close", actual.abs_close_points[label]),
        ):
            source_key = {
                "up": "up_points",
                "down": "down_points",
                "abs_close": "abs_close_points",
            }[side]
            rows[label][side] = {
                "q50": bool(actual_value <= float(f[source_key]["q50"])),
                "q75": bool(actual_value <= float(f[source_key]["q75"])),
                "q90": bool(actual_value <= float(f[source_key]["q90"])),
            }
    return rows


def evaluate_expected_move_v170(bars: Sequence[Bar]) -> dict[str, Any]:
    rows = _validate_bars(bars)
    max_horizon = max(HORIZONS.values())
    outcomes = tuple(
        outcome
        for index in range(len(rows) - max_horizon)
        if (outcome := _move_outcome(rows, index)) is not None
    )

    validation_candidates = outcomes[-VALIDATION_POINTS:]
    scored = []
    for actual in validation_candidates:
        matches = _prior_matches(
            outcomes,
            target_index=actual.index,
            target_slot=actual.slot,
            max_horizon=max_horizon,
        )
        forecast = _forecast_from_matches(matches, price=actual.price)
        if forecast is None:
            continue
        scored.append(_coverage(actual=actual, forecast=forecast))

    coverage_summary: dict[str, Any] = {}
    for label in HORIZONS:
        coverage_summary[label] = {}
        for side in ("up", "down", "abs_close"):
            side_row = {}
            for q, nominal in (("q50", 0.50), ("q75", 0.75), ("q90", 0.90)):
                values = [
                    float(row[label][side][q])
                    for row in scored
                ]
                observed = None if not values else float(np.mean(values))
                side_row[q] = {
                    "nominal": nominal,
                    "observed_coverage": observed,
                    "calibration_error": None
                    if observed is None
                    else float(observed - nominal),
                }
            coverage_summary[label][side] = side_row

    errors = [
        abs(float(cell["calibration_error"]))
        for horizon in coverage_summary.values()
        for side in horizon.values()
        for cell in side.values()
        if cell["calibration_error"] is not None
    ]

    current_index = len(rows) - 1
    current_matches = _prior_matches(
        outcomes,
        target_index=current_index,
        target_slot=_slot(rows[current_index]),
        max_horizon=max_horizon,
    )
    current = _forecast_from_matches(
        current_matches,
        price=float(rows[current_index].close),
    )
    if current is not None:
        current = {
            "as_of": ensure_utc(rows[current_index].timestamp).isoformat(),
            "price": float(rows[current_index].close),
            "utc_slot": _slot(rows[current_index]),
            **current,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "history_bars": len(rows),
        "lookback_contract": {
            "matching_prior_observations": LOOKBACK_MATCHES,
            "match_key": "UTC_15_MINUTE_SLOT",
            "future_outcome_must_be_fully_known_before_anchor": True,
            "quantiles": list(QUANTILES),
            "horizons": HORIZONS,
            "no_parameter_grid": True,
        },
        "validation": {
            "requested_points": VALIDATION_POINTS,
            "scored_points": len(scored),
            "coverage": coverage_summary,
            "mean_absolute_coverage_error": None
            if not errors
            else float(np.mean(errors)),
            "contract": (
                "PREQUENTIAL_ROLLING_60_MATCHES: each envelope uses only prior "
                "same-UTC-slot observations with the full 8h future already known."
            ),
        },
        "current_envelope": current,
        "decision": {
            "stage": "FORECAST_ENVELOPE_DIAGNOSTIC_ONLY",
            "promotion": False,
            "execution_change": False,
            "note": (
                "V170 estimates move magnitude and target plausibility, not direction. "
                "It is a public-component reconstruction inspired by expected-move "
                "stress testing, not a reconstruction of any proprietary AIRV3 formula."
            ),
        },
    }
