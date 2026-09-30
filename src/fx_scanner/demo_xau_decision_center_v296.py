from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage.supabase_operational import SupabaseOperationalStore
from .xau_decision_meta_v296 import calibrate_outcomes, build_meta_decision


WORKER_NAME = "ctrader_demo_xau_decision_center_v296"
EVENT_TYPE = "DEMO_XAU_META_DECISION"
EVENT_CODE = "XAU_META_DECISION_V296_1"
SYMBOL = "XAUUSD"
MAX_HEARTBEAT_AGE_SECONDS = 900.0
V284_PRECISION_REPORT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "xau-entry-tp-precision-v284-walk-forward.json"
)

ENGINE_SPECS = {
    "RIZAN_DEPTH": {
        "worker": "ctrader_demo_xau_v229_depth_execution",
        "base_weight": 1.20,
        "outcome_prefixes": ("RIZAN_DEPTH_",),
        "role": "PRIMARY_EXECUTION_GEOMETRY",
    },
    "V182_STRUCTURE": {
        "worker": "ctrader_demo_xau_supply_demand_atlas_v182",
        "base_weight": 0.60,
        "outcome_prefixes": ("XAU_SUPPLY_DEMAND_PROSPECTIVE_V184",),
        "role": "STRUCTURAL_PATH",
    },
    "M15_SMC_RECLAIM": {
        "worker": "ctrader_demo_xau_m15_ema_smc_reclaim_candidate_producer",
        "base_weight": 0.70,
        "outcome_prefixes": ("XAU_M15_EMA_SMC_RECLAIM_V1",),
        "role": "TACTICAL_TECHNICAL",
    },
    "M15_REVERSAL": {
        "worker": "ctrader_demo_xau_m15_ema_reversal_candidate_producer",
        "base_weight": 0.55,
        "outcome_prefixes": ("XAU_M15_EMA_REVERSAL_RECOVERY_V1",),
        "role": "TACTICAL_REVERSAL",
    },
    "M15_SWEEP_FADE": {
        "worker": "ctrader_demo_xau_m15_liquidity_sweep_fade_candidate_producer",
        "base_weight": 0.55,
        "outcome_prefixes": ("XAU_M15_LIQUIDITY_SWEEP_FADE_V1",),
        "role": "LIQUIDITY_REVERSAL",
    },
    "V24_CHAMPION": {
        "worker": "ctrader_demo_xau_v24_champion_candidate_producer",
        "base_weight": 0.45,
        "outcome_prefixes": ("XAU_V24_CHAMPION_DEMO_V1",),
        "role": "LEGACY_CHAMPION",
    },
    "D1_TSMOM": {
        "worker": "ctrader_demo_xau_d1_forward_evidence",
        "base_weight": 0.35,
        "outcome_prefixes": ("D1_TSMOM_60_200",),
        "role": "MACRO_TREND",
    },
    "D1_EXPANSION": {
        "worker": "ctrader_demo_xau_expansion_v42_candidate_producer",
        "base_weight": 0.35,
        "outcome_prefixes": ("D1_EXPANSION_S2R2T2H0_V42",),
        "role": "MACRO_EXPANSION",
    },
    "V171_MACRO_PRIOR": {
        "worker": "ctrader_xau_forecast_ensemble_v171",
        "base_weight": 0.30,
        "outcome_prefixes": (),
        "role": "MACRO_CONDITIONAL_PRIOR",
    },
}

SUPPORT_WORKERS = (
    "ctrader_demo_xau_v226_rizan_depth_map",
    "ctrader_demo_xau_v229_child_executor",
    "ctrader_demo_xau_event_risk_v192",
    "ctrader_demo_xau_dom_v191",
)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _latest_heartbeats(store: SupabaseOperationalStore) -> dict[str, dict[str, Any]]:
    names = [spec["worker"] for spec in ENGINE_SPECS.values()] + list(SUPPORT_WORKERS)
    response = (
        store.client.table("runtime_heartbeats")
        .select("worker_name,observed_at,healthy,details")
        .in_("worker_name", names)
        .order("observed_at", desc=True)
        .limit(max(64, len(names) * 4))
        .execute()
    )
    latest: dict[str, dict[str, Any]] = {}
    for raw in response.data or []:
        row = dict(raw or {})
        name = str(row.get("worker_name") or "")
        if name and name not in latest:
            latest[name] = row
    return latest


def _recent_signals(store: SupabaseOperationalStore) -> list[dict[str, Any]]:
    response = (
        store.client.table("signals")
        .select(
            "id,observed_at,state,direction,setup_type,final_score,"
            "entry_low,entry_high,sl,tp1,tp2,rr1,rr2,active_guards,expires_at"
        )
        .eq("symbol", SYMBOL)
        .order("observed_at", desc=True)
        .limit(120)
        .execute()
    )
    return [dict(row or {}) for row in (response.data or [])]


def _outcome_rows(store: SupabaseOperationalStore) -> list[dict[str, Any]]:
    response = (
        store.client.table("xau_outcome_ledger")
        .select(
            "strategy_id,outcome_class,tp1_hit,stop_hit,mfe_r,mae_r,observed_at,outcome_at,"
            "order_accepted_at,protection_verified_at,missed_execution"
        )
        .order("observed_at", desc=True)
        .limit(800)
        .execute()
    )
    return [dict(row or {}) for row in (response.data or [])]


def _calibration_by_engine(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for engine, spec in ENGINE_SPECS.items():
        prefixes = tuple(str(x) for x in spec.get("outcome_prefixes") or ())
        selected = [
            row
            for row in rows
            if prefixes
            and any(
                str(row.get("strategy_id") or "").startswith(prefix)
                for prefix in prefixes
            )
            and row.get("outcome_class")
        ]
        geometry_cal = calibrate_outcomes(selected)
        executed = [
            row
            for row in selected
            if row.get("order_accepted_at")
            and not bool(row.get("missed_execution"))
        ]
        executed_cal = calibrate_outcomes(executed)
        chosen = dict(
            executed_cal
            if int(executed_cal.get("decisive") or 0) >= 5
            else geometry_cal
        )
        chosen["basis"] = (
            "EXECUTED_DEMO"
            if int(executed_cal.get("decisive") or 0) >= 5
            else "GEOMETRY_PRIOR"
        )
        chosen["executed_decisive"] = int(executed_cal.get("decisive") or 0)
        chosen["geometry_decisive"] = int(geometry_cal.get("decisive") or 0)
        output[engine] = chosen
    return output


def _meta_research_calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if str(row.get("strategy_id") or "") == "RIZAN_META_RESEARCH_V297"
        and row.get("outcome_class")
    ]
    executed = [
        row
        for row in selected
        if row.get("order_accepted_at")
        and not bool(row.get("missed_execution"))
    ]
    return {
        "all_geometry": calibrate_outcomes(selected),
        "executed_demo": calibrate_outcomes(executed),
        "basis": "EXECUTED_DEMO_TRUTH",
        "promotion_authority": False,
    }


def _v171_direction(details: dict[str, Any]) -> str | None:
    ensemble = dict(details.get("ensemble") or {})
    components = dict(ensemble.get("components") or {})
    score = 0.0
    weight = 0.0
    for name, base in (("conditional", 0.50), ("cot", 0.30), ("acd", 0.20)):
        row = dict(components.get(name) or {})
        if not bool(row.get("available")):
            continue
        direction = str(row.get("direction") or "").upper()
        raw_score = row.get("direction_score")
        try:
            directional = float(raw_score)
        except (TypeError, ValueError):
            directional = 1.0 if direction == "LONG" else -1.0 if direction == "SHORT" else 0.0
        score += base * directional
        weight += base
    if weight <= 0:
        return None
    normalized = score / weight
    if normalized >= 0.10:
        return "LONG"
    if normalized <= -0.10:
        return "SHORT"
    return None


def _engine_direction(engine: str, hb: dict[str, Any]) -> tuple[str | None, str]:
    details = dict(hb.get("details") or {})
    if engine == "RIZAN_DEPTH":
        plan = dict(details.get("plan") or {})
        direction = str(plan.get("direction") or "").upper()
        return (direction if direction in {"LONG", "SHORT"} else None, str(details.get("reason") or ""))
    if engine == "V182_STRUCTURE":
        evaluation = dict(details.get("evaluation") or {})
        active_path = dict(dict(evaluation.get("path_map") or {}).get("active_path") or {})
        direction = str(active_path.get("reaction_direction") or "").upper()
        return (direction if direction in {"LONG", "SHORT"} else None, str(evaluation.get("state") or ""))
    if engine == "D1_TSMOM":
        evaluation = dict(details.get("evaluation") or {})
        if not bool(evaluation.get("active")):
            return None, str(evaluation.get("reason") or "INACTIVE")
        direction = str(evaluation.get("direction") or "").upper()
        return (direction if direction in {"LONG", "SHORT"} else None, str(evaluation.get("reason") or ""))
    if engine == "V171_MACRO_PRIOR":
        return _v171_direction(details), "SHADOW_MACRO_PRIOR"

    reason = str(details.get("signal_reason") or "")
    direction = str(details.get("signal_direction") or "").upper()
    execution_ready = int(details.get("execution_ready") or 0)
    no_trade = (
        not direction
        or direction not in {"LONG", "SHORT"}
        or "NOT_MET" in reason
        or "MODEL_NO_TRADE" in reason
        or "CONTRACT_NOT_MET" in reason
    )
    if no_trade:
        return None, reason or "NO_ACTIVE_SIGNAL"
    if execution_ready <= 0 and engine in {"M15_REVERSAL", "M15_SWEEP_FADE", "D1_EXPANSION"}:
        return None, reason or "NOT_EXECUTION_READY"
    return direction, reason


def _engine_for_signal(row: dict[str, Any]) -> str:
    setup = str(row.get("setup_type") or "").upper()
    if setup.startswith("RIZAN_DEPTH_"):
        return "RIZAN_DEPTH"
    if "LIQUIDITY_SWEEP" in setup:
        return "M15_SWEEP_FADE"
    if "EMA_SMC" in setup or "SMC_RECLAIM" in setup:
        return "M15_SMC_RECLAIM"
    if "EMA_REVERSAL" in setup or "REVERSAL_RECOVERY" in setup:
        return "M15_REVERSAL"
    if "EXPANSION" in setup:
        return "D1_EXPANSION"
    if "TSMOM" in setup:
        return "D1_TSMOM"
    if "V24" in setup or "CHAMPION" in setup:
        return "V24_CHAMPION"
    return "OTHER"


def _geometry_candidates(
    signals: list[dict[str, Any]],
    calibrations: dict[str, dict[str, Any]],
    child_hb: dict[str, Any] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    child_details = {} if child_hb is None else dict(child_hb.get("details") or {})
    pressure = dict(child_details.get("pressure_transition") or {})
    reversal = dict(child_details.get("reversal_stage") or {})
    hazard = dict(child_details.get("dynamic_depth_hazard") or {})
    aligned_parent_signal_ids = {
        str(value)
        for value in list(child_details.get("aligned_parent_signal_ids") or [])
        if str(value)
    }
    research_probe_ok = bool(
        not bool(pressure.get("hard_block"))
        and bool(pressure.get("calibration_entry_allowed"))
        and not bool(reversal.get("hard_execution_block"))
        and not bool(reversal.get("setup_invalid"))
        and bool(reversal.get("terminal_rr_ok", True))
        and str(hazard.get("action") or "") in {"ENTRY_WINDOW", "WAIT_DEEPER", "WAIT_DEEPER_HAZARD"}
        and float(hazard.get("current_depth") or 0.0) <= 0.85 + 1e-9
    )

    output: list[dict[str, Any]] = []
    for row in signals:
        expires = _parse_dt(row.get("expires_at"))
        if expires is not None and expires < now:
            continue
        state = str(row.get("state") or "").upper()
        if state in {"INVALIDATED", "EXPIRED"}:
            continue
        direction = str(row.get("direction") or "").upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        if any(row.get(key) is None for key in ("entry_low", "entry_high", "sl", "tp1")):
            continue
        engine = _engine_for_signal(row)
        signal_id = str(row.get("id") or "")
        aligned_parent = bool(
            engine == "RIZAN_DEPTH"
            and signal_id
            and signal_id in aligned_parent_signal_ids
        )
        output.append(
            {
                "engine": engine,
                "signal_id": signal_id,
                "direction": direction,
                "state": state,
                "score": row.get("final_score"),
                "entry_low": row.get("entry_low"),
                "entry_high": row.get("entry_high"),
                "sl": row.get("sl"),
                "tp1": row.get("tp1"),
                "tp2": row.get("tp2"),
                "rr1": row.get("rr1"),
                "rr2": row.get("rr2"),
                "active_guards": list(row.get("active_guards") or []),
                "geometry_authority": engine == "RIZAN_DEPTH",
                "aligned_parent": aligned_parent,
                "research_probe_eligible": bool(
                    engine == "RIZAN_DEPTH"
                    and aligned_parent
                    and research_probe_ok
                    and state in {"ARMED", "EXECUTION_READY"}
                ),
                "calibration": calibrations.get(engine, {}),
                "observed_at": row.get("observed_at"),
            }
        )
    return output


def _gates(latest: dict[str, dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    child = dict(latest.get("ctrader_demo_xau_v229_child_executor") or {})
    child_details = dict(child.get("details") or {})
    pressure = dict(child_details.get("pressure_transition") or {})
    reversal = dict(child_details.get("reversal_stage") or {})
    hazard = dict(child_details.get("dynamic_depth_hazard") or {})
    event = dict(latest.get("ctrader_demo_xau_event_risk_v192") or {})
    event_risk = dict(dict(event.get("details") or {}).get("risk") or {})

    gates = [
        {
            "name": "V280_REVERSAL_STAGE",
            "hard_block": bool(reversal.get("hard_execution_block")),
            "warning": str(reversal.get("stage") or "") in {"REVERSAL_WATCH", "REACTION_VISIBLE"},
            "state": str(reversal.get("stage") or "UNAVAILABLE"),
            "reason": ",".join(str(x) for x in (reversal.get("reasons") or [])),
        },
        {
            "name": "PRESSURE_TRANSITION",
            "hard_block": bool(pressure.get("hard_block")),
            "warning": not bool(pressure.get("fresh", False)),
            "state": str(pressure.get("state") or "UNAVAILABLE"),
            "reason": str(pressure.get("reason") or ""),
        },
        {
            "name": "DYNAMIC_DEPTH",
            "hard_block": str(hazard.get("action") or "") in {"NO_CHASE", "INVALIDATE", "BLOCK"},
            "warning": str(hazard.get("action") or "") not in {"ENTRY_WINDOW"},
            "state": str(hazard.get("action") or "UNAVAILABLE"),
            "reason": str(hazard.get("location_state") or ""),
        },
        {
            "name": "EVENT_RISK",
            "hard_block": False,
            "warning": str(event_risk.get("state") or "").upper() not in {"CLEAR", ""},
            "state": str(event_risk.get("state") or "UNAVAILABLE"),
            "reason": str(event_risk.get("action") or ""),
        },
    ]
    return gates


def _v284_precision_evidence(
    report_path: Path = V284_PRECISION_REPORT_PATH,
) -> dict[str, Any]:
    """Expose V284 only as historical precision calibration, never as a vote."""
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "engine": "V284_ENTRY_TP_PRECISION",
            "role": "NON_VOTING_HISTORICAL_PRECISION_CALIBRATION",
            "decision": "CONTEXT",
            "state": "REPORT_UNAVAILABLE",
            "detail": f"{type(exc).__name__}",
            "execution_authority": False,
            "execution_influence": False,
        }

    folds = {
        int(row.get("test_year")): dict(row)
        for row in list(payload.get("folds") or [])
        if row.get("test_year") is not None
    }
    y2025 = folds.get(2025, {})
    y2026 = folds.get(2026, {})
    authority = bool(payload.get("execution_authority"))
    influence = bool(payload.get("execution_influence"))
    blocked = bool(
        not authority
        and not influence
        and not bool(y2025.get("eligible"))
        and not bool(y2026.get("eligible"))
    )
    state = "BLOCKED_RESEARCH_ONLY" if blocked else "REVIEW_REQUIRED"
    detail = (
        f"plans={int(payload.get('plans') or 0)}; "
        f"censored={int(payload.get('censored_plans') or 0)}; "
        f"2025={str(y2025.get('reason') or 'UNKNOWN')}; "
        f"2026={str(y2026.get('reason') or 'UNKNOWN')}; "
        f"fill_proxy={str(payload.get('fill_proxy') or 'UNKNOWN')}"
    )
    return {
        "engine": "V284_ENTRY_TP_PRECISION",
        "role": "NON_VOTING_HISTORICAL_PRECISION_CALIBRATION",
        "decision": "CONTEXT",
        "state": state,
        "detail": detail,
        "execution_authority": False,
        "execution_influence": False,
        "research_version": str(payload.get("research_version") or "V284"),
    }


def _support_evidence(latest: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    v226 = dict(latest.get("ctrader_demo_xau_v226_rizan_depth_map") or {})
    v226_eval = dict(dict(v226.get("details") or {}).get("evaluation") or {})
    candidate = dict(v226_eval.get("depth_entry_candidate") or {})
    child = dict(latest.get("ctrader_demo_xau_v229_child_executor") or {})
    child_details = dict(child.get("details") or {})
    pressure = dict(child_details.get("pressure_transition") or {})
    reversal = dict(child_details.get("reversal_stage") or {})
    hazard = dict(child_details.get("dynamic_depth_hazard") or {})
    dom = dict(latest.get("ctrader_demo_xau_dom_v191") or {})
    dom_analysis = dict(dict(dom.get("details") or {}).get("analysis") or {})
    event = dict(latest.get("ctrader_demo_xau_event_risk_v192") or {})
    event_risk = dict(dict(event.get("details") or {}).get("risk") or {})

    return [
        {
            "engine": "V226_DEPTH_MAP",
            "role": "NON_VOTING_GEOMETRY_CONTEXT",
            "decision": str(v226_eval.get("focus_direction") or "WAIT").upper(),
            "state": str(candidate.get("display_status") or v226_eval.get("state") or "UNAVAILABLE"),
            "detail": (
                f"depth={candidate.get('entry_reference')}"
                if candidate
                else "NO_DEPTH_CANDIDATE"
            ),
        },
        {
            "engine": "V280_REVERSAL_STAGE",
            "role": "NON_VOTING_EXECUTION_GATE",
            "decision": str(reversal.get("direction") or "WAIT").upper(),
            "state": str(reversal.get("stage") or "UNAVAILABLE"),
            "detail": ",".join(str(x) for x in (reversal.get("reasons") or [])),
        },
        {
            "engine": "V251_DYNAMIC_DEPTH",
            "role": "NON_VOTING_EXECUTION_GATE",
            "decision": str(hazard.get("direction") or "WAIT").upper(),
            "state": str(hazard.get("action") or "UNAVAILABLE"),
            "detail": f"depth={hazard.get('current_depth')}",
        },
        {
            "engine": "V191_DOM_PRESSURE",
            "role": "NON_VOTING_TIMING_GATE",
            "decision": str(pressure.get("direction") or "WAIT").upper(),
            "state": str(pressure.get("state") or dom_analysis.get("state") or "UNAVAILABLE"),
            "detail": str(pressure.get("reason") or ""),
        },
        {
            "engine": "V192_EVENT_RISK",
            "role": "NON_VOTING_CONTEXT_GATE",
            "decision": "CONTEXT",
            "state": str(event_risk.get("state") or "UNAVAILABLE"),
            "detail": str(event_risk.get("action") or ""),
        },
        _v284_precision_evidence(),
    ]


def _decision_signature(decision: dict[str, Any]) -> str:
    geometry = dict(
        decision.get("geometry")
        or decision.get("reference_geometry")
        or {}
    )
    directional_key = str(
        decision.get("consensus_direction")
        if str(decision.get("consensus_direction") or "").upper()
        in {"LONG", "SHORT"}
        else decision.get("dominant_direction")
        or "WAIT"
    )
    payload = "|".join(
        [
            directional_key,
            str(decision.get("action") or ""),
            str(geometry.get("signal_id") or ""),
            str(round(float(geometry.get("entry_low") or 0.0), 3)),
            str(round(float(geometry.get("entry_high") or 0.0), 3)),
            str(round(float(decision.get("confidence") or 0.0), 1)),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _latest_logged_signature(store: SupabaseOperationalStore) -> str | None:
    response = (
        store.client.table("broker_order_events")
        .select("payload")
        .eq("event_type", EVENT_TYPE)
        .eq("code", EVENT_CODE)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None
    return str(dict(rows[0].get("payload") or {}).get("decision_signature") or "") or None


def run() -> int:
    store = SupabaseOperationalStore.from_env(execution_ready_score_floor=65.0)
    now = datetime.now(tz=UTC)
    latest = _latest_heartbeats(store)
    outcomes = _outcome_rows(store)
    calibrations = _calibration_by_engine(outcomes)
    meta_research_calibration = _meta_research_calibration(outcomes)

    votes: list[dict[str, Any]] = []
    for engine, spec in ENGINE_SPECS.items():
        hb = dict(latest.get(str(spec["worker"])) or {})
        age = _age_seconds(hb.get("observed_at"), now)
        healthy = bool(hb.get("healthy"))
        direction, reason = _engine_direction(engine, hb) if hb else (None, "NO_HEARTBEAT")
        fresh = bool(age is not None and age <= MAX_HEARTBEAT_AGE_SECONDS)
        votes.append(
            {
                "engine": engine,
                "role": spec["role"],
                "direction": direction,
                "available": bool(direction and healthy and fresh),
                "base_weight": spec["base_weight"],
                "freshness_factor": (
                    1.0
                    if fresh and age is not None and age <= 180.0
                    else 0.70
                    if fresh
                    else 0.0
                ),
                "age_seconds": age,
                "healthy": healthy,
                "reason": reason,
                "calibration": calibrations.get(engine, {}),
            }
        )

    signals = _recent_signals(store)
    child_hb = latest.get("ctrader_demo_xau_v229_child_executor")
    geometry = _geometry_candidates(signals, calibrations, child_hb, now)
    gates = _gates(latest, now)
    possible_weight = sum(float(spec["base_weight"]) for spec in ENGINE_SPECS.values())
    decision = build_meta_decision(
        votes=votes,
        geometry_candidates=geometry,
        gates=gates,
        possible_base_weight=possible_weight,
    )
    decision["observed_at"] = now.isoformat()
    decision["code_version"] = os.getenv("GITHUB_SHA", "LOCAL")
    decision["decision_signature"] = _decision_signature(decision)
    decision["calibration_source"] = "XAU_OUTCOME_LEDGER_FORWARD_FIRST"
    decision["calibration_min_decisive_sample"] = 30
    decision["meta_research_calibration"] = meta_research_calibration
    decision["support_evidence"] = _support_evidence(latest)

    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details={
            "decision": decision,
            "engine_calibration": calibrations,
            "execution_influence": False,
            "environment": "DEMO",
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )

    try:
        previous = _latest_logged_signature(store)
    except Exception:
        previous = None
    if previous != decision["decision_signature"]:
        try:
            store.record_order_event(
                backend="CTRADER",
                account_id="DEMO_META_DECISION",
                signal_key=f"V296:{decision['decision_signature']}",
                event_type=EVENT_TYPE,
                accepted=None,
                code=EVENT_CODE,
                message=str(decision.get("action") or "WAIT"),
                payload={
                    "decision_signature": decision["decision_signature"],
                    "decision": decision,
                    "execution_influence": False,
                    "prospective_research": True,
                },
            )
        except Exception:
            pass

    print(
        "CTRADER_DEMO_XAU_DECISION_CENTER_V296 "
        f"direction={decision['consensus_direction']} "
        f"confidence={decision['confidence']:.1f} "
        f"action={decision['action']} engines={decision['active_engine_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
