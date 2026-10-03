from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Iterable

import pandas as pd

from .models import ensure_utc

CONTRACT = "XAU_RIZAN_AFIQ_BEHAVIORAL_LAYER_V376"
EXECUTION_SCOPE = "DEMO_ONLY_GATING_PLUS_MANUAL_LIVE_DECISION_SUPPORT"
LIVE_EXECUTION_ENABLED = False


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _frame(bars: Iterable[Any], *, minutes: int, as_of: datetime) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    now = pd.Timestamp(ensure_utc(as_of))
    delta = pd.Timedelta(minutes=minutes)
    for bar in bars:
        ts = getattr(bar, "timestamp", None)
        if ts is None:
            continue
        stamp = pd.Timestamp(ensure_utc(ts))
        if stamp + delta > now:
            continue
        rows.append(
            {
                "timestamp": stamp,
                "open": float(getattr(bar, "open")),
                "high": float(getattr(bar, "high")),
                "low": float(getattr(bar, "low")),
                "close": float(getattr(bar, "close")),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    return (
        pd.DataFrame(rows)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    previous = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=max(6, period // 2)).mean()


def _m30_from_m15(bars_m15: Iterable[Any], *, as_of: datetime) -> pd.DataFrame:
    m15 = _frame(bars_m15, minutes=15, as_of=as_of)
    if m15.empty:
        return m15
    work = m15.set_index("timestamp")
    out = work.resample("30min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    # A 30-minute candle is only known once both M15 components are complete.
    now = pd.Timestamp(ensure_utc(as_of))
    out = out[(out.index + pd.Timedelta(minutes=30)) <= now]
    return out.reset_index()


def _regime(sd: dict[str, Any], m15: pd.DataFrame) -> dict[str, Any]:
    structure = dict(sd.get("market_structure") or {})
    h4 = str(dict(structure.get("H4") or {}).get("state") or "UNKNOWN")
    h1 = str(dict(structure.get("H1") or {}).get("state") or "UNKNOWN")

    if h4.startswith("BULLISH_BREAK") and h1.startswith("BULLISH"):
        state = "TREND_EXPANSION_UP"
    elif h4.startswith("BEARISH_BREAK") and h1.startswith("BEARISH"):
        state = "TREND_EXPANSION_DOWN"
    elif h4.startswith("BULLISH") and h1.startswith("BEARISH"):
        state = "TRANSITION_DOWN"
    elif h4.startswith("BEARISH") and h1.startswith("BULLISH"):
        state = "TRANSITION_UP"
    elif h4.startswith("BULLISH") and h1.startswith("BULLISH"):
        state = "TREND_EXPANSION_UP"
    elif h4.startswith("BEARISH") and h1.startswith("BEARISH"):
        state = "TREND_EXPANSION_DOWN"
    else:
        state = "BALANCE_ROTATION"

    impulse_atr = None
    rejection = False
    if len(m15) >= 16:
        work = m15.tail(40).copy()
        work["atr14"] = _atr(work)
        last = work.iloc[-1]
        atr = _f(last.get("atr14"))
        if atr and atr > 0:
            prior_close = float(work.iloc[-4]["close"]) if len(work) >= 4 else float(work.iloc[0]["close"])
            impulse_atr = abs(float(last["close"]) - prior_close) / atr
            rng = max(float(last["high"]) - float(last["low"]), 1e-9)
            upper_wick = float(last["high"]) - max(float(last["open"]), float(last["close"]))
            lower_wick = min(float(last["open"]), float(last["close"])) - float(last["low"])
            rejection = max(upper_wick, lower_wick) / rng >= 0.45
            if impulse_atr >= 2.5 and rejection:
                state = (
                    "CLIMAX_EXHAUSTION_UP"
                    if float(last["close"]) >= prior_close
                    else "CLIMAX_EXHAUSTION_DOWN"
                )

    return {
        "state": state,
        "h4": h4,
        "h1": h1,
        "m15_impulse_3bar_atr": impulse_atr,
        "m15_rejection_wick": rejection,
        "rule": "HTF_STRUCTURE_FIRST_WITH_M15_CLIMAX_OVERRIDE",
    }


def _m30_state(m30: pd.DataFrame) -> dict[str, Any]:
    if len(m30) < 24:
        return {"state": "UNKNOWN", "reason": "INSUFFICIENT_COMPLETED_M30"}
    work = m30.tail(80).copy()
    work["ema20"] = work["close"].ewm(span=20, adjust=False).mean()
    work["atr14"] = _atr(work)
    last = work.iloc[-1]
    prior = work.iloc[-7:-1]
    close = float(last["close"])
    prior_high = float(prior["high"].max())
    prior_low = float(prior["low"].min())
    ema20 = float(last["ema20"])
    atr = _f(last.get("atr14"))
    rng = max(float(last["high"]) - float(last["low"]), 1e-9)
    body_fraction = abs(float(last["close"]) - float(last["open"])) / rng
    displacement = bool(atr and atr > 0 and rng >= 0.85 * atr and body_fraction >= 0.50)

    if close > prior_high:
        state = "BULLISH_INTERNAL_BREAK"
    elif close < prior_low:
        state = "BEARISH_INTERNAL_BREAK"
    elif close > ema20:
        state = "BULLISH_INTERNAL_RANGE"
    elif close < ema20:
        state = "BEARISH_INTERNAL_RANGE"
    else:
        state = "NEUTRAL"

    return {
        "state": state,
        "close": close,
        "ema20": ema20,
        "prior_high": prior_high,
        "prior_low": prior_low,
        "displacement": displacement,
        "completed_at": (
            pd.Timestamp(last["timestamp"]) + pd.Timedelta(minutes=30)
        ).isoformat(),
    }


def _zone_roles(sd: dict[str, Any], regime: str, price_now: float | None) -> list[dict[str, Any]]:
    zones = [dict(row or {}) for row in list(sd.get("active_zones") or [])]
    main = dict(sd.get("main_reversal_zone") or sd.get("decision_zone") or {})
    refinement = dict(sd.get("refinement_zone") or {})
    main_id = str(main.get("zone_id") or "")
    refinement_id = str(refinement.get("zone_id") or "")
    direction = str(sd.get("expected_reversal_direction") or "WAIT")
    path = list(dict(sd.get("structural_path") or {}).get("checkpoints") or [])
    path_zone_ids = {
        str(row.get("zone_id") or "")
        for row in path
        if str(row.get("type") or "") == "ZONE"
    }

    out: list[dict[str, Any]] = []
    for zone in zones:
        zid = str(zone.get("zone_id") or "")
        condition = str(zone.get("condition") or dict(zone.get("lifecycle") or {}).get("freshness") or "ACTIVE")
        eligible = bool(zone.get("main_reversal_eligible"))
        zdir = str(zone.get("direction") or "")
        tf = str(zone.get("timeframe") or "")

        if zid and zid == main_id:
            role = "MAIN_REVERSAL"
        elif zid and zid == refinement_id:
            role = "PULLBACK_CONTINUATION" if regime.startswith("TREND_EXPANSION") else "SECONDARY_REACTION"
        elif condition in {"BROKEN", "EXPIRED", "NEAR_EXHAUSTED"}:
            role = "FAILED_RETIRED" if condition in {"BROKEN", "EXPIRED"} else "CONTEXT_ONLY"
        elif zid in path_zone_ids and zdir != direction:
            role = "LIQUIDITY_DESTINATION" if not eligible else "SECONDARY_REACTION"
        elif tf == "H1" and zdir == direction and regime.startswith("TREND_EXPANSION"):
            role = "PULLBACK_CONTINUATION"
        elif eligible:
            role = "SECONDARY_REACTION"
        else:
            role = "CONTEXT_ONLY"

        center = None
        low = _f(zone.get("low"))
        high = _f(zone.get("high"))
        if low is not None and high is not None:
            center = (low + high) / 2.0
        out.append(
            {
                "zone_id": zid or None,
                "timeframe": tf,
                "direction": zdir,
                "low": low,
                "high": high,
                "center": center,
                "role": role,
                "condition": condition,
                "quality_score": zone.get("main_reversal_score") or zone.get("score"),
                "distance_points": (
                    abs(float(price_now) - center)
                    if price_now is not None and center is not None
                    else None
                ),
            }
        )
    out.sort(
        key=lambda row: (
            0 if row.get("role") == "MAIN_REVERSAL" else 1,
            float(row.get("distance_points") or 1e18),
        )
    )
    return out


def _acceptance_rejection(
    sd: dict[str, Any],
    m15: pd.DataFrame,
    *,
    price_now: float | None,
) -> dict[str, Any]:
    zone = dict(sd.get("main_reversal_zone") or sd.get("decision_zone") or {})
    if not zone or len(m15) < 3:
        return {"state": "UNAVAILABLE", "interacting": False}
    direction = str(zone.get("direction") or "")
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    distal = _f(zone.get("distal"))
    proximal = _f(zone.get("proximal"))
    atr = _f(zone.get("atr"))
    if None in {low, high, distal, proximal, atr} or not atr or atr <= 0:
        return {"state": "UNAVAILABLE", "interacting": False}

    recent = m15.tail(12).copy()
    if direction == "LONG":
        interaction = (recent["low"] <= high) & (recent["high"] >= low)
        outside = recent["close"] < distal
        deep_outside = recent["close"] < distal - 0.15 * atr
        reclaimed = recent["close"] > proximal
        adverse_extreme = float(recent["low"].min())
        penetration_atr = max(0.0, distal - adverse_extreme) / atr
        latest_supportive = float(recent.iloc[-1]["close"]) > proximal
        displacement_away = float(recent.iloc[-1]["close"]) - float(recent.iloc[-3]["close"]) >= 0.45 * atr
    else:
        interaction = (recent["high"] >= low) & (recent["low"] <= high)
        outside = recent["close"] > distal
        deep_outside = recent["close"] > distal + 0.15 * atr
        reclaimed = recent["close"] < proximal
        adverse_extreme = float(recent["high"].max())
        penetration_atr = max(0.0, adverse_extreme - distal) / atr
        latest_supportive = float(recent.iloc[-1]["close"]) < proximal
        displacement_away = float(recent.iloc[-3]["close"]) - float(recent.iloc[-1]["close"]) >= 0.45 * atr

    interacted = bool(interaction.any()) or (
        price_now is not None and float(low) - 0.25 * atr <= float(price_now) <= float(high) + 0.25 * atr
    )
    outside_count = int(outside.tail(4).sum())
    deep_latest = bool(deep_outside.iloc[-1])
    two_latest = bool(len(outside) >= 2 and outside.iloc[-1] and outside.iloc[-2])
    reclaim_seen = bool(reclaimed.tail(5).any())

    if interacted and (deep_latest or two_latest) and not latest_supportive:
        state = "ACCEPTANCE_AGAINST_THESIS"
    elif interacted and reclaim_seen and latest_supportive and displacement_away:
        state = "REJECTION_CONFIRMED"
    elif interacted and reclaim_seen and latest_supportive:
        state = "REJECTION_DEVELOPING"
    elif interacted:
        state = "TESTING_ZONE"
    else:
        state = "NO_INTERACTION"

    return {
        "state": state,
        "interacting": interacted,
        "direction": direction,
        "outside_close_count_last4": outside_count,
        "deep_outside_latest": deep_latest,
        "reclaim_seen": reclaim_seen,
        "latest_supportive_close": latest_supportive,
        "displacement_away": displacement_away,
        "penetration_atr": penetration_atr,
        "rule": (
            "REJECTION=brief penetration/reclaim with supportive close; "
            "ACCEPTANCE=deep latest or two consecutive completed M15 closes beyond distal without supportive reclaim"
        ),
    }


def _response_timer(
    sd: dict[str, Any],
    m5: pd.DataFrame,
    acceptance: dict[str, Any],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    micro = dict(sd.get("micro_confirmation") or {})
    if not bool(micro.get("early_confirmed")):
        return {"state": "NOT_STARTED", "bars_elapsed": 0}
    raw = micro.get("reclaim_at")
    if not raw:
        return {"state": "NOT_STARTED", "bars_elapsed": 0}
    try:
        reclaim_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return {"state": "INVALID_RECLAIM_TIME", "bars_elapsed": 0}
    reclaim_at = ensure_utc(reclaim_at)
    direction = str(sd.get("expected_reversal_direction") or "")
    local_atr = _f(micro.get("local_atr")) or _f(dict(sd.get("main_reversal_zone") or {}).get("atr"))
    reference = _f(micro.get("confirmation_close")) or _f(sd.get("price_now"))
    if m5.empty or local_atr is None or local_atr <= 0 or reference is None:
        return {"state": "UNAVAILABLE", "bars_elapsed": 0}

    after = m5[m5["timestamp"] >= pd.Timestamp(reclaim_at - timedelta(minutes=5))].tail(12)
    bars_elapsed = max(0, int((ensure_utc(as_of) - reclaim_at).total_seconds() // 300))
    if after.empty:
        return {"state": "FOLLOW_THROUGH_PENDING", "bars_elapsed": bars_elapsed}

    if direction == "LONG":
        favorable = max(0.0, float(after["high"].max()) - reference) / local_atr
        adverse = max(0.0, reference - float(after["low"].min())) / local_atr
    else:
        favorable = max(0.0, reference - float(after["low"].min())) / local_atr
        adverse = max(0.0, float(after["high"].max()) - reference) / local_atr

    if str(acceptance.get("state")) == "ACCEPTANCE_AGAINST_THESIS" or adverse >= 0.75:
        state = "REACTION_FAILED"
    elif bool(micro.get("confirmed")) or favorable >= 0.75:
        state = "FOLLOW_THROUGH_CONFIRMED"
    elif bars_elapsed <= 3:
        state = "FOLLOW_THROUGH_PENDING"
    elif bars_elapsed >= 6 and favorable < 0.35:
        state = "REACTION_STALLED"
    else:
        state = "FOLLOW_THROUGH_WEAK"

    return {
        "state": state,
        "bars_elapsed": bars_elapsed,
        "favorable_excursion_local_atr": favorable,
        "adverse_excursion_local_atr": adverse,
        "reclaim_at": reclaim_at.isoformat(),
        "window_rule": "3_M5_BARS_EXPECT_RESPONSE;_6_BARS_WITH_LT0P35_ATR_FAVORABLE=STALL",
    }


def _expected_path(sd: dict[str, Any]) -> list[dict[str, Any]]:
    direction = str(sd.get("expected_reversal_direction") or "WAIT")
    sweep = dict(sd.get("liquidity_map") or {})
    main = dict(sd.get("main_reversal_zone") or {})
    destination = dict(sd.get("structural_destination") or {})
    nearest_rb = dict(sd.get("nearest_roadblock") or {})
    path: list[dict[str, Any]] = []
    for liq in list(sweep.get("liquidity_candidates") or [])[:2]:
        path.append({"role": "LIQUIDITY_TEST", "price": liq.get("price"), "side": liq.get("side")})
    if main:
        path.append(
            {
                "role": "MAIN_REVERSAL",
                "low": main.get("low"),
                "high": main.get("high"),
                "timeframe": main.get("timeframe"),
            }
        )
    if nearest_rb:
        path.append(
            {
                "role": "FIRST_STRUCTURAL_TARGET",
                "price": nearest_rb.get("near_edge") or nearest_rb.get("price"),
                "source": nearest_rb.get("source") or nearest_rb.get("timeframe"),
            }
        )
    if destination:
        path.append(
            {
                "role": "OPPOSING_HTF_DESTINATION",
                "price": destination.get("price"),
                "low": destination.get("low"),
                "high": destination.get("high"),
                "timeframe": destination.get("timeframe"),
            }
        )
    return [{"direction": direction, **row} for row in path]


def evaluate_afiq_behavioral_layer(
    *,
    sd_evaluation: dict[str, Any],
    bars_m15: Iterable[Any],
    bars_m5: Iterable[Any],
    as_of: datetime,
    price_now: float | None = None,
) -> dict[str, Any]:
    """Augment V342 with Afiq-style decision semantics without enabling LIVE automation.

    This layer is deliberately conservative for DEMO: it may hard-block an order
    when causal evidence says the active thesis has failed, but it does not create
    a new entry by itself. Manual LIVE use is informational only.
    """
    sd = dict(sd_evaluation or {})
    now = ensure_utc(as_of)
    price = _f(price_now) or _f(sd.get("price_now"))
    m15 = _frame(bars_m15, minutes=15, as_of=now)
    m5 = _frame(bars_m5, minutes=5, as_of=now)
    m30 = _m30_from_m15(bars_m15, as_of=now)

    regime = _regime(sd, m15)
    m30_state = _m30_state(m30)
    acceptance = _acceptance_rejection(sd, m15, price_now=price)
    response = _response_timer(sd, m5, acceptance, as_of=now)
    zone_roles = _zone_roles(sd, str(regime.get("state")), price)
    expected_path = _expected_path(sd)
    direction = str(sd.get("expected_reversal_direction") or "WAIT")
    m30_raw = str(m30_state.get("state") or "UNKNOWN")
    m30_aligned = (
        direction == "LONG" and m30_raw.startswith("BULLISH")
    ) or (
        direction == "SHORT" and m30_raw.startswith("BEARISH")
    )
    m30_conflict = (
        direction == "LONG" and m30_raw.startswith("BEARISH")
    ) or (
        direction == "SHORT" and m30_raw.startswith("BULLISH")
    )

    hard_block_reason = None
    if str(acceptance.get("state")) == "ACCEPTANCE_AGAINST_THESIS":
        hard_block_reason = "ACTIVE_ZONE_ACCEPTED_BEYOND_DISTAL"
    elif str(response.get("state")) == "REACTION_FAILED":
        hard_block_reason = "EARLY_REACTION_FAILED_RESPONSE_TIMER"

    if hard_block_reason:
        demo_gate = "BLOCK_BEHAVIORAL_FAILURE"
        manual_state = "FAILED_REBUILD"
    elif str(response.get("state")) == "REACTION_STALLED":
        demo_gate = "WATCH_REACTION_STALLED"
        manual_state = "WAIT_FOLLOW_THROUGH"
    elif m30_conflict:
        demo_gate = "WATCH_M30_CONFLICT"
        manual_state = "WAIT_M30_ALIGNMENT"
    elif str(acceptance.get("state")) in {"REJECTION_CONFIRMED", "REJECTION_DEVELOPING"} and m30_aligned:
        demo_gate = "ALLOW_WITH_EXISTING_GATES"
        manual_state = "PREPARE_OR_READY_PER_V342_CONFIRMATION"
    else:
        demo_gate = "ALLOW_WITH_EXISTING_GATES"
        manual_state = "WAIT_EXISTING_V342_CONFIRMATION"

    main_role = next((row for row in zone_roles if row.get("role") == "MAIN_REVERSAL"), {})
    return {
        "contract": CONTRACT,
        "as_of": now.isoformat(),
        "price_now": price,
        "direction": direction,
        "regime": regime,
        "zone_roles": zone_roles,
        "active_zone_role": main_role,
        "expected_path": expected_path,
        "acceptance_rejection": acceptance,
        "m30_internal": m30_state,
        "m30_aligned": bool(m30_aligned),
        "m30_conflict": bool(m30_conflict),
        "response_timer": response,
        "manual_decision_state": manual_state,
        "demo_entry_gate": demo_gate,
        "hard_block_reason": hard_block_reason,
        "execution_scope": EXECUTION_SCOPE,
        "execution_authority": False,
        "execution_influence": True,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "rule": (
            "HTF_STORY->REGIME->ZONE_ROLE->LIQUIDITY_TEST->ACCEPTANCE_REJECTION->"
            "M30_INTERNAL->M15_CONFIRMATION->M5_REFINEMENT->RESPONSE_TIMER->STRUCTURAL_TARGET"
        ),
    }
