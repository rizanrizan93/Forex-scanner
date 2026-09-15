from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    DonchianVariant,
    TournamentCosts,
    TournamentMetrics,
    TournamentTrade,
    _atr_at,
    _trade_outcome,
    _validate_bars,
    compute_metrics,
    walk_forward,
)
from .models import Bar
from .technical import structure_snapshot

CONTEXTUAL_VERSION = "DONCHIAN_CONTEXTUAL_H1_V2"
CORE_VARIANT = DonchianVariant(20, 14, 0.10)
DEVELOPMENT_FRACTION = 0.60
MIN_DEVELOPMENT_TRADES = 130
MIN_HOLDOUT_TRADES = 100
STRUCTURE_WINDOW = 120
LIQUID_UTC_START = 7
LIQUID_UTC_END = 20


@dataclass(frozen=True, slots=True)
class ContextProfile:
    profile_id: str
    require_trend: bool = False
    require_displacement: bool = False
    require_fvg: bool = False
    require_liquid_window: bool = False
    selection_eligible: bool = True


PROFILES = (
    ContextProfile("RAW_CONTROL", selection_eligible=False),
    ContextProfile("H1_TREND_ALIGNED", require_trend=True),
    ContextProfile("H1_DISPLACEMENT", require_displacement=True),
    ContextProfile("H1_TREND_DISPLACEMENT", require_trend=True, require_displacement=True),
    ContextProfile(
        "H1_TREND_DISPLACEMENT_FVG",
        require_trend=True,
        require_displacement=True,
        require_fvg=True,
    ),
    ContextProfile(
        "H1_DISPLACEMENT_LONDON_NY",
        require_displacement=True,
        require_liquid_window=True,
    ),
    ContextProfile(
        "H1_TREND_DISPLACEMENT_LONDON_NY",
        require_trend=True,
        require_displacement=True,
        require_liquid_window=True,
    ),
)


@dataclass(frozen=True, slots=True)
class ContextSignal:
    direction: str
    trend_aligned: bool
    displacement_aligned: bool
    fvg_aligned: bool
    liquid_window: bool
    trend: str
    bos: str | None
    mss: str | None


@dataclass(frozen=True, slots=True)
class ContextEvaluation:
    profile: ContextProfile
    development_metrics: TournamentMetrics
    stressed_development_metrics: TournamentMetrics
    walk_forward_pass_fraction: float
    walk_forward_passed: bool
    development_stress_passed: bool
    development_passed: bool

    def payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile.profile_id,
            "selection_eligible": self.profile.selection_eligible,
            "requirements": {
                "trend": self.profile.require_trend,
                "displacement": self.profile.require_displacement,
                "fvg": self.profile.require_fvg,
                "liquid_window": self.profile.require_liquid_window,
            },
            "development": self.development_metrics.payload(),
            "stressed_development": self.stressed_development_metrics.payload(),
            "walk_forward_pass_fraction": self.walk_forward_pass_fraction,
            "walk_forward_passed": self.walk_forward_passed,
            "development_stress_passed": self.development_stress_passed,
            "development_passed": self.development_passed,
        }


def profile_by_id(profile_id: str) -> ContextProfile:
    normalized = str(profile_id).strip().upper()
    for profile in PROFILES:
        if profile.profile_id == normalized:
            return profile
    raise ValueError("DONCHIAN_CONTEXT_PROFILE_UNKNOWN")


def _aligned(token: str | None, direction: str) -> bool:
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    return str(token or "").upper() == expected


def _context_signal(rows: Sequence[Bar], index: int, direction: str) -> ContextSignal:
    start = max(0, index - STRUCTURE_WINDOW + 1)
    snapshot = structure_snapshot(
        list(rows[start:index + 1]),
        swing_lookback=2,
        atr_period=CORE_VARIANT.atr_period,
        sweep_reclaim_bars=3,
    )
    displacement = snapshot.displacement
    fvg = snapshot.fvg
    liquid = LIQUID_UTC_START <= rows[index].timestamp.hour < LIQUID_UTC_END
    return ContextSignal(
        direction=direction,
        trend_aligned=_aligned(snapshot.trend, direction),
        displacement_aligned=bool(
            displacement is not None
            and displacement.valid
            and _aligned(displacement.direction, direction)
        ),
        fvg_aligned=bool(fvg is not None and fvg.valid and _aligned(fvg.direction, direction)),
        liquid_window=liquid,
        trend=str(snapshot.trend),
        bos=None if snapshot.bos is None else str(snapshot.bos),
        mss=None if snapshot.mss is None else str(snapshot.mss),
    )


def context_accepts(profile: ContextProfile, signal: ContextSignal) -> bool:
    return bool(
        (not profile.require_trend or signal.trend_aligned)
        and (not profile.require_displacement or signal.displacement_aligned)
        and (not profile.require_fvg or signal.fvg_aligned)
        and (not profile.require_liquid_window or signal.liquid_window)
    )


def simulate_context_profile(
    bars: Sequence[Bar],
    *,
    symbol: str,
    pip_size: float,
    profile: ContextProfile,
    costs: TournamentCosts,
) -> tuple[TournamentTrade, ...]:
    rows = _validate_bars(bars, symbol)
    warmup = max(CORE_VARIANT.lookback, CORE_VARIANT.atr_period, 40)
    trades: list[TournamentTrade] = []
    index = warmup
    contextual_id = f"DONCHIAN_CTX_{profile.profile_id}_V2"
    while index < len(rows) - 1:
        atr_value = _atr_at(rows, index, CORE_VARIANT.atr_period)
        if atr_value is None:
            index += 1
            continue
        channel = rows[index - CORE_VARIANT.lookback:index]
        upper = max(float(row.high) for row in channel)
        lower = min(float(row.low) for row in channel)
        close = float(rows[index].close)
        buffer_abs = CORE_VARIANT.buffer_atr * atr_value
        direction = None
        if close >= upper + buffer_abs:
            direction = "LONG"
        elif close <= lower - buffer_abs:
            direction = "SHORT"
        if direction is None:
            index += 1
            continue
        signal = _context_signal(rows, index, direction)
        if not context_accepts(profile, signal):
            index += 1
            continue
        trade = _trade_outcome(
            rows=rows,
            symbol=symbol.upper(),
            signal_index=index,
            direction=direction,
            atr_value=atr_value,
            pip_size=float(pip_size),
            costs=costs,
            variant=CORE_VARIANT,
        )
        if trade is None:
            index += 1
            continue
        trades.append(replace(trade, strategy_id=contextual_id))
        index = max(index + 1, trade.exit_index + 1)
    return tuple(trades)


def _metrics_pass(metrics: TournamentMetrics, cfg: Mapping[str, Any]) -> bool:
    return bool(
        metrics.win_rate is not None
        and metrics.win_rate >= float(cfg["win_rate_min"])
        and metrics.profit_factor is not None
        and metrics.profit_factor >= float(cfg["profit_factor_min"])
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= float(cfg["expectancy_r_min"])
    )


def evaluate_development(
    *,
    profile: ContextProfile,
    base_trades: Sequence[TournamentTrade],
    stressed_trades: Sequence[TournamentTrade],
    validation_cfg: Mapping[str, Any],
) -> ContextEvaluation:
    base = compute_metrics(base_trades)
    stressed = compute_metrics(stressed_trades)
    folds, pass_fraction, wf_passed = walk_forward(base_trades, validation_cfg["walk_forward"])
    stress_passed = _metrics_pass(stressed, validation_cfg["stress_acceptance"])
    development_passed = bool(
        profile.selection_eligible
        and base.completed_trades >= MIN_DEVELOPMENT_TRADES
        and wf_passed
        and stress_passed
    )
    return ContextEvaluation(
        profile=profile,
        development_metrics=base,
        stressed_development_metrics=stressed,
        walk_forward_pass_fraction=pass_fraction,
        walk_forward_passed=wf_passed,
        development_stress_passed=stress_passed,
        development_passed=development_passed,
    )


def select_on_development(evaluations: Sequence[ContextEvaluation]) -> ContextEvaluation | None:
    eligible = [row for row in evaluations if row.development_passed]
    if not eligible:
        return None
    eligible.sort(
        key=lambda row: (
            row.walk_forward_pass_fraction,
            row.stressed_development_metrics.expectancy_r
            if row.stressed_development_metrics.expectancy_r is not None else -999.0,
            row.stressed_development_metrics.profit_factor
            if row.stressed_development_metrics.profit_factor is not None else -999.0,
            row.development_metrics.expectancy_r
            if row.development_metrics.expectancy_r is not None else -999.0,
            -row.development_metrics.max_drawdown_r,
        ),
        reverse=True,
    )
    return eligible[0]


def evaluate_untouched_holdout(
    *,
    selected: ContextEvaluation | None,
    holdout_base: Sequence[TournamentTrade],
    holdout_stressed: Sequence[TournamentTrade],
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    if selected is None:
        return {
            "stage": "RESEARCH_ONLY",
            "selected_profile_id": None,
            "development_pass": False,
            "holdout_pass": False,
            "reason": "NO_CONTEXT_PROFILE_PASSED_DEVELOPMENT_GATES",
            "execution_influence": False,
        }
    base = compute_metrics(holdout_base)
    stressed = compute_metrics(holdout_stressed)
    base_pass = _metrics_pass(base, validation_cfg["stress_acceptance"])
    stress_pass = _metrics_pass(stressed, validation_cfg["stress_acceptance"])
    sample_pass = base.completed_trades >= MIN_HOLDOUT_TRADES
    holdout_pass = bool(sample_pass and base_pass and stress_pass)
    return {
        "stage": "FORWARD_SHADOW_ELIGIBLE" if holdout_pass else "RESEARCH_ONLY",
        "selected_profile_id": selected.profile.profile_id,
        "strategy_id": f"DONCHIAN_CTX_{selected.profile.profile_id}_V2",
        "core_params": {
            "lookback": CORE_VARIANT.lookback,
            "atr_period": CORE_VARIANT.atr_period,
            "buffer_atr": CORE_VARIANT.buffer_atr,
        },
        "development_pass": True,
        "holdout_pass": holdout_pass,
        "holdout_sample_pass": sample_pass,
        "minimum_holdout_trades": MIN_HOLDOUT_TRADES,
        "holdout": base.payload(),
        "stressed_holdout": stressed.payload(),
        "reason": "UNTOUCHED_HOLDOUT_PASS" if holdout_pass else "UNTOUCHED_HOLDOUT_FAILED",
        "execution_influence": False,
        "policy_effect": "SHADOW_ONLY",
    }
