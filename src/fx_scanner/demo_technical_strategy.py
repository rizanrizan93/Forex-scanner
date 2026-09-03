from __future__ import annotations

import os
from dataclasses import replace
from math import isfinite
from typing import Mapping, Sequence

from .decision import build_decision
from .demo_trade_plan_geometry import build_demo_trade_plan
from .exceptions import DataContractError
from .models import Bar, SignalState, ensure_utc
from .ranking import PairRank
from .strategy import (
    DeepScanReport,
    MTFAnalysis,
    SetupType,
    _directional_structure_score,
    analyze_pair_mtf,
    select_pair_candidates,
)


def _demo_calibration_pretrigger_enabled() -> bool:
    return os.getenv("CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER", "0").strip() == "1"


def _demo_fvg_max_age_minutes() -> float:
    raw = os.getenv("CTRADER_DEMO_FVG_MAX_AGE_MINUTES", "90").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise DataContractError("CTRADER_DEMO_FVG_MAX_AGE_MINUTES must be numeric") from exc
    if not 15.0 <= value <= 240.0:
        raise DataContractError("CTRADER_DEMO_FVG_MAX_AGE_MINUTES must be in [15,240]")
    return value


def _fresh_directional_fvg(base: MTFAnalysis, *, as_of) -> bool:
    wanted = "BULLISH" if base.direction == "LONG" else "BEARISH"
    now = ensure_utc(as_of)
    max_age_seconds = 60.0 * _demo_fvg_max_age_minutes()
    for gap in base.liquidity.fvgs:
        if gap.direction != wanted or gap.status not in {"OPEN", "PARTIAL"}:
            continue
        age = (now - ensure_utc(gap.origin_at)).total_seconds()
        if 0.0 <= age <= max_age_seconds:
            return True
    return False


def _demo_transition_confirmed(snapshot, direction: str) -> bool:
    """Accept a fresh SMC transition even while pivot-derived trend still lags."""
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    if snapshot.mss == wanted:
        return True
    displacement = getattr(snapshot, "displacement", None)
    return bool(
        snapshot.bos == wanted
        and displacement is not None
        and bool(getattr(displacement, "valid", False))
        and getattr(displacement, "direction", None) == wanted
    )


def _demo_snapshot_conflict(snapshot, direction: str) -> bool:
    opposite = "BEARISH" if direction == "LONG" else "BULLISH"
    return bool(
        snapshot.trend == opposite
        and not _demo_transition_confirmed(snapshot, direction)
    )


def _demo_structure_conflict(base: MTFAnalysis) -> bool:
    return bool(
        _demo_snapshot_conflict(base.h1, base.direction)
        or _demo_snapshot_conflict(base.m15, base.direction)
    )


def _demo_directional_structure_score(snapshot, direction: str) -> float | None:
    score = _directional_structure_score(snapshot, direction)
    if score is None:
        return None
    opposite = "BEARISH" if direction == "LONG" else "BULLISH"
    if snapshot.trend == opposite and _demo_transition_confirmed(snapshot, direction):
        return min(100.0, score + 40.0)
    return score


def _early_structure_valid(base: MTFAnalysis) -> bool:
    if _demo_structure_conflict(base):
        return False
    return bool(
        (_demo_directional_structure_score(base.h1, base.direction) or 0.0) >= 55.0
        and (_demo_directional_structure_score(base.m15, base.direction) or 0.0) >= 55.0
    )


def _demo_setup_recognition_structure_valid(base: MTFAnalysis) -> bool:
    if _demo_structure_conflict(base):
        return False
    h1_score = _demo_directional_structure_score(base.h1, base.direction)
    m15_score = _demo_directional_structure_score(base.m15, base.direction)
    return bool(
        h1_score is not None
        and m15_score is not None
        and h1_score >= 50.0
        and m15_score >= 50.0
    )


def _demo_snapshot_directional_evidence(snapshot, direction: str) -> bool:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    displacement = getattr(snapshot, "displacement", None)
    fvg = getattr(snapshot, "fvg", None)
    sweep = getattr(snapshot, "sweep", None)
    return bool(
        snapshot.bos == wanted
        or snapshot.mss == wanted
        or (
            displacement is not None
            and bool(getattr(displacement, "valid", False))
            and getattr(displacement, "direction", None) == wanted
        )
        or (
            fvg is not None
            and bool(getattr(fvg, "valid", False))
            and getattr(fvg, "direction", None) == wanted
        )
        or (
            sweep is not None
            and bool(getattr(sweep, "valid", False))
            and getattr(sweep, "direction", None) == wanted
        )
    )


def _demo_setup_type(base: MTFAnalysis, *, as_of) -> SetupType | None:
    """Recognize technical patterns below the score-driven DEMO admission floor."""
    if base.setup_type is not None:
        return base.setup_type
    if not _demo_setup_recognition_structure_valid(base):
        return None
    if _fresh_directional_fvg(base, as_of=as_of):
        return SetupType.TREND_CONTINUATION
    if _demo_transition_confirmed(base.h1, base.direction) or _demo_transition_confirmed(
        base.m15, base.direction
    ):
        return SetupType.TREND_CONTINUATION
    h1_score = _demo_directional_structure_score(base.h1, base.direction) or 0.0
    if h1_score >= 55.0 and _demo_snapshot_directional_evidence(base.m15, base.direction):
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
    """Run canonical analysis, then apply the DEMO score-driven admission policy."""
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
    setup_type = _demo_setup_type(base, as_of=as_of)
    early_structure = _early_structure_valid(base)
    fresh_fvg = _fresh_directional_fvg(base, as_of=as_of)

    components = dict(base.conviction_components)
    components["execution_quality"] = _execution_quality(
        plan,
        plan_cfg,
        execution_quality_score,
        trigger_confirmed=base.trigger_confirmed,
    )

    computed = dict(base.computed_guards)
    # DEMO score-driven policy: structure remains diagnostic telemetry but is no
    # longer a hard execution veto. Other market/risk guards remain enforced.
    computed["STRUCTURE_INVALID"] = False
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

    score = decision.conviction_score
    execution_floor = float(cfg.scoring["states"]["execution_candidate_min"])
    score_driven_setup = bool(score is not None and float(score) >= execution_floor)
    if score_driven_setup and setup_type is None:
        setup_type = SetupType.TREND_CONTINUATION

    state = decision.state
    if not decision.guards:
        plan_ready = bool(
            plan is not None
            and plan.rr2 is not None
            and plan.rr2 >= float(plan_cfg["minimum_tp2_rr"])
            and plan.chase_distance_atr <= float(plan_cfg["chase_block_atr"])
        )
        early_watch = bool(
            setup_type is not None
            and early_structure
            and fresh_fvg
        )
        calibration_ready = bool(
            _demo_calibration_pretrigger_enabled()
            and score_driven_setup
            and plan_ready
        )

        if calibration_ready:
            state = SignalState.EXECUTION_READY
        elif setup_type is None:
            if state not in {SignalState.NO_TRADE, SignalState.WATCH}:
                state = SignalState.WATCH
        elif early_watch and state in {SignalState.NO_TRADE, SignalState.WATCH}:
            state = SignalState.SETUP_FORMING
        elif setup_type is not None and not base.trigger_confirmed and state in {
            SignalState.ARMED,
            SignalState.EXECUTION_READY,
        }:
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
