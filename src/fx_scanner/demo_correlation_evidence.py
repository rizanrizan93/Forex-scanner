from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .models import Bar
from .producer_guards import ProductionGuardResolver, GuardResolution, _aligned_directional_correlation
from .ranking import PairRank


@dataclass(frozen=True, slots=True)
class CorrelationEvidence:
    symbol: str
    peer_symbol: str
    correlation: float
    threshold: float
    lookback_bars: int
    blocked: bool


class EvidenceProductionGuardResolver(ProductionGuardResolver):
    """DEMO resolver that keeps the canonical guard decision and exposes its evidence.

    The parent resolver remains the sole owner of CORRELATION_BLOCK. This class only
    recomputes the same aligned H1 correlations for observability after the canonical
    flags have been resolved; it does not alter any guard outcome.
    """

    last_correlation_evidence: Mapping[str, tuple[CorrelationEvidence, ...]] = {}

    def resolve(
        self,
        *,
        candidates: Sequence[PairRank],
        bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
        as_of,
    ) -> GuardResolution:
        resolution = super().resolve(
            candidates=candidates,
            bars_by_symbol=bars_by_symbol,
            as_of=as_of,
        )
        guard_cfg = self.cfg.strategy["guard_evidence"]
        lookback = int(guard_cfg["correlation_lookback_bars"])
        threshold = float(guard_cfg["correlation_threshold"])
        evidence: dict[str, tuple[CorrelationEvidence, ...]] = {}

        for index, candidate in enumerate(candidates):
            rows: list[CorrelationEvidence] = []
            for peer in candidates[:index]:
                value = _aligned_directional_correlation(
                    candidate,
                    peer,
                    bars_by_symbol,
                    lookback=lookback,
                )
                if value is None:
                    continue
                rows.append(
                    CorrelationEvidence(
                        symbol=candidate.symbol,
                        peer_symbol=peer.symbol,
                        correlation=float(value),
                        threshold=threshold,
                        lookback_bars=lookback,
                        blocked=bool(value >= threshold),
                    )
                )
            rows.sort(key=lambda item: (-item.correlation, item.peer_symbol))
            evidence[candidate.symbol] = tuple(rows)

        self.last_correlation_evidence = evidence
        return resolution
