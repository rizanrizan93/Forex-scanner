from __future__ import annotations

import os
from dataclasses import replace
from math import isfinite
from typing import Mapping, Sequence

from .decision import build_decision
from .demo_trade_plan_geometry import build_demo_trade_plan
from .exceptions import DataContractError
from .models import Bar, SignalState
from .ranking import PairRank
from .strategy import (
    DeepScanReport,
    MTFAnalysis,
    SetupType,
    _directional_structure_score,
    _htf_conflict,
    analyze_pair_mtf,
    select_pair_candidates,
)


def _demo_calibration_pretrigger_enabled() -> bool:
    return os.getenv("CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER", "0").strip() == "1"


def _demo_setup_type(base: MTFAnalysis) -> SetupType | None:
    if base.setup_type is not None:
        return base.setup_type
    if _htf_conflict(base.direction, base.h1, base.m15):
        return None
    if (_directional_structure_score(base.h1, base.direction) or 0.0) < 55.0:
        return None
    if (_directional_structure_score(base.m15, base.direction) or 0.0) < 55.0:
        return None
    wanted = "BULLISH" if base.direction == "LONG" else "BEARISH"
    if any(
        gap.direction == wanted and gap.status in {"OPEN", "PARTIAL"}
        for gap in base.liquidity.fvgs
    ):
        return SetupType.TREND_CONTINUATION
    return None


def _execution_quality(
    plan,
    plan_cfg: Mapping,
    external_score: float | None,
    *,
    trigger_confirmed: bool,
) -> float | None:
    if plan is None:
        internal = 20.0 if trigger_confirmed else 10.0
    else:
        chase_ok = float(plan_cfg["chase_ok_atr"])
        chase_block = float(plan_cfg["chase_block_atr"])
        if plan.chase_distance_atr <= chase_ok:
            chase_quality = 100.0
        else:
            span = max(1e-12, chase_block - chase_ok)
            chase_quality = max(
                40.0,
                100.0 - 60.0 * (plan.chase_distance_atr - chase_ok) / span,
            )
        preferred_rr = float(plan_cfg["preferred_tp2_rr"])
        minimum_rr = float(plan_cfg["minimum_tp2_rr"])
        if plan.rr2 is None:
            rr_quality = 20.0
        elif plan.rr2 >= preferred_rr:
            rr_quality = 100.0
        elif plan.rr2 >= minimum_rr:
            rr_quality = 70.0 + 30.0 * (
                (plan.rr2 - minimum_rr) / max(1e-12, preferred_rr - minimum_rr)
            )
        else:
            rr_quality = max(0.0, 70.0 * plan.rr2 / minimum_rr)
        internal = min(chase_quality, rr_quality)

    if external_score is None:
        return internal
    if isinstance(external_score, bool) or not isfinite(float(external_score)):
        raise DataContractError("execution_quality_score must be finite numeric")
    if not 0 <= float(external_score) <= 100:
        raise DataContractError("execution_quality_score must be in [0,100]")
    return min(internal, float(external_score))


def analyze_demo_pair_mtf(
    *,
    rank: PairRank,
    bars_by_timeframe: Mapping[str, Sequence[Bar]],
    cfg,
    as_of,
    external_guard_flags: Mapping[str, bool],
    execution_quality_score: float | None = None,
) -> MTFAnalysis:
    """Run canonical technical analysis, then explicitly bind DEMO geometry.

    No module-level strategy function is replaced. The DEMO trade-plan builder
    is called directly and all plan-dependent scoring/guards are recomputed from
    that explicit result before the final decision is returned.
    """
    base = analyze_pair_mtf(
        rank=rank,
        bars_by_timeframe=bars_by_timeframe,
        cfg=cfg,
        as_of=as_of,
        external_guard_flags=external_guard_flags,
        execution_quality_score=execution_quality_score,
        technical_scalping=True,
    )

    plan_cfg = cfg.strategy["trade_plan"]
    mtf_cfg = cfg.strategy["mtf"]
    closed_m5 = tuple(bars_by_timeframe["M5"])
    if not closed_m5:
        raise DataContractError("DEMO technical path requires M5 bars")
    current_price = float(closed_m5[-1].close)

    plan = build_demo_trade_plan(
        direction=rank.direction,
        current_price=current_price,
        m15=base.m15,
        h1=base.h1,
        m5=base.m5,
        liquidity=base.liquidity,
        m5_bars=closed_m5,
        atr_period=int(mtf_cfg["atr_period"]),
        sl_buffer_atr=float(plan_cfg["sl_buffer_atr"]),
        minimum_entry_zone_atr=float(plan_cfg["minimum_entry_zone_atr"]),
        chase_block_atr=float(plan_cfg["chase_block_atr"]),
    )
    setup_type = _demo_setup_type(base)

    components = dict(base.conviction_components)
    components["execution_quality"] = _execution_quality(
        plan,
        plan_cfg,
        execution_quality_score,
        trigger_confirmed=base.trigger_confirmed,
    )

    computed = dict(base.computed_guards)
    computed["CHASE_BLOCK"] = bool(
        plan is not None
        and plan.chase_distance_atr > float(plan_cfg["chase_block_atr"])
    )
    computed["RR_BLOCK"] = bool(
        plan is not None
        and (plan.rr2 is None or plan.rr2 < float(plan_cfg["minimum_tp2_rr"]))
    )

    guard_flags = dict(external_guard_flags)
    guard_flags.update(computed)
    decision = build_decision(
        rank=rank,
        timestamp=as_of,
        conviction_components=components,
        conviction_weights=cfg.scoring["execution_conviction"],
        thresholds=cfg.scoring["states"],
        guard_flags=guard_flags,
        required_guards=cfg.scoring["hard_guards"],
        minimum_coverage=0.80,
        minimum_pair_coverage=0.85,
    )

    state = decision.state
    if not decision.guards:
        if setup_type is None and state not in {SignalState.NO_TRADE, SignalState.WATCH}:
            state = SignalState.WATCH
        elif setup_type is not None and not base.trigger_confirmed and state in {
            SignalState.ARMED,
            SignalState.EXECUTION_READY,
        }:
            calibration_ready = (
                _demo_calibration_pretrigger_enabled()
                and plan is not None
                and plan.rr2 is not None
                and plan.rr2 >= float(plan_cfg["minimum_tp2_rr"])
                and plan.chase_distance_atr <= float(plan_cfg["chase_block_atr"])
            )
            if not calibration_ready:
                state = SignalState.SETUP_FORMING
        elif base.trigger_confirmed and plan is None and state in {
            SignalState.ARMED,
            SignalState.EXECUTION_READY,
        }:
            state = SignalState.SETUP_FORMING
    if state != decision.state:
        decision = replace(decision, state=state)

    return replace(
        base,
        setup_type=setup_type,
        trade_plan=plan,
        conviction_components=components,
        computed_guards=computed,
        decision=decision,
    )


def scan_demo_deep_candidates_report(
    *,
    ranked: Sequence[PairRank],
    bars_by_symbol: Mapping[str, Mapping[str, Sequence[Bar]]],
    cfg,
    as_of,
    external_guards_by_symbol: Mapping[str, Mapping[str, bool]],
    execution_quality_by_symbol: Mapping[str, float | None] | None = None,
) -> DeepScanReport:
    selection_cfg = cfg.strategy["selection"]
    selected = select_pair_candidates(
        ranked,
        macro_compatible_top=int(selection_cfg["macro_compatible_top"]),
        deep_analysis_top=int(selection_cfg["deep_analysis_top"]),
        compatibility_mode="TECHNICAL",
    )
    execution_quality_by_symbol = execution_quality_by_symbol or {}
    analyses: list[MTFAnalysis] = []
    skipped: dict[str, str] = {}
    for rank in selected.deep_analysis:
        bars = bars_by_symbol.get(rank.symbol)
        if bars is None:
            skipped[rank.symbol] = "MISSING_MTF_BUNDLE"
            continue
        try:
            analyses.append(
                analyze_demo_pair_mtf(
                    rank=rank,
                    bars_by_timeframe=bars,
                    cfg=cfg,
                    as_of=as_of,
                    external_guard_flags=external_guards_by_symbol.get(rank.symbol, {}),
                    execution_quality_score=execution_quality_by_symbol.get(rank.symbol),
                )
            )
        except DataContractError as exc:
            skipped[rank.symbol] = f"DATA_CONTRACT:{exc}"
    analyses.sort(
        key=lambda x: (
            0 if x.decision.state == SignalState.EXECUTION_READY else
            1 if x.decision.state == SignalState.ARMED else
            2 if x.decision.state == SignalState.SETUP_FORMING else
            3 if x.decision.state == SignalState.WATCH else 4,
            -(x.decision.conviction_score or -1),
            x.symbol,
        )
    )
    return DeepScanReport(selected, tuple(analyses), dict(sorted(skipped.items())))
