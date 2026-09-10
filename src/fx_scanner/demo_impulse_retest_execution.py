from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from .demo_impulse_retest_v2 import (
    EXECUTION_SYMBOLS,
    build_impulse_retest_v2_plan,
    evaluate_impulse_retest_v2,
)
from .demo_technical_strategy import analyze_demo_pair_mtf
from .exceptions import DataContractError
from .models import Bar, SignalState
from .ranking import PairRank
from .strategy import DeepScanReport, UniverseSelection


def scan_demo_deep_candidates_report(
    *,
    ranked: Sequence[PairRank],
    bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
    cfg,
    as_of,
    external_guards_by_symbol: Mapping[str, Mapping[str, bool]],
    execution_quality_by_symbol: Mapping[str, float | None] | None = None,
) -> DeepScanReport:
    """DEMO execution scanner with IMPULSE_RETEST_V2 as the only strategy.

    Legacy strategy code remains importable solely for feature construction and
    historical lineage. It has no authority to emit DEMO execution candidates.
    """
    execution_quality_by_symbol = execution_quality_by_symbol or {}
    by_symbol = {item.symbol: item for item in ranked}
    selected_ranks = tuple(by_symbol[s] for s in sorted(EXECUTION_SYMBOLS) if s in by_symbol)
    selection = UniverseSelection(selected_ranks, selected_ranks)
    analyses = []
    skipped: dict[str, str] = {}

    for rank in selected_ranks:
        bars = bars_by_symbol.get(rank.symbol)
        if bars is None:
            skipped[rank.symbol] = "MISSING_MTF_BUNDLE"
            continue
        try:
            base = analyze_demo_pair_mtf(
                rank=rank,
                bars_by_timeframe=bars,
                cfg=cfg,
                as_of=as_of,
                external_guard_flags=external_guards_by_symbol.get(rank.symbol, {}),
                execution_quality_score=execution_quality_by_symbol.get(rank.symbol),
            )
            m5 = tuple(bars.get("M5", ()))
            signal = evaluate_impulse_retest_v2(m5, direction=rank.direction)
            plan = build_impulse_retest_v2_plan(signal, current_price=float(m5[-1].close)) if m5 else None

            # Old strategy/setup recognition is explicitly discarded here.
            state = SignalState.WATCH
            setup_type = None
            trigger_confirmed = False
            if signal.active and signal.execution_eligible and plan is not None:
                trigger_confirmed = True
                # Reuse the legacy enum only as a storage compatibility token;
                # execution authority comes exclusively from this v2 gate.
                setup_type = base.setup_type
                if setup_type is None:
                    from .strategy import SetupType
                    setup_type = SetupType.TREND_CONTINUATION
                score = base.decision.conviction_score
                execution_floor = float(cfg.scoring["states"]["execution_candidate_min"])
                if (
                    not base.decision.guards
                    and score is not None
                    and float(score) >= execution_floor
                    and plan.rr2 is not None
                    and plan.rr2 >= float(cfg.strategy["trade_plan"]["minimum_tp2_rr"])
                ):
                    state = SignalState.EXECUTION_READY
                else:
                    state = SignalState.SETUP_FORMING

            decision = replace(base.decision, state=state)
            analyses.append(
                replace(
                    base,
                    setup_type=setup_type,
                    trigger_confirmed=trigger_confirmed,
                    trade_plan=plan if trigger_confirmed else None,
                    decision=decision,
                )
            )
        except (DataContractError, ValueError, IndexError) as exc:
            skipped[rank.symbol] = f"IMPULSE_RETEST_V2:{type(exc).__name__}:{exc}"

    analyses.sort(
        key=lambda x: (
            0 if x.decision.state == SignalState.EXECUTION_READY else
            1 if x.decision.state == SignalState.SETUP_FORMING else 2,
            -(x.decision.conviction_score or -1),
            x.symbol,
        )
    )
    return DeepScanReport(selection, tuple(analyses), dict(sorted(skipped.items())))
