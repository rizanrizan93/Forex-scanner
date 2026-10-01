from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .models import ensure_utc
from .research_brent_v229_historical_v239 import (
    BASE_SLIPPAGE_PIPS,
    BASE_SPREAD_PIPS,
    CHILD_LOT,
    CHILD_UNITS,
    COMMISSION_PIPS_ROUND_TRIP,
    CONTRACT_UNITS_PER_LOT,
    MIN_STOP_PIPS,
    PIP_SIZE,
    STRESS_SLIPPAGE_MULTIPLIER,
    STRESS_SPREAD_MULTIPLIER,
    PriceArrays,
    _dt,
    price_arrays,
    summarize_trades,
)
from .research_xau_zone_reversal_depth_v225 import (
    DepthEpisode,
    REACTION_HORIZON_MINUTES,
    _price_index,
    build_zones,
    causal_superseded_at,
    evaluate_first_touch,
)

RESEARCH_VERSION = "BRENT_DIRECT_M15_DEPTH_V240_1"
ARTIFACT_CONTRACT = "BRENT_DIRECT_M15_DEPTH_V240_1_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False
LIVE_EXECUTION_ENABLED = False

TIMEFRAME = "M15"
PRIMARY_VARIANT = "D10"
DEPTH_VARIANTS: dict[str, float] = {
    "D05": 0.05,
    "D10": 0.10,
    "D15": 0.15,
}
TARGET_ATR_MULTIPLE = 0.50
STOP_BUFFER_ATR = 0.15
MAX_POSITION_MINUTES = REACTION_HORIZON_MINUTES[TIMEFRAME]
MAX_POSITIONS = 10


def _depth_price(row: DepthEpisode, depth: float) -> float:
    d = min(max(float(depth), 0.0), 1.0)
    if row.direction == "LONG":
        return float(row.zone_high) - d * float(row.zone_width)
    return float(row.zone_low) + d * float(row.zone_width)


def _target_price(row: DepthEpisode) -> float:
    reaction = TARGET_ATR_MULTIPLE * float(row.atr_points)
    if row.direction == "LONG":
        return float(row.proximal) + reaction
    return float(row.proximal) - reaction


def _stop_price(row: DepthEpisode) -> float:
    buffer = STOP_BUFFER_ATR * float(row.atr_points)
    if row.direction == "LONG":
        return float(row.distal) - buffer
    return float(row.distal) + buffer


def build_m15_first_touch_episodes(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> tuple[DepthEpisode, ...]:
    zones = build_zones(price_m1)
    px_index = _price_index(price_m1)
    superseded = causal_superseded_at(zones)
    output: list[DepthEpisode] = []
    for zone in zones:
        if str(zone.timeframe).upper() != TIMEFRAME:
            continue
        episode = evaluate_first_touch(
            price_m1,
            zone=zone,
            index=px_index,
            valid_until=superseded.get(zone.zone_id),
        )
        if episode is None:
            continue
        if ensure_utc(episode.touch_at).year != int(target_year):
            continue
        output.append(episode)
    output.sort(key=lambda row: (ensure_utc(row.touch_at), row.zone_id))
    return tuple(output)


def _simulate_direct_trade(
    *,
    px: PriceArrays,
    episode: DepthEpisode,
    depth: float,
    spread_pips: float,
    slippage_pips: float,
    commission_pips: float = COMMISSION_PIPS_ROUND_TRIP,
) -> dict[str, Any]:
    direction = str(episode.direction).upper()
    touch_at = ensure_utc(episode.touch_at)
    pending_expiry = ensure_utc(episode.outcome_at)
    # The limit was already resting before first touch. Starting one minute
    # earlier includes the first-touch M1 bar without using future information.
    order_at = touch_at - timedelta(minutes=1)
    if pending_expiry < touch_at:
        return {"state": "MISSED", "reason": "INVALID_FIRST_TOUCH_WINDOW"}

    planned_entry = _depth_price(episode, depth)
    stop = _stop_price(episode)
    target = _target_price(episode)

    start = bisect_right(px.timestamps, pd.Timestamp(order_at))
    end = bisect_right(px.timestamps, pd.Timestamp(pending_expiry))
    if start >= end:
        return {"state": "MISSED", "reason": "NO_M1_IN_FIRST_TOUCH_WINDOW"}

    entry_mask = (
        (px.lows[start:end] <= float(planned_entry))
        & (px.highs[start:end] >= float(planned_entry))
    )
    hits = np.flatnonzero(entry_mask)
    if len(hits) == 0:
        return {"state": "MISSED", "reason": "DEPTH_NOT_REACHED_ON_FIRST_TOUCH"}

    entry_index = start + int(hits[0])
    entry_at = ensure_utc(px.timestamps[entry_index].to_pydatetime())
    adverse_fill = 0.5 * (float(spread_pips) + float(slippage_pips)) * PIP_SIZE
    fill = (
        float(planned_entry) + adverse_fill
        if direction == "LONG"
        else float(planned_entry) - adverse_fill
    )

    risk = fill - stop if direction == "LONG" else stop - fill
    risk_pips = risk / PIP_SIZE
    if risk <= 0 or risk_pips < MIN_STOP_PIPS:
        return {
            "state": "REJECTED",
            "reason": "INVALID_STOP_AFTER_COSTS",
            "planned_entry": float(planned_entry),
            "fill_price": float(fill),
            "stop": float(stop),
            "target": float(target),
        }
    target_favorable = target > fill if direction == "LONG" else target < fill
    if not target_favorable:
        return {
            "state": "REJECTED",
            "reason": "INVALID_TARGET_AFTER_COSTS",
            "planned_entry": float(planned_entry),
            "fill_price": float(fill),
            "stop": float(stop),
            "target": float(target),
            "risk_pips": float(risk_pips),
        }

    horizon = touch_at + timedelta(minutes=MAX_POSITION_MINUTES)
    eval_end = bisect_right(px.timestamps, pd.Timestamp(horizon))
    if eval_end <= entry_index:
        return {"state": "OPEN", "reason": "NO_OUTCOME_HISTORY"}

    half_exit_spread = 0.5 * float(spread_pips) * PIP_SIZE
    future_high = px.highs[entry_index:eval_end]
    future_low = px.lows[entry_index:eval_end]

    if direction == "LONG":
        stop_mask = future_low - half_exit_spread <= stop
        target_mask = future_high - half_exit_spread >= target
    else:
        stop_mask = future_high + half_exit_spread >= stop
        target_mask = future_low + half_exit_spread <= target

    raw_target_on_entry = bool(target_mask[0]) if len(target_mask) else False
    if len(target_mask):
        target_mask = target_mask.copy()
        target_mask[0] = False
    events = np.flatnonzero(stop_mask | target_mask)

    if len(events):
        rel = int(events[0])
        absolute = entry_index + rel
        stop_hit = bool(stop_mask[rel])
        target_hit = bool(target_mask[rel])
        ambiguous = bool(stop_hit and (target_hit or (rel == 0 and raw_target_on_entry)))
        if stop_hit:
            exit_price = float(stop)
            reason = "STOP_FIRST_AMBIGUOUS" if ambiguous else "STOP_HIT"
        else:
            exit_price = float(target)
            reason = "TARGET_HIT"
        exit_at = ensure_utc(px.timestamps[absolute].to_pydatetime())
        end_index = absolute
    else:
        absolute = min(eval_end - 1, len(px.timestamps) - 1)
        if absolute <= entry_index:
            return {"state": "OPEN", "reason": "HISTORY_ENDED_AFTER_FILL"}
        exit_at = ensure_utc(px.timestamps[absolute].to_pydatetime())
        close = float(px.closes[absolute])
        exit_price = (
            close - half_exit_spread
            if direction == "LONG"
            else close + half_exit_spread
        )
        reason = "V240_MAX_4H_RESEARCH_EXIT"
        end_index = absolute

    gross_price = (
        float(exit_price) - fill
        if direction == "LONG"
        else fill - float(exit_price)
    )
    gross_r = gross_price / risk
    cost_pips = 0.5 * float(slippage_pips) + float(commission_pips)
    cost_r = cost_pips / risk_pips
    net_r = gross_r - cost_r
    net_pnl = net_r * risk * CHILD_UNITS

    sample_high = px.highs[entry_index:end_index + 1]
    sample_low = px.lows[entry_index:end_index + 1]
    if direction == "LONG":
        mfe = max(0.0, float(np.max(sample_high)) - fill) / risk
        mae = max(0.0, fill - float(np.min(sample_low))) / risk
    else:
        mfe = max(0.0, fill - float(np.min(sample_low))) / risk
        mae = max(0.0, float(np.max(sample_high)) - fill) / risk

    return {
        "state": "WIN" if net_r > 0 else "LOSS" if net_r < 0 else "BREAKEVEN",
        "reason": reason,
        "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "planned_entry": float(planned_entry),
        "fill_price": float(fill),
        "exit_price": float(exit_price),
        "stop": float(stop),
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
        "elapsed_minutes": max(0.0, (exit_at - entry_at).total_seconds() / 60.0),
    }


def simulate_year(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> dict[str, Any]:
    episodes = build_m15_first_touch_episodes(price_m1, target_year=target_year)
    px = price_arrays(price_m1)
    trades: list[dict[str, Any]] = []

    for episode in episodes:
        for variant, depth in DEPTH_VARIANTS.items():
            for cost_mode, spread_pips, slippage_pips in (
                ("BASE", BASE_SPREAD_PIPS, BASE_SLIPPAGE_PIPS),
                (
                    "STRESS",
                    BASE_SPREAD_PIPS * STRESS_SPREAD_MULTIPLIER,
                    BASE_SLIPPAGE_PIPS * STRESS_SLIPPAGE_MULTIPLIER,
                ),
            ):
                result = _simulate_direct_trade(
                    px=px,
                    episode=episode,
                    depth=depth,
                    spread_pips=spread_pips,
                    slippage_pips=slippage_pips,
                )
                trades.append(
                    {
                        **result,
                        "year": int(target_year),
                        "zone_id": episode.zone_id,
                        "direction": episode.direction,
                        "variant": variant,
                        "depth": float(depth),
                        "cost_mode": cost_mode,
                        "available_at": ensure_utc(episode.available_at).isoformat(),
                        "touch_at": ensure_utc(episode.touch_at).isoformat(),
                        "episode_outcome_at": ensure_utc(episode.outcome_at).isoformat(),
                        "episode_outcome": episode.outcome,
                        "zone_low": float(episode.zone_low),
                        "zone_high": float(episode.zone_high),
                        "proximal": float(episode.proximal),
                        "distal": float(episode.distal),
                        "atr_points": float(episode.atr_points),
                        "zone_width": float(episode.zone_width),
                    }
                )

    return {
        "year": int(target_year),
        "m15_episode_count": len(episodes),
        "trade_record_count": len(trades),
        "trades": trades,
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "pair": "BCOUSD",
        "broker_reference_symbol": "BRENT",
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


def account_ledger(
    rows: Sequence[dict[str, Any]],
    *,
    initial_balance: float = 100.0,
    leverage: float = 100.0,
    margin_cap_fraction: float | None = 0.50,
    max_positions: int = MAX_POSITIONS,
) -> dict[str, Any]:
    candidates = [
        dict(row)
        for row in rows
        if str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
        and _dt(row.get("entry_at")) is not None
        and _dt(row.get("exit_at")) is not None
    ]
    candidates.sort(
        key=lambda row: (
            _dt(row.get("entry_at")) or datetime.max.replace(tzinfo=UTC),
            str(row.get("zone_id") or ""),
        )
    )

    balance = float(initial_balance)
    peak = balance
    max_dd = 0.0
    used_margin = 0.0
    max_used_margin = 0.0
    max_margin_fraction = 0.0
    accepted: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    margin_rejected = 0
    position_rejected = 0
    bust = False

    def release_until(point: datetime) -> None:
        nonlocal balance, peak, max_dd, used_margin, open_rows, bust
        closing = sorted(
            [
                row
                for row in open_rows
                if (_dt(row.get("exit_at")) or datetime.max.replace(tzinfo=UTC)) <= point
            ],
            key=lambda row: _dt(row.get("exit_at")) or datetime.max.replace(tzinfo=UTC),
        )
        for row in closing:
            balance = max(0.0, balance + float(row.get("net_pnl_usd") or 0.0))
            used_margin = max(
                0.0,
                used_margin - float(row.get("_margin_required") or 0.0),
            )
            peak = max(peak, balance)
            dd = 0.0 if peak <= 0 else (peak - balance) / peak
            max_dd = max(max_dd, dd)
            if balance <= 0:
                bust = True
        closed_ids = {id(row) for row in closing}
        open_rows = [row for row in open_rows if id(row) not in closed_ids]

    for row in candidates:
        entry_at = _dt(row.get("entry_at"))
        assert entry_at is not None
        release_until(entry_at)
        if bust or balance <= 0:
            break
        if len(open_rows) >= int(max_positions):
            position_rejected += 1
            continue

        fill = float(row.get("fill_price") or row.get("planned_entry") or 0.0)
        if fill <= 0:
            continue
        margin = CHILD_UNITS * fill / float(leverage)
        projected = used_margin + margin
        cap = (
            balance
            if margin_cap_fraction is None
            else balance * float(margin_cap_fraction)
        )
        if projected > cap + 1e-12:
            margin_rejected += 1
            continue
        row["_margin_required"] = margin
        accepted.append(row)
        open_rows.append(row)
        used_margin = projected
        max_used_margin = max(max_used_margin, used_margin)
        if balance > 0:
            max_margin_fraction = max(max_margin_fraction, used_margin / balance)

    release_until(datetime.max.replace(tzinfo=UTC))
    return {
        "initial_balance": float(initial_balance),
        "ending_balance": float(balance),
        "net_profit": float(balance - initial_balance),
        "return_multiple": float(balance / initial_balance) if initial_balance > 0 else None,
        "leverage": float(leverage),
        "child_lot": CHILD_LOT,
        "contract_units_per_lot": CONTRACT_UNITS_PER_LOT,
        "max_positions": int(max_positions),
        "margin_cap_fraction": margin_cap_fraction,
        "accepted_trades": len(accepted),
        "margin_rejected": int(margin_rejected),
        "position_rejected": int(position_rejected),
        "realized_max_drawdown_pct": float(max_dd * 100.0),
        "max_used_margin_usd": float(max_used_margin),
        "max_used_margin_fraction_of_balance": float(max_margin_fraction),
        "account_bust": bool(bust),
        "trade_summary": summarize_trades(accepted),
    }
