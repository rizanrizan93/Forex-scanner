from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from .config import PairSpec
from .exceptions import DataContractError


@dataclass(frozen=True, slots=True)
class CurrencyStrength:
    currency: str
    score: float
    contributing_pairs: int


@dataclass(frozen=True, slots=True)
class PairRank:
    symbol: str
    direction: str
    relative_macro_edge: float
    relative_technical_edge: float
    cross_asset_edge: float
    pair_edge: float
    absolute_edge: float
    rank: int


def compute_currency_strength(
    pair_momentum: Mapping[str, float],
    pairs: tuple[PairSpec, ...] | list[PairSpec],
) -> dict[str, CurrencyStrength]:
    """Aggregate normalized signed pair momentum (-100..100) by currency.

    A positive pair momentum strengthens base and weakens quote. Missing pairs are
    omitted rather than interpreted as zero.
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for pair in pairs:
        raw = pair_momentum.get(pair.symbol)
        if raw is None:
            continue
        value = float(raw)
        if not isfinite(value) or not -100 <= value <= 100:
            raise DataContractError(f"invalid normalized momentum for {pair.symbol}")
        for currency, contribution in ((pair.base, value), (pair.quote, -value)):
            sums[currency] = sums.get(currency, 0.0) + contribution
            counts[currency] = counts.get(currency, 0) + 1

    out: dict[str, CurrencyStrength] = {}
    for currency, total in sums.items():
        count = counts[currency]
        out[currency] = CurrencyStrength(currency, total / count, count)
    return out


def rank_pairs(
    pairs: tuple[PairSpec, ...] | list[PairSpec],
    *,
    macro_scores: Mapping[str, float],
    technical_strength: Mapping[str, CurrencyStrength | float],
    cross_asset_edges: Mapping[str, float] | None = None,
) -> list[PairRank]:
    cross_asset_edges = cross_asset_edges or {}
    candidates: list[tuple[PairSpec, float, float, float, float]] = []

    def strength(currency: str) -> float | None:
        value = technical_strength.get(currency)
        if value is None:
            return None
        if isinstance(value, CurrencyStrength):
            return float(value.score)
        return float(value)

    for pair in pairs:
        if pair.base not in macro_scores or pair.quote not in macro_scores:
            continue
        base_tech = strength(pair.base)
        quote_tech = strength(pair.quote)
        if base_tech is None or quote_tech is None:
            continue
        macro_edge = float(macro_scores[pair.base]) - float(macro_scores[pair.quote])
        tech_edge = base_tech - quote_tech
        cross = float(cross_asset_edges.get(pair.symbol, 0.0))
        if not all(isfinite(x) for x in (macro_edge, tech_edge, cross)):
            raise DataContractError(f"non-finite pair edge for {pair.symbol}")
        if not -100 <= cross <= 100:
            raise DataContractError(f"cross-asset edge must be in [-100,100] for {pair.symbol}")

        # Macro difference naturally spans [-200,200]; normalize to [-100,100].
        macro_norm = max(-100.0, min(100.0, macro_edge / 2.0))
        tech_norm = max(-100.0, min(100.0, tech_edge / 2.0))
        pair_edge = 0.55 * macro_norm + 0.30 * tech_norm + 0.15 * cross
        candidates.append((pair, macro_edge, tech_edge, cross, pair_edge))

    candidates.sort(key=lambda x: (-abs(x[4]), x[0].symbol))
    ranked: list[PairRank] = []
    for idx, (pair, macro_edge, tech_edge, cross, edge) in enumerate(candidates, start=1):
        ranked.append(
            PairRank(
                symbol=pair.symbol,
                direction="LONG" if edge > 0 else "SHORT" if edge < 0 else "NEUTRAL",
                relative_macro_edge=macro_edge,
                relative_technical_edge=tech_edge,
                cross_asset_edge=cross,
                pair_edge=edge,
                absolute_edge=abs(edge),
                rank=idx,
            )
        )
    return ranked
