from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import load_project_config
from .demo_xau_m15_ict_layer import evaluate_ict_execution_context
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
HISTORY_BARS = 60_000
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


def _already_recorded(store: Any, signal_key: str) -> bool:
    response = (
        store.client.table("broker_order_events")
        .select("id")
        .eq("signal_key", signal_key)
        .eq("event_type", EVENT_TYPE)
        .limit(1)
        .execute()
    )
    return bool(response.data or [])


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
    ict = evaluate_ict_execution_context(
        context_rows,
        direction=str(signal.direction).upper(),
        atr_value=float(signal.atr),
        as_of=signal_at.replace(tzinfo=UTC) + __import__("datetime").timedelta(minutes=15),
    )

    target = (
        entry_price + float(signal.reward_r) * risk_price
        if str(signal.direction).upper() == "LONG"
        else entry_price - float(signal.reward_r) * risk_price
    )

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
    d1_lookup = _Asof(d1_context)
    h1_lookup = _Asof(h1_context)
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
        if _already_recorded(store, key):
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
