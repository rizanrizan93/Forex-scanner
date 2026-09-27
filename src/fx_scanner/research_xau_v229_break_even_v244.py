from __future__ import annotations

from bisect import bisect_right
from datetime import datetime
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd

from .models import ensure_utc
from .research_xau_v229_historical_v242 import (
    CHILD_UNITS,
    COMMISSION_PIPS_ROUND_TRIP,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    MAX_POSITION_HOLD,
    MIN_STOP_PIPS,
    PIP_SIZE,
    POLICY_EFFECT,
    PriceArrays,
    price_arrays,
    simulate_year as simulate_v242_year,
)

RESEARCH_VERSION = "XAU_V229_BREAK_EVEN_MANAGEMENT_V244_1"
ARTIFACT_CONTRACT = "XAU_V229_BREAK_EVEN_MANAGEMENT_V244_1_EVIDENCE_1"
SYMBOL = "XAUUSD"

MANAGEMENT_VARIANTS: dict[str, float | None] = {
    "BASELINE": None,
    "BE_0_5R": 0.50,
    "BE_1_0R": 1.00,
}

_SIMULATOR_FIELDS = {
    "state",
    "reason",
    "entry_at",
    "exit_at",
    "planned_entry",
    "fill_price",
    "exit_price",
    "stop",
    "target",
    "risk_pips",
    "gross_r",
    "cost_r",
    "net_r",
    "net_pnl_usd",
    "mae_r",
    "mfe_r",
    "ambiguous_bar",
    "spread_pips",
    "slippage_pips",
    "elapsed_days",
    "be_trigger_r",
    "be_triggered",
    "be_stop",
    "be_armed_at",
}


def _managed_limit_trade(
    *,
    px: PriceArrays,
    direction: str,
    order_at: datetime,
    expires_at: datetime,
    entry: float,
    stop: float,
    target: float,
    spread_pips: float,
    slippage_pips: float,
    be_trigger_r: float,
    commission_pips: float = COMMISSION_PIPS_ROUND_TRIP,
) -> dict[str, Any]:
    """Replay one V229 child with causal net-break-even protection.

    The BE trigger is observed on a completed M1 bar. The adjusted stop becomes
    active only from the NEXT M1 bar. This deliberately avoids assuming whether
    a favorable excursion or a retracement happened first inside the trigger bar.

    The BE stop is shifted beyond the entry fill by the separately deducted
    exit slippage/commission term so that a BE stop produces approximately 0R
    net under the same V242 cost accounting.
    """
    side = str(direction or "").upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("V244_DIRECTION_INVALID")
    trigger_r = float(be_trigger_r)
    if not isfinite(trigger_r) or trigger_r <= 0:
        raise ValueError("V244_BE_TRIGGER_R_INVALID")

    signal = ensure_utc(order_at)
    expiry = ensure_utc(expires_at)
    if expiry <= signal:
        return {"state": "MISSED", "reason": "NO_PENDING_WINDOW"}

    start = bisect_right(px.timestamps, pd.Timestamp(signal))
    end = bisect_right(px.timestamps, pd.Timestamp(expiry))
    if start >= end:
        return {"state": "MISSED", "reason": "NO_M1_AFTER_ORDER"}

    entry_mask = (
        (px.lows[start:end] <= float(entry))
        & (px.highs[start:end] >= float(entry))
    )
    hits = np.flatnonzero(entry_mask)
    if len(hits) == 0:
        return {"state": "MISSED", "reason": "LIMIT_NOT_TOUCHED"}

    entry_index = start + int(hits[0])
    entry_at = ensure_utc(px.timestamps[entry_index].to_pydatetime())
    adverse_fill = 0.5 * (float(spread_pips) + float(slippage_pips)) * PIP_SIZE
    fill = float(entry) + adverse_fill if side == "LONG" else float(entry) - adverse_fill
    original_stop = float(stop)
    risk = fill - original_stop if side == "LONG" else original_stop - fill
    risk_pips = risk / PIP_SIZE
    if risk <= 0 or risk_pips < MIN_STOP_PIPS:
        return {"state": "REJECTED", "reason": "INVALID_STOP_AFTER_COSTS"}

    target_favorable = float(target) > fill if side == "LONG" else float(target) < fill
    if not target_favorable:
        return {
            "state": "REJECTED",
            "reason": "INVALID_TARGET_AFTER_COSTS",
            "planned_entry": float(entry),
            "fill_price": float(fill),
            "stop": original_stop,
            "target": float(target),
            "risk_pips": float(risk_pips),
        }

    horizon = entry_at + MAX_POSITION_HOLD
    eval_end = bisect_right(px.timestamps, pd.Timestamp(horizon))
    if eval_end <= entry_index:
        return {"state": "OPEN", "reason": "NO_OUTCOME_HISTORY"}

    half_exit_spread = 0.5 * float(spread_pips) * PIP_SIZE
    exit_cost_pips = 0.5 * float(slippage_pips) + float(commission_pips)
    be_offset = exit_cost_pips * PIP_SIZE
    be_stop = fill + be_offset if side == "LONG" else fill - be_offset
    trigger_price = (
        fill + trigger_r * risk
        if side == "LONG"
        else fill - trigger_r * risk
    )

    active_stop = original_stop
    arm_index: int | None = None
    armed_at: datetime | None = None
    triggered = False
    exit_at: datetime | None = None
    exit_price: float | None = None
    reason: str | None = None
    end_index: int | None = None

    for absolute in range(entry_index, eval_end):
        if arm_index is not None and absolute >= arm_index:
            active_stop = float(be_stop)

        high = float(px.highs[absolute])
        low = float(px.lows[absolute])
        if side == "LONG":
            stop_hit = low - half_exit_spread <= active_stop
            target_hit = high - half_exit_spread >= float(target)
            trigger_hit = high - half_exit_spread >= trigger_price
        else:
            stop_hit = high + half_exit_spread >= active_stop
            target_hit = low + half_exit_spread <= float(target)
            trigger_hit = low + half_exit_spread <= trigger_price

        raw_target_on_entry = bool(absolute == entry_index and target_hit)
        if absolute == entry_index:
            target_hit = False

        # Conservative ambiguity contract: the currently active stop wins.
        if stop_hit:
            exit_at = ensure_utc(px.timestamps[absolute].to_pydatetime())
            exit_price = float(active_stop)
            using_be = arm_index is not None and absolute >= arm_index
            if using_be:
                reason = (
                    "NET_BE_STOP_HIT_AFTER_0_5R"
                    if abs(trigger_r - 0.5) < 1e-12
                    else "NET_BE_STOP_HIT_AFTER_1_0R"
                    if abs(trigger_r - 1.0) < 1e-12
                    else "NET_BE_STOP_HIT"
                )
            else:
                reason = (
                    "STOP_FIRST_AMBIGUOUS"
                    if target_hit or raw_target_on_entry
                    else "STOP_HIT"
                )
            end_index = absolute
            break

        if target_hit:
            exit_at = ensure_utc(px.timestamps[absolute].to_pydatetime())
            exit_price = float(target)
            reason = "TARGET_HIT"
            end_index = absolute
            break

        # Do not activate BE inside the same M1 bar that first proves the trigger.
        if not triggered and trigger_hit:
            triggered = True
            if absolute + 1 < eval_end:
                arm_index = absolute + 1
                armed_at = ensure_utc(px.timestamps[arm_index].to_pydatetime())

    if exit_at is None or exit_price is None or end_index is None:
        absolute = min(eval_end - 1, len(px.timestamps) - 1)
        if absolute <= entry_index:
            return {"state": "OPEN", "reason": "HISTORY_ENDED_AFTER_FILL"}
        exit_at = ensure_utc(px.timestamps[absolute].to_pydatetime())
        close = float(px.closes[absolute])
        exit_price = (
            close - half_exit_spread
            if side == "LONG"
            else close + half_exit_spread
        )
        reason = "V244_MAX_30D_RESEARCH_EXIT"
        end_index = absolute

    gross_price = (
        float(exit_price) - fill
        if side == "LONG"
        else fill - float(exit_price)
    )
    gross_r = gross_price / risk
    cost_r = exit_cost_pips / risk_pips
    net_r = gross_r - cost_r
    if abs(net_r) <= 1e-10:
        state = "BREAKEVEN"
        net_r = 0.0
    else:
        state = "WIN" if net_r > 0 else "LOSS"
    net_pnl = net_r * risk * CHILD_UNITS
    elapsed_days = max(0.0, (exit_at - entry_at).total_seconds() / 86400.0)

    sample_high = px.highs[entry_index : end_index + 1]
    sample_low = px.lows[entry_index : end_index + 1]
    if side == "LONG":
        mfe = max(0.0, float(np.max(sample_high)) - fill) / risk
        mae = max(0.0, fill - float(np.min(sample_low))) / risk
    else:
        mfe = max(0.0, fill - float(np.min(sample_low))) / risk
        mae = max(0.0, float(np.max(sample_high)) - fill) / risk

    return {
        "state": state,
        "reason": reason,
        "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "planned_entry": float(entry),
        "fill_price": float(fill),
        "exit_price": float(exit_price),
        "stop": original_stop,
        "target": float(target),
        "risk_pips": float(risk_pips),
        "gross_r": float(gross_r),
        "cost_r": float(cost_r),
        "net_r": float(net_r),
        "net_pnl_usd": float(net_pnl),
        "mae_r": float(mae),
        "mfe_r": float(mfe),
        "ambiguous_bar": bool(reason == "STOP_FIRST_AMBIGUOUS"),
        "spread_pips": float(spread_pips),
        "slippage_pips": float(slippage_pips),
        "elapsed_days": float(elapsed_days),
        "be_trigger_r": float(trigger_r),
        "be_triggered": bool(triggered),
        "be_stop": float(be_stop),
        "be_armed_at": None if armed_at is None else armed_at.isoformat(),
    }


def _managed_copy(
    *,
    px: PriceArrays,
    raw: dict[str, Any],
    variant: str,
    trigger_r: float,
) -> dict[str, Any]:
    row = dict(raw)
    if str(row.get("state") or "") not in {"WIN", "LOSS", "BREAKEVEN"}:
        return {
            **row,
            "management_variant": variant,
            "be_trigger_r": float(trigger_r),
            "be_triggered": False,
            "be_stop": None,
            "be_armed_at": None,
        }

    required = (
        "order_at",
        "signal_expires_at",
        "planned_entry",
        "stop",
        "target",
        "spread_pips",
        "slippage_pips",
    )
    if any(row.get(key) in (None, "") for key in required):
        return {
            **row,
            "management_variant": variant,
            "state": "REJECTED",
            "reason": "V244_REPLAY_FIELDS_MISSING",
        }

    clean = {key: value for key, value in row.items() if key not in _SIMULATOR_FIELDS}
    outcome = _managed_limit_trade(
        px=px,
        direction=str(row.get("direction") or ""),
        order_at=ensure_utc(datetime.fromisoformat(str(row["order_at"]).replace("Z", "+00:00"))),
        expires_at=ensure_utc(datetime.fromisoformat(str(row["signal_expires_at"]).replace("Z", "+00:00"))),
        entry=float(row["planned_entry"]),
        stop=float(row["stop"]),
        target=float(row["target"]),
        spread_pips=float(row["spread_pips"]),
        slippage_pips=float(row["slippage_pips"]),
        be_trigger_r=float(trigger_r),
    )
    return {
        **clean,
        "management_variant": variant,
        **outcome,
    }


def simulate_year(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> dict[str, Any]:
    upstream = simulate_v242_year(price_m1, target_year=target_year)
    px = price_arrays(price_m1)
    trades: list[dict[str, Any]] = []

    for raw in list(upstream.get("trades") or []):
        row = dict(raw)
        trades.append(
            {
                **row,
                "management_variant": "BASELINE",
                "be_trigger_r": None,
                "be_triggered": False,
                "be_stop": None,
                "be_armed_at": None,
            }
        )
        for variant, trigger_r in MANAGEMENT_VARIANTS.items():
            if variant == "BASELINE" or trigger_r is None:
                continue
            trades.append(
                _managed_copy(
                    px=px,
                    raw=row,
                    variant=variant,
                    trigger_r=float(trigger_r),
                )
            )

    return {
        **upstream,
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "upstream_research_version": upstream.get("research_version"),
        "trades": trades,
        "trade_record_count": len(trades),
        "management_contract": {
            "variants": dict(MANAGEMENT_VARIANTS),
            "activation_clock": "NEXT_M1_BAR_AFTER_TRIGGER_BAR",
            "trigger_measurement": "EXECUTABLE_EXTREME_AFTER_HALF_EXIT_SPREAD",
            "intrabar_ambiguity": "CURRENT_ACTIVE_STOP_FIRST",
            "be_stop": "NET_BREAK_EVEN_AFTER_SEPARATELY_DEDUCTED_EXIT_SLIPPAGE_AND_COMMISSION",
            "target_geometry": "UNCHANGED_V229_STRUCTURAL_TARGET",
            "parameter_search": False,
        },
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }
