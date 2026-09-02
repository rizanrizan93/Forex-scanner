from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from .config import PairSpec
from .exceptions import DataContractError
from .macro import CurrencyMacroScore


@dataclass(frozen=True, slots=True)
class CurrencyStrength:
    currency: str
    score: float
    contributing_pairs: int
    expected_pairs: int
    coverage: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", self.currency.upper())
        if len(self.currency) != 3:
            raise DataContractError("currency strength requires a three-letter currency")
        if not isfinite(self.score) or not -100 <= self.score <= 100:
            raise DataContractError("currency strength score must be in [-100,100]")
        if self.contributing_pairs <= 0 or self.expected_pairs <= 0:
            raise DataContractError("currency strength pair counts must be positive")
        if self.contributing_pairs > self.expected_pairs:
            raise DataContractError("contributing_pairs cannot exceed expected_pairs")
        if not 0 < self.coverage <= 1:
            raise DataContractError("currency strength coverage must be in (0,1]")
        expected_coverage = self.contributing_pairs / self.expected_pairs
        if abs(self.coverage - expected_coverage) > 1e-9:
            raise DataContractError("currency strength coverage/count mismatch")


@dataclass(frozen=True, slots=True)
class PairRank:
    symbol: str
    direction: str
    relative_macro_edge: float
    relative_technical_edge: float
    cross_asset_edge: float | None
    pair_edge: float
    absolute_edge: float
    coverage: float
    missing_components: tuple[str, ...]
    rank: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "direction", self.direction.upper())
        if not self.symbol:
            raise DataContractError("pair rank symbol is required")
        if self.direction not in {"LONG", "SHORT", "NEUTRAL"}:
            raise DataContractError("pair rank direction is invalid")
        for name, value, lower, upper in (
            ("relative_macro_edge", self.relative_macro_edge, -200.0, 200.0),
            ("relative_technical_edge", self.relative_technical_edge, -200.0, 200.0),
            ("pair_edge", self.pair_edge, -100.0, 100.0),
            ("absolute_edge", self.absolute_edge, 0.0, 100.0),
        ):
            if not isfinite(value) or not lower <= value <= upper:
                raise DataContractError(f"{name} outside [{lower},{upper}]")
        if self.cross_asset_edge is not None:
            if not isfinite(self.cross_asset_edge) or not -100 <= self.cross_asset_edge <= 100:
                raise DataContractError("cross_asset_edge must be in [-100,100]")
        if not 0 <= self.coverage <= 1:
            raise DataContractError("pair rank coverage must be in [0,1]")
        if self.rank <= 0:
            raise DataContractError("pair rank must be positive")
        if abs(self.absolute_edge - abs(self.pair_edge)) > 1e-9:
            raise DataContractError("absolute_edge must equal abs(pair_edge)")
        if self.direction == "LONG" and self.pair_edge <= 0:
            raise DataContractError("LONG pair rank requires positive pair_edge")
        if self.direction == "SHORT" and self.pair_edge >= 0:
            raise DataContractError("SHORT pair rank requires negative pair_edge")
        if self.direction == "NEUTRAL" and abs(self.pair_edge) > 1e-12:
            raise DataContractError("NEUTRAL pair rank requires zero pair_edge")


def compute_currency_strength(
    pair_momentum: Mapping[str, float],
    pairs: tuple[PairSpec, ...] | list[PairSpec],
) -> dict[str, CurrencyStrength]:
    """Aggregate normalized signed pair momentum (-100..100) by currency.

    Missing pairs are omitted rather than interpreted as zero. Coverage records
    how much of each currency's configured pair universe contributed.
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    expected: dict[str, int] = {}
    for pair in pairs:
        expected[pair.base] = expected.get(pair.base, 0) + 1
        expected[pair.quote] = expected.get(pair.quote, 0) + 1

        raw = pair_momentum.get(pair.symbol)
        if raw is None:
            continue
        if isinstance(raw, bool):
            raise DataContractError(f"boolean momentum is invalid for {pair.symbol}")
        value = float(raw)
        if not isfinite(value) or not -100 <= value <= 100:
            raise DataContractError(f"invalid normalized momentum for {pair.symbol}")
        for currency, contribution in ((pair.base, value), (pair.quote, -value)):
            sums[currency] = sums.get(currency, 0.0) + contribution
            counts[currency] = counts.get(currency, 0) + 1

    out: dict[str, CurrencyStrength] = {}
    for currency, total in sums.items():
        count = counts[currency]
        expected_count = expected[currency]
        out[currency] = CurrencyStrength(
            currency,
            total / count,
            count,
            expected_count,
            count / expected_count,
        )
    return out


def rank_pairs(
    pairs: tuple[PairSpec, ...] | list[PairSpec],
    *,
    macro_scores: Mapping[str, CurrencyMacroScore | float],
    technical_strength: Mapping[str, CurrencyStrength | float],
    cross_asset_edges: Mapping[str, float | None] | None = None,
    minimum_coverage: float = 0.80,
) -> list[PairRank]:
    """Rank pairs while preserving partial/missing evidence coverage.

    Pair-edge formula is fixed at 55% macro, 30% technical, 15% cross-asset.
    Missing cross-asset does not become neutral zero; the observed formula is
    re-normalized over available top-level components, while evidence coverage
    separately tracks macro/technical source coverage.
    """
    if not 0 < minimum_coverage <= 1:
        raise DataContractError("minimum_coverage must be in (0,1]")
    cross_asset_edges = cross_asset_edges or {}
    candidates: list[tuple[PairSpec, float, float, float | None, float, float, tuple[str, ...]]] = []

    def macro_value(currency: str) -> tuple[float, float] | None:
        value = macro_scores.get(currency)
        if value is None:
            return None
        if isinstance(value, CurrencyMacroScore):
            if value.score is None:
                return None
            return float(value.score), float(value.coverage)
        if isinstance(value, bool):
            raise DataContractError(f"boolean macro score is invalid for {currency}")
        numeric = float(value)
        if not isfinite(numeric) or not -100 <= numeric <= 100:
            raise DataContractError(f"macro score must be in [-100,100] for {currency}")
        return numeric, 1.0

    def strength_value(currency: str) -> tuple[float, float] | None:
        value = technical_strength.get(currency)
        if value is None:
            return None
        if isinstance(value, CurrencyStrength):
            return float(value.score), float(value.coverage)
        if isinstance(value, bool):
            raise DataContractError(f"boolean technical strength is invalid for {currency}")
        numeric = float(value)
        if not isfinite(numeric) or not -100 <= numeric <= 100:
            raise DataContractError(f"technical strength must be in [-100,100] for {currency}")
        return numeric, 1.0

    for pair in pairs:
        base_macro = macro_value(pair.base)
        quote_macro = macro_value(pair.quote)
        base_tech = strength_value(pair.base)
        quote_tech = strength_value(pair.quote)
        if base_macro is None or quote_macro is None or base_tech is None or quote_tech is None:
            continue

        macro_edge = base_macro[0] - quote_macro[0]
        tech_edge = base_tech[0] - quote_tech[0]
        if not all(isfinite(x) for x in (macro_edge, tech_edge)):
            raise DataContractError(f"non-finite pair edge for {pair.symbol}")

        macro_norm = max(-100.0, min(100.0, macro_edge / 2.0))
        tech_norm = max(-100.0, min(100.0, tech_edge / 2.0))
        observed_sum = 0.55 * macro_norm + 0.30 * tech_norm
        observed_weight = 0.85
        evidence_coverage = (
            0.55 * min(base_macro[1], quote_macro[1])
            + 0.30 * min(base_tech[1], quote_tech[1])
        )
        missing: list[str] = []

        cross_raw = cross_asset_edges.get(pair.symbol)
        cross: float | None
        if cross_raw is None:
            cross = None
            missing.append("cross_asset")
        else:
            if isinstance(cross_raw, bool):
                raise DataContractError(f"boolean cross-asset edge is invalid for {pair.symbol}")
            cross = float(cross_raw)
            if not isfinite(cross) or not -100 <= cross <= 100:
                raise DataContractError(f"cross-asset edge must be in [-100,100] for {pair.symbol}")
            observed_sum += 0.15 * cross
            observed_weight += 0.15
            evidence_coverage += 0.15

        # Preserve absolute weighted evidence coverage for downstream audit.
        # Apply the ranking gate to completeness of the components that are
        # actually observed, matching score renormalization. Missing cross-asset
        # remains explicit and is never converted to a neutral zero.
        coverage = evidence_coverage
        gate_coverage = evidence_coverage / observed_weight
        if gate_coverage < minimum_coverage:
            continue

        pair_edge = observed_sum / observed_weight
        candidates.append(
            (pair, macro_edge, tech_edge, cross, pair_edge, coverage, tuple(sorted(missing)))
        )

    candidates.sort(key=lambda x: (-abs(x[4]), -x[5], x[0].symbol))
    ranked: list[PairRank] = []
    for idx, (pair, macro_edge, tech_edge, cross, edge, coverage, missing) in enumerate(candidates, start=1):
        ranked.append(
            PairRank(
                symbol=pair.symbol,
                direction="LONG" if edge > 0 else "SHORT" if edge < 0 else "NEUTRAL",
                relative_macro_edge=macro_edge,
                relative_technical_edge=tech_edge,
                cross_asset_edge=cross,
                pair_edge=edge,
                absolute_edge=abs(edge),
                coverage=coverage,
                missing_components=missing,
                rank=idx,
            )
        )
    return ranked


def rank_pairs_technical_only(
    pairs: tuple[PairSpec, ...] | list[PairSpec],
    *,
    technical_strength: Mapping[str, CurrencyStrength | float],
    minimum_coverage: float = 0.80,
) -> list[PairRank]:
    """Rank the DEMO scalping universe from technical strength only.

    Macro, cross-asset and positioning inputs are intentionally absent. Pair
    coverage therefore represents only observed technical evidence. This is
    used exclusively by the DEMO technical-only profile.
    """
    if not 0 < minimum_coverage <= 1:
        raise DataContractError("minimum_coverage must be in (0,1]")

    def strength_value(currency: str) -> tuple[float, float] | None:
        value = technical_strength.get(currency)
        if value is None:
            return None
        if isinstance(value, CurrencyStrength):
            return float(value.score), float(value.coverage)
        if isinstance(value, bool):
            raise DataContractError(f"boolean technical strength is invalid for {currency}")
        numeric = float(value)
        if not isfinite(numeric) or not -100 <= numeric <= 100:
            raise DataContractError(f"technical strength must be in [-100,100] for {currency}")
        return numeric, 1.0

    candidates: list[tuple[PairSpec, float, float, float]] = []
    for pair in pairs:
        base = strength_value(pair.base)
        quote = strength_value(pair.quote)
        if base is None or quote is None:
            continue
        technical_edge = base[0] - quote[0]
        if not isfinite(technical_edge):
            raise DataContractError(f"non-finite technical edge for {pair.symbol}")
        coverage = min(base[1], quote[1])
        if coverage < minimum_coverage:
            continue
        pair_edge = max(-100.0, min(100.0, technical_edge / 2.0))
        candidates.append((pair, technical_edge, pair_edge, coverage))

    candidates.sort(key=lambda x: (-abs(x[2]), -x[3], x[0].symbol))
    ranked: list[PairRank] = []
    for idx, (pair, technical_edge, edge, coverage) in enumerate(candidates, start=1):
        ranked.append(
            PairRank(
                symbol=pair.symbol,
                direction="LONG" if edge > 0 else "SHORT" if edge < 0 else "NEUTRAL",
                relative_macro_edge=0.0,
                relative_technical_edge=technical_edge,
                cross_asset_edge=None,
                pair_edge=edge,
                absolute_edge=abs(edge),
                coverage=coverage,
                missing_components=(),
                rank=idx,
            )
        )
    return ranked
