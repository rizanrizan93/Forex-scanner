from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from .models import ensure_utc
from .research_xau_v229_historical_v242 import (
    ARTIFACT_CONTRACT as V242_ARTIFACT_CONTRACT,
    CHILD_UNITS,
    COMMISSION_PIPS_ROUND_TRIP,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    MAX_POSITION_HOLD,
    PIP_SIZE,
    POLICY_EFFECT,
    PriceArrays,
    RESEARCH_VERSION as V242_RESEARCH_VERSION,
    price_arrays,
    simulate_year as simulate_v242_year,
)

RESEARCH_VERSION = "XAU_V229_BE_MANAGEMENT_V244_1"
ARTIFACT_CONTRACT = "XAU_V229_BE_MANAGEMENT_V244_1_EVIDENCE_1"
SYMBOL = "XAUUSD"

# Pre-registered management family. No other trigger is searched in V244.
MANAGEMENT_VARIANTS: dict[str, float | None] = {
    "BASELINE": None,
    "BE_AFTER_0_5R": 0.50,
    "BE_AFTER_1_0R": 1.00,
}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return ensure_utc(parsed)


def _completed(row: dict[str, Any]) -> bool:
    return str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}


def _managed_completed_trade(
    *,
    px: PriceArrays,
    row: dict[str, Any],
    trigger_r: float,
) -> dict[str, Any]:
    direction = str(row.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("V244_DIRECTION_REQUIRED")

    entry_at = _dt(row.get("entry_at"))
    if entry_at is None:
        raise ValueError("V244_ENTRY_AT_REQUIRED")
    entry_index = bisect_left(px.timestamps, pd.Timestamp(entry_at))
    if (
        entry_index >= len(px.timestamps)
        or ensure_utc(px.timestamps[entry_index].to_pydatetime()) != entry_at
    ):
        raise ValueError("V244_ENTRY_TIMESTAMP_NOT_FOUND")

    fill = float(row["fill_price"])
    initial_stop = float(row["stop"])
    target = float(row["target"])
    risk = fill - initial_stop if direction == "LONG" else initial_stop - fill
    if risk <= 0:
        raise ValueError("V244_INVALID_INITIAL_RISK")

    spread_pips = float(row.get("spread_pips") or 0.0)
    slippage_pips = float(row.get("slippage_pips") or 0.0)
    risk_pips = float(row.get("risk_pips") or (risk / PIP_SIZE))
    if risk_pips <= 0:
        raise ValueError("V244_INVALID_RISK_PIPS")

    half_exit_spread = 0.5 * spread_pips * PIP_SIZE
    explicit_cost_pips = 0.5 * slippage_pips + COMMISSION_PIPS_ROUND_TRIP
    explicit_cost_price = explicit_cost_pips * PIP_SIZE

    # Cost-neutral BE: if filled at this stop and charged the same explicit
    # slippage/commission model as V242, net R is approximately zero.
    be_stop = (
        fill + explicit_cost_price
        if direction == "LONG"
        else fill - explicit_cost_price
    )
    trigger_price = (
        fill + float(trigger_r) * risk
        if direction == "LONG"
        else fill - float(trigger_r) * risk
    )

    horizon = entry_at + MAX_POSITION_HOLD
    eval_end = bisect_right(px.timestamps, pd.Timestamp(horizon))
    if eval_end <= entry_index:
        return {**row, "state": "OPEN", "reason": "NO_OUTCOME_HISTORY"}

    be_active = False
    be_armed_at: datetime | None = None
    be_active_at: datetime | None = None
    active_stop = initial_stop
    exit_price: float | None = None
    exit_at: datetime | None = None
    end_index = entry_index
    reason = ""
    ambiguous = False

    for absolute in range(entry_index, eval_end):
        rel = absolute - entry_index
        high = float(px.highs[absolute])
        low = float(px.lows[absolute])
        ts = ensure_utc(px.timestamps[absolute].to_pydatetime())

        if be_active:
            active_stop = be_stop

        if direction == "LONG":
            stop_hit = low - half_exit_spread <= active_stop
            raw_target_hit = high - half_exit_spread >= target
            trigger_hit = high - half_exit_spread >= trigger_price
        else:
            stop_hit = high + half_exit_spread >= active_stop
            raw_target_hit = low + half_exit_spread <= target
            trigger_hit = low + half_exit_spread <= trigger_price

        # Preserve V242's fill-bar contract: target-only on the entry M1 is
        # unknowable and is ignored. Stop remains authoritative.
        target_hit = bool(raw_target_hit and rel > 0)
        if stop_hit:
            exit_price = active_stop
            exit_at = ts
            end_index = absolute
            ambiguous = bool(target_hit or (rel == 0 and raw_target_hit))
            if be_active:
                reason = "BE_STOP_FIRST_AMBIGUOUS" if ambiguous else "BE_STOP_HIT"
            else:
                reason = "STOP_FIRST_AMBIGUOUS" if ambiguous else "STOP_HIT"
            break
        if target_hit:
            exit_price = target
            exit_at = ts
            end_index = absolute
            reason = "TARGET_HIT"
            break

        # Conservative causality: a trigger observed inside a completed M1 bar
        # only moves the stop for the NEXT M1 bar. Entry bar can never arm BE.
        if not be_active and rel > 0 and trigger_hit:
            be_armed_at = ts
            if absolute + 1 < eval_end:
                be_active_at = ensure_utc(px.timestamps[absolute + 1].to_pydatetime())
                be_active = True

    if exit_price is None or exit_at is None:
        absolute = min(eval_end - 1, len(px.timestamps) - 1)
        if absolute <= entry_index:
            return {**row, "state": "OPEN", "reason": "HISTORY_ENDED_AFTER_FILL"}
        exit_at = ensure_utc(px.timestamps[absolute].to_pydatetime())
        close = float(px.closes[absolute])
        exit_price = (
            close - half_exit_spread
            if direction == "LONG"
            else close + half_exit_spread
        )
        end_index = absolute
        reason = "V244_MAX_30D_RESEARCH_EXIT"

    gross_price = (
        float(exit_price) - fill
        if direction == "LONG"
        else fill - float(exit_price)
    )
    gross_r = gross_price / risk
    cost_r = explicit_cost_pips / risk_pips
    net_r = gross_r - cost_r

    net_pnl = net_r * risk * CHILD_UNITS

    sample_high = px.highs[entry_index : end_index + 1]
    sample_low = px.lows[entry_index : end_index + 1]
    if direction == "LONG":
        mfe = max(0.0, float(np.max(sample_high)) - fill) / risk
        mae = max(0.0, fill - float(np.min(sample_low))) / risk
    else:
        mfe = max(0.0, fill - float(np.min(sample_low))) / risk
        mae = max(0.0, float(np.max(sample_high)) - fill) / risk

    elapsed_days = max(0.0, (exit_at - entry_at).total_seconds() / 86400.0)
    return {
        **row,
        "state": "WIN" if net_r > 1e-12 else "LOSS" if net_r < -1e-12 else "BREAKEVEN",
        "reason": reason,
        "exit_at": exit_at.isoformat(),
        "exit_price": float(exit_price),
        "gross_r": float(gross_r),
        "cost_r": float(cost_r),
        "net_r": float(net_r),
        "net_pnl_usd": float(net_pnl),
        "mae_r": float(mae),
        "mfe_r": float(mfe),
        "ambiguous_bar": bool(ambiguous),
        "elapsed_days": float(elapsed_days),
        "be_trigger_r": float(trigger_r),
        "be_trigger_price": float(trigger_price),
        "be_stop_price": float(be_stop),
        "be_armed_at": None if be_armed_at is None else be_armed_at.isoformat(),
        "be_active_at": None if be_active_at is None else be_active_at.isoformat(),
        "be_activated": bool(be_armed_at is not None),
        "be_cost_neutral": True,
        "be_activation_policy": "NEXT_M1_BAR_AFTER_TRIGGER",
    }


def apply_management_variants(
    *,
    price_m1: pd.DataFrame,
    base_result: dict[str, Any],
) -> dict[str, Any]:
    px = price_arrays(price_m1)
    output: list[dict[str, Any]] = []
    for raw in list(base_result.get("trades") or []):
        row = dict(raw)
        for variant, trigger in MANAGEMENT_VARIANTS.items():
            if variant == "BASELINE" or not _completed(row):
                managed = dict(row)
            else:
                assert trigger is not None
                managed = _managed_completed_trade(
                    px=px,
                    row=row,
                    trigger_r=float(trigger),
                )
            output.append(
                {
                    **managed,
                    "management_variant": variant,
                    "management_trigger_r": trigger,
                }
            )
    return {
        **base_result,
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "upstream_v242_research_version": V242_RESEARCH_VERSION,
        "upstream_v242_artifact_contract": V242_ARTIFACT_CONTRACT,
        "trades": output,
        "trade_record_count": len(output),
        "management_contract": {
            "variants": MANAGEMENT_VARIANTS,
            "be_stop": "COST_NEUTRAL",
            "activation": "NEXT_M1_BAR_AFTER_COMPLETED_TRIGGER_BAR",
            "same_bar_policy": "ORIGINAL_STOP_FIRST_BE_NOT_ACTIVE_UNTIL_NEXT_BAR",
            "target_contract": "UNCHANGED_V229_STRUCTURAL_TARGET",
            "entry_contract": "UNCHANGED_V229_ENTRY",
            "parameter_search": False,
        },
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


def simulate_year(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> dict[str, Any]:
    base = simulate_v242_year(price_m1, target_year=target_year)
    return apply_management_variants(price_m1=price_m1, base_result=base)
