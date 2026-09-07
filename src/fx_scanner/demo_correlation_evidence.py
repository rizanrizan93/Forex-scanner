from __future__ import annotations

import os
from dataclasses import dataclass
from math import isfinite
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
    """DEMO resolver that keeps canonical guard decisions and exposes evidence.

    Correlation semantics remain canonical. The only DEMO-specific mutation is
    an explicit process-local risk ceiling up to 1%, driven by the calibration
    environment variable after the caller has already validated DEMO mode.
    """

    last_correlation_evidence: Mapping[str, tuple[CorrelationEvidence, ...]] = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        raw = os.getenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "").strip()
        if raw:
            value = float(raw)
            if not isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError("CTRADER_DEMO_RISK_PER_TRADE_PCT must be in (0,1]")
            self.demo_max_risk_pct = max(self.demo_max_risk_pct, value)

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
