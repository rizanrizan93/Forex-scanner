from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isfinite, log
from typing import Any, Sequence

import numpy as np

from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _indicator_series, _validate_bars

RESEARCH_VERSION = "XAU_ANALOG_PATH_FORECAST_V168"
ARTIFACT_CONTRACT = "XAU_ANALOG_PATH_FORECAST_V168_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

SYMBOL = "XAUUSD"
HORIZON_BARS = 32          # 8 hours on M15
ANCHOR_STRIDE = 4          # hourly historical states
K_NEIGHBORS = 64
MIN_CANDIDATES = 256
VALIDATION_POINTS = 400
WARMUP_BARS = 240
FIRST_HIT_ATR = 1.0

FIRST_HIT_CLASSES = ("UP", "DOWN", "NEITHER", "AMBIGUOUS")
PATH_CLASSES = (
    "UP_CONTINUE",
    "UP_THEN_DOWN",
    "DOWN_CONTINUE",
    "DOWN_THEN_UP",
    "RANGE",
    "WHIPSAW_SAME_BAR",
)


@dataclass(frozen=True, slots=True)
class AnalogState:
    index: int
    timestamp: Any
    session: str
    features: tuple[float, ...]
    outcome: dict[str, Any] | None


def _session(row: Bar) -> str:
    hour = ensure_utc(row.timestamp).hour
    if hour >= 22 or hour < 7:
        return "ASIA"
    if 7 <= hour < 12:
        return "EUROPE"
    if 12 <= hour < 21:
        return "US"
    return "OFF_SESSION"


def _clip(value: float, low: float = -4.0, high: float = 4.0) -> float:
    return max(low, min(high, float(value)))


def _feature_at(
    rows: Sequence[Bar],
    indicators: dict[str, tuple[float | None, ...]],
    index: int,
) -> tuple[float, ...] | None:
    if index < WARMUP_BARS or index >= len(rows):
        return None
    atr = indicators["atr"][index]
    ema20 = indicators["ema20"][index]
    ema50 = indicators["ema50"][index]
    ema200 = indicators["ema200"][index]
    adx = indicators["adx"][index]
    plus_di = indicators["plus_di"][index]
    minus_di = indicators["minus_di"][index]
    if None in (atr, ema20, ema50, ema200, adx, plus_di, minus_di):
        return None
    atr = float(atr)
    if not isfinite(atr) or atr <= 0:
        return None

    close = float(rows[index].close)
    prior_1h = float(rows[index - 4].close)
    prior_4h = float(rows[index - 16].close)
    prior_8h = float(rows[index - 32].close)
    lookback = rows[index - 31 : index + 1]
    rolling_high = max(float(row.high) for row in lookback)
    rolling_low = min(float(row.low) for row in lookback)
    span = max(rolling_high - rolling_low, 1e-12)
    range_loc = 2.0 * ((close - rolling_low) / span) - 1.0
    body = (float(rows[index].close) - float(rows[index].open)) / atr
    atr_fraction = atr / max(abs(close), 1e-12)

    return (
        _clip((close - prior_1h) / atr),
        _clip((close - prior_4h) / atr),
        _clip((close - prior_8h) / atr),
        _clip((close - float(ema20)) / atr),
        _clip((close - float(ema50)) / atr),
        _clip((close - float(ema200)) / atr),
        _clip(float(adx) / 25.0, 0.0, 4.0),
        _clip((float(plus_di) - float(minus_di)) / 25.0),
        _clip(range_loc, -1.0, 1.0),
        _clip(body),
        _clip(atr_fraction * 1000.0, 0.0, 4.0),
    )


def _path_outcome(rows: Sequence[Bar], index: int, atr: float) -> dict[str, Any] | None:
    if index < 0 or index + HORIZON_BARS >= len(rows) or atr <= 0:
        return None
    anchor = float(rows[index].close)
    up_level = anchor + FIRST_HIT_ATR * atr
    down_level = anchor - FIRST_HIT_ATR * atr

    first_up = None
    first_down = None
    max_up = 0.0
    max_down = 0.0
    for offset in range(1, HORIZON_BARS + 1):
        row = rows[index + offset]
        max_up = max(max_up, (float(row.high) - anchor) / atr)
        max_down = max(max_down, (anchor - float(row.low)) / atr)
        if first_up is None and float(row.high) >= up_level:
            first_up = offset
        if first_down is None and float(row.low) <= down_level:
            first_down = offset

    if first_up is None and first_down is None:
        first_hit = "NEITHER"
        path = "RANGE"
    elif first_up is not None and first_down is not None and first_up == first_down:
        first_hit = "AMBIGUOUS"
        path = "WHIPSAW_SAME_BAR"
    elif first_down is None or (first_up is not None and first_up < first_down):
        first_hit = "UP"
        path = "UP_THEN_DOWN" if first_down is not None else "UP_CONTINUE"
    else:
        first_hit = "DOWN"
        path = "DOWN_THEN_UP" if first_up is not None else "DOWN_CONTINUE"

    def ret(offset: int) -> float:
        return (float(rows[index + offset].close) - anchor) / atr

    return {
        "first_hit": first_hit,
        "path": path,
        "first_up_bar": first_up,
        "first_down_bar": first_down,
        "max_up_atr": float(max_up),
        "max_down_atr": float(max_down),
        "return_1h_atr": float(ret(4)),
        "return_4h_atr": float(ret(16)),
        "return_8h_atr": float(ret(32)),
    }


def _probabilities(values: Sequence[str], classes: Sequence[str]) -> dict[str, float]:
    counts = Counter(str(value) for value in values)
    total = max(1, len(values))
    return {name: float(counts.get(name, 0) / total) for name in classes}


def _entropy_confidence(probabilities: dict[str, float]) -> float:
    values = [float(v) for v in probabilities.values() if float(v) > 0]
    if len(probabilities) <= 1:
        return 1.0
    entropy = -sum(p * log(p) for p in values)
    maximum = log(len(probabilities))
    return float(max(0.0, min(1.0, 1.0 - entropy / maximum)))


def _quantiles(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    return {
        "q10": float(np.quantile(arr, 0.10)),
        "q25": float(np.quantile(arr, 0.25)),
        "q50": float(np.quantile(arr, 0.50)),
        "q75": float(np.quantile(arr, 0.75)),
        "q90": float(np.quantile(arr, 0.90)),
    }


def _neighbor_forecast(
    states: Sequence[AnalogState],
    *,
    target_features: tuple[float, ...],
    target_session: str,
    target_index: int,
    k: int = K_NEIGHBORS,
) -> dict[str, Any] | None:
    candidates = [
        state
        for state in states
        if state.outcome is not None
        and state.session == target_session
        and state.index <= target_index - HORIZON_BARS
    ]
    if len(candidates) < MIN_CANDIDATES:
        return None

    matrix = np.asarray([state.features for state in candidates], dtype=float)
    target = np.asarray(target_features, dtype=float)
    distances = np.sqrt(np.sum((matrix - target) ** 2, axis=1))
    take = min(int(k), len(candidates))
    selected_positions = np.argpartition(distances, take - 1)[:take]
    selected_positions = selected_positions[np.argsort(distances[selected_positions])]
    neighbors = [candidates[int(pos)] for pos in selected_positions]
    neighbor_distances = [float(distances[int(pos)]) for pos in selected_positions]

    first_probs = _probabilities(
        [str(state.outcome["first_hit"]) for state in neighbors if state.outcome],
        FIRST_HIT_CLASSES,
    )
    path_probs = _probabilities(
        [str(state.outcome["path"]) for state in neighbors if state.outcome],
        PATH_CLASSES,
    )

    return {
        "neighbors": len(neighbors),
        "candidate_pool": len(candidates),
        "first_hit_probabilities": first_probs,
        "path_probabilities": path_probs,
        "first_hit_top": max(first_probs, key=first_probs.get),
        "path_top": max(path_probs, key=path_probs.get),
        "confidence_entropy": _entropy_confidence(path_probs),
        "distance": {
            "nearest": min(neighbor_distances),
            "median": float(np.median(np.asarray(neighbor_distances))),
            "furthest_selected": max(neighbor_distances),
        },
        "excursion_atr": {
            "max_up": _quantiles([float(state.outcome["max_up_atr"]) for state in neighbors if state.outcome]),
            "max_down": _quantiles([float(state.outcome["max_down_atr"]) for state in neighbors if state.outcome]),
        },
        "return_atr": {
            "1h": _quantiles([float(state.outcome["return_1h_atr"]) for state in neighbors if state.outcome]),
            "4h": _quantiles([float(state.outcome["return_4h_atr"]) for state in neighbors if state.outcome]),
            "8h": _quantiles([float(state.outcome["return_8h_atr"]) for state in neighbors if state.outcome]),
        },
        "closest_analogs": [
            {
                "timestamp": ensure_utc(state.timestamp).isoformat(),
                "distance": float(distance),
                "first_hit": state.outcome["first_hit"],
                "path": state.outcome["path"],
                "return_8h_atr": state.outcome["return_8h_atr"],
                "max_up_atr": state.outcome["max_up_atr"],
                "max_down_atr": state.outcome["max_down_atr"],
            }
            for state, distance in zip(neighbors[:8], neighbor_distances[:8])
            if state.outcome is not None
        ],
    }


def _one_hot(label: str, classes: Sequence[str]) -> np.ndarray:
    return np.asarray([1.0 if label == name else 0.0 for name in classes], dtype=float)


def _validate_forecast(states: Sequence[AnalogState]) -> dict[str, Any]:
    eligible = [state for state in states if state.outcome is not None]
    evaluation = eligible[-VALIDATION_POINTS:]
    rows = []
    for state in evaluation:
        forecast = _neighbor_forecast(
            states,
            target_features=state.features,
            target_session=state.session,
            target_index=state.index,
        )
        if forecast is None:
            continue
        candidates = [
            prior
            for prior in states
            if prior.outcome is not None
            and prior.session == state.session
            and prior.index <= state.index - HORIZON_BARS
        ]
        baseline_probs = _probabilities(
            [str(prior.outcome["first_hit"]) for prior in candidates if prior.outcome],
            FIRST_HIT_CLASSES,
        )
        actual = str(state.outcome["first_hit"])
        model = np.asarray([forecast["first_hit_probabilities"][name] for name in FIRST_HIT_CLASSES])
        baseline = np.asarray([baseline_probs[name] for name in FIRST_HIT_CLASSES])
        truth = _one_hot(actual, FIRST_HIT_CLASSES)
        model_brier = float(np.sum((model - truth) ** 2))
        baseline_brier = float(np.sum((baseline - truth) ** 2))
        path_actual = str(state.outcome["path"])
        rows.append(
            {
                "model_brier": model_brier,
                "baseline_brier": baseline_brier,
                "first_hit_correct": forecast["first_hit_top"] == actual,
                "path_correct": forecast["path_top"] == path_actual,
                "top_probability": max(forecast["first_hit_probabilities"].values()),
            }
        )

    if not rows:
        return {
            "evaluation_points": 0,
            "model_brier": None,
            "baseline_brier": None,
            "brier_skill_score": None,
            "first_hit_top1_accuracy": None,
            "path_top1_accuracy": None,
            "mean_top_probability": None,
        }

    model_brier = float(np.mean([row["model_brier"] for row in rows]))
    baseline_brier = float(np.mean([row["baseline_brier"] for row in rows]))
    skill = None if baseline_brier <= 0 else float(1.0 - model_brier / baseline_brier)
    return {
        "evaluation_points": len(rows),
        "model_brier": model_brier,
        "baseline_brier": baseline_brier,
        "brier_skill_score": skill,
        "first_hit_top1_accuracy": float(np.mean([row["first_hit_correct"] for row in rows])),
        "path_top1_accuracy": float(np.mean([row["path_correct"] for row in rows])),
        "mean_top_probability": float(np.mean([row["top_probability"] for row in rows])),
        "validation_contract": (
            "PREQUENTIAL_PAST_ONLY: every validation forecast uses only same-session "
            "analogs whose 8h outcome was fully known before the evaluation anchor."
        ),
    }


def evaluate_analog_path_forecast_v168(bars: Sequence[Bar]) -> dict[str, Any]:
    rows = _validate_bars(bars)
    indicators = _indicator_series(rows)
    states: list[AnalogState] = []

    last_outcome_anchor = len(rows) - HORIZON_BARS - 1
    for index in range(WARMUP_BARS, last_outcome_anchor + 1, ANCHOR_STRIDE):
        features = _feature_at(rows, indicators, index)
        atr = indicators["atr"][index]
        if features is None or atr is None or float(atr) <= 0:
            continue
        states.append(
            AnalogState(
                index=index,
                timestamp=ensure_utc(rows[index].timestamp),
                session=_session(rows[index]),
                features=features,
                outcome=_path_outcome(rows, index, float(atr)),
            )
        )

    current_index = len(rows) - 1
    current_features = _feature_at(rows, indicators, current_index)
    current_forecast = None
    if current_features is not None:
        current_forecast = _neighbor_forecast(
            states,
            target_features=current_features,
            target_session=_session(rows[current_index]),
            target_index=current_index,
        )
        if current_forecast is not None:
            current_forecast = {
                "as_of": ensure_utc(rows[current_index].timestamp).isoformat(),
                "price": float(rows[current_index].close),
                "session": _session(rows[current_index]),
                "atr": float(indicators["atr"][current_index]),
                **current_forecast,
            }

    validation = _validate_forecast(states)
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "symbol": SYMBOL,
        "timeframe": "M15",
        "history_bars": len(rows),
        "analog_states": len(states),
        "horizon_bars": HORIZON_BARS,
        "horizon_hours": HORIZON_BARS * 0.25,
        "anchor_stride_bars": ANCHOR_STRIDE,
        "k_neighbors": K_NEIGHBORS,
        "first_hit_atr": FIRST_HIT_ATR,
        "features": [
            "return_1h_atr",
            "return_4h_atr",
            "return_8h_atr",
            "close_minus_ema20_atr",
            "close_minus_ema50_atr",
            "close_minus_ema200_atr",
            "adx_scaled",
            "di_spread_scaled",
            "rolling_8h_range_location",
            "current_bar_body_atr",
            "atr_fraction_scaled",
        ],
        "validation": validation,
        "current_forecast": current_forecast,
        "decision": {
            "stage": "DIAGNOSTIC_ONLY",
            "promotion": False,
            "execution_change": False,
            "note": (
                "V168 measures whether nearest historical same-session states have "
                "positive out-of-sample path forecasting skill. It does not authorize trades."
            ),
        },
    }
