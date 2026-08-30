from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Mapping

from ..config import ProjectConfig
from ..exceptions import DataContractError
from .metrics import PerformanceMetrics


@dataclass(frozen=True, slots=True)
class ParameterVariant:
    name: str
    section: str
    key: str
    multiplier: float


@dataclass(frozen=True, slots=True)
class PerturbationResult:
    variants: Mapping[str, PerformanceMetrics]
    pass_fraction: float
    passed: bool


def canonical_parameter_variants() -> tuple[ParameterVariant, ...]:
    return (
        ParameterVariant("equal_tolerance_minus10", "liquidity", "equal_level_tolerance_atr", 0.90),
        ParameterVariant("equal_tolerance_plus10", "liquidity", "equal_level_tolerance_atr", 1.10),
        ParameterVariant("sl_buffer_minus10", "trade_plan", "sl_buffer_atr", 0.90),
        ParameterVariant("sl_buffer_plus10", "trade_plan", "sl_buffer_atr", 1.10),
        ParameterVariant("entry_zone_minus10", "trade_plan", "minimum_entry_zone_atr", 0.90),
        ParameterVariant("entry_zone_plus10", "trade_plan", "minimum_entry_zone_atr", 1.10),
    )


def apply_parameter_variant(cfg: ProjectConfig, variant: ParameterVariant) -> ProjectConfig:
    strategy = deepcopy(cfg.strategy)
    section = strategy.get(variant.section)
    if not isinstance(section, dict) or variant.key not in section:
        raise DataContractError(f"variant path is invalid: {variant.section}.{variant.key}")
    raw = section[variant.key]
    if isinstance(raw, bool):
        raise DataContractError("variant target cannot be boolean")
    section[variant.key] = float(raw) * float(variant.multiplier)
    return replace(cfg, strategy=strategy)


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
