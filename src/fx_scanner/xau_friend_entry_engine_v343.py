from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Iterable

import pandas as pd

from .models import ensure_utc

CONTRACT = "XAU_RIZAN_FRIEND_ENTRY_V343_1"
DISPLAY_NAME = "RIZAN MICRO ENTRY RECONSTRUCTION"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = True
LIVE_EXECUTION_ENABLED = False

# Frozen from the completed V323 2012-2026 reconstruction.
DELTA_FRACTION = 0.10
PRIMARY_ENTRY_TIER = "Y"
TARGET_MULTIPLES = (5, 8, 13)
IMPULSE_ATR = 0.75
SL_BUFFER_ATR = 0.10

HISTORICAL_EVIDENCE = {
    "source": "XAU_RIZAN_AXY_DELTA_CALIBRATION_V323_EVIDENCE_1",
    "years": list(range(2012, 2027)),
    "selected_candidate": "D0.10|Y|TP5",
    "delta_fraction": 0.10,
    "entry_tier": "Y",
    "selection_fit_period": "2012-2024",
    "oos_period": "2025-2026",
    "full_2012_2026": {
        "fills": 13933,
        "resolved": 13837,
        "wins": 12970,
        "losses": 867,
        "win_rate_resolved": 0.9373419093734191,
        "profit_factor_gross_r": 2.102156886821743,
        "expectancy_r_all_fills": 0.06858322119245326,
        "average_planned_rr": 0.18787856101470818,
        "mean_entry_error_atr": 1.2683780373504256,
    },
    "oos_2025_2026": {
        "fills": 1824,
        "win_rate_resolved": 0.9499174463401211,
        "profit_factor_gross_r": 2.7497797003169775,
        "expectancy_r_all_fills": 0.08729712320660359,
    },
    "oos_gate_pass": False,
    "oos_gate_reason": "EXPECTANCY_R_ALL_FILLS_BELOW_0P10",
    "friction": "NOT_INCLUDED_GROSS_RESEARCH",
    "interpretation": (
        "High hit-rate coexists with small planned reward relative to structural risk. "
        "This evidence supports a shadow reconstruction, not automatic execution."
    ),
}


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _frame(bars: Iterable[Any]) -> pd.DataFrame:
    rows = []
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
    return (
        pd.DataFrame(rows)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=8).mean()


def _parent_touch_at(parent: dict[str, Any]) -> datetime | None:
    lifecycle = dict(parent.get("lifecycle") or {})
    raw = lifecycle.get("last_touch_at") or lifecycle.get("first_touch_at")
    if not raw:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _live_parent_touch_at(
    parent: dict[str, Any],
    *,
    m5: pd.DataFrame,
    as_of: datetime,
) -> datetime | None:
    """Recover a causal M5 touch when HTF lifecycle metadata has not caught up.

    The fallback is only allowed after the HTF zone was available. This avoids
    inventing historical touches from M5 bars that predate zone publication.
    """
    available_raw = parent.get("available_at")
    if not available_raw or m5.empty:
        return None
    try:
        available_at = ensure_utc(
            datetime.fromisoformat(str(available_raw).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    low = _f(parent.get("low"))
    high = _f(parent.get("high"))
    if low is None or high is None or high <= low:
        return None

    work = m5.copy()
    work["known_at"] = work["timestamp"] + pd.Timedelta(minutes=5)
    rows = work[
        (work["known_at"] > pd.Timestamp(available_at))
        & (work["known_at"] <= pd.Timestamp(ensure_utc(as_of)))
        & (work["high"].astype(float) >= low)
        & (work["low"].astype(float) <= high)
    ]
    if rows.empty:
        return None
    return ensure_utc(rows.iloc[0]["known_at"].to_pydatetime())


def _anchor(
    *,
    direction: str,
    proximal: float,
    touch_at: datetime,
    m5: pd.DataFrame,
    as_of: datetime,
) -> dict[str, Any]:
    work = m5.copy()
    work["atr14"] = _atr(work)
    work["known_at"] = work["timestamp"] + pd.Timedelta(minutes=5)
    known_before_touch = work[
        (work["known_at"] <= pd.Timestamp(touch_at))
        & work["atr14"].notna()
    ]
    if known_before_touch.empty:
        return {"state": "NO_CAUSAL_ATR"}
    touch_atr = _f(known_before_touch.iloc[-1]["atr14"])
    if touch_atr is None or touch_atr <= 0:
        return {"state": "NO_CAUSAL_ATR"}

    rows = work[
        (work["known_at"] > pd.Timestamp(touch_at))
        & (work["known_at"] <= pd.Timestamp(ensure_utc(as_of)))
    ].reset_index(drop=True)
    if len(rows) < 4:
        return {"state": "WAIT_POST_TOUCH_BARS", "atr": touch_atr}

    sign = 1.0 if direction == "LONG" else -1.0
    impulse_threshold = proximal + sign * IMPULSE_ATR * touch_atr
    impulse_idx = None
    for i, row in rows.iterrows():
        if direction == "LONG" and float(row["high"]) >= impulse_threshold:
            impulse_idx = int(i)
            break
        if direction == "SHORT" and float(row["low"]) <= impulse_threshold:
            impulse_idx = int(i)
            break
    if impulse_idx is None:
        return {
            "state": "WAIT_IMPULSE",
            "atr": touch_atr,
            "impulse_threshold": impulse_threshold,
        }

    reclaim_idx = None
    for i in range(1, len(rows)):
        a, b = float(rows.iloc[i - 1]["close"]), float(rows.iloc[i]["close"])
        if direction == "LONG" and a > proximal and b > proximal:
            reclaim_idx = i
            break
        if direction == "SHORT" and a < proximal and b < proximal:
            reclaim_idx = i
            break
    if reclaim_idx is None:
        return {
            "state": "WAIT_TWO_CLOSE_RECLAIM",
            "atr": touch_atr,
            "impulse_threshold": impulse_threshold,
        }

    scan_start = max(1, impulse_idx + 1, reclaim_idx)
    for i in range(scan_start, len(rows) - 1):
        prev_row, row, next_row = rows.iloc[i - 1], rows.iloc[i], rows.iloc[i + 1]
        if direction == "LONG":
            pivot = (
                float(row["low"]) <= float(prev_row["low"])
                and float(row["low"]) < float(next_row["low"])
                and float(next_row["close"]) > float(row["close"])
            )
            a = float(row["low"])
        else:
            pivot = (
                float(row["high"]) >= float(prev_row["high"])
                and float(row["high"]) > float(next_row["high"])
                and float(next_row["close"]) < float(row["close"])
            )
            a = float(row["high"])
        if not pivot:
            continue
        atr_now = _f(next_row.get("atr14")) or touch_atr
        return {
            "state": "ANCHOR_CONFIRMED",
            "a": a,
            "atr": float(atr_now),
            "touch_at": ensure_utc(touch_at).isoformat(),
            "impulse_at": ensure_utc(rows.iloc[impulse_idx]["known_at"].to_pydatetime()).isoformat(),
            "reclaim_at": ensure_utc(rows.iloc[reclaim_idx]["known_at"].to_pydatetime()).isoformat(),
            "pivot_at": ensure_utc(row["timestamp"].to_pydatetime()).isoformat(),
            "confirmed_at": ensure_utc(next_row["known_at"].to_pydatetime()).isoformat(),
        }
    return {
        "state": "WAIT_PULLBACK_ANCHOR",
        "atr": touch_atr,
        "impulse_threshold": impulse_threshold,
    }


def evaluate_friend_entry(
    *,
    parent_zone: dict[str, Any],
    bars_m5: Iterable[Any],
    as_of: datetime,
    price_now: float | None = None,
) -> dict[str, Any]:
    """Reconstruct the friend's A/X/Y geometry as isolated forecast evidence.

    The module can influence DEMO setup confidence but has no direct broker
    authority. It consumes one explicit parent zone and M5 bars without reviving
    or averaging legacy engines.
    """
    parent = dict(parent_zone or {})
    direction = str(parent.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": "NO_PARENT_ZONE",
            "execution_authority": False,
            "execution_influence": False,
            "historical_evidence": HISTORICAL_EVIDENCE,
        }
    proximal = _f(parent.get("proximal"))
    distal = _f(parent.get("distal"))
    if proximal is None or distal is None:
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": "INVALID_PARENT_GEOMETRY",
            "direction": direction,
            "execution_authority": False,
            "execution_influence": False,
            "historical_evidence": HISTORICAL_EVIDENCE,
        }

    m5 = _frame(bars_m5)
    if m5.empty:
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": "NO_M5_DATA",
            "direction": direction,
            "execution_authority": False,
            "execution_influence": False,
            "historical_evidence": HISTORICAL_EVIDENCE,
        }
    current = _f(price_now)
    if current is None:
        current = float(m5.iloc[-1]["close"])

    touch_at = _parent_touch_at(parent)
    touch_source = "HTF_LIFECYCLE"
    if touch_at is None:
        touch_at = _live_parent_touch_at(
            parent,
            m5=m5,
            as_of=ensure_utc(as_of),
        )
        touch_source = "M5_CAUSAL_LIVE_OVERLAP"
    if touch_at is None:
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": "WAIT_PARENT_TOUCH",
            "direction": direction,
            "price_now": current,
            "parent_zone": parent,
            "formula": "A -> X=A±Δ -> Y=A±2Δ -> TP=5Δ/8Δ/13Δ",
            "historical_evidence": HISTORICAL_EVIDENCE,
            "execution_authority": False,
            "execution_influence": EXECUTION_INFLUENCE,
        }

    anchor = _anchor(
        direction=direction,
        proximal=proximal,
        touch_at=touch_at,
        m5=m5,
        as_of=ensure_utc(as_of),
    )
    if anchor.get("state") != "ANCHOR_CONFIRMED":
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": str(anchor.get("state") or "WAIT_ANCHOR"),
            "direction": direction,
            "price_now": current,
            "parent_zone": parent,
            "parent_touch_source": touch_source,
            "anchor": anchor,
            "formula": "A -> X=A±Δ -> Y=A±2Δ -> TP=5Δ/8Δ/13Δ",
            "historical_evidence": HISTORICAL_EVIDENCE,
            "execution_authority": False,
            "execution_influence": EXECUTION_INFLUENCE,
        }

    a = float(anchor["a"])
    atr = max(float(anchor["atr"]), 1e-9)
    delta = DELTA_FRACTION * atr
    sign = 1.0 if direction == "LONG" else -1.0
    x = a + sign * delta
    y = a + sign * 2.0 * delta
    targets = {
        f"TP{multiple}": a + sign * float(multiple) * delta
        for multiple in TARGET_MULTIPLES
    }
    sl = (
        distal - SL_BUFFER_ATR * atr
        if direction == "LONG"
        else distal + SL_BUFFER_ATR * atr
    )

    invalid = current <= sl if direction == "LONG" else current >= sl
    target5 = float(targets["TP5"])
    passed_target = current >= target5 if direction == "LONG" else current <= target5
    if invalid:
        phase = "INVALIDATED"
    elif passed_target:
        phase = "CYCLE_TARGET_REACHED_REANCHOR_REQUIRED"
    else:
        if direction == "LONG":
            phase = "Y_RETEST_WINDOW" if current <= y + 0.20 * delta else "MOVE_IN_FLIGHT_NO_CHASE"
        else:
            phase = "Y_RETEST_WINDOW" if current >= y - 0.20 * delta else "MOVE_IN_FLIGHT_NO_CHASE"

    return {
        "contract": CONTRACT,
        "name": DISPLAY_NAME,
        "state": phase,
        "direction": direction,
        "price_now": current,
        "parent_zone": parent,
        "parent_touch_source": touch_source,
        "anchor": anchor,
        "delta": delta,
        "delta_fraction_m5_atr": DELTA_FRACTION,
        "levels": {"A": a, "X": x, "Y": y},
        "entries": {
            "A_RETEST": a,
            "X": x,
            "Y": y,
            "historical_primary": "Y",
            "historical_primary_price": y,
        },
        "stop_loss": sl,
        "targets": targets,
        "no_chase": phase == "MOVE_IN_FLIGHT_NO_CHASE",
        "next_cycle_rule": (
            "After TP/structural destination, do not mechanically flip. "
            "Wait for the opposite H1/H4 parent zone, then rebuild A/X/Y from a new causal anchor."
        ),
        "historical_evidence": HISTORICAL_EVIDENCE,
        "caveat": (
            "V323 OOS historical gate did not pass the >=0.10R expectancy threshold. "
            "This remains forecast/shadow geometry with zero execution authority."
        ),
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }
