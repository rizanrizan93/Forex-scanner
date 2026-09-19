from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import ceil, floor, isfinite
from statistics import mean, median
from typing import Any, Mapping, Sequence

import numpy as np

from .models import Bar, ensure_utc
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    build_d1_context,
    build_h1_context,
)

RESEARCH_VERSION = "XAU_ROUND_NUMBER_BARRIER_V54"
ARTIFACT_CONTRACT = "XAU_ROUND_NUMBER_BARRIER_V54_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

ATR_PERIOD = 14
COOLDOWN_BARS_PER_EVENT = 16
FORWARD_HORIZONS = (1, 4, 16)
MAJOR_STEP = 100.0
MINOR_STEP = 10.0

EVENT_KINDS = (
    "UP_CROSS",
    "DOWN_CROSS",
    "REJECT_FROM_BELOW",
    "REJECT_FROM_ABOVE",
)


@dataclass(frozen=True, slots=True)
class BarrierEvent:
    barrier_class: str
    barrier: float
    event_kind: str
    index: int
    signal_at: Any
    atr: float
    event_close: float
    direction_sign: int
    d1_regime: str
    d1_side: int
    h1_normal: bool
    utc_hour: int
    pre_abs_move16_atr: float


def _atr_series(rows: Sequence[Bar], period: int = ATR_PERIOD) -> list[float | None]:
    out: list[float | None] = [None] * len(rows)
    if not rows:
        return out
    tr: list[float] = []
    for i, row in enumerate(rows):
        if i == 0:
            value = float(row.high) - float(row.low)
        else:
            prev = float(rows[i - 1].close)
            value = max(
                float(row.high) - float(row.low),
                abs(float(row.high) - prev),
                abs(float(row.low) - prev),
            )
        tr.append(value)
    alpha = 1.0 / float(period)
    value = tr[0]
    for i in range(1, len(tr)):
        value = alpha * tr[i] + (1.0 - alpha) * value
        if i >= period - 1:
            out[i] = float(value)
    return out


def _h1_normal(row: Mapping[str, Any], direction_sign: int) -> bool:
    close = float(row.get("close", np.nan))
    ema20 = float(row.get("ema20", np.nan))
    ema50 = float(row.get("ema50", np.nan))
    ema200 = float(row.get("ema200", np.nan))
    if not all(isfinite(x) for x in (close, ema20, ema50, ema200)):
        return False
    if direction_sign > 0:
        return close > ema200 and ema20 > ema50
    return close < ema200 and ema20 < ema50


def _nearest_above(price: float, step: float) -> float:
    quotient = price / step
    if abs(quotient - round(quotient)) < 1e-12:
        return price + step
    return ceil(quotient) * step


def _nearest_below(price: float, step: float) -> float:
    quotient = price / step
    if abs(quotient - round(quotient)) < 1e-12:
        return price - step
    return floor(quotient) * step


def _classify_barrier(step: float, barrier: float) -> str | None:
    if step == MAJOR_STEP:
        return "MAJOR_100"
    if step == MINOR_STEP:
        # Keep the $10 class orthogonal to the $100 class.
        if abs((barrier / MAJOR_STEP) - round(barrier / MAJOR_STEP)) < 1e-12:
            return None
        return "MINOR_10_NON100"
    raise ValueError(f"V54_STEP_INVALID:{step}")


def _pre_abs_move_atr(rows: Sequence[Bar], i: int, atr: float, bars: int = 16) -> float:
    if i < bars:
        return float("nan")
    total = 0.0
    for j in range(i - bars + 1, i + 1):
        total += abs(float(rows[j].close) - float(rows[j - 1].close))
    return total / atr if atr > 0 else float("nan")


def extract_barrier_events(rows: Sequence[Bar]) -> tuple[BarrierEvent, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()

    atrs = _atr_series(bars)
    d1 = build_d1_context(bars)
    h1 = build_h1_context(bars)
    d1_lookup = _Asof(d1)
    h1_lookup = _Asof(h1)

    last_seen: dict[tuple[str, float, str], int] = {}
    out: list[BarrierEvent] = []

    for i in range(max(ATR_PERIOD + 2, 20), len(bars) - max(FORWARD_HORIZONS) - 1):
        atr = atrs[i]
        if atr is None or not isfinite(float(atr)) or float(atr) <= 0:
            continue

        prev_close = float(bars[i - 1].close)
        row = bars[i]
        close = float(row.close)
        high = float(row.high)
        low = float(row.low)
        signal_at = ensure_utc(row.timestamp)
        d1_row = d1_lookup.row(signal_at)
        h1_row = h1_lookup.row(signal_at)
        if d1_row is None or h1_row is None:
            continue

        for step in (MAJOR_STEP, MINOR_STEP):
            above = _nearest_above(prev_close, step)
            below = _nearest_below(prev_close, step)

            candidates: list[tuple[str, float, int]] = []
            if close >= above:
                candidates.append(("UP_CROSS", above, 1))
            elif high >= above and close < above:
                candidates.append(("REJECT_FROM_BELOW", above, -1))

            if close <= below:
                candidates.append(("DOWN_CROSS", below, -1))
            elif low <= below and close > below:
                candidates.append(("REJECT_FROM_ABOVE", below, 1))

            for event_kind, barrier, direction_sign in candidates:
                barrier_class = _classify_barrier(step, barrier)
                if barrier_class is None:
                    continue
                key = (barrier_class, float(barrier), event_kind)
                prior_i = last_seen.get(key)
                if prior_i is not None and i - prior_i < COOLDOWN_BARS_PER_EVENT:
                    continue
                last_seen[key] = i

                out.append(
                    BarrierEvent(
                        barrier_class=barrier_class,
                        barrier=float(barrier),
                        event_kind=event_kind,
                        index=i,
                        signal_at=signal_at,
                        atr=float(atr),
                        event_close=close,
                        direction_sign=direction_sign,
                        d1_regime=str(d1_row.get("regime")),
                        d1_side=int(d1_row.get("regime_side") or 0),
                        h1_normal=_h1_normal(h1_row, direction_sign),
                        utc_hour=signal_at.hour,
                        pre_abs_move16_atr=_pre_abs_move_atr(
                            bars, i, float(atr), bars=16
                        ),
                    )
                )
    return tuple(out)


def _event_observation(
    bars: Sequence[Bar],
    event: BarrierEvent,
) -> dict[str, Any]:
    i = event.index
    atr = event.atr
    sign = event.direction_sign
    close0 = event.event_close
    payload: dict[str, Any] = {
        "barrier_class": event.barrier_class,
        "barrier": event.barrier,
        "event_kind": event.event_kind,
        "signal_at": ensure_utc(event.signal_at).isoformat(),
        "direction_sign": sign,
        "d1_regime": event.d1_regime,
        "d1_side": event.d1_side,
        "h1_normal": event.h1_normal,
        "utc_hour": event.utc_hour,
        "pre_abs_move16_atr": event.pre_abs_move16_atr,
    }

    for horizon in FORWARD_HORIZONS:
        future_close = float(bars[i + horizon].close)
        directional = sign * (future_close - close0) / atr
        highs = [float(bars[j].high) for j in range(i + 1, i + horizon + 1)]
        lows = [float(bars[j].low) for j in range(i + 1, i + horizon + 1)]
        if sign > 0:
            mfe = (max(highs) - close0) / atr
            mae = (close0 - min(lows)) / atr
        else:
            mfe = (close0 - min(lows)) / atr
            mae = (max(highs) - close0) / atr

        abs_move = 0.0
        prev = close0
        for j in range(i + 1, i + horizon + 1):
            current = float(bars[j].close)
            abs_move += abs(current - prev)
            prev = current

        payload[f"dir_ret_{horizon}_atr"] = directional
        payload[f"mfe_{horizon}_atr"] = mfe
        payload[f"mae_{horizon}_atr"] = mae
        payload[f"abs_move_{horizon}_atr"] = abs_move / atr

    payload["post_pre_abs_move16_ratio"] = (
        payload["abs_move_16_atr"] / event.pre_abs_move16_atr
        if isfinite(event.pre_abs_move16_atr) and event.pre_abs_move16_atr > 0
        else None
    )
    return payload


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = tuple(rows)
    if not values:
        return {"events": 0}

    out: dict[str, Any] = {"events": len(values)}
    for horizon in FORWARD_HORIZONS:
        xs = [float(x[f"dir_ret_{horizon}_atr"]) for x in values]
        mfe = [float(x[f"mfe_{horizon}_atr"]) for x in values]
        mae = [float(x[f"mae_{horizon}_atr"]) for x in values]
        abs_move = [float(x[f"abs_move_{horizon}_atr"]) for x in values]
        out[f"h{horizon}"] = {
            "directional_mean_atr": mean(xs),
            "directional_median_atr": median(xs),
            "directional_positive_fraction": sum(1 for x in xs if x > 0.0) / len(xs),
            "mfe_mean_atr": mean(mfe),
            "mae_mean_atr": mean(mae),
            "abs_move_mean_atr": mean(abs_move),
        }

    ratios = [
        float(x["post_pre_abs_move16_ratio"])
        for x in values
        if x.get("post_pre_abs_move16_ratio") is not None
        and isfinite(float(x["post_pre_abs_move16_ratio"]))
    ]
    out["volatility_shift_16"] = {
        "mean_post_pre_abs_move_ratio": mean(ratios) if ratios else None,
        "median_post_pre_abs_move_ratio": median(ratios) if ratios else None,
        "fraction_post_gt_pre": (
            sum(1 for x in ratios if x > 1.0) / len(ratios)
            if ratios else None
        ),
    }
    return out


def evaluate_v54(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V54_EMPTY_HISTORY")
    start = ensure_utc(era_start)
    end = ensure_utc(era_end)

    events = tuple(
        event
        for event in extract_barrier_events(rows)
        if start <= ensure_utc(event.signal_at) < end
    )
    observations = tuple(_event_observation(rows, event) for event in events)

    by_class_kind: dict[str, Any] = {}
    for barrier_class in ("MAJOR_100", "MINOR_10_NON100"):
        for event_kind in EVENT_KINDS:
            key = f"{barrier_class}|{event_kind}"
            by_class_kind[key] = _summary(
                tuple(
                    row
                    for row in observations
                    if row["barrier_class"] == barrier_class
                    and row["event_kind"] == event_kind
                )
            )

    by_regime: dict[str, Any] = {}
    regime_keys = sorted({str(row["d1_regime"]) for row in observations})
    for barrier_class in ("MAJOR_100", "MINOR_10_NON100"):
        for event_kind in EVENT_KINDS:
            for regime in regime_keys:
                selected = tuple(
                    row
                    for row in observations
                    if row["barrier_class"] == barrier_class
                    and row["event_kind"] == event_kind
                    and row["d1_regime"] == regime
                )
                if selected:
                    by_regime[f"{barrier_class}|{event_kind}|{regime}"] = _summary(selected)

    h1_breakdown: dict[str, Any] = {}
    for barrier_class in ("MAJOR_100", "MINOR_10_NON100"):
        for event_kind in EVENT_KINDS:
            for state in (False, True):
                selected = tuple(
                    row
                    for row in observations
                    if row["barrier_class"] == barrier_class
                    and row["event_kind"] == event_kind
                    and bool(row["h1_normal"]) is state
                )
                if selected:
                    h1_breakdown[
                        f"{barrier_class}|{event_kind}|H1_NORMAL_{int(state)}"
                    ] = _summary(selected)

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "era_id": era_id,
        "era_start": start.isoformat(),
        "era_end_exclusive": end.isoformat(),
        "event_count": len(observations),
        "preregistered_contract": {
            "barrier_classes": {
                "MAJOR_100": "integer multiples of USD 100 per oz",
                "MINOR_10_NON100": "integer multiples of USD 10 excluding USD 100 multiples",
            },
            "evidence_basis": (
                "Aggarwal-Lucey gold barrier evidence: strong daily barriers at 100s; "
                "high-frequency evidence also at 10s. Osler FX evidence motivates separate "
                "rejection versus continuation responses around round-number order clusters."
            ),
            "event_kinds": list(EVENT_KINDS),
            "cooldown_bars_same_barrier_kind": COOLDOWN_BARS_PER_EVENT,
            "forward_horizons_m15_bars": list(FORWARD_HORIZONS),
            "directional_trade_rule_created": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "by_barrier_class_and_event": by_class_kind,
        "by_d1_regime": by_regime,
        "by_h1_permission": h1_breakdown,
        "note": (
            "V54 is an event study, not a trading strategy. It asks whether gold round-number "
            "barriers change direction and/or realized movement consistently across eras before "
            "any executable round-number strategy is defined."
        ),
    }
