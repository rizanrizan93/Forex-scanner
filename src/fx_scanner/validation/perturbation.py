from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..exceptions import DataContractError
from .metrics import PerformanceMetrics


@dataclass(frozen=True, slots=True)
class PerturbationResult:
    variants: Mapping[str, PerformanceMetrics]
    pass_fraction: float
    passed: bool


def evaluate_parameter_perturbations(
    variants: Mapping[str, PerformanceMetrics],
    *,
    minimum_variants: int,
    profit_factor_min: float,
    expectancy_r_min: float,
    minimum_pass_fraction: float,
) -> PerturbationResult:
    if minimum_variants < 1:
        raise DataContractError("minimum_variants must be positive")
    if not 0 < minimum_pass_fraction <= 1:
        raise DataContractError("minimum_pass_fraction must be in (0,1]")
    if len(variants) < minimum_variants:
        return PerturbationResult(dict(variants), 0.0, False)

    passed_count = 0
    for metrics in variants.values():
        if (
            metrics.profit_factor is not None
            and metrics.profit_factor >= profit_factor_min
            and metrics.expectancy_r is not None
            and metrics.expectancy_r >= expectancy_r_min
        ):
            passed_count += 1
    pass_fraction = passed_count / len(variants)
    return PerturbationResult(dict(variants), pass_fraction, pass_fraction >= minimum_pass_fraction)
