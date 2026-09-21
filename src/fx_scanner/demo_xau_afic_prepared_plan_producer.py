from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from .config import load_project_config
from .demo_xau_afic_path_shadow_observer import (
    CONFIRM_WINDOW_M15,
    LOOKBACK_DAYS,
    REQUEST_COUNT,
    STOP_BUFFER_ATR,
    SYMBOL,
    _target,
    evaluate_afic_shadow,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

STRATEGY_ID="XAU_AFIC_PATH_PREPARED_V1"
EXECUTION_STRATEGY_ID="XAU_AFIC_PATH_EXECUTION_V1"
WORKER_NAME="ctrader_demo_xau_afic_prepared_plan_producer"
EVENT_TYPE="DEMO_XAU_AFIC_PREPARED_PLAN"
DATA_CONTRACT="XAU_AFIC_PREPARED_PLAN_FORWARD_V1"

MAX_ZONE_DISTANCE_ATR=0.75
MAX_H4_DIRECTIONAL_CLOSE_LOC=0.65
CONFIRMED_TTL_SECONDS=300
ARMED_TTL_HOURS=24

# Deliberately false in the committed workflow. The path is built so a future
# DEMO-only promotion can change the durable state without changing the
# forecasting/geometry logic, but research code cannot silently self-promote.
EXECUTION_ENV="CTRADER_DEMO_AFIC_EXECUTION_ENABLED"


def _bool_env(name:str,default:bool=False)->bool:
    raw=os.getenv(name)
    if raw is None:
        return bool(default)
    v=raw.strip().upper()
    if v in {"1","TRUE","YES","ON"}:
        return True
    if v in {"0","FALSE","NO","OFF"}:
        return False
    raise SystemExit(f"{name}_INVALID_BOOLEAN")


def _account_label()->str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID","").strip()
        or os.getenv("CTRADER_TRADER_LOGIN","").strip()
    )


def selector_grade(features:dict[str,Any]|None)->str:
    f=dict(features or {})
    try:
        dist=float(f.get("zone_distance_atr"))
        loc=float(f.get("h4_directional_close_location"))
    except (TypeError,ValueError):
        return "C"
    if not isfinite(dist) or not isfinite(loc):
        return "C"
    if dist<=MAX_ZONE_DISTANCE_ATR and loc<=MAX_H4_DIRECTIONAL_CLOSE_LOC:
        return "A"
    if dist<=MAX_ZONE_DISTANCE_ATR:
        return "B"
    return "C"


def _zone_stop(zone:dict[str,Any],direction:str)->float:
    low=float(zone["low"]);high=float(zone["high"]);atr=float(zone["h1_atr"])
    if direction=="LONG":
        return low-STOP_BUFFER_ATR*atr
    return high+STOP_BUFFER_ATR*atr


def _reference_entry(zone:dict[str,Any],direction:str)->float:
    # AFIC public-material reconstruction waits for rejection back through the
    # proximal edge. Use that edge only as a forecast blueprint reference.
    return float(zone["high"] if direction=="LONG" else zone["low"])


def _plan_from_entry(*,entry:float,stop:float,direction:str):
    target=_target(float(entry),float(stop),str(direction))
    if target is None:
        return None
    round_level,terminal,ladder=target
    if not ladder:
        return None
    risk=(entry-stop) if direction=="LONG" else (stop-entry)
    if risk<=0:
        return None
    rr1=((ladder[0]-entry) if direction=="LONG" else (entry-ladder[0]))/risk
    rr2=((terminal-entry) if direction=="LONG" else (entry-terminal))/risk
    return {
        "entry":float(entry),
        "stop":float(stop),
        "round_liquidity":float(round_level),
        "tp_ladder":[float(x) for x in ladder],
        "tp1":float(ladder[0]),
        "tp2":float(terminal),
        "rr1":float(rr1),
        "rr2":float(rr2),
    }


def prepared_blueprint(payload:dict[str,Any])->dict[str,Any]|None:
    direction=str(payload.get("continuation_direction") or "").upper()
    zone=dict(payload.get("zone") or {})
    if direction not in {"LONG","SHORT"} or not zone:
        return None
    stop=_zone_stop(zone,direction)
    entry=_reference_entry(zone,direction)
    plan=_plan_from_entry(entry=entry,stop=stop,direction=direction)
    if plan is None:
        return None
    return {
        **plan,
        "entry_zone":[float(zone["low"]),float(zone["high"])],
        "confirmation_required":"M15_ENGULF_REJECTION",
        "invalidation_close":float(zone["high"] if direction=="SHORT" else zone["low"]),
        "selector_grade":selector_grade(payload.get("h4_features")),
    }


def _dedupe_key(payload:dict[str,Any],kind:str)->str:
    fields=(
        STRATEGY_ID,
        kind,
        str(payload.get("map_at") or "NONE"),
        str(payload.get("continuation_direction") or "NONE"),
        str(payload.get("confirm_at") or "NONE"),
        str(dict(payload.get("zone") or {}).get("origin_at") or "NONE"),
    )
    return "|".join(fields)


def _already_recorded(store,key:str)->bool:
    try:
        response=(
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type",EVENT_TYPE)
            .eq("code",STRATEGY_ID)
            .order("observed_at",desc=True)
            .limit(120)
            .execute()
        )
    except Exception:
        # Persistence uncertainty must suppress duplicate signal creation.
        return True
    return any(
        str(dict(r.get("payload") or {}).get("dedupe_key") or "")==key
        for r in response.data or []
    )


def _record_event(store,*,key:str,kind:str,payload:dict[str,Any],plan:dict[str,Any]|None,signal_id:str|None)->None:
    account=_account_label()
    if not account:
        raise SystemExit("CTRADER_ACCOUNT_ID_REQUIRED_FOR_AFIC_PREPARED_PLAN")
    store.record_order_event(
        backend="CTRADER",
        account_id=account,
        signal_key=signal_id or f"AFIC_PREP:{hashlib.sha256(key.encode()).hexdigest()[:24]}",
        broker_order_id=None,
        event_type=EVENT_TYPE,
        accepted=None,
        code=STRATEGY_ID,
        message="AFIC forecast/order blueprint prepared; broker action disabled unless explicitly promoted",
        payload={
            "dedupe_key":key,
            "kind":kind,
            "strategy_id":STRATEGY_ID,
            "execution_strategy_id":EXECUTION_STRATEGY_ID,
            "environment":"DEMO",
            "execution_influence":False,
            "live_execution_enabled":False,
            "forecast":payload,
            "prepared_plan":plan,
            "signal_id":signal_id,
            "code_version":os.getenv("GITHUB_SHA","LOCAL"),
        },
    )


def _write_signal(
    store,
    *,
    payload:dict[str,Any],
    plan:dict[str,Any],
    observed_at:datetime,
    execution_enabled:bool,
)->str:
    direction=str(payload["continuation_direction"]).upper()
    grade=str(plan["selector_grade"])
    confirmed=bool(payload.get("confirm_at"))
    state="EXECUTION_READY" if execution_enabled and confirmed else "ARMED"
    score={"A":95.0,"B":90.0,"C":85.0}[grade]
    risk=abs(float(plan["entry"])-float(plan["stop"]))
    half_width=max(0.05,risk*0.02)
    entry=float(plan["entry"])
    expires=(
        observed_at+timedelta(seconds=CONFIRMED_TTL_SECONDS)
        if confirmed
        else observed_at+timedelta(hours=ARMED_TTL_HOURS)
    )
    run_id=store.start_scanner_run(
        mode="DEMO_ONLY",
        code_version=os.getenv("GITHUB_SHA","LOCAL"),
        data_contract_version=DATA_CONTRACT,
        started_at=observed_at,
    )
    row={
        "run_id":run_id,
        "observed_at":observed_at.isoformat(),
        "symbol":SYMBOL,
        "direction":direction,
        "setup_type":"AFIC_PATH_CONFIRMED" if confirmed else "AFIC_PATH_FORECAST",
        "state":state,
        "pair_score":score,
        "execution_score":score,
        "final_score":score,
        "entry_low":entry-half_width,
        "entry_high":entry+half_width,
        "sl":float(plan["stop"]),
        "tp1":float(plan["tp1"]),
        "tp2":float(plan["tp2"]),
        "tp3":None,
        "rr1":float(plan["rr1"]),
        "rr2":float(plan["rr2"]),
        "rr3":None,
        "macro_bias":direction,
        "h4_bias":direction,
        "h1_bias":direction,
        "active_guards":[] if state=="EXECUTION_READY" else ["AFIC_FORWARD_VALIDATION"],
        "data_coverage":1.0,
        "expires_at":expires.isoformat(),
    }
    try:
        store.write_signal_rows([row])
        persisted=store.list_signals_for_run(run_id)
        if len(persisted)!=1 or not persisted[0].get("id"):
            raise RuntimeError("AFIC_PREPARED_SIGNAL_CARDINALITY_INVALID")
        signal_id=str(persisted[0]["id"])
        store.finish_scanner_run(run_id,status="COMPLETED",finished_at=datetime.now(tz=UTC))
        return signal_id
    except Exception:
        try:
            store.finish_scanner_run(run_id,status="FAILED",finished_at=datetime.now(tz=UTC))
        except Exception:
            pass
        raise


def run()->int:
    cfg=load_project_config(None)
    policy=load_execution_policy(None)
    if str(policy.ctrader.get("environment","")).upper()!="DEMO":
        raise SystemExit("AFIC_PREPARED_PLAN_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo",False)):
        raise SystemExit("AFIC_PREPARED_PLAN_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("AFIC_PREPARED_PLAN_XAUUSD_NOT_CONFIGURED")

    # Hard fail closed in the committed workflow. Enabling the environment
    # alone is not sufficient for broker execution because the exact strategy
    # is intentionally not in the handoff allowlist yet.
    execution_enabled=_bool_env(EXECUTION_ENV,False)

    feed=build_ctrader_research_feed(policy,(SYMBOL,))
    store=SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    store.ensure_reference_symbols((cfg.pair_map[SYMBOL],))
    now=datetime.now(tz=UTC)
    raw_count=0
    payload:dict[str,Any]={}
    plan=None
    emitted=False
    signal_id=None
    kind="NONE"
    error=None
    try:
        feed.ensure_connected()
        raw=tuple(feed.historical_bars(
            SYMBOL,"M15",
            from_time=now-timedelta(days=LOOKBACK_DAYS),
            to_time=now,
            count=REQUEST_COUNT,
        ))
        raw_count=len(raw)
        payload=evaluate_afic_shadow(raw,as_of=now)
        state=str(payload.get("state") or "")

        if payload.get("zone") and payload.get("continuation_direction"):
            plan=prepared_blueprint(payload)

        confirmed=state in {"CONFIRMED_PENDING_ENTRY_BAR","CONFIRMED_SHADOW","CONFIRMED_NO_TARGET_GEOMETRY"}
        if confirmed:
            direction=str(payload["continuation_direction"]).upper()
            quote=feed.quote(SYMBOL,at=now)
            live_entry=float(quote.ask if direction=="LONG" else quote.bid)
            stop=_zone_stop(dict(payload["zone"]),direction)
            live_plan=_plan_from_entry(entry=live_entry,stop=stop,direction=direction)
            if live_plan is not None:
                plan={
                    **live_plan,
                    "entry_zone":[float(payload["zone"]["low"]),float(payload["zone"]["high"])],
                    "confirmation_required":"ALREADY_CONFIRMED",
                    "invalidation_close":float(payload["zone"]["high"] if direction=="SHORT" else payload["zone"]["low"]),
                    "selector_grade":selector_grade(payload.get("h4_features")),
                }
                kind="CONFIRMED_LIVE_BLUEPRINT"
        elif plan is not None:
            kind="FORECAST_BLUEPRINT"

        if plan is not None and kind!="NONE":
            key=_dedupe_key(payload,kind)
            if not _already_recorded(store,key):
                signal_id=_write_signal(
                    store,
                    payload=payload,
                    plan=plan,
                    observed_at=now,
                    execution_enabled=execution_enabled,
                )
                _record_event(
                    store,key=key,kind=kind,payload=payload,plan=plan,signal_id=signal_id
                )
                emitted=True

    except Exception as exc:
        error=f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy=error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "strategy_id":STRATEGY_ID,
            "execution_strategy_id":EXECUTION_STRATEGY_ID,
            "environment":"DEMO",
            "execution_influence":False,
            "execution_enabled_env":execution_enabled,
            "handoff_allowlisted":False,
            "live_execution_enabled":False,
            "raw_m15_bars":raw_count,
            "forecast_state":payload.get("state"),
            "selector_grade":None if plan is None else plan.get("selector_grade"),
            "blueprint_kind":kind,
            "signal_id":signal_id,
            "emitted":emitted,
            "error":error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_AFIC_PREPARED_PLAN "
        f"healthy={int(healthy)} forecast_state={payload.get('state','ERROR')} "
        f"blueprint={kind} grade={None if plan is None else plan.get('selector_grade')} "
        f"emitted={int(emitted)} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__=="__main__":
    raise SystemExit(run())
