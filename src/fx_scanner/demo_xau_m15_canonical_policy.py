from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Mapping

CANONICAL_POLICY_CONTRACT = "XAU_M15_CANONICAL_DECISION_V1"
MIN_EXECUTION_SCORE = 75.0
MIN_TREND_ADX = 15.0
MATURE_TREND_ADX = 25.0
TP1_MILESTONE_R = 1.50
RUNNER_TRAIL_R = 2.00


class MarketRegime(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    CHOP = "CHOP"
    UNKNOWN = "UNKNOWN"


class EntryMode(StrEnum):
    RECLAIM = "RECLAIM"
    BREAKOUT_RETEST = "BREAKOUT_RETEST"
    CONTINUATION_PULLBACK = "CONTINUATION_PULLBACK"
    COUNTERTREND_SCALP = "COUNTERTREND_SCALP"
    NONE = "NONE"


class PositionStage(StrEnum):
    HOLD_INITIAL = "HOLD_INITIAL"
    HOLD_PROTECTED = "HOLD_PROTECTED"
    PROTECT_RUNNER = "PROTECT_RUNNER"
    TRAIL_RUNNER = "TRAIL_RUNNER"
    EXIT_ADVERSE_STRUCTURE = "EXIT_ADVERSE_STRUCTURE"


@dataclass(frozen=True, slots=True)
class CanonicalDecision:
    contract: str
    direction: str | None
    regime: MarketRegime
    entry_mode: EntryMode
    execution_ready: bool
    countertrend: bool
    reasons: tuple[str, ...]
    score: float
    adx: float | None
    h1_trend: str | None
    m15_trend: str | None
    ordered_smc: bool
    retracement_ok: bool
    ict_ready: bool
    ict_confluence_count: int

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["regime"] = self.regime.value
        payload["entry_mode"] = self.entry_mode.value
        return payload


@dataclass(frozen=True, slots=True)
class PositionManagementDecision:
    stage: PositionStage
    protect_stop: bool
    exit_position: bool
    reason: str
    current_r: float | None


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _infer_regime(evidence: Mapping[str, Any]) -> MarketRegime:
    adx = _finite(evidence.get("adx14"))
    if adx is None:
        return MarketRegime.UNKNOWN
    if adx < MIN_TREND_ADX:
        return MarketRegime.CHOP

    h1 = str(evidence.get("h1_trend") or "UNKNOWN").upper()
    m15 = str(evidence.get("m15_trend") or "UNKNOWN").upper()
    plus_di = _finite(evidence.get("plus_di14"))
    minus_di = _finite(evidence.get("minus_di14"))
    full_alignment = bool(evidence.get("full_ema_alignment"))
    momentum_alignment = bool(evidence.get("momentum_alignment"))
    price = _finite(evidence.get("price"))
    ema20 = _finite(evidence.get("ema20"))
    ema50 = _finite(evidence.get("ema50"))
    ema200 = _finite(evidence.get("ema200"))

    bullish_ema = bool(
        price is not None
        and ema20 is not None
        and ema50 is not None
        and ema200 is not None
        and price > ema20 > ema50 > ema200
    )
    bearish_ema = bool(
        price is not None
        and ema20 is not None
        and ema50 is not None
        and ema200 is not None
        and price < ema20 < ema50 < ema200
    )
    bullish_di = plus_di is not None and minus_di is not None and plus_di > minus_di
    bearish_di = plus_di is not None and minus_di is not None and minus_di > plus_di

    bull_votes = sum(
        (
            h1 == "BULLISH",
            m15 == "BULLISH",
            bullish_ema,
            bullish_di,
            full_alignment and bullish_ema,
            momentum_alignment and bullish_di,
        )
    )
    bear_votes = sum(
        (
            h1 == "BEARISH",
            m15 == "BEARISH",
            bearish_ema,
            bearish_di,
            full_alignment and bearish_ema,
            momentum_alignment and bearish_di,
        )
    )

    if bull_votes >= 3 and bull_votes >= bear_votes + 2:
        return MarketRegime.BULLISH
    if bear_votes >= 3 and bear_votes >= bull_votes + 2:
        return MarketRegime.BEARISH
    return MarketRegime.CHOP


def _entry_mode(
    *,
    direction: str,
    evidence: Mapping[str, Any],
    ict: Mapping[str, Any],
    countertrend: bool,
) -> EntryMode:
    if countertrend:
        return EntryMode.COUNTERTREND_SCALP
    if bool(evidence.get("transition_reclaim")):
        return EntryMode.RECLAIM

    sequence = dict(evidence.get("recent_smc_sequence") or {})
    ordered = bool(sequence.get("ordered"))
    retracement_ok = bool(sequence.get("retracement_ok"))
    fvg_or_ob = bool(
        sequence.get("fvg_retrace")
        or ict.get("fvg_retest")
        or ict.get("order_block_retest")
        or ict.get("ote_retest")
    )
    if ordered and retracement_ok and fvg_or_ob:
        return EntryMode.CONTINUATION_PULLBACK

    m15_bos = str(evidence.get("m15_bos") or "").upper()
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    if m15_bos == wanted and retracement_ok:
        return EntryMode.BREAKOUT_RETEST
    return EntryMode.NONE


def evaluate_canonical_xau_decision(
    *,
    direction: str | None,
    score: float,
    evidence: Mapping[str, Any],
    ict_evidence: Mapping[str, Any] | None,
) -> CanonicalDecision:
    """Deterministic final authority for the canonical XAU M15 execution path.

    The base EMA/SMC score and ICT layer remain evidence producers. This policy
    decides whether that evidence is coherent enough for DEMO execution. It
    deliberately blocks counter-trend scalps from automatic execution in V1;
    they remain research evidence until forward expectancy proves otherwise.
    """

    direction_text = str(direction or "").upper()
    ict = dict(ict_evidence or {})
    reasons: list[str] = []
    if direction_text not in {"LONG", "SHORT"}:
        reasons.append("DIRECTION_INVALID")

    regime = _infer_regime(evidence)
    desired = "LONG" if regime == MarketRegime.BULLISH else "SHORT" if regime == MarketRegime.BEARISH else None
    countertrend = bool(direction_text in {"LONG", "SHORT"} and desired is not None and direction_text != desired)
    mode = _entry_mode(
        direction=direction_text if direction_text in {"LONG", "SHORT"} else "LONG",
        evidence=evidence,
        ict=ict,
        countertrend=countertrend,
    )

    sequence = dict(evidence.get("recent_smc_sequence") or {})
    ordered_smc = bool(sequence.get("ordered"))
    retracement_ok = bool(sequence.get("retracement_ok"))
    ict_ready = bool(ict.get("execution_ready"))
    ict_confluence = int(ict.get("confluence_count") or 0)
    adx = _finite(evidence.get("adx14"))
    directional_di = bool(evidence.get("directional_di"))

    if float(score) < MIN_EXECUTION_SCORE:
        reasons.append("SCORE_BELOW_EXECUTION_MIN")
    if regime in {MarketRegime.CHOP, MarketRegime.UNKNOWN}:
        reasons.append("REGIME_NOT_DIRECTIONAL")
    if countertrend:
        reasons.append("COUNTERTREND_RESEARCH_ONLY")
    if mode == EntryMode.NONE:
        reasons.append("ENTRY_MODE_UNCONFIRMED")
    if not ordered_smc:
        reasons.append("SMC_SEQUENCE_NOT_ORDERED")
    if not retracement_ok:
        reasons.append("POST_IMPULSE_RETRACEMENT_MISSING")
    if adx is None or adx < MIN_TREND_ADX:
        reasons.append("ADX_REGIME_TOO_WEAK")
    if not directional_di:
        reasons.append("DI_DIRECTION_NOT_CONFIRMED")
    if not ict_ready:
        reasons.append("ICT_CONTEXT_NOT_READY")
    if ict_confluence < 2:
        reasons.append("ICT_CONFLUENCE_INSUFFICIENT")
    if not bool(ict.get("anti_chase_ok")):
        reasons.append("ANTI_FOMO_BLOCK")

    h1 = str(evidence.get("h1_trend") or "UNKNOWN").upper()
    m15 = str(evidence.get("m15_trend") or "UNKNOWN").upper()
    if direction_text == "LONG" and h1 == "BEARISH":
        reasons.append("H1_OPPOSES_LONG")
    elif direction_text == "SHORT" and h1 == "BULLISH":
        reasons.append("H1_OPPOSES_SHORT")

    # Weak/developing ADX is permitted only for an explicit reclaim transition.
    if adx is not None and MIN_TREND_ADX <= adx < 20.0 and mode != EntryMode.RECLAIM:
        reasons.append("DEVELOPING_ADX_REQUIRES_RECLAIM")

    return CanonicalDecision(
        contract=CANONICAL_POLICY_CONTRACT,
        direction=direction_text if direction_text in {"LONG", "SHORT"} else None,
        regime=regime,
        entry_mode=mode,
        execution_ready=not reasons,
        countertrend=countertrend,
        reasons=tuple(dict.fromkeys(reasons)),
        score=float(score),
        adx=adx,
        h1_trend=h1,
        m15_trend=m15,
        ordered_smc=ordered_smc,
        retracement_ok=retracement_ok,
        ict_ready=ict_ready,
        ict_confluence_count=ict_confluence,
    )


def evaluate_position_management(
    *,
    current_r: float | None,
    profitable: bool,
    adverse_structure_confirmed: bool,
) -> PositionManagementDecision:
    """Position-aware state machine used after a canonical XAU fill.

    It never widens risk. Before TP1 the trade keeps structural room. Once the
    TP1 milestone is reached, the remaining runner may be protected near entry;
    stronger progress permits structural trailing. A confirmed adverse
    structure while profitable has priority over holding for the fixed target.
    """

    r_value = _finite(current_r)
    if profitable and adverse_structure_confirmed:
        return PositionManagementDecision(
            PositionStage.EXIT_ADVERSE_STRUCTURE,
            False,
            True,
            "CONFIRMED_ADVERSE_STRUCTURE_WHILE_PROFITABLE",
            r_value,
        )
    if r_value is None or r_value < 1.0:
        return PositionManagementDecision(
            PositionStage.HOLD_INITIAL,
            False,
            False,
            "STRUCTURAL_ROOM_REQUIRED",
            r_value,
        )
    if r_value < TP1_MILESTONE_R:
        return PositionManagementDecision(
            PositionStage.HOLD_PROTECTED,
            False,
            False,
            "PROFIT_POSITIVE_BUT_BE_NOT_YET_JUSTIFIED",
            r_value,
        )
    if r_value < RUNNER_TRAIL_R:
        return PositionManagementDecision(
            PositionStage.PROTECT_RUNNER,
            True,
            False,
            "TP1_MILESTONE_REACHED_PROTECT_RUNNER",
            r_value,
        )
    return PositionManagementDecision(
        PositionStage.TRAIL_RUNNER,
        True,
        False,
        "RUNNER_ELIGIBLE_FOR_STRUCTURAL_TRAIL",
        r_value,
    )
