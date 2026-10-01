from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Sequence

import numpy as np

from .models import Bar, ensure_utc

RESEARCH_VERSION = "XAU_CHART_POINT_CONDITIONAL_V171"
ARTIFACT_CONTRACT = "XAU_CHART_POINT_CONDITIONAL_V171_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

SYMBOL = "XAUUSD"
TIMEFRAME = "D1"
ATR_PERIOD = 14
MOMENTUM_LOOKBACK = 20  # transparent 4-week approximation to Raschke's 3-4 week wording
REACTION_ATR = 0.50     # explicit public example
REACTION_WAIT_DAYS = 5  # researcher-defined diagnostic window, not attributed to Raschke
PRIMARY_REVISIT_DAYS = 5
SENSITIVITY_REVISIT_DAYS = (2, 10)
DEVELOPMENT_FRACTION = 0.70


@dataclass(frozen=True, slots=True)
class ConditionalCase:
    anchor_index: int
    reaction_index: int
    side: str
    extreme_momentum: bool
    anchor_at: datetime
    reaction_at: datetime
    anchor_extreme: float
    atr: float
    revisit_2d: bool
    revisit_5d: bool
    revisit_10d: bool
    directional_return_2d_atr: float | None
    directional_return_5d_atr: float | None
    directional_return_10d_atr: float | None


def _validate(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    bars = tuple(sorted(rows, key=lambda row: ensure_utc(row.timestamp)))
    if not bars:
        raise ValueError("V171_BARS_EMPTY")
    if any(row.symbol.upper() != SYMBOL for row in bars):
        raise ValueError("V171_REQUIRES_XAUUSD")
    if any(
        ensure_utc(bars[i].timestamp) >= ensure_utc(bars[i + 1].timestamp)
        for i in range(len(bars) - 1)
    ):
        raise ValueError("V171_BARS_NOT_CHRONOLOGICAL")
    return bars


def _atr(rows: Sequence[Bar], period: int = ATR_PERIOD) -> tuple[float | None, ...]:
    if period <= 0:
        raise ValueError("V171_ATR_PERIOD_INVALID")
    trs: list[float] = []
    previous_close = float(rows[0].close)
    for row in rows:
        high = float(row.high)
        low = float(row.low)
        trs.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )
        previous_close = float(row.close)

    output: list[float | None] = [None] * len(rows)
    if len(rows) < period:
        return tuple(output)
    seed = sum(trs[:period]) / period
    output[period - 1] = seed
    previous = seed
    for i in range(period, len(rows)):
        previous = ((previous * (period - 1)) + trs[i]) / period
        output[i] = float(previous)
    return tuple(output)


def _roc2(rows: Sequence[Bar]) -> tuple[float | None, ...]:
    out: list[float | None] = [None, None]
    for i in range(2, len(rows)):
        out.append(float(rows[i].close) - float(rows[i - 2].close))
    return tuple(out[: len(rows)])


def _is_extreme_momentum(
    roc: Sequence[float | None],
    index: int,
    side: str,
) -> bool:
    if index < MOMENTUM_LOOKBACK + 2 or roc[index] is None:
        return False
    history = [
        float(value)
        for value in roc[index - MOMENTUM_LOOKBACK : index]
        if value is not None
    ]
    if len(history) < MOMENTUM_LOOKBACK:
        return False
    value = float(roc[index])
    if side == "LOW":
        return value < min(history)
    if side == "HIGH":
        return value > max(history)
    raise ValueError(f"V171_SIDE_INVALID:{side}")


def _find_clean_reaction(
    rows: Sequence[Bar],
    *,
    anchor_index: int,
    side: str,
    atr: float,
) -> int | None:
    anchor = rows[anchor_index]
    if side == "LOW":
        extreme = float(anchor.low)
        threshold = extreme + REACTION_ATR * atr
    elif side == "HIGH":
        extreme = float(anchor.high)
        threshold = extreme - REACTION_ATR * atr
    else:
        raise ValueError(f"V171_SIDE_INVALID:{side}")

    end = min(len(rows) - 1, anchor_index + REACTION_WAIT_DAYS)
    for j in range(anchor_index + 1, end + 1):
        row = rows[j]
        if side == "LOW":
            # The public proposition concerns a later revisit after the reaction.
            # If the original low is already broken before/inside the reaction bar,
            # chronology is contaminated and the case is excluded.
            if float(row.low) <= extreme:
                return None
            if float(row.high) >= threshold:
                return j
        else:
            if float(row.high) >= extreme:
                return None
            if float(row.low) <= threshold:
                return j
    return None


def _post_reaction_case(
    rows: Sequence[Bar],
    *,
    anchor_index: int,
    reaction_index: int,
    side: str,
    extreme_momentum: bool,
    atr: float,
) -> ConditionalCase | None:
    max_horizon = max(PRIMARY_REVISIT_DAYS, *SENSITIVITY_REVISIT_DAYS)
    if reaction_index + max_horizon >= len(rows):
        return None

    if side == "LOW":
        anchor_extreme = float(rows[anchor_index].low)
        sign = -1.0
    elif side == "HIGH":
        anchor_extreme = float(rows[anchor_index].high)
        sign = 1.0
    else:
        raise ValueError(f"V171_SIDE_INVALID:{side}")

    reaction_close = float(rows[reaction_index].close)

    def revisit(days: int) -> bool:
        future = rows[reaction_index + 1 : reaction_index + days + 1]
        if side == "LOW":
            return any(float(row.low) <= anchor_extreme for row in future)
        return any(float(row.high) >= anchor_extreme for row in future)

    def directional_return(days: int) -> float | None:
        idx = reaction_index + days
        if idx >= len(rows):
            return None
        # Positive means movement toward the forecasted extreme-retest direction.
        return float(sign * (float(rows[idx].close) - reaction_close) / atr)

    return ConditionalCase(
        anchor_index=anchor_index,
        reaction_index=reaction_index,
        side=side,
        extreme_momentum=bool(extreme_momentum),
        anchor_at=ensure_utc(rows[anchor_index].timestamp),
        reaction_at=ensure_utc(rows[reaction_index].timestamp),
        anchor_extreme=anchor_extreme,
        atr=float(atr),
        revisit_2d=revisit(2),
        revisit_5d=revisit(5),
        revisit_10d=revisit(10),
        directional_return_2d_atr=directional_return(2),
        directional_return_5d_atr=directional_return(5),
        directional_return_10d_atr=directional_return(10),
    )


def build_cases(rows: Sequence[Bar]) -> tuple[ConditionalCase, ...]:
    bars = _validate(rows)
    atr_values = _atr(bars)
    roc = _roc2(bars)
    cases: list[ConditionalCase] = []

    start = max(ATR_PERIOD, MOMENTUM_LOOKBACK + 2)
    stop = len(bars) - max(PRIMARY_REVISIT_DAYS, *SENSITIVITY_REVISIT_DAYS) - 1
    for i in range(start, stop):
        atr = atr_values[i]
        momentum = roc[i]
        if atr is None or momentum is None or not isfinite(float(atr)) or float(atr) <= 0:
            continue

        if float(momentum) < 0:
            side = "LOW"
        elif float(momentum) > 0:
            side = "HIGH"
        else:
            continue

        reaction_index = _find_clean_reaction(
            bars,
            anchor_index=i,
            side=side,
            atr=float(atr),
        )
        if reaction_index is None:
            continue

        case = _post_reaction_case(
            bars,
            anchor_index=i,
            reaction_index=reaction_index,
            side=side,
            extreme_momentum=_is_extreme_momentum(roc, i, side),
            atr=float(atr),
        )
        if case is not None:
            cases.append(case)

    return tuple(cases)


def _quantiles(values: Sequence[float]) -> dict[str, float] | None:
    clean = [float(value) for value in values if isfinite(float(value))]
    if not clean:
        return None
    arr = np.asarray(clean, dtype=float)
    return {
        "q25": float(np.quantile(arr, 0.25)),
        "q50": float(np.quantile(arr, 0.50)),
        "q75": float(np.quantile(arr, 0.75)),
    }


def _summarize(cases: Sequence[ConditionalCase]) -> dict[str, Any]:
    rows = tuple(cases)
    if not rows:
        return {
            "n": 0,
            "revisit_2d_rate": None,
            "revisit_5d_rate": None,
            "revisit_10d_rate": None,
            "directional_return_atr": {"2d": None, "5d": None, "10d": None},
        }
    return {
        "n": len(rows),
        "revisit_2d_rate": sum(row.revisit_2d for row in rows) / len(rows),
        "revisit_5d_rate": sum(row.revisit_5d for row in rows) / len(rows),
        "revisit_10d_rate": sum(row.revisit_10d for row in rows) / len(rows),
        "directional_return_atr": {
            "2d": _quantiles(
                [
                    row.directional_return_2d_atr
                    for row in rows
                    if row.directional_return_2d_atr is not None
                ]
            ),
            "5d": _quantiles(
                [
                    row.directional_return_5d_atr
                    for row in rows
                    if row.directional_return_5d_atr is not None
                ]
            ),
            "10d": _quantiles(
                [
                    row.directional_return_10d_atr
                    for row in rows
                    if row.directional_return_10d_atr is not None
                ]
            ),
        },
    }


def _comparison(cases: Sequence[ConditionalCase]) -> dict[str, Any]:
    extreme = tuple(row for row in cases if row.extreme_momentum)
    baseline = tuple(row for row in cases if not row.extreme_momentum)
    extreme_summary = _summarize(extreme)
    baseline_summary = _summarize(baseline)
    lift = None
    if (
        extreme_summary["revisit_5d_rate"] is not None
        and baseline_summary["revisit_5d_rate"] is not None
    ):
        lift = (
            float(extreme_summary["revisit_5d_rate"])
            - float(baseline_summary["revisit_5d_rate"])
        )
    return {
        "extreme_momentum": extreme_summary,
        "same_sign_non_extreme_baseline": baseline_summary,
        "primary_5d_revisit_lift": lift,
    }


def evaluate_v171(rows: Sequence[Bar]) -> dict[str, Any]:
    bars = _validate(rows)
    cases = build_cases(bars)
    split_index = max(1, min(len(bars) - 1, int(len(bars) * DEVELOPMENT_FRACTION)))
    split_at = ensure_utc(bars[split_index].timestamp)

    development = tuple(row for row in cases if row.anchor_index < split_index)
    holdout = tuple(row for row in cases if row.anchor_index >= split_index)

    def scope(values: Sequence[ConditionalCase]) -> dict[str, Any]:
        low = tuple(row for row in values if row.side == "LOW")
        high = tuple(row for row in values if row.side == "HIGH")
        return {
            "all": _comparison(values),
            "momentum_low_then_half_atr_reaction": _comparison(low),
            "momentum_high_then_half_atr_reaction": _comparison(high),
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "history_bars": len(bars),
        "history_start": ensure_utc(bars[0].timestamp).isoformat(),
        "history_end": ensure_utc(bars[-1].timestamp).isoformat(),
        "split_at": split_at.isoformat(),
        "public_hypothesis_contract": {
            "source_component": (
                "Raschke public interview example: quantify actual chart points; "
                "after a new momentum low and a +0.5 ATR reaction, measure odds "
                "that price later trades below that low."
            ),
            "momentum": "2-bar close difference, matching the interview's 2-period ROC description",
            "extreme_window_sessions": MOMENTUM_LOOKBACK,
            "extreme_window_note": "20 sessions is a transparent ~4-week approximation to the stated 3-4 weeks",
            "reaction_atr": REACTION_ATR,
            "reaction_wait_days": REACTION_WAIT_DAYS,
            "reaction_wait_note": "researcher-defined; not attributed to Raschke",
            "primary_revisit_days": PRIMARY_REVISIT_DAYS,
            "primary_horizon_note": "researcher-defined; not attributed to Raschke",
            "sensitivity_revisit_days": list(SENSITIVITY_REVISIT_DAYS),
            "same_bar_or_pre_reaction_extreme_break": "EXCLUDED_AS_CHRONOLOGY_CONTAMINATED",
            "no_parameter_grid": True,
            "no_same_sample_promotion": True,
        },
        "full": scope(cases),
        "development": scope(development),
        "holdout": scope(holdout),
        "decision": {
            "stage": "CONDITIONAL_PROBABILITY_DIAGNOSTIC_ONLY",
            "promotion": False,
            "execution_change": False,
            "note": (
                "V171 tests whether the public chart-point/ATR conditional example "
                "transfers to XAUUSD. It is not claimed as Raschke's complete system."
            ),
        },
    }
