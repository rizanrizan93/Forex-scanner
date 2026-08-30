from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .guards import GuardResult, evaluate_hard_guards
from .models import SignalState, ensure_utc
from .ranking import PairRank
from .scoring import ScoreResult, score_with_state


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    symbol: str
    direction: str
    timestamp: datetime
    pair_rank: int
    pair_edge: float
    conviction_score: float | None
    coverage: float
    pair_coverage: float
    state: SignalState
    guards: tuple[str, ...]
    missing_components: tuple[str, ...]
    pair_missing_components: tuple[str, ...]


def build_decision(
    *,
    rank: PairRank,
    timestamp: datetime,
    conviction_components: Mapping[str, float | None],
    conviction_weights: Mapping[str, float],
    thresholds: Mapping[str, float],
    guard_flags: Mapping[str, bool],
    required_guards: tuple[str, ...] | list[str],
    minimum_coverage: float = 0.80,
    minimum_pair_coverage: float = 0.85,
) -> DecisionSnapshot:
    if not 0 < minimum_pair_coverage <= 1:
        raise ValueError("minimum_pair_coverage must be in (0,1]")
    guard_result: GuardResult = evaluate_hard_guards(
        required_names=required_guards,
        **dict(guard_flags),
    )
    internal_guards: list[str] = []
    if rank.direction == "NEUTRAL":
        internal_guards.append("PAIR_DIRECTION_NEUTRAL")
    if rank.coverage < minimum_pair_coverage:
        internal_guards.append("PAIR_COVERAGE_BLOCK")
    combined_guards = tuple(sorted(set(guard_result.active_guards).union(internal_guards)))

    score: ScoreResult = score_with_state(
        conviction_components,
        conviction_weights,
        thresholds,
        hard_guards_clear=not combined_guards,
        minimum_coverage=minimum_coverage,
    )
    return DecisionSnapshot(
        symbol=rank.symbol,
        direction=rank.direction,
        timestamp=ensure_utc(timestamp),
        pair_rank=rank.rank,
        pair_edge=rank.pair_edge,
        conviction_score=score.score,
        coverage=score.coverage,
        pair_coverage=rank.coverage,
        state=score.state,
        guards=combined_guards,
        missing_components=score.missing_components,
        pair_missing_components=rank.missing_components,
    )
