from __future__ import annotations

from math import isfinite
import hashlib
from typing import Any, Sequence

import pandas as pd

CONTRACT = "XAU_STRUCTURAL_TARGET_LADDER_V229_1"
TIMEFRAME_ORDER = ("M15", "H1", "H4", "D1")
FRONT_RUN_ZONE_FRACTION = 0.10
FRONT_RUN_MAX_USD = 1.0


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None



M15_MIN_DEPARTURE_RANGE_ATR = 1.00
M15_MIN_DEPARTURE_BODY_FRACTION = 0.50
M15_MAX_BASE_RANGE_ATR = 1.25


def _m15_frame(raw_bars: Sequence[dict[str, Any]]) -> pd.DataFrame:
    if not raw_bars:
        return pd.DataFrame()
    frame = pd.DataFrame(list(raw_bars))
    required = {"time", "open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.dropna(subset=list(required))
        .sort_values("time")
        .drop_duplicates("time", keep="last")
        .reset_index(drop=True)
    )


def _atr14(frame: pd.DataFrame) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous).abs(), (low - previous).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()


def _base_geometry(base: pd.DataFrame, direction: str) -> tuple[float, float, float, float]:
    low = float(base["low"].min())
    high = float(base["high"].max())
    body_high = float(
        pd.concat([base["open"], base["close"]], axis=1).max(axis=1).max()
    )
    body_low = float(
        pd.concat([base["open"], base["close"]], axis=1).min(axis=1).min()
    )
    if direction == "LONG":
        return low, high, min(high, body_high), low
    return low, high, max(low, body_low), high


def _classify_pattern(*, direction: str, pre_base_close: float, base_mid: float) -> str:
    if direction == "LONG":
        return "RBR" if pre_base_close <= base_mid else "DBR"
    return "DBD" if pre_base_close >= base_mid else "RBD"


def _stable_m15_id(
    *,
    direction: str,
    origin_at: pd.Timestamp,
    available_at: pd.Timestamp,
    low: float,
    high: float,
) -> str:
    raw = "|".join(
        (
            "M15",
            direction,
            "IMBALANCE",
            origin_at.isoformat(),
            available_at.isoformat(),
            f"{low:.8f}",
            f"{high:.8f}",
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def runtime_m15_target_zones(
    raw_bars: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Standalone causal M15 target detector with no AFIC/V226 imports."""
    frame = _m15_frame(raw_bars)
    if frame.empty or len(frame) < 20:
        return []
    work = frame.copy()
    work["atr14"] = _atr14(work)
    detected: list[dict[str, Any]] = []

    for i in range(16, len(work)):
        row = work.iloc[i]
        atr = _f(row.get("atr14"))
        if atr is None or atr <= 0:
            continue
        o = float(row["open"])
        h = float(row["high"])
        low_row = float(row["low"])
        c = float(row["close"])
        rng = max(h - low_row, 1e-12)
        body_fraction = abs(c - o) / rng
        range_atr = rng / atr
        if range_atr < M15_MIN_DEPARTURE_RANGE_ATR:
            continue
        if body_fraction < M15_MIN_DEPARTURE_BODY_FRACTION:
            continue
        direction = "LONG" if c > o else "SHORT" if c < o else ""
        if not direction:
            continue

        best: tuple[float, int, pd.DataFrame] | None = None
        for base_len in (1, 2, 3):
            start = i - base_len
            if start < 2:
                continue
            base = work.iloc[start:i]
            base_range = float(base["high"].max() - base["low"].min())
            base_range_atr = base_range / atr
            body_fracs = (
                (base["close"].astype(float) - base["open"].astype(float)).abs()
                / (base["high"].astype(float) - base["low"].astype(float)).clip(lower=1e-12)
            )
            compactness = base_range_atr + float(body_fracs.mean()) * 0.35
            if base_range_atr > M15_MAX_BASE_RANGE_ATR:
                continue
            if best is None or compactness < best[0]:
                best = (compactness, base_len, base.copy())
        if best is None:
            continue

        _, base_len, base = best
        low, high, proximal, distal = _base_geometry(base, direction)
        if high <= low or (high - low) / atr > M15_MAX_BASE_RANGE_ATR:
            continue
        pre_close = float(work.iloc[i - base_len - 1]["close"])
        pattern = _classify_pattern(
            direction=direction,
            pre_base_close=pre_close,
            base_mid=(low + high) / 2.0,
        )
        departure_open = pd.Timestamp(row["time"])
        available_at = departure_open + pd.Timedelta(minutes=15)
        origin_at = pd.Timestamp(base.iloc[0]["time"])
        detected.append(
            {
                "zone_id": _stable_m15_id(
                    direction=direction,
                    origin_at=origin_at,
                    available_at=available_at,
                    low=low,
                    high=high,
                ),
                "timeframe": "M15",
                "zone_class": "IMBALANCE",
                "pattern": pattern,
                "direction": direction,
                "low": low,
                "high": high,
                "proximal": proximal,
                "distal": distal,
                "available_at": available_at.isoformat(),
                "origin_at": origin_at.isoformat(),
                "departure_at": available_at.isoformat(),
                "atr_points": atr,
                "base_range_atr": (high - low) / atr,
                "departure_range_atr": range_atr,
                "departure_body_fraction": body_fraction,
            }
        )

    active: list[dict[str, Any]] = []
    for zone in detected:
        available = pd.Timestamp(zone["available_at"])
        sample = work[work["time"] >= available]
        touches = 0
        was_inside = False
        invalidated_at = None
        for _, row in sample.iterrows():
            inside = (
                float(row["low"]) <= float(zone["high"])
                and float(row["high"]) >= float(zone["low"])
            )
            if inside and not was_inside:
                touches += 1
            invalid = (
                float(row["close"]) < float(zone["distal"])
                if zone["direction"] == "LONG"
                else float(row["close"]) > float(zone["distal"])
            )
            if invalid:
                invalidated_at = pd.Timestamp(row["time"]).isoformat()
                break
            was_inside = inside
        lifecycle = {
            "active": invalidated_at is None,
            "touch_count": touches,
            "freshness": (
                "BROKEN" if invalidated_at is not None
                else "FRESH" if touches == 0
                else "FIRST_TEST" if touches == 1
                else "MULTI_TESTED"
            ),
            "invalidated_at": invalidated_at,
        }
        if invalidated_at is None:
            active.append(
                {
                    **zone,
                    "lifecycle": lifecycle,
                    "status": "V229_M15_TARGET_ACTIVE",
                    "execution_influence": False,
                    "execution_authority": False,
                }
            )
    active.sort(key=lambda zone: str(zone.get("available_at") or ""), reverse=True)
    return active


def _active(zone: dict[str, Any]) -> bool:
    lifecycle = dict(zone.get("lifecycle") or {})
    if lifecycle and lifecycle.get("active") is False:
        return False
    status = str(zone.get("status") or "").upper()
    return "BROKEN" not in status and "INVALID" not in status


def _front_run_price(zone: dict[str, Any], direction: str) -> tuple[float, float] | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None or high <= low:
        return None
    buffer = min(FRONT_RUN_MAX_USD, (high - low) * FRONT_RUN_ZONE_FRACTION)
    if direction == "LONG":
        return low - buffer, buffer
    if direction == "SHORT":
        return high + buffer, buffer
    return None


def _ahead(zone: dict[str, Any], *, direction: str, entry: float) -> bool:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None:
        return False
    if direction == "LONG":
        return low > entry
    if direction == "SHORT":
        return high < entry
    return False


def _opposing(zone: dict[str, Any], direction: str) -> bool:
    wanted = "SHORT" if direction == "LONG" else "LONG"
    return str(zone.get("direction") or "").upper() == wanted


def _distance(zone: dict[str, Any], *, direction: str, entry: float) -> float:
    low = float(zone["low"])
    high = float(zone["high"])
    return low - entry if direction == "LONG" else entry - high


def _nearest_per_timeframe(
    zones: Sequence[dict[str, Any]],
    *,
    direction: str,
    entry: float,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for timeframe in TIMEFRAME_ORDER:
        candidates = [
            dict(zone)
            for zone in zones
            if str(zone.get("timeframe") or "").upper() == timeframe
            and _active(zone)
            and _opposing(zone, direction)
            and _ahead(zone, direction=direction, entry=entry)
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda zone: (
                _distance(zone, direction=direction, entry=entry),
                -float(_f(zone.get("research_score")) or 0.0),
            )
        )
        output.append(candidates[0])
    return output


def build_structural_target_plan(
    *,
    direction: str,
    entry: float,
    stop: float,
    m15_zones: Sequence[dict[str, Any]] = (),
    htf_zones: Sequence[dict[str, Any]] = (),
    minimum_rr: float = 1.5,
) -> dict[str, Any]:
    """Map scale-out targets to opposing M15 -> H1 -> H4 structure.

    D1 is retained as an optional macro terminal. A zone is mapped even when it
    is too close for execution; RR is a validation gate, not the target source.
    """
    side = str(direction or "").upper()
    if side not in {"LONG", "SHORT"}:
        return {}
    entry_f = _f(entry)
    stop_f = _f(stop)
    min_rr = _f(minimum_rr)
    if entry_f is None or stop_f is None or min_rr is None or min_rr <= 0:
        return {}
    risk = entry_f - stop_f if side == "LONG" else stop_f - entry_f
    if risk <= 0:
        return {}

    zones = [dict(zone) for zone in list(m15_zones) + list(htf_zones)]
    selected = _nearest_per_timeframe(zones, direction=side, entry=entry_f)
    selected.sort(key=lambda zone: _distance(zone, direction=side, entry=entry_f))
    mapped: list[dict[str, Any]] = []
    for zone in selected:
        front = _front_run_price(zone, side)
        if front is None:
            continue
        target, buffer = front
        reward = target - entry_f if side == "LONG" else entry_f - target
        if reward <= 0:
            continue
        rr = reward / risk
        timeframe = str(zone.get("timeframe") or "").upper()
        mapped.append(
            {
                "timeframe": timeframe,
                "zone_id": zone.get("zone_id"),
                "zone_low": float(zone["low"]),
                "zone_high": float(zone["high"]),
                "proximal_edge": float(zone["low"] if side == "LONG" else zone["high"]),
                "front_run_buffer": float(buffer),
                "target_price": float(target),
                "rr": float(rr),
                "minimum_rr": float(min_rr),
                "rr_eligible": bool(rr + 1e-12 >= min_rr),
                "role": "MACRO_TERMINAL" if timeframe == "D1" else f"{timeframe}_SCALE_OUT",
                "source": "OPPOSING_SUPPLY_DEMAND",
            }
        )

    broker_candidates = [
        item
        for item in mapped
        if str(item["timeframe"]) in {"M15", "H1", "H4"}
    ]
    broker_candidates.sort(key=lambda item: float(item["rr"]))
    terminal_structural = broker_candidates[-1] if broker_candidates else None
    terminal_rr_eligible = bool(
        terminal_structural is not None
        and float(terminal_structural["rr"]) + 1e-12 >= float(min_rr)
    )
    # Earlier opposing zones remain valid partial scale-outs even below 1.5R.
    # The minimum RR applies to the terminal structural objective, matching the
    # existing executor's terminal-RR contract and preventing us from ignoring
    # a nearby M15 barrier merely to target a farther H1/H4 zone.
    broker = list(broker_candidates) if terminal_rr_eligible else []
    macro = next(
        (
            item
            for item in mapped
            if str(item["timeframe"]) == "D1" and bool(item["rr_eligible"])
        ),
        None,
    )
    return {
        "contract": CONTRACT,
        "direction": side,
        "entry": float(entry_f),
        "stop": float(stop_f),
        "risk_points": float(risk),
        "minimum_rr": float(min_rr),
        "front_run_rule": {
            "zone_fraction": FRONT_RUN_ZONE_FRACTION,
            "max_usd": FRONT_RUN_MAX_USD,
        },
        "mapped_targets": mapped,
        "broker_scaleout_targets": broker,
        "terminal_structural_target": terminal_structural,
        "terminal_rr_eligible": terminal_rr_eligible,
        "primary_opposing_barrier": None if not mapped else mapped[0],
        "macro_terminal_target": macro,
        "structural_target_available": bool(broker),
        "target_timeframe_order": list(TIMEFRAME_ORDER),
        "execution_influence": False,
        "execution_authority": False,
        "note": (
            "Opposing supply/demand determines target location. Earlier M15/H1 barriers "
            "remain partial scale-outs even below minimum RR; minimum RR validates the "
            "terminal structural objective. D1 remains an optional macro terminal."
        ),
    }
