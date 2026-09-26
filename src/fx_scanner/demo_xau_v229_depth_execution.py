from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from .config import load_project_config
from .demo_xau_v226_rizan_depth_map import (
    ATLAS_WORKER,
    WORKER_NAME as V226_WORKER,
)
from .execution.factory import build_ctrader_research_feed
from .demo_xau_v229_ladder_plan import build_parent_ladder_plan
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
STRATEGY_ID = "XAU_RIZAN_DEPTH_EXECUTION_V1"
WORKER_NAME = "ctrader_demo_xau_v229_depth_execution"
EVENT_TYPE = "DEMO_SIGNAL_GEOMETRY"
DATA_CONTRACT = "XAU_RIZAN_DEPTH_EXECUTION_V229_1"
EXECUTION_ENV = "CTRADER_DEMO_DEPTH_EXECUTION_ENABLED"

SIGNAL_TTL_SECONDS = 16 * 60 * 60
MAX_V226_AGE_SECONDS = 600
H4_STOP_BUFFER_ATR = 0.15
MIN_PLAN_RR = 1.0
SCORE = 93.0


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = raw.strip().upper()
    if value in {"1", "TRUE", "YES", "ON"}:
        return True
    if value in {"0", "FALSE", "NO", "OFF"}:
        return False
    raise SystemExit(f"{name}_INVALID_BOOLEAN")


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _latest_heartbeat(
    store: SupabaseOperationalStore,
    worker_name: str,
) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


def _path_target(
    atlas_evaluation: dict[str, Any],
    *,
    direction: str,
    entry: float,
) -> tuple[float | None, str | None]:
    path_map = dict(atlas_evaluation.get("path_map") or {})
    path = dict(
        path_map.get("demand_to_supply" if direction == "LONG" else "supply_to_demand")
        or {}
    )

    candidates: list[tuple[float, str]] = []
    reaction = dict(path.get("reaction_target") or {})
    reaction_price = _f(reaction.get("price"))
    if reaction_price is not None:
        candidates.append((reaction_price, "ATLAS_REACTION_TARGET"))

    terminal = dict(path.get("terminal_target_zone") or {})
    if direction == "LONG":
        terminal_price = _f(terminal.get("low"))
    else:
        terminal_price = _f(terminal.get("high"))
    if terminal_price is not None:
        candidates.append((terminal_price, "ATLAS_TERMINAL_OPPOSING_ZONE"))

    favorable = [
        (price, source)
        for price, source in candidates
        if (price > entry if direction == "LONG" else price < entry)
    ]
    if not favorable:
        return None, None

    # Prefer the path engine reaction target. If it cannot provide the minimum
    # DEMO RR, the caller may use the terminal opposing-zone proximal boundary.
    return favorable[0]


def build_execution_plan(
    *,
    v226_evaluation: dict[str, Any],
    atlas_evaluation: dict[str, Any],
    live_price: float,
    min_rr: float = MIN_PLAN_RR,
) -> dict[str, Any] | None:
    """Build the DEMO-only four-child parent plan before first touch.

    V226 owns entry geometry. V229 maps four 0.01-lot child slots and structural
    M15/H1/H4 targets. Slots 1-2 may become pre-touch LIMIT orders; slots 3-4
    stay reserved for M5 reclaim/MSS and displacement/retest evidence.
    """
    _ = min_rr  # terminal RR is enforced by the structural target planner at 1.5R.
    return build_parent_ladder_plan(
        v226_evaluation=v226_evaluation,
        atlas_evaluation=atlas_evaluation,
        live_price=live_price,
    )

def _candidate_key(plan: dict[str, Any]) -> str:
    return str(plan.get("candidate_key") or "")


def _already_recorded(
    store: SupabaseOperationalStore,
    key: str,
    *,
    now: datetime,
) -> bool:
    """Suppress duplicate active/claimed authority, but permit an expired retry."""
    try:
        response = (
            store.client.table("broker_order_events")
            .select("signal_key,payload,event_type,code")
            .eq("event_type", EVENT_TYPE)
            .eq("code", STRATEGY_ID)
            .order("observed_at", desc=True)
            .limit(80)
            .execute()
        )
    except Exception:
        # Persistence uncertainty must suppress duplicate broker authority.
        return True

    for row in response.data or []:
        payload = dict(row.get("payload") or {})
        if str(payload.get("candidate_key") or "") != key:
            continue
        signal_id = str(row.get("signal_key") or "").strip()
        if not signal_id:
            return True
        try:
            state_response = (
                store.client.table("signals")
                .select("state,expires_at")
                .eq("id", signal_id)
                .limit(1)
                .execute()
            )
            signal_rows = list(state_response.data or [])
        except Exception:
            return True
        if not signal_rows:
            return True
        signal = dict(signal_rows[0])
        state = str(signal.get("state") or "").upper()
        if state == "COOLDOWN":
            return True
        if state == "EXECUTION_READY":
            expires_at = _dt(signal.get("expires_at"))
            if expires_at is None or now <= expires_at:
                return True
            # An unclaimed expired signal should not permanently suppress a
            # still-valid physical first-touch candidate on the next cycle.
            continue
    return False


def _invalidate_prior_ready(
    store: SupabaseOperationalStore,
    *,
    current_key: str,
) -> int:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key,payload,event_type,code")
        .eq("event_type", EVENT_TYPE)
        .eq("code", STRATEGY_ID)
        .order("observed_at", desc=True)
        .limit(80)
        .execute()
    )
    invalidated = 0
    seen: set[str] = set()
    for row in response.data or []:
        signal_id = str(row.get("signal_key") or "").strip()
        if not signal_id or signal_id in seen:
            continue
        seen.add(signal_id)
        payload = dict(row.get("payload") or {})
        if str(payload.get("candidate_key") or "") == current_key:
            continue
        result = (
            store.client.table("signals")
            .update(
                {
                    "state": "INVALIDATED",
                    "active_guards": ["RIZAN_DEPTH_CANDIDATE_SUPERSEDED"],
                }
            )
            .eq("id", signal_id)
            .eq("state", "EXECUTION_READY")
            .execute()
        )
        invalidated += len(list(result.data or []))
    return invalidated


def _write_signal(
    store: SupabaseOperationalStore,
    *,
    plan: dict[str, Any],
    observed_at: datetime,
) -> str:
    run_id = store.start_scanner_run(
        mode="DEMO_ONLY",
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        data_contract_version=DATA_CONTRACT,
        started_at=observed_at,
    )
    row = {
        "run_id": run_id,
        "observed_at": observed_at.isoformat(),
        "symbol": SYMBOL,
        "direction": plan["direction"],
        "setup_type": "RIZAN_DEPTH_FIRST_TOUCH",
        "state": "EXECUTION_READY",
        "pair_score": SCORE,
        "execution_score": SCORE,
        "final_score": SCORE,
        "entry_low": float(plan["entry_low"]),
        "entry_high": float(plan["entry_high"]),
        "sl": float(plan["sl"]),
        "tp1": float(plan["tp1"]),
        "tp2": float(plan["tp2"]),
        "tp3": float(plan["tp2"]),
        "rr1": float(plan["rr1"]),
        "rr2": float(plan["rr2"]),
        "rr3": float(plan["rr2"]),
        "macro_bias": plan["direction"],
        "h4_bias": plan["direction"],
        "h1_bias": plan["direction"],
        "active_guards": [],
        "data_coverage": 1.0,
        "expires_at": (
            observed_at + timedelta(seconds=SIGNAL_TTL_SECONDS)
        ).isoformat(),
    }
    try:
        store.write_signal_rows([row])
        persisted = store.list_signals_for_run(run_id)
        if len(persisted) != 1 or not persisted[0].get("id"):
            raise RuntimeError("RIZAN_DEPTH_SIGNAL_CARDINALITY_INVALID")
        signal_id = str(persisted[0]["id"])
        store.finish_scanner_run(
            run_id,
            status="COMPLETED",
            finished_at=datetime.now(tz=UTC),
        )
        return signal_id
    except Exception:
        try:
            store.finish_scanner_run(
                run_id,
                status="FAILED",
                finished_at=datetime.now(tz=UTC),
            )
        except Exception:
            pass
        raise


def _record_execution_geometry(
    store: SupabaseOperationalStore,
    *,
    signal_id: str,
    candidate_key: str,
    plan: dict[str, Any],
) -> None:
    account = _account_label()
    if not account:
        raise SystemExit("CTRADER_ACCOUNT_ID_REQUIRED_FOR_RIZAN_DEPTH_EXECUTION")
    store.record_order_event(
        backend="CTRADER",
        account_id=account,
        signal_key=signal_id,
        broker_order_id=f"GEOMETRY:{signal_id}",
        event_type=EVENT_TYPE,
        accepted=True,
        code=STRATEGY_ID,
        message="user-authorized fresh V226 depth candidate promoted to cTrader DEMO execution",
        payload={
            "signal_id": signal_id,
            "candidate_key": candidate_key,
            "symbol": SYMBOL,
            "direction": plan["direction"],
            "strategy_id": STRATEGY_ID,
            "entry_mode": "FOUR_CHILD_2_PRETOUCH_2_M5_CONFIRMATION",
            "candidate_low": plan["entry_low"],
            "candidate_high": plan["entry_high"],
            "planned_entry": plan["entry"],
            "planned_sl": plan["sl"],
            "planned_tp1": plan["tp1"],
            "planned_tp2": plan["tp2"],
            "rr1": plan["rr1"],
            "rr2": plan["rr2"],
            "source_layer": plan["source_layer"],
            "target_source": "STRUCTURAL_M15_H1_H4",
            "h4_zone_id": plan["h4_zone_id"],
            "plan_id": plan.get("plan_id"),
            "children": list(plan.get("children") or []),
            "max_children": plan.get("max_children"),
            "child_lot": plan.get("child_lot"),
            "max_total_lot": plan.get("max_total_lot"),
            "generic_market_handoff_allowed": False,
            "execution_influence": True,
            "execution_authority": True,
            "environment": "DEMO",
            "live_execution_enabled": False,
            "server_side_sl_tp_required": True,
            "microstructure_confirmation_required": "SLOTS_3_4_ONLY",
        },
    )


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("RIZAN_DEPTH_EXECUTION_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("RIZAN_DEPTH_EXECUTION_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("RIZAN_DEPTH_EXECUTION_XAUUSD_NOT_CONFIGURED")

    execution_enabled = _bool_env(EXECUTION_ENV, False)
    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    store.ensure_reference_symbols((cfg.pair_map[SYMBOL],))
    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))

    signal_id: str | None = None
    candidate_key: str | None = None
    plan: dict[str, Any] | None = None
    reason = "NO_READY_CANDIDATE"
    error: str | None = None
    prior_invalidated = 0

    try:
        if not execution_enabled:
            reason = "RIZAN_DEPTH_DEMO_EXECUTION_DISABLED"
        else:
            v226_hb = _latest_heartbeat(store, V226_WORKER)
            atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
            if not bool(v226_hb.get("healthy")):
                raise RuntimeError("RIZAN_DEPTH_V226_UNHEALTHY")
            if not bool(atlas_hb.get("healthy")):
                raise RuntimeError("RIZAN_DEPTH_ATLAS_UNHEALTHY")

            v226_at = _dt(v226_hb.get("observed_at"))
            if v226_at is None or (now - v226_at).total_seconds() > MAX_V226_AGE_SECONDS:
                raise RuntimeError("RIZAN_DEPTH_V226_STALE")

            v226_eval = dict(dict(v226_hb.get("details") or {}).get("evaluation") or {})
            atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})

            feed.ensure_connected()
            quote = feed.quote(SYMBOL, at=now)
            direction = str(v226_eval.get("focus_direction") or "").upper()
            if direction == "LONG":
                live_price = float(quote.ask)
            elif direction == "SHORT":
                live_price = float(quote.bid)
            else:
                live_price = (float(quote.bid) + float(quote.ask)) / 2.0

            plan = build_execution_plan(
                v226_evaluation=v226_eval,
                atlas_evaluation=atlas_eval,
                live_price=live_price,
                min_rr=MIN_PLAN_RR,
            )
            if plan is None:
                reason = "WAIT_FRESH_DEPTH_CANDIDATE_OR_STRUCTURAL_TARGET"
            else:
                candidate_key = _candidate_key(plan)
                prior_invalidated = _invalidate_prior_ready(
                    store,
                    current_key=candidate_key,
                )
                if _already_recorded(store, candidate_key, now=now):
                    reason = "CANDIDATE_ALREADY_EMITTED"
                else:
                    signal_id = _write_signal(
                        store,
                        plan=plan,
                        observed_at=now,
                    )
                    _record_execution_geometry(
                        store,
                        signal_id=signal_id,
                        candidate_key=candidate_key,
                        plan=plan,
                    )
                    reason = "EXECUTION_READY_EMITTED"
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": DATA_CONTRACT,
            "environment": "DEMO",
            "strategy_id": STRATEGY_ID,
            "execution_enabled": execution_enabled,
            "execution_authority": True,
            "live_execution_enabled": False,
            "microstructure_confirmation_required": "SLOTS_3_4_ONLY",
            "reason": reason,
            "signal_id": signal_id,
            "candidate_key": candidate_key,
            "plan": plan or {},
            "prior_ready_invalidated": prior_invalidated,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "observed_at": now.isoformat(),
        },
    )
    print(
        "CTRADER_DEMO_XAU_RIZAN_DEPTH_EXECUTION "
        f"healthy={int(healthy)} reason={reason} "
        f"signal_id={signal_id or 'NONE'} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
