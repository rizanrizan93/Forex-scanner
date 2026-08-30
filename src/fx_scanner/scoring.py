from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from .exceptions import DataContractError
from .models import SignalState


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: float | None
    coverage: float
    state: SignalState
    missing_components: tuple[str, ...]


def weighted_score(
    components: Mapping[str, float | None],
    weights: Mapping[str, float],
    *,
    minimum_coverage: float = 0.80,
) -> ScoreResult:
    """Weighted 0..100 score with explicit missing-evidence coverage."""
    total_weight = sum(float(v) for v in weights.values())
    if total_weight <= 0:
        raise DataContractError("score weights must sum positive")
    observed_weight = 0.0
    weighted_sum = 0.0
    missing: list[str] = []

    for name, weight_raw in weights.items():
        if isinstance(weight_raw, bool):
            raise DataContractError(f"score weight {name} cannot be boolean")
        weight = float(weight_raw)
        if not isfinite(weight) or weight <= 0:
            raise DataContractError(f"score weight {name} must be positive finite")
        value = components.get(name)
        if value is None:
            missing.append(name)
            continue
        if isinstance(value, bool):
            raise DataContractError(f"score component {name} cannot be boolean")
        value = float(value)
        if not isfinite(value) or not 0 <= value <= 100:
            raise DataContractError(f"score component {name} must be in [0,100]")
        observed_weight += weight
        weighted_sum += value * weight

    coverage = observed_weight / total_weight
    if observed_weight == 0 or coverage < minimum_coverage:
        return ScoreResult(None, coverage, SignalState.NO_TRADE, tuple(sorted(missing)))

    score = weighted_sum / observed_weight
    return ScoreResult(score, coverage, SignalState.NO_TRADE, tuple(sorted(missing)))


def state_from_conviction(
    score: float | None,
    *,
    hard_guards_clear: bool,
    thresholds: Mapping[str, float],
) -> SignalState:
    if score is None or not hard_guards_clear:
        return SignalState.NO_TRADE
    if score >= float(thresholds["execution_candidate_min"]):
        return SignalState.EXECUTION_READY
    if score >= float(thresholds["armed_min"]):
        return SignalState.ARMED
    if score >= float(thresholds["setup_forming_min"]):
        return SignalState.SETUP_FORMING
    if score >= float(thresholds["watch_min"]):
        return SignalState.WATCH
    return SignalState.NO_TRADE


def score_with_state(
    components: Mapping[str, float | None],
    weights: Mapping[str, float],
    thresholds: Mapping[str, float],
    *,
    hard_guards_clear: bool,
    minimum_coverage: float = 0.80,
) -> ScoreResult:
    base = weighted_score(components, weights, minimum_coverage=minimum_coverage)
    state = state_from_conviction(base.score, hard_guards_clear=hard_guards_clear, thresholds=thresholds)
    return ScoreResult(base.score, base.coverage, state, base.missing_components)
