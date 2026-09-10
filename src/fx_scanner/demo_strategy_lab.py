from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Mapping


class StrategyFamily(StrEnum):
    """DEMO research families. These labels have no execution authority."""

    TREND_MOMENTUM = "TREND_MOMENTUM"
    SESSION_BREAKOUT = "SESSION_BREAKOUT"
    PULLBACK_TREND = "PULLBACK_TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    FOUR_EMA_PULLBACK = "FOUR_EMA_PULLBACK"
    IMPULSE_RETEST = "IMPULSE_RETEST"


@dataclass(frozen=True, slots=True)
class StrategyHypothesis:
    family: StrategyFamily
    score: float
    active: bool
    evidence: Mapping[str, Any]
    policy_effect: str = "OBSERVATION_ONLY"
    hypothesis_version: int = 1

    def __post_init__(self) -> None:
        if not isfinite(float(self.score)) or not 0.0 <= float(self.score) <= 100.0:
            raise ValueError("strategy hypothesis score must be finite and in [0,100]")
        if self.policy_effect != "OBSERVATION_ONLY":
            raise ValueError("strategy lab hypotheses must remain observation-only")

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["family"] = self.family.value
        return payload


def _enumish(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw).strip().upper()
    return text or None


def _aligned(value: Any, direction: str) -> bool:
    wanted = "BULLISH" if str(direction).upper() == "LONG" else "BEARISH"
    return _enumish(value) == wanted


def _valid_directional(feature: Any, direction: str) -> bool:
    return bool(
        feature is not None
        and bool(getattr(feature, "valid", False))
        and _aligned(getattr(feature, "direction", None), direction)
    )


def _cap(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _ema_row(evidence: Mapping[str, Any], timeframe: str) -> Mapping[str, Any]:
    value = evidence.get(timeframe.lower())
    return value if isinstance(value, Mapping) else {}


def build_strategy_lab_hypotheses(
    *,
    analysis: Any,
    regime: str,
    session: str,
    geometry_payload: Mapping[str, Any] | None = None,
    ema_evidence: Mapping[str, Any] | None = None,
) -> tuple[StrategyHypothesis, ...]:
    """Build competing DEMO strategy hypotheses from one immutable signal snapshot.

    This function deliberately does not alter setup classification, conviction,
    guards, geometry, risk, or execution state. It only emits research labels
    that can later be joined to durable trade outcomes.
    """

    direction = str(getattr(analysis, "direction", "")).upper()
    h1 = analysis.h1
    m15 = analysis.m15
    m5 = analysis.m5
    regime = str(regime or "UNKNOWN").upper()
    session = str(session or "UNKNOWN").upper()
    geometry_payload = dict(geometry_payload or {})
    ema_evidence = dict(ema_evidence or {})

    aligned_h1 = _aligned(getattr(h1, "trend", None), direction)
    aligned_m15 = _aligned(getattr(m15, "trend", None), direction)
    aligned_m5 = _aligned(getattr(m5, "trend", None), direction)
    m5_displacement = _valid_directional(getattr(m5, "displacement", None), direction)
    m15_displacement = _valid_directional(getattr(m15, "displacement", None), direction)
    m5_bos = _aligned(getattr(m5, "bos", None), direction)
    m15_bos = _aligned(getattr(m15, "bos", None), direction)
    m5_sweep = _valid_directional(getattr(m5, "sweep", None), direction)
    m15_sweep = _valid_directional(getattr(m15, "sweep", None), direction)
    m5_fvg = _valid_directional(getattr(m5, "fvg", None), direction)
    m15_fvg = _valid_directional(getattr(m15, "fvg", None), direction)

    entry_mode = str(geometry_payload.get("entry_mode") or "").upper()
    confirmation = str(geometry_payload.get("confirmation") or "").upper()
    pullback_atr = geometry_payload.get("pullback_atr")
    try:
        pullback_atr_f = float(pullback_atr) if pullback_atr is not None else None
    except (TypeError, ValueError):
        pullback_atr_f = None

    trend_score = 20.0
    trend_score += 25.0 if aligned_h1 else 0.0
    trend_score += 20.0 if aligned_m15 else 0.0
    trend_score += 10.0 if aligned_m5 else 0.0
    trend_score += 15.0 if (m5_displacement or m15_displacement) else 0.0
    trend_score += 10.0 if (m5_bos or m15_bos) else 0.0
    if regime == "TREND_STRONG":
        trend_score += 10.0
    elif regime in {"RANGE", "REVERSAL"}:
        trend_score -= 20.0

    liquid_session = session in {"LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP", "OVERLAP"}
    breakout_score = 15.0
    breakout_score += 25.0 if liquid_session else 0.0
    breakout_score += 25.0 if (m5_displacement or m15_displacement) else 0.0
    breakout_score += 20.0 if (m5_bos or m15_bos) else 0.0
    breakout_score += 10.0 if aligned_h1 else 0.0
    breakout_score += 5.0 if regime in {"TREND_STRONG", "TRANSITION"} else 0.0

    pullback_score = 15.0
    pullback_score += 25.0 if aligned_h1 else 0.0
    pullback_score += 20.0 if aligned_m15 else 0.0
    pullback_score += 15.0 if (m5_fvg or m15_fvg) else 0.0
    pullback_score += 15.0 if any(token in entry_mode for token in ("PULLBACK", "RETRACE", "FVG")) else 0.0
    if pullback_atr_f is not None and 0.10 <= pullback_atr_f <= 1.25:
        pullback_score += 10.0
    if "PULLBACK" in confirmation:
        pullback_score += 5.0

    mean_reversion_score = 10.0
    mean_reversion_score += 35.0 if regime == "RANGE" else 0.0
    mean_reversion_score += 20.0 if (m5_sweep or m15_sweep) else 0.0
    mean_reversion_score += 15.0 if not aligned_h1 else 0.0
    mean_reversion_score += 10.0 if not (m5_displacement or m15_displacement) else -10.0
    mean_reversion_score += 10.0 if "RECLAIM" in confirmation else 0.0

    sweep_score = 10.0
    sweep_score += 35.0 if (m5_sweep or m15_sweep) else 0.0
    sweep_score += 20.0 if (m5_displacement or m15_displacement) else 0.0
    sweep_score += 15.0 if (m5_bos or m15_bos) else 0.0
    sweep_score += 10.0 if regime in {"REVERSAL", "TRANSITION"} else 0.0
    sweep_score += 10.0 if any(token in confirmation for token in ("MSS", "RECLAIM", "STRUCTURE_BREAK")) else 0.0

    ema_h1 = _ema_row(ema_evidence, "H1")
    ema_m15 = _ema_row(ema_evidence, "M15")
    ema_m5 = _ema_row(ema_evidence, "M5")
    ema_available = any(bool(row.get("available")) for row in (ema_h1, ema_m15, ema_m5))
    ema_score = 5.0 if not ema_available else 10.0
    ema_score += 20.0 if bool(ema_h1.get("directional_aligned")) else 0.0
    ema_score += 20.0 if bool(ema_m15.get("directional_aligned")) else 0.0
    ema_score += 10.0 if bool(ema_m5.get("directional_aligned")) else 0.0
    ema_score += 10.0 if bool(ema_h1.get("directional_slopes")) else 0.0
    ema_score += 10.0 if bool(ema_m15.get("directional_slopes")) else 0.0
    ema_score += 5.0 if str(ema_h1.get("spread_state", "")).upper() in {"STABLE", "EXPANDING"} else 0.0
    ema_score += 5.0 if str(ema_m15.get("spread_state", "")).upper() == "EXPANDING" else 0.0
    ema_pullback = bool(ema_m5.get("pullback_near_fast_cluster")) or bool(
        ema_m15.get("pullback_near_fast_cluster")
    )
    ema_score += 10.0 if ema_pullback else 0.0
    ema_score += 10.0 if (m5_displacement or m15_displacement or m5_bos or m15_bos) else 0.0
    ema_score -= 20.0 if bool(ema_h1.get("opposite_aligned")) else 0.0
    ema_score -= 15.0 if bool(ema_m15.get("opposite_aligned")) else 0.0
    if regime == "RANGE" and str(ema_m15.get("spread_state", "")).upper() == "COMPRESSING":
        ema_score -= 10.0

    # Original research hypothesis: a directional move is treated as credible only
    # after an impulse has been accepted and price returns in a controlled retest.
    # This intentionally rejects bare M5 structure breaks, which dominate the
    # current weak DEMO outcome cohort, and uses four-EMA state only as secondary
    # expansion/context evidence rather than as an execution trigger.
    impulse_present = m5_displacement or m15_displacement
    structure_present = m5_bos or m15_bos
    directional_fvg = m5_fvg or m15_fvg
    directional_sweep = m5_sweep or m15_sweep
    ema_not_opposed = not bool(ema_h1.get("opposite_aligned")) and not bool(
        ema_m15.get("opposite_aligned")
    )
    ema_release = str(ema_m5.get("spread_state", "")).upper() == "EXPANDING" or str(
        ema_m15.get("spread_state", "")
    ).upper() == "EXPANDING"
    controlled_retest = bool(
        pullback_atr_f is not None
        and 0.10 <= pullback_atr_f <= 1.25
        and any(token in entry_mode for token in ("PULLBACK", "RETRACE", "FVG"))
    )
    impulse_retest_score = 5.0
    impulse_retest_score += 20.0 if regime in {"TRANSITION", "TREND_WEAK", "TREND_STRONG"} else 0.0
    impulse_retest_score += 20.0 if impulse_present else -40.0
    impulse_retest_score += 10.0 if structure_present else 0.0
    impulse_retest_score += 10.0 if directional_fvg else 0.0
    impulse_retest_score += 5.0 if directional_sweep else 0.0
    impulse_retest_score += 10.0 if aligned_m15 else 0.0
    impulse_retest_score += 5.0 if aligned_h1 else 0.0
    impulse_retest_score += 5.0 if bool(ema_m15.get("directional_aligned")) else 0.0
    impulse_retest_score += 5.0 if bool(ema_m5.get("directional_aligned")) else 0.0
    impulse_retest_score += 5.0 if ema_release else 0.0
    impulse_retest_score += 10.0 if controlled_retest else 0.0
    impulse_retest_score += 5.0 if liquid_session else 0.0
    impulse_retest_score -= 20.0 if regime == "RANGE" else 0.0
    impulse_retest_score -= 20.0 if not ema_not_opposed else 0.0

    raw = (
        (StrategyFamily.TREND_MOMENTUM, trend_score, {
            "aligned_h1": aligned_h1,
            "aligned_m15": aligned_m15,
            "aligned_m5": aligned_m5,
            "directional_displacement": m5_displacement or m15_displacement,
            "directional_bos": m5_bos or m15_bos,
            "regime": regime,
        }),
        (StrategyFamily.SESSION_BREAKOUT, breakout_score, {
            "liquid_session": liquid_session,
            "directional_displacement": m5_displacement or m15_displacement,
            "directional_bos": m5_bos or m15_bos,
            "aligned_h1": aligned_h1,
            "session": session,
            "regime": regime,
        }),
        (StrategyFamily.PULLBACK_TREND, pullback_score, {
            "aligned_h1": aligned_h1,
            "aligned_m15": aligned_m15,
            "directional_fvg": m5_fvg or m15_fvg,
            "entry_mode": entry_mode or None,
            "confirmation": confirmation or None,
            "pullback_atr": pullback_atr_f,
        }),
        (StrategyFamily.MEAN_REVERSION, mean_reversion_score, {
            "range_regime": regime == "RANGE",
            "directional_sweep": m5_sweep or m15_sweep,
            "h1_not_aligned": not aligned_h1,
            "directional_displacement": m5_displacement or m15_displacement,
            "confirmation": confirmation or None,
        }),
        (StrategyFamily.LIQUIDITY_SWEEP, sweep_score, {
            "directional_sweep": m5_sweep or m15_sweep,
            "directional_displacement": m5_displacement or m15_displacement,
            "directional_bos": m5_bos or m15_bos,
            "regime": regime,
            "confirmation": confirmation or None,
        }),
        (StrategyFamily.FOUR_EMA_PULLBACK, ema_score, {
            "profile": ema_evidence.get("profile"),
            "periods": ema_evidence.get("periods"),
            "brochure_periods_confirmed": bool(ema_evidence.get("brochure_periods_confirmed", False)),
            "available_timeframes": ema_evidence.get("available_timeframes", 0),
            "mature_timeframes": ema_evidence.get("mature_timeframes", 0),
            "directional_confluence": ema_evidence.get("directional_confluence", 0),
            "h1_directional_aligned": bool(ema_h1.get("directional_aligned")),
            "m15_directional_aligned": bool(ema_m15.get("directional_aligned")),
            "m5_directional_aligned": bool(ema_m5.get("directional_aligned")),
            "h1_directional_slopes": bool(ema_h1.get("directional_slopes")),
            "m15_directional_slopes": bool(ema_m15.get("directional_slopes")),
            "h1_spread_state": ema_h1.get("spread_state"),
            "m15_spread_state": ema_m15.get("spread_state"),
            "pullback_near_fast_cluster": ema_pullback,
            "smc_confirmation": m5_displacement or m15_displacement or m5_bos or m15_bos,
            "regime": regime,
        }),
        (StrategyFamily.IMPULSE_RETEST, impulse_retest_score, {
            "regime": regime,
            "session": session,
            "impulse_present": impulse_present,
            "directional_structure": structure_present,
            "directional_fvg": directional_fvg,
            "directional_sweep": directional_sweep,
            "aligned_h1": aligned_h1,
            "aligned_m15": aligned_m15,
            "ema_not_opposed": ema_not_opposed,
            "ema_release": ema_release,
            "controlled_retest": controlled_retest,
            "pullback_atr": pullback_atr_f,
            "entry_mode": entry_mode or None,
            "confirmation": confirmation or None,
            "design_basis": "IMPULSE_ACCEPTANCE_THEN_FIRST_CONTROLLED_RETEST",
        }),
    )

    hypotheses = tuple(
        StrategyHypothesis(
            family=family,
            score=_cap(score),
            active=_cap(score) >= 60.0,
            evidence=evidence,
        )
        for family, score, evidence in raw
    )
    return tuple(sorted(hypotheses, key=lambda item: (-item.score, item.family.value)))


def strategy_lab_payload(**kwargs: Any) -> list[dict[str, Any]]:
    return [item.to_payload() for item in build_strategy_lab_hypotheses(**kwargs)]
