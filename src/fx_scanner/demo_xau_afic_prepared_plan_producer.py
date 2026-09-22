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
STATE_EVENT_TYPE="DEMO_XAU_AFIC_FORECAST_STATE"
STATE_CODE="XAU_AFIC_PATH_STATE_V1"
DATA_CONTRACT="XAU_AFIC_PREPARED_PLAN_FORWARD_V1"

MAX_ZONE_DISTANCE_ATR=0.75
MAX_H4_DIRECTIONAL_CLOSE_LOC=0.65
CONFIRMED_TTL_SECONDS=300
ARMED_TTL_HOURS=24
NEAR_ZONE_ATR=1.0
EXECUTION_EVENT_TYPE="DEMO_SIGNAL_GEOMETRY"

# Explicit DEMO-only execution authority. The workflow must set this gate and
# the exact strategy identity must still pass the shared broker handoff.
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


def zone_proximity(*,price:float|None,zone:dict[str,Any]|None)->dict[str,Any]:
    z=dict(zone or {})
    try:
        px=float(price)
        low=float(z["low"]);high=float(z["high"]);atr=float(z["h1_atr"])
    except (TypeError,ValueError,KeyError):
        return {
            "live_price":None,
            "inside_zone":False,
            "distance_points":None,
            "distance_atr":None,
            "proximity_state":"UNKNOWN",
            "recommended_scan_seconds":300,
        }
    if not all(isfinite(x) for x in (px,low,high,atr)) or atr<=0 or low>=high:
        return {
            "live_price":None,
            "inside_zone":False,
            "distance_points":None,
            "distance_atr":None,
            "proximity_state":"UNKNOWN",
            "recommended_scan_seconds":300,
        }
    if low<=px<=high:
        dist=0.0
        state="IN_ZONE"
    elif px<low:
        dist=low-px
        state="NEAR_ZONE" if dist/atr<=NEAR_ZONE_ATR else "FAR"
    else:
        dist=px-high
        state="NEAR_ZONE" if dist/atr<=NEAR_ZONE_ATR else "FAR"
    return {
        "live_price":px,
        "inside_zone":bool(low<=px<=high),
        "distance_points":float(dist),
        "distance_atr":float(dist/atr),
        "proximity_state":state,
        "recommended_scan_seconds":60 if state in {"IN_ZONE","NEAR_ZONE"} else 300,
    }


def signal_state_and_guards(*,execution_enabled:bool,confirmed:bool,grade:str)->tuple[str,list[str]]:
    if execution_enabled and confirmed and str(grade).upper()=="A":
        return "EXECUTION_READY",[]
    guards=[]
    if str(grade).upper()!="A":
        guards.append("AFIC_SELECTOR_GRADE_A_REQUIRED")
    if not confirmed:
        guards.append("AFIC_M15_CONFIRMATION_REQUIRED")
    if not execution_enabled:
        guards.append("AFIC_DEMO_EXECUTION_DISABLED")
    return "ARMED",guards


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


def confirmation_latency_seconds(payload:dict[str,Any],*,detected_at:datetime)->float|None:
    raw=payload.get("confirm_at")
    if not raw:
        return None
    try:
        confirm_open=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    except ValueError:
        return None
    if confirm_open.tzinfo is None:
        return None
    completed_at=ensure_utc(confirm_open)+timedelta(minutes=15)
    return max(0.0,(ensure_utc(detected_at)-completed_at).total_seconds())


def entry_drift_metrics(*,prepared:dict[str,Any]|None,live:dict[str,Any]|None)->dict[str,float|None]:
    if prepared is None or live is None:
        return {
            "prepared_reference_entry":None,
            "live_entry":None,
            "entry_drift_abs":None,
            "entry_drift_r":None,
        }
    ref=float(prepared["entry"]);px=float(live["entry"]);stop=float(prepared["stop"])
    risk=abs(ref-stop)
    drift=abs(px-ref)
    return {
        "prepared_reference_entry":ref,
        "live_entry":px,
        "entry_drift_abs":drift,
        "entry_drift_r":None if risk<=0 else drift/risk,
    }


def prepared_observability(
    payload:dict[str,Any],
    *,
    prepared_reference:dict[str,Any]|None,
    final_plan:dict[str,Any]|None,
    kind:str,
    confirmed:bool,
)->dict[str,Any]:
    zone=dict(payload.get("zone") or {})
    features=dict(payload.get("h4_features") or {})
    direction=str(payload.get("continuation_direction") or "").upper()
    valid_context=direction in {"LONG","SHORT"} and bool(zone)
    grade=selector_grade(features) if valid_context and features else None

    if not valid_context:
        block_reason="NO_FORECAST_ZONE"
    elif confirmed and kind!="CONFIRMED_LIVE_BLUEPRINT":
        block_reason="CONFIRMED_LIVE_TARGET_GEOMETRY_INVALID"
    elif not confirmed and prepared_reference is None:
        block_reason="FORECAST_TARGET_GEOMETRY_INVALID"
    elif kind=="NONE":
        block_reason="NO_BLUEPRINT_KIND"
    else:
        block_reason=None

    def _float_or_none(value):
        try:
            x=float(value)
        except (TypeError,ValueError):
            return None
        return x if isfinite(x) else None

    return {
        "blueprint_block_reason":block_reason,
        "forecast_selector_grade":grade,
        "continuation_direction":direction if direction in {"LONG","SHORT"} else None,
        "map_at":payload.get("map_at"),
        "zone_low":_float_or_none(zone.get("low")),
        "zone_high":_float_or_none(zone.get("high")),
        "zone_distance_atr":_float_or_none(features.get("zone_distance_atr")),
        "h4_directional_close_location":_float_or_none(
            features.get("h4_directional_close_location")
        ),
        "prepared_reference_entry":None if prepared_reference is None else _float_or_none(
            prepared_reference.get("entry")
        ),
        "final_entry":None if final_plan is None else _float_or_none(final_plan.get("entry")),
    }


def forecast_state_key(payload:dict[str,Any])->str:
    zone=dict(payload.get("zone") or {})
    fields=(
        STATE_CODE,
        str(payload.get("map_at") or "NONE"),
        str(payload.get("state") or "NONE"),
        str(payload.get("continuation_direction") or "NONE"),
        str(payload.get("first_touch_at") or "NONE"),
        str(payload.get("confirm_at") or "NONE"),
        str(payload.get("invalidated_at") or "NONE"),
        str(zone.get("origin_at") or "NONE"),
    )
    return "|".join(fields)


def _forecast_state_recorded(store,key:str)->bool:
    try:
        response=(
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type",STATE_EVENT_TYPE)
            .eq("code",STATE_CODE)
            .order("observed_at",desc=True)
            .limit(240)
            .execute()
        )
    except Exception:
        # Evidence persistence uncertainty must not create duplicate state rows.
        return True
    return any(
        str(dict(r.get("payload") or {}).get("state_key") or "")==key
        for r in response.data or []
    )


def _record_forecast_state(store,*,payload:dict[str,Any])->bool:
    key=forecast_state_key(payload)
    if _forecast_state_recorded(store,key):
        return False
    account=_account_label()
    if not account:
        raise SystemExit("CTRADER_ACCOUNT_ID_REQUIRED_FOR_AFIC_FORECAST_STATE")
    digest=hashlib.sha256(key.encode()).hexdigest()[:24]
    store.record_order_event(
        backend="CTRADER",
        account_id=account,
        signal_key=f"AFIC_STATE:{digest}",
        broker_order_id=None,
        event_type=STATE_EVENT_TYPE,
        accepted=None,
        code=STATE_CODE,
        message="AFIC prospective forecast state transition; no broker action",
        payload={
            "state_key":key,
            "environment":"DEMO",
            "execution_influence":False,
            "promotion_authority":False,
            "live_execution_enabled":False,
            "forecast":payload,
            "code_version":os.getenv("GITHUB_SHA","LOCAL"),
        },
    )
    return True


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


def _record_event(
    store,*,key:str,kind:str,payload:dict[str,Any],plan:dict[str,Any]|None,
    signal_id:str|None,latency:float|None=None,drift:dict[str,float|None]|None=None,
)->None:
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
        message="AFIC forecast/order blueprint prepared; broker action remains gated by Grade-A confirmation and exact DEMO handoff",
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
            "confirmation_detection_lag_seconds":latency,
            "entry_drift":dict(drift or {}),
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
    state,guards=signal_state_and_guards(
        execution_enabled=execution_enabled,
        confirmed=confirmed,
        grade=grade,
    )
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
        "active_guards":guards,
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


def geometry_matches_current_forecast(
    geometry_payload:dict[str,Any],
    forecast_payload:dict[str,Any],
)->bool:
    state=str(forecast_payload.get("state") or "")
    confirmed=state in {
        "CONFIRMED_PENDING_ENTRY_BAR",
        "CONFIRMED_SHADOW",
        "CONFIRMED_NO_TARGET_GEOMETRY",
    }
    if not confirmed:
        return False
    return bool(
        str(geometry_payload.get("map_at") or "")
        == str(forecast_payload.get("map_at") or "")
        and str(geometry_payload.get("confirm_at") or "")
        == str(forecast_payload.get("confirm_at") or "")
    )


def _invalidate_stale_execution_ready(store,*,payload:dict[str,Any])->int:
    try:
        response=(
            store.client.table("broker_order_events")
            .select("signal_key,payload,event_type,code")
            .eq("event_type",EXECUTION_EVENT_TYPE)
            .eq("code",EXECUTION_STRATEGY_ID)
            .order("observed_at",desc=True)
            .limit(40)
            .execute()
        )
    except Exception:
        # If execution-identity reconciliation cannot be proven, fail closed by
        # suppressing new authority at the caller rather than guessing.
        raise
    invalidated=0
    seen=set()
    for row in response.data or []:
        signal_id=str(row.get("signal_key") or "").strip()
        if not signal_id or signal_id in seen:
            continue
        seen.add(signal_id)
        geometry=dict(row.get("payload") or {})
        if geometry_matches_current_forecast(geometry,payload):
            continue
        result=(
            store.client.table("signals")
            .update({"state":"INVALIDATED","active_guards":["AFIC_MAP_NO_LONGER_CURRENT"]})
            .eq("id",signal_id)
            .eq("state","EXECUTION_READY")
            .execute()
        )
        invalidated+=len(list(result.data or []))
    return invalidated


def _record_execution_geometry(
    store,
    *,
    signal_id:str,
    payload:dict[str,Any],
    plan:dict[str,Any],
)->None:
    account=_account_label()
    if not account:
        raise SystemExit("CTRADER_ACCOUNT_ID_REQUIRED_FOR_AFIC_EXECUTION_GEOMETRY")
    store.record_order_event(
        backend="CTRADER",
        account_id=account,
        signal_key=str(signal_id),
        broker_order_id=f"GEOMETRY:{signal_id}",
        event_type=EXECUTION_EVENT_TYPE,
        accepted=True,
        code=EXECUTION_STRATEGY_ID,
        message="user-authorized AFIC grade-A confirmed DEMO geometry persisted",
        payload={
            "signal_id":str(signal_id),
            "symbol":SYMBOL,
            "direction":str(payload["continuation_direction"]).upper(),
            "strategy_id":EXECUTION_STRATEGY_ID,
            "forecast_strategy_id":STRATEGY_ID,
            "map_at":payload.get("map_at"),
            "confirm_at":payload.get("confirm_at"),
            "selector_grade":plan.get("selector_grade"),
            "entry_mode":"MARKET_ON_CONFIRM",
            "limit_blueprint_entry":plan.get("prepared_reference_entry",plan.get("entry")),
            "planned_entry":plan.get("entry"),
            "planned_sl":plan.get("stop"),
            "planned_tp1":plan.get("tp1"),
            "planned_tp2":plan.get("tp2"),
            "rr1":plan.get("rr1"),
            "rr2":plan.get("rr2"),
            "execution_influence":True,
            "environment":"DEMO",
            "live_execution_enabled":False,
            "server_side_sl_tp_required":True,
        },
    )


def run()->int:
    cfg=load_project_config(None)
    policy=load_execution_policy(None)
    if str(policy.ctrader.get("environment","")).upper()!="DEMO":
        raise SystemExit("AFIC_PREPARED_PLAN_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo",False)):
        raise SystemExit("AFIC_PREPARED_PLAN_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("AFIC_PREPARED_PLAN_XAUUSD_NOT_CONFIGURED")

    # Environment authorization alone is insufficient: Grade A, completed M15
    # confirmation, fresh geometry, exact strategy identity, atomic claim, risk,
    # margin and server-side protection checks remain authoritative.
    execution_enabled=_bool_env(EXECUTION_ENV,False)

    feed=build_ctrader_research_feed(policy,(SYMBOL,))
    store=SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    store.ensure_reference_symbols((cfg.pair_map[SYMBOL],))
    now=datetime.now(tz=UTC)
    raw_count=0
    payload:dict[str,Any]={}
    plan=None
    prepared_reference=None
    confirmation_lag=None
    drift_metrics=entry_drift_metrics(prepared=None,live=None)
    emitted=False
    state_transition_persisted=False
    signal_id=None
    kind="NONE"
    error=None
    confirmed=False
    observability:dict[str,Any]={}
    proximity=zone_proximity(price=None,zone=None)
    live_quote_error=None
    stale_ready_invalidated=0
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
        state_transition_persisted=_record_forecast_state(store,payload=payload)
        stale_ready_invalidated=_invalidate_stale_execution_ready(
            store,payload=payload
        )

        quote=None
        if payload.get("zone"):
            try:
                quote=feed.quote(SYMBOL,at=now)
                live_mid=(float(quote.bid)+float(quote.ask))/2.0
                proximity=zone_proximity(price=live_mid,zone=dict(payload.get("zone") or {}))
            except Exception as exc:
                live_quote_error=f"{type(exc).__name__}:{exc}"

        if payload.get("zone") and payload.get("continuation_direction"):
            plan=prepared_blueprint(payload)
            prepared_reference=None if plan is None else dict(plan)

        confirmed=state in {"CONFIRMED_PENDING_ENTRY_BAR","CONFIRMED_SHADOW","CONFIRMED_NO_TARGET_GEOMETRY"}
        if confirmed:
            direction=str(payload["continuation_direction"]).upper()
            if quote is None:
                quote=feed.quote(SYMBOL,at=now)
                live_mid=(float(quote.bid)+float(quote.ask))/2.0
                proximity=zone_proximity(price=live_mid,zone=dict(payload.get("zone") or {}))
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
                confirmation_lag=confirmation_latency_seconds(payload,detected_at=now)
                drift_metrics=entry_drift_metrics(
                    prepared=prepared_reference,live=plan
                )
        elif plan is not None:
            kind="FORECAST_BLUEPRINT"

        observability=prepared_observability(
            payload,
            prepared_reference=prepared_reference,
            final_plan=plan,
            kind=kind,
            confirmed=confirmed,
        )

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
                    store,key=key,kind=kind,payload=payload,plan=plan,signal_id=signal_id,
                    latency=confirmation_lag,drift=drift_metrics,
                )
                auto_authorized=bool(
                    execution_enabled
                    and confirmed
                    and str(plan.get("selector_grade") or "").upper()=="A"
                )
                if auto_authorized:
                    _record_execution_geometry(
                        store,
                        signal_id=signal_id,
                        payload=payload,
                        plan={
                            **plan,
                            "prepared_reference_entry":None
                            if prepared_reference is None
                            else prepared_reference.get("entry"),
                        },
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
            "execution_influence":bool(execution_enabled),
            "execution_enabled_env":execution_enabled,
            "handoff_allowlisted":True,
            "live_execution_enabled":False,
            "raw_m15_bars":raw_count,
            "forecast_state":payload.get("state"),
            "selector_grade":None if plan is None else plan.get("selector_grade"),
            "forecast_selector_grade":observability.get("forecast_selector_grade"),
            "blueprint_kind":kind,
            "blueprint_block_reason":observability.get("blueprint_block_reason"),
            "map_at":observability.get("map_at"),
            "continuation_direction":observability.get("continuation_direction"),
            "zone_low":observability.get("zone_low"),
            "zone_high":observability.get("zone_high"),
            "zone_distance_atr":observability.get("zone_distance_atr"),
            "h4_directional_close_location":observability.get("h4_directional_close_location"),
            "prepared_reference_entry":observability.get("prepared_reference_entry"),
            "final_entry":observability.get("final_entry"),
            "live_price":proximity.get("live_price"),
            "inside_zone":proximity.get("inside_zone"),
            "distance_to_zone_points":proximity.get("distance_points"),
            "distance_to_zone_atr":proximity.get("distance_atr"),
            "proximity_state":proximity.get("proximity_state"),
            "recommended_scan_seconds":proximity.get("recommended_scan_seconds"),
            "effective_scan_seconds":60,
            "live_quote_error":live_quote_error,
            "stale_ready_invalidated":stale_ready_invalidated,
            "signal_id":signal_id,
            "confirmation_detection_lag_seconds":confirmation_lag,
            "entry_drift_r":drift_metrics.get("entry_drift_r"),
            "emitted":emitted,
            "state_transition_persisted":state_transition_persisted,
            "error":error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_AFIC_PREPARED_PLAN "
        f"healthy={int(healthy)} forecast_state={payload.get('state','ERROR')} "
        f"blueprint={kind} grade={None if plan is None else plan.get('selector_grade')} "
        f"forecast_grade={observability.get('forecast_selector_grade')} "
        f"block={observability.get('blueprint_block_reason')} "
        f"confirm_lag_s={confirmation_lag} drift_r={drift_metrics.get('entry_drift_r')} "
        f"emitted={int(emitted)} state_persisted={int(state_transition_persisted)} "
        f"execution_authority=0"
    )
    return 0 if healthy else 2


if __name__=="__main__":
    raise SystemExit(run())
