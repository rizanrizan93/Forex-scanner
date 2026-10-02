from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Iterable, Sequence

import pandas as pd

from .models import ensure_utc

CONTRACT = "XAU_RIZAN_STRUCTURAL_SR_MAP_V363"
DISPLAY_NAME = "RIZAN STRUCTURAL S/R MAP"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
DIRECTION_SIGNAL = False

_TF_MINUTES = {"M5": 5, "M15": 15}


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _bar_frame(
    bars: Iterable[Any],
    *,
    timeframe: str,
    as_of: datetime,
) -> pd.DataFrame:
    tf = str(timeframe).upper()
    if tf not in _TF_MINUTES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    rows: list[dict[str, Any]] = []
    for bar in bars:
        ts = getattr(bar, "timestamp", None)
        if ts is None:
            continue
        rows.append(
            {
                "timestamp": pd.Timestamp(ensure_utc(ts)),
                "open": float(getattr(bar, "open")),
                "high": float(getattr(bar, "high")),
                "low": float(getattr(bar, "low")),
                "close": float(getattr(bar, "close")),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    frame = (
        pd.DataFrame(rows)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    known_delta = pd.Timedelta(minutes=_TF_MINUTES[tf])
    now = pd.Timestamp(ensure_utc(as_of))
    return frame[(frame["timestamp"] + known_delta) <= now].copy()


def _parse_available_at(value: Any) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed


def _accepted_breaks(
    frame: pd.DataFrame,
    *,
    band_low: float,
    band_high: float,
    buffer: float,
) -> list[dict[str, Any]]:
    if len(frame) < 3:
        return []
    events: list[dict[str, Any]] = []
    closes = frame["close"].astype(float)
    for i in range(1, len(frame) - 1):
        previous = float(closes.iloc[i - 1])
        current = float(closes.iloc[i])
        follow = frame.iloc[i + 1 : min(len(frame), i + 3)]
        if follow.empty:
            continue

        if previous <= band_high + buffer and current > band_high + buffer:
            accepted = bool((follow["close"].astype(float) > band_high).any())
            if accepted:
                confirmation_row = follow[
                    follow["close"].astype(float) > band_high
                ].iloc[0]
                events.append(
                    {
                        "direction": "BULLISH",
                        "break_index": i,
                        "confirm_index": int(confirmation_row.name),
                        "break_at": ensure_utc(
                            (
                                frame.iloc[i]["timestamp"]
                                + pd.Timedelta(minutes=1)
                            ).to_pydatetime()
                        ).isoformat(),
                    }
                )

        if previous >= band_low - buffer and current < band_low - buffer:
            accepted = bool((follow["close"].astype(float) < band_low).any())
            if accepted:
                confirmation_row = follow[
                    follow["close"].astype(float) < band_low
                ].iloc[0]
                events.append(
                    {
                        "direction": "BEARISH",
                        "break_index": i,
                        "confirm_index": int(confirmation_row.name),
                        "break_at": ensure_utc(
                            (
                                frame.iloc[i]["timestamp"]
                                + pd.Timedelta(minutes=1)
                            ).to_pydatetime()
                        ).isoformat(),
                    }
                )
    events.sort(key=lambda event: int(event["confirm_index"]))
    return events


def _classify_level_lifecycle(
    level: dict[str, Any],
    *,
    frame: pd.DataFrame,
    timeframe: str,
    price_now: float,
    atr_reference: float,
) -> dict[str, Any]:
    price = float(level["price"])
    base_kind = str(level.get("kind") or "FLIP").upper()
    half_band = max(0.055 * max(atr_reference, 1e-9), 0.50)
    acceptance_buffer = max(0.025 * max(atr_reference, 1e-9), 0.20)
    band_low = price - half_band
    band_high = price + half_band

    working = frame.copy()
    available_at = _parse_available_at(level.get("available_at"))
    if available_at is not None and not working.empty:
        known_delta = pd.Timedelta(minutes=_TF_MINUTES[timeframe])
        working = working[
            (working["timestamp"] + known_delta) >= available_at
        ].copy()
    working = working.tail(160).reset_index(drop=True)

    status = (
        "ACTIVE_SUPPORT"
        if base_kind == "SUPPORT"
        else "ACTIVE_RESISTANCE"
        if base_kind == "RESISTANCE"
        else "ACTIVE_FLIP_CONTEXT"
    )
    current_role = base_kind
    breakout_direction: str | None = None
    breakout_at: str | None = None
    retest_at: str | None = None
    confirmed_flip = False
    reclaim_required = False

    events = _accepted_breaks(
        working,
        band_low=band_low,
        band_high=band_high,
        buffer=acceptance_buffer,
    )
    eligible = [
        event
        for event in events
        if (
            event["direction"] == "BULLISH"
            and base_kind in {"RESISTANCE", "FLIP"}
        )
        or (
            event["direction"] == "BEARISH"
            and base_kind in {"SUPPORT", "FLIP"}
        )
    ]
    event = eligible[-1] if eligible else None

    if event is not None:
        breakout_direction = str(event["direction"])
        breakout_at = str(event["break_at"])
        confirm_index = int(event["confirm_index"])
        post = working.iloc[confirm_index + 1 :].copy()

        if breakout_direction == "BULLISH":
            failure_rows = post[
                post["close"].astype(float) < band_low - acceptance_buffer
            ]
            if not failure_rows.empty:
                status = "FAILED_BULL_BREAKOUT_RECLAIM_REQUIRED"
                current_role = "RESISTANCE_CANDIDATE"
                reclaim_required = True
            else:
                touches = post[
                    (post["low"].astype(float) <= band_high)
                    & (post["high"].astype(float) >= band_low)
                ]
                if touches.empty:
                    status = "BULL_BREAKOUT_AWAIT_RETEST"
                    current_role = "SUPPORT_FLIP_CANDIDATE"
                else:
                    touch_index = int(touches.index[0])
                    retest_at = ensure_utc(
                        (
                            working.iloc[touch_index]["timestamp"]
                            + pd.Timedelta(minutes=_TF_MINUTES[timeframe])
                        ).to_pydatetime()
                    ).isoformat()
                    after_touch = working.iloc[touch_index:].copy()
                    held = bool(
                        len(after_touch) >= 2
                        and (after_touch["close"].astype(float) >= band_high).sum() >= 2
                        and float(after_touch.iloc[-1]["close"]) >= band_high
                    )
                    if held:
                        status = "CONFIRMED_SUPPORT_FLIP"
                        current_role = "SUPPORT"
                        confirmed_flip = True
                    else:
                        status = "BULL_RETEST_IN_PROGRESS"
                        current_role = "SUPPORT_FLIP_CANDIDATE"

        else:
            failure_rows = post[
                post["close"].astype(float) > band_high + acceptance_buffer
            ]
            if not failure_rows.empty:
                status = "FAILED_BEAR_BREAKDOWN_RECLAIM_REQUIRED"
                current_role = "SUPPORT_CANDIDATE"
                reclaim_required = True
            else:
                touches = post[
                    (post["high"].astype(float) >= band_low)
                    & (post["low"].astype(float) <= band_high)
                ]
                if touches.empty:
                    status = "BEAR_BREAKDOWN_AWAIT_RETEST"
                    current_role = "RESISTANCE_FLIP_CANDIDATE"
                else:
                    touch_index = int(touches.index[0])
                    retest_at = ensure_utc(
                        (
                            working.iloc[touch_index]["timestamp"]
                            + pd.Timedelta(minutes=_TF_MINUTES[timeframe])
                        ).to_pydatetime()
                    ).isoformat()
                    after_touch = working.iloc[touch_index:].copy()
                    held = bool(
                        len(after_touch) >= 2
                        and (after_touch["close"].astype(float) <= band_low).sum() >= 2
                        and float(after_touch.iloc[-1]["close"]) <= band_low
                    )
                    if held:
                        status = "CONFIRMED_RESISTANCE_FLIP"
                        current_role = "RESISTANCE"
                        confirmed_flip = True
                    else:
                        status = "BEAR_RETEST_IN_PROGRESS"
                        current_role = "RESISTANCE_FLIP_CANDIDATE"

    elif not working.empty:
        recent = working.tail(16)
        if base_kind in {"RESISTANCE", "FLIP"}:
            upside_reject = recent[
                (recent["high"].astype(float) > band_high + acceptance_buffer)
                & (recent["close"].astype(float) <= band_high)
            ]
        else:
            upside_reject = recent.iloc[0:0]
        if base_kind in {"SUPPORT", "FLIP"}:
            downside_reject = recent[
                (recent["low"].astype(float) < band_low - acceptance_buffer)
                & (recent["close"].astype(float) >= band_low)
            ]
        else:
            downside_reject = recent.iloc[0:0]

        if not upside_reject.empty and (
            downside_reject.empty
            or int(upside_reject.index[-1]) >= int(downside_reject.index[-1])
        ):
            status = "UPSIDE_SWEEP_LIKE_REJECTION"
            current_role = "RESISTANCE"
        elif not downside_reject.empty:
            status = "DOWNSIDE_SWEEP_LIKE_REJECTION"
            current_role = "SUPPORT"
        elif base_kind == "RESISTANCE" and price_now > band_high:
            status = "PRICE_ABOVE_RESISTANCE_UNRESOLVED"
            current_role = "FLIP_CANDIDATE"
        elif base_kind == "SUPPORT" and price_now < band_low:
            status = "PRICE_BELOW_SUPPORT_UNRESOLVED"
            current_role = "FLIP_CANDIDATE"

    return {
        **level,
        "base_kind": base_kind,
        "kind": current_role,
        "current_role": current_role,
        "lifecycle_state": status,
        "band_low": band_low,
        "band_high": band_high,
        "validation_timeframe": timeframe,
        "breakout_direction": breakout_direction,
        "breakout_at": breakout_at,
        "retest_at": retest_at,
        "confirmed_flip": confirmed_flip,
        "reclaim_required": reclaim_required,
        "distance_points": abs(price_now - price),
        "distance_atr": abs(price_now - price) / max(atr_reference, 1e-9),
        "direction_signal": False,
    }


def _nearest(
    levels: Sequence[dict[str, Any]],
    *,
    price_now: float,
    roles: set[str],
    side: str,
) -> dict[str, Any]:
    candidates = []
    for row in levels:
        if str(row.get("current_role") or "") not in roles:
            continue
        px = float(row["price"])
        if side == "BELOW" and px > price_now:
            continue
        if side == "ABOVE" and px < price_now:
            continue
        candidates.append(row)
    if not candidates:
        return {}
    candidates.sort(
        key=lambda row: (
            abs(float(row["price"]) - price_now),
            -float(row.get("strength") or 0.0),
        )
    )
    return dict(candidates[0])


def _path(
    *,
    direction: str,
    price_now: float,
    levels: Sequence[dict[str, Any]],
    flip_watch: dict[str, Any],
) -> dict[str, Any]:
    if direction == "LONG":
        targets = [
            row for row in levels
            if str(row.get("current_role") or "") == "RESISTANCE"
            and float(row["price"]) > price_now
        ]
        targets.sort(key=lambda row: float(row["price"]))
        prerequisite = "HOLD_CONFIRMED_SUPPORT"
        if str(flip_watch.get("breakout_direction") or "") == "BULLISH":
            prerequisite = (
                "RECLAIM_THEN_HOLD"
                if bool(flip_watch.get("reclaim_required"))
                else "RETEST_AND_HOLD"
            )
    else:
        targets = [
            row for row in levels
            if str(row.get("current_role") or "") == "SUPPORT"
            and float(row["price"]) < price_now
        ]
        targets.sort(key=lambda row: float(row["price"]), reverse=True)
        prerequisite = "HOLD_CONFIRMED_RESISTANCE"
        if str(flip_watch.get("breakout_direction") or "") == "BEARISH":
            prerequisite = (
                "RECLAIM_THEN_HOLD"
                if bool(flip_watch.get("reclaim_required"))
                else "RETEST_AND_HOLD"
            )
    return {
        "state": "CONDITIONAL_CONTEXT_ONLY",
        "direction": direction,
        "prerequisite": prerequisite,
        "flip_level": flip_watch.get("price"),
        "checkpoints": [
            {
                "price": row.get("price"),
                "role": row.get("current_role"),
                "state": row.get("lifecycle_state"),
                "strength": row.get("strength"),
            }
            for row in targets[:3]
        ],
        "rule": "CONTEXT_ONLY_NOT_AN_ENTRY_SIGNAL",
    }


def build_structural_sr_map(
    *,
    levels: Sequence[dict[str, Any]],
    bars_m15: Iterable[Any],
    bars_m5: Iterable[Any],
    as_of: datetime,
    price_now: float,
    atr_reference: float,
) -> dict[str, Any]:
    """Attach causal breakout/retest/flip lifecycle to structural S/R levels.

    A crossed resistance is not promoted to support merely because price traded
    above it. The map requires completed-bar acceptance and then a retest/hold.
    Failed acceptance is explicitly labelled RECLAIM_REQUIRED.
    """
    current = float(price_now)
    atr = max(float(atr_reference), 1e-9)
    m15 = _bar_frame(bars_m15, timeframe="M15", as_of=as_of)
    m5 = _bar_frame(bars_m5, timeframe="M5", as_of=as_of)
    if len(m15) >= 24:
        frame = m15
        validation_tf = "M15"
    elif len(m5) >= 36:
        frame = m5
        validation_tf = "M5"
    else:
        frame = m15 if not m15.empty else m5
        validation_tf = "M15" if not m15.empty else "M5"

    enriched = [
        _classify_level_lifecycle(
            dict(level),
            frame=frame,
            timeframe=validation_tf,
            price_now=current,
            atr_reference=atr,
        )
        for level in list(levels or [])
        if _f(dict(level).get("price")) is not None
    ]
    enriched.sort(
        key=lambda row: (
            float(row.get("distance_points") or 0.0),
            -float(row.get("strength") or 0.0),
        )
    )

    nearest_support = _nearest(
        enriched,
        price_now=current,
        roles={"SUPPORT"},
        side="BELOW",
    )
    nearest_resistance = _nearest(
        enriched,
        price_now=current,
        roles={"RESISTANCE"},
        side="ABOVE",
    )

    watch_states = {
        "BULL_BREAKOUT_AWAIT_RETEST",
        "BULL_RETEST_IN_PROGRESS",
        "FAILED_BULL_BREAKOUT_RECLAIM_REQUIRED",
        "BEAR_BREAKDOWN_AWAIT_RETEST",
        "BEAR_RETEST_IN_PROGRESS",
        "FAILED_BEAR_BREAKDOWN_RECLAIM_REQUIRED",
        "CONFIRMED_SUPPORT_FLIP",
        "CONFIRMED_RESISTANCE_FLIP",
        "PRICE_ABOVE_RESISTANCE_UNRESOLVED",
        "PRICE_BELOW_SUPPORT_UNRESOLVED",
    }
    watches = [
        row for row in enriched
        if str(row.get("lifecycle_state") or "") in watch_states
    ]
    watches.sort(
        key=lambda row: (
            0 if bool(row.get("reclaim_required")) else 1,
            float(row.get("distance_points") or 0.0),
        )
    )
    flip_watch = dict(watches[0]) if watches else {}

    return {
        "contract": CONTRACT,
        "name": DISPLAY_NAME,
        "state": "MAP_AVAILABLE" if enriched else "NO_SR_LEVEL",
        "as_of": ensure_utc(as_of).isoformat(),
        "price_now": current,
        "validation_timeframe": validation_tf,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "flip_watch": flip_watch,
        "levels": enriched[:10],
        "bull_path": _path(
            direction="LONG",
            price_now=current,
            levels=enriched,
            flip_watch=flip_watch,
        ),
        "bear_path": _path(
            direction="SHORT",
            price_now=current,
            levels=enriched,
            flip_watch=flip_watch,
        ),
        "rule": (
            "LEVEL -> COMPLETED_BAR_BREAKOUT -> ACCEPTANCE -> RETEST -> HOLD -> ROLE_FLIP; "
            "FAILED_BREAKOUT => RECLAIM_REQUIRED. SUPPORT_IS_NOT_AUTO_BUY; "
            "RESISTANCE_IS_NOT_AUTO_SELL."
        ),
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "direction_signal": DIRECTION_SIGNAL,
    }
