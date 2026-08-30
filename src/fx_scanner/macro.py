from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Mapping

from .exceptions import DataContractError


class MacroStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class CurrencyMacroScore:
    currency: str
    score: float | None
    coverage: float
    status: MacroStatus
    missing_factors: tuple[str, ...]


def score_currency_macro(
    currency: str,
    factors: Mapping[str, float | None],
    weights: Mapping[str, float],
    *,
    minimum_coverage: float = 0.70,
    factor_min: float = -100.0,
    factor_max: float = 100.0,
) -> CurrencyMacroScore:
    """Score one currency without converting missing evidence into neutral zero.

    Observed factors are reweighted over their available weight. A numeric score
    is returned only when observed weight reaches minimum_coverage.
    """
    currency = str(currency).upper().strip()
    if len(currency) != 3:
        raise DataContractError("currency must be a three-letter code")
    if not 0 < minimum_coverage <= 1:
        raise DataContractError("minimum_coverage must be in (0, 1]")
    if not weights:
        raise DataContractError("macro weights are required")

    total_weight = sum(float(w) for w in weights.values())
    if total_weight <= 0:
        raise DataContractError("macro weights must sum to a positive value")

    observed_weight = 0.0
    weighted_sum = 0.0
    missing: list[str] = []
    invalid = False

    for name, raw_weight in weights.items():
        if isinstance(raw_weight, bool):
            raise DataContractError(f"invalid macro weight: {name}")
        weight = float(raw_weight)
        if weight <= 0 or not isfinite(weight):
            raise DataContractError(f"invalid macro weight: {name}")
        value = factors.get(name)
        if value is None:
            missing.append(str(name))
            continue
        if isinstance(value, bool):
            invalid = True
            continue
        value = float(value)
        if not isfinite(value) or value < factor_min or value > factor_max:
            invalid = True
            continue
        observed_weight += weight
        weighted_sum += value * weight

    if invalid:
        return CurrencyMacroScore(currency, None, observed_weight / total_weight, MacroStatus.INVALID, tuple(sorted(missing)))

    coverage = observed_weight / total_weight
    if observed_weight == 0:
        return CurrencyMacroScore(currency, None, 0.0, MacroStatus.MISSING, tuple(sorted(weights)))

    if coverage < minimum_coverage:
        return CurrencyMacroScore(currency, None, coverage, MacroStatus.PARTIAL, tuple(sorted(missing)))

    score = weighted_sum / observed_weight
    status = MacroStatus.AVAILABLE if coverage == 1.0 else MacroStatus.PARTIAL
    return CurrencyMacroScore(currency, score, coverage, status, tuple(sorted(missing)))


def relative_macro_edge(
    base: CurrencyMacroScore,
    quote: CurrencyMacroScore,
) -> float | None:
    if base.score is None or quote.score is None:
        return None
    edge = float(base.score) - float(quote.score)
    return max(-200.0, min(200.0, edge))
