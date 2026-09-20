from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import load_project_config
from .demo_xau_m15_ict_layer import (
    LIQUIDITY_SWEEP_LOOKBACK,
    evaluate_ict_execution_context,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    BreakoutSignal,
    extract_signals as extract_m15_breakout,
)
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    _date_cutoff,
    _family_streams,
    _route_family_candidates,
    _trailing_health,
)
from .research_xau_hierarchical_regime_router_v35 import (
    L12_ID,
    L20_ID,
    _Asof,
    build_h1_context,
)
from .research_xau_h1_structure_context_v56 import build_h1_structure_context
from .research_xau_h1_volatility_state_v63 import build_h1_volatility_context
from .research_xau_realized_skew_state_v64 import build_prior_day_skew_context
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_m15_dual_strategy_runtime import _fetch_history
from .research_xau_multihorizon_100usd_v20 import M15_VARIANTS, _trading_dates
from .research_xau_secular_regime_router_v46 import COST_R_CAP, build_secular_d1
from .research_xau_v47_forward_freeze_v69 import (
    ARTIFACT_CONTRACT as FREEZE_ARTIFACT_CONTRACT,
    BASE_ROUTE,
    FORWARD_CONTRACT,
    PROSPECTIVE_EPOCH,
)
from .research_xau_v47_forward_telemetry_v72 import (
    ARTIFACT_CONTRACT as TELEMETRY_ARTIFACT_CONTRACT,
    TELEMETRY_CONTRACT,
)
from .research_xau_v47_target_credibility_v74 import build_d1_range_context
from .research_xau_v47_forward_sweep_telemetry_v82 import (
    ARTIFACT_CONTRACT as SWEEP_TELEMETRY_ARTIFACT_CONTRACT,
    SWEEP_TELEMETRY_CONTRACT,
)
from .research_xau_v47_target_forward_freeze_v77 import (
    ARTIFACT_CONTRACT as TARGET_FREEZE_ARTIFACT_CONTRACT,
    FORWARD_CONTRACT as TARGET_FORWARD_CONTRACT,
    PROSPECTIVE_EPOCH as TARGET_PROSPECTIVE_EPOCH,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
RESEARCH_VERSION = "XAU_V47_FORWARD_OBSERVER_V70"
ARTIFACT_CONTRACT = "XAU_V47_FORWARD_OBSERVER_V70_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False
SYMBOL = "XAUUSD"
EVENT_TYPE = "DEMO_XAU_V47_FORWARD_EVALUATION"
WORKER_NAME = "ctrader_demo_xau_v47_forward_observer_v70"
HISTORY_BARS = 45_000
PIP_SIZE = 0.01

# Freeze exact historical stress assumptions so the prospective eligibility
# decision is comparable to the V47/V66 evidence. Current broker spread is
# recorded separately as telemetry and does not change this route.
FORWARD_STRESS_COSTS = M15ResearchCosts(
    spread_pips=37.0,
    slippage_pips=0.2,
    commission_pips_round_trip=0.2,
    swap_pips_per_day=0.0,
    spread_multiplier=1.25,
    slippage_multiplier=1.50,
)


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _friction_pips(costs: M15ResearchCosts) -> float:
    return (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
    )


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _int_or_none(value: Any) -> int | None:
    number = _finite_or_none(value)
    return None if number is None else int(number)


def _raw_sweep_telemetry(
    context_rows: Sequence[Bar],
    *,
    direction: str,
    atr_value: float,
    as_of: datetime,
    ict: Any,
) -> dict[str, Any]:
    side = str(direction).upper()
    if side not in {"LONG", "SHORT"} or not isfinite(float(atr_value)) or float(atr_value) <= 0.0:
        return {
            "contract": SWEEP_TELEMETRY_ARTIFACT_CONTRACT,
            "latest_sweep_at": None,
            "latest_sweep_age_m15_bars": None,
            "latest_sweep_source": None,
            "latest_sweep_level": None,
            "penetration_atr": None,
            "reclaim_atr": None,
            "body_atr": None,
            "close_location": None,
            "all_recent_sweep_events": [],
        }

    completed = tuple(
        row
        for row in sorted(context_rows, key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= ensure_utc(as_of)
    )
    if not completed:
        return {
            "contract": SWEEP_TELEMETRY_ARTIFACT_CONTRACT,
            "latest_sweep_at": None,
            "latest_sweep_age_m15_bars": None,
            "latest_sweep_source": None,
            "latest_sweep_level": None,
            "penetration_atr": None,
            "reclaim_atr": None,
            "body_atr": None,
            "close_location": None,
            "all_recent_sweep_events": [],
        }

    levels = (
        {
            "PDL": ict.previous_day_low,
            "ASIA_LOW": ict.asian_low,
            "LONDON_LOW": ict.london_low,
            "NEW_YORK_LOW": ict.new_york_low,
        }
        if side == "LONG"
        else {
            "PDH": ict.previous_day_high,
            "ASIA_HIGH": ict.asian_high,
            "LONDON_HIGH": ict.london_high,
            "NEW_YORK_HIGH": ict.new_york_high,
        }
    )

    start = max(0, len(completed) - LIQUIDITY_SWEEP_LOOKBACK)
    events: list[dict[str, Any]] = []
    for index in range(start, len(completed)):
        row = completed[index]
        candle_range = max(float(row.high) - float(row.low), 1e-12)
        body_atr = abs(float(row.close) - float(row.open)) / float(atr_value)
        close_location = (
            (float(row.close) - float(row.low)) / candle_range
            if side == "LONG"
            else (float(row.high) - float(row.close)) / candle_range
        )
        for source, raw_level in levels.items():
            if raw_level is None:
                continue
            level = float(raw_level)
            if side == "LONG":
                swept = float(row.low) < level and float(row.close) > level
                penetration = (level - float(row.low)) / float(atr_value)
                reclaim = (float(row.close) - level) / float(atr_value)
            else:
                swept = float(row.high) > level and float(row.close) < level
                penetration = (float(row.high) - level) / float(atr_value)
                reclaim = (level - float(row.close)) / float(atr_value)
            if not swept:
                continue
            events.append(
                {
                    "source": source,
                    "level": level,
                    "sweep_at": ensure_utc(row.timestamp).isoformat(),
                    "age_m15_bars": len(completed) - 1 - index,
                    "penetration_atr": penetration,
                    "reclaim_atr": reclaim,
                    "body_atr": body_atr,
                    "close_location": close_location,
                }
            )

    latest = max(
        events,
        key=lambda row: (
            str(row["sweep_at"]),
            str(row["source"]),
        ),
        default=None,
    )
    return {
        "contract": SWEEP_TELEMETRY_ARTIFACT_CONTRACT,
        "latest_sweep_at": None if latest is None else latest["sweep_at"],
        "latest_sweep_age_m15_bars": None if latest is None else latest["age_m15_bars"],
        "latest_sweep_source": None if latest is None else latest["source"],
        "latest_sweep_level": None if latest is None else latest["level"],
        "penetration_atr": None if latest is None else latest["penetration_atr"],
        "reclaim_atr": None if latest is None else latest["reclaim_atr"],
        "body_atr": None if latest is None else latest["body_atr"],
        "close_location": None if latest is None else latest["close_location"],
        "all_recent_sweep_events": events,
    }


def route_eligibility(
    *,
    direction: str,
    d1_side: int,
    secular_regime: str,
    transition_outcome: str,
    post_transition_age_days: int,
    h1_close: float,
    h1_ema20: float,
    h1_ema50: float,
    h1_ema200: float,
    entry_friction_r: float,
) -> bool:
    side = str(direction).upper()
    if side != "LONG":
        return False
    numeric = (h1_close, h1_ema20, h1_ema50, h1_ema200, entry_friction_r)
    if not all(isfinite(float(x)) for x in numeric):
        return False
    d1_match = int(d1_side) == 1
    h1_normal = (
        float(h1_close) > float(h1_ema200)
        and float(h1_ema20) > float(h1_ema50)
    )
    return bool(
        d1_match
        and h1_normal
        and float(entry_friction_r) <= COST_R_CAP
        and str(secular_regime) == "SECULAR_BULL"
        and str(transition_outcome) == "REACCELERATION"
        and 1 <= int(post_transition_age_days) <= 20
    )


def _family_variant_map() -> dict[str, Any]:
    by_id = {variant.variant_id: variant for variant in M15_VARIANTS}
    return {
        "L12": by_id[L12_ID],
        "L20": by_id[L20_ID],
    }


def _existing_signal_keys(store: Any) -> set[str]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key")
        .eq("event_type", EVENT_TYPE)
        .eq("code", RESEARCH_VERSION)
        .order("observed_at", desc=False)
        .limit(5000)
        .execute()
    )
    return {
        str(row["signal_key"])
        for row in (response.data or [])
        if row.get("signal_key")
    }


def _signal_key(family: str, signal: BreakoutSignal) -> str:
    raw = "|".join(
        (
            RESEARCH_VERSION,
            family,
            ensure_utc(signal.signal_at).isoformat(),
            str(signal.direction).upper(),
            str(signal.variant_id),
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"XAU_V47_FORWARD:{digest}"


def _health_at_signal(
    candidate_history,
    *,
    signal_at: datetime,
    trading_dates,
) -> dict[str, Any]:
    stamp = ensure_utc(signal_at)
    cutoff_date = _date_cutoff(stamp, trading_dates=trading_dates)
    completed = tuple(
        trade
        for trade in candidate_history
        if ensure_utc(trade.exit_at) < stamp
        and ensure_utc(trade.exit_at).date() >= cutoff_date
    )
    return _trailing_health(completed)


def _evaluate_signal(
    rows: Sequence[Bar],
    *,
    family: str,
    signal: BreakoutSignal,
    d1_lookup: _Asof,
    h1_lookup: _Asof,
    structure_lookup: _Asof,
    volatility_lookup: _Asof,
    skew_lookup: _Asof,
    d1_range_lookup: _Asof,
    candidate_history,
    trading_dates,
) -> dict[str, Any] | None:
    signal_at = ensure_utc(signal.signal_at)
    if signal_at < PROSPECTIVE_EPOCH:
        return None
    entry_index = int(signal.signal_index) + 1
    if entry_index >= len(rows):
        return None

    entry_bar = rows[entry_index]
    entry_at = ensure_utc(entry_bar.timestamp)
    entry_price = float(entry_bar.open)
    stop = float(signal.stop)
    risk_price = (
        entry_price - stop
        if str(signal.direction).upper() == "LONG"
        else stop - entry_price
    )
    if not isfinite(risk_price) or risk_price <= 0.0:
        return None

    risk_pips = risk_price / PIP_SIZE
    friction_pips = _friction_pips(FORWARD_STRESS_COSTS)
    friction_r = friction_pips / risk_pips

    d1 = d1_lookup.row(signal_at)
    h1 = h1_lookup.row(signal_at)
    structure = structure_lookup.row(signal_at)
    volatility = volatility_lookup.row(signal_at)
    skew = skew_lookup.row(signal_at)
    d1_range = d1_range_lookup.row(signal_at)
    if d1 is None or h1 is None:
        return None

    route_ok = route_eligibility(
        direction=signal.direction,
        d1_side=int(d1.get("regime_side") or 0),
        secular_regime=str(d1.get("secular_regime") or "SECULAR_NEUTRAL"),
        transition_outcome=str(d1.get("transition_outcome") or "NONE"),
        post_transition_age_days=int(d1.get("post_transition_age_days") or 0),
        h1_close=float(h1.get("close")),
        h1_ema20=float(h1.get("ema20")),
        h1_ema50=float(h1.get("ema50")),
        h1_ema200=float(h1.get("ema200")),
        entry_friction_r=friction_r,
    )
    family_health = _health_at_signal(
        candidate_history,
        signal_at=signal_at,
        trading_dates=trading_dates,
    )
    family_gate_active = bool(family_health.get("active"))

    context_rows = tuple(rows[max(0, int(signal.signal_index) - 699): int(signal.signal_index) + 1])
    ict_as_of = signal_at + timedelta(minutes=15)
    ict = evaluate_ict_execution_context(
        context_rows,
        direction=str(signal.direction).upper(),
        atr_value=float(signal.atr),
        as_of=ict_as_of,
    )
    sweep_telemetry = _raw_sweep_telemetry(
        context_rows,
        direction=str(signal.direction).upper(),
        atr_value=float(signal.atr),
        as_of=ict_as_of,
        ict=ict,
    )

    target = (
        entry_price + float(signal.reward_r) * risk_price
        if str(signal.direction).upper() == "LONG"
        else entry_price - float(signal.reward_r) * risk_price
    )

    prior60_d1_median_range = (
        None
        if d1_range is None
        else _finite_or_none(d1_range.get("range_median60"))
    )
    target_distance = abs(float(target) - float(entry_price))
    target_to_prior60_d1_median = (
        None
        if prior60_d1_median_range is None or prior60_d1_median_range <= 0.0
        else target_distance / prior60_d1_median_range
    )
    if signal_at < TARGET_PROSPECTIVE_EPOCH:
        target_forward_group = "BEFORE_V77_EPOCH"
    elif not bool(route_ok and family_gate_active):
        target_forward_group = "V47_NOT_APPROVED"
    elif target_to_prior60_d1_median is None:
        target_forward_group = "UNAVAILABLE"
    elif target_to_prior60_d1_median > 0.75:
        target_forward_group = "TARGET_GT_0_75"
    else:
        target_forward_group = "TARGET_LE_0_75"

    return {
        "family": family,
        "variant_id": str(signal.variant_id),
        "signal_at": signal_at.isoformat(),
        "entry_at": entry_at.isoformat(),
        "direction": str(signal.direction).upper(),
        "entry_price": entry_price,
        "stop": stop,
        "target": target,
        "reward_r": float(signal.reward_r),
        "atr_at_signal": float(signal.atr),
        "risk_price": risk_price,
        "risk_pips": risk_pips,
        "frozen_friction_pips": friction_pips,
        "entry_friction_r": friction_r,
        "route_eligible": route_ok,
        "family_gate_active": family_gate_active,
        "v47_approved": bool(route_ok and family_gate_active),
        "family_health": family_health,
        "d1": {
            "regime_side": int(d1.get("regime_side") or 0),
            "secular_regime": str(d1.get("secular_regime") or "SECULAR_NEUTRAL"),
            "transition_outcome": str(d1.get("transition_outcome") or "NONE"),
            "post_transition_age_days": int(d1.get("post_transition_age_days") or 0),
        },
        "h1": {
            "close": float(h1.get("close")),
            "ema20": float(h1.get("ema20")),
            "ema50": float(h1.get("ema50")),
            "ema200": float(h1.get("ema200")),
        },
        "secondary_telemetry_contract": TELEMETRY_ARTIFACT_CONTRACT,
        "secondary_telemetry": {
            "h1_structure": {
                "swing_structure_state": (
                    "INSUFFICIENT"
                    if structure is None
                    else str(structure.get("swing_structure_state") or "INSUFFICIENT")
                ),
                "last_break_event": (
                    "NONE"
                    if structure is None
                    else str(structure.get("last_break_event") or "NONE")
                ),
                "bars_since_last_break": (
                    None
                    if structure is None
                    else _int_or_none(structure.get("bars_since_last_break"))
                ),
                "last_confirmed_swing_high": (
                    None
                    if structure is None
                    else _finite_or_none(structure.get("last_confirmed_swing_high"))
                ),
                "last_confirmed_swing_low": (
                    None
                    if structure is None
                    else _finite_or_none(structure.get("last_confirmed_swing_low"))
                ),
            },
            "h1_volatility": {
                "vol_state": (
                    "UNAVAILABLE"
                    if volatility is None
                    else str(volatility.get("vol_state") or "UNAVAILABLE")
                ),
                "atr14": (
                    None
                    if volatility is None
                    else _finite_or_none(volatility.get("atr14"))
                ),
                "atr_to_prior_median": (
                    None
                    if volatility is None
                    else _finite_or_none(volatility.get("atr_to_prior_median"))
                ),
            },
            "prior_day_realized_skew": {
                "skew_state": (
                    "UNAVAILABLE"
                    if skew is None
                    else str(skew.get("skew_state") or "UNAVAILABLE")
                ),
                "realized_skew": (
                    None
                    if skew is None
                    else _finite_or_none(skew.get("realized_skew"))
                ),
                "realized_variance": (
                    None
                    if skew is None
                    else _finite_or_none(skew.get("realized_variance"))
                ),
                "intraday_returns": (
                    None
                    if skew is None
                    else _int_or_none(skew.get("intraday_returns"))
                ),
            },
        },
        "ict": {
            "contract": ict.contract,
            "available": bool(ict.available),
            "execution_ready": bool(ict.execution_ready),
            "swept_liquidity": list(ict.swept_liquidity),
            "sweep_present": bool(ict.swept_liquidity),
            "fvg_retest": bool(ict.fvg_retest),
            "order_block_retest": bool(ict.order_block_retest),
            "ote_retest": bool(ict.ote_retest),
            "premium_discount_ok": bool(ict.premium_discount_ok),
            "anti_chase_ok": bool(ict.anti_chase_ok),
            "confluence_count": int(ict.confluence_count),
            "reasons": list(ict.reasons),
        },
        "sweep_telemetry": sweep_telemetry,
        "target_credibility": {
            "contract": TARGET_FREEZE_ARTIFACT_CONTRACT,
            "forward_contract": TARGET_FORWARD_CONTRACT,
            "prospective_epoch": TARGET_PROSPECTIVE_EPOCH.isoformat(),
            "prior60_completed_d1_median_range": prior60_d1_median_range,
            "target_distance": target_distance,
            "target_to_prior60_d1_median": target_to_prior60_d1_median,
            "target_forward_group": target_forward_group,
            "changes_entry": False,
            "changes_stop": False,
            "changes_target": False,
        },
        "primary_forward_group": (
            "SWEEP"
            if bool(route_ok and family_gate_active and ict.swept_liquidity)
            else (
                "NON_SWEEP"
                if bool(route_ok and family_gate_active)
                else "V47_NOT_APPROVED"
            )
        ),
    }


def evaluate_forward_observer(
    rows: Sequence[Bar],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if len(bars) < 5_000:
        raise ValueError("V70_INSUFFICIENT_HISTORY")

    d1_context = build_secular_d1(bars)
    h1_context = build_h1_context(bars)
    structure_context = build_h1_structure_context(bars)
    volatility_context = build_h1_volatility_context(bars)
    skew_context = build_prior_day_skew_context(bars)
    d1_range_context = build_d1_range_context(bars)
    d1_lookup = _Asof(d1_context)
    h1_lookup = _Asof(h1_context)
    structure_lookup = _Asof(structure_context)
    volatility_lookup = _Asof(volatility_context)
    skew_lookup = _Asof(skew_context)
    d1_range_lookup = _Asof(d1_range_context)
    trading_dates = _trading_dates(
        bars,
        start=ensure_utc(bars[0].timestamp),
        end=ensure_utc(as_of),
    )

    annotated_by_family = _family_streams(
        bars,
        costs=FORWARD_STRESS_COSTS,
        pip_size=PIP_SIZE,
        d1_context=d1_context,
        h1_context=h1_context,
    )
    history = {
        family: _route_family_candidates(
            annotated_by_family[family],
            route=BASE_ROUTE,
        )
        for family in FAMILY_MAP
    }

    evaluations: list[dict[str, Any]] = []
    variants = _family_variant_map()
    for family, variant in variants.items():
        signals = extract_m15_breakout(bars, variant=variant)
        for signal in signals:
            if ensure_utc(signal.signal_at) < PROSPECTIVE_EPOCH:
                continue
            payload = _evaluate_signal(
                bars,
                family=family,
                signal=signal,
                d1_lookup=d1_lookup,
                h1_lookup=h1_lookup,
                structure_lookup=structure_lookup,
                volatility_lookup=volatility_lookup,
                skew_lookup=skew_lookup,
                d1_range_lookup=d1_range_lookup,
                candidate_history=history[family],
                trading_dates=trading_dates,
            )
            if payload is not None:
                evaluations.append(payload)

    evaluations.sort(
        key=lambda row: (
            str(row["signal_at"]),
            str(row["family"]),
        )
    )
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "freeze_artifact_contract": FREEZE_ARTIFACT_CONTRACT,
        "forward_contract": FORWARD_CONTRACT,
        "secondary_telemetry_contract": TELEMETRY_CONTRACT,
        "sweep_telemetry_contract": SWEEP_TELEMETRY_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "observed_at": ensure_utc(as_of).isoformat(),
        "history_bars": len(bars),
        "evaluations": evaluations,
        "counts": {
            "total_after_epoch": len(evaluations),
            "v47_approved": sum(int(row["v47_approved"]) for row in evaluations),
            "sweep": sum(int(row["primary_forward_group"] == "SWEEP") for row in evaluations),
            "non_sweep": sum(int(row["primary_forward_group"] == "NON_SWEEP") for row in evaluations),
            "target_gt_0_75": sum(
                int(row.get("target_credibility", {}).get("target_forward_group") == "TARGET_GT_0_75")
                for row in evaluations
            ),
            "target_le_0_75": sum(
                int(row.get("target_credibility", {}).get("target_forward_group") == "TARGET_LE_0_75")
                for row in evaluations
            ),
        },
    }


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V70_CTRADER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V70_REQUIRE_DEMO")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("V70_XAU_NOT_CONFIGURED")

    as_of = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_history(feed, target=HISTORY_BARS, as_of=as_of)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    result = evaluate_forward_observer(bars, as_of=as_of)
    result["history_pages"] = pages

    store = SupabaseOperationalStore.from_env()
    account = _account_label()
    if not account:
        raise SystemExit("V70_CTRADER_ACCOUNT_LABEL_REQUIRED")

    persisted = 0
    existing_keys = _existing_signal_keys(store)
    for evaluation in result["evaluations"]:
        signal = BreakoutSignal(
            variant_id=str(evaluation["variant_id"]),
            symbol=SYMBOL,
            signal_index=0,
            direction=str(evaluation["direction"]),
            signal_at=datetime.fromisoformat(str(evaluation["signal_at"])),
            atr=float(evaluation["atr_at_signal"]),
            stop=float(evaluation["stop"]),
            reward_r=float(evaluation["reward_r"]),
        )
        key = _signal_key(str(evaluation["family"]), signal)
        if key in existing_keys:
            continue
        store.record_order_event(
            backend="CTRADER",
            account_id=account,
            signal_key=key,
            broker_order_id=None,
            event_type=EVENT_TYPE,
            accepted=None,
            code=RESEARCH_VERSION,
            message="Prospective XAU V47 forward evaluation; no broker action",
            payload={
                **evaluation,
                "environment": "DEMO",
                "prospective_epoch": PROSPECTIVE_EPOCH.isoformat(),
                "execution_influence": False,
                "promotion_authority": False,
                "live_money": False,
                "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            },
        )
        existing_keys.add(key)
        persisted += 1

    result["persisted_new_events"] = persisted
    result["storage_table"] = "broker_order_events"
    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=result,
    )

    path = Path(
        os.getenv(
            "V70_EVIDENCE_OUTPUT",
            "artifacts/xau-v47-forward-observer-v70.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": result,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ) + "\n"
    )
    print(
        "V70_FORWARD_OBSERVER "
        f"bars={len(bars)} after_epoch={result['counts']['total_after_epoch']} "
        f"approved={result['counts']['v47_approved']} "
        f"sweep={result['counts']['sweep']} nonsweep={result['counts']['non_sweep']} "
        f"persisted={persisted} artifact={path} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
