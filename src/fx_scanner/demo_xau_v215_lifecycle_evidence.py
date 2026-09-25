from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from typing import Any

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v215_lifecycle_evidence"
CONTRACT = "XAU_M5_LIFECYCLE_PROSPECTIVE_EVIDENCE_V215"
SOURCE_WORKER = "ctrader_demo_xau_v214_pocket_lifecycle"
EVENT_TYPE = "DEMO_XAU_M5_LIFECYCLE_V215"
EVENT_CODE = "XAU_M5_LIFECYCLE_V215"
ACCOUNT_ID = "OBSERVABILITY"


def _latest_heartbeat(store: SupabaseOperationalStore, worker_name: str) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


def _stable_signal_key(role: str, leg: dict[str, Any]) -> str | None:
    evidence = dict(leg.get("candidate_evidence") or {})
    physical_key = str(evidence.get("physical_key") or "").strip()
    if physical_key:
        return "V215:" + physical_key

    pocket = dict(leg.get("initial_pocket") or {})
    direction = str(leg.get("direction") or "").upper()
    low = pocket.get("low")
    high = pocket.get("high")
    origin_at = pocket.get("origin_at")
    if not pocket or direction not in {"LONG", "SHORT"}:
        return None

    raw = "|".join(
        (
            CONTRACT,
            role,
            direction,
            str(low),
            str(high),
            str(origin_at or ""),
        )
    )
    return "V215:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _stage(leg: dict[str, Any]) -> str:
    timeline = dict(leg.get("timeline") or {})
    ladder = dict(leg.get("reaction_ladder") or {})
    if dict(leg.get("refined_pocket") or {}):
        if any(bool(dict(item).get("hit")) for item in ladder.values()):
            return "REFINED_WITH_REACTION"
        return "REFINED_WAIT_REACTION"
    if timeline.get("mss_at"):
        return "MSS_CONFIRMED"
    if timeline.get("reclaim_at"):
        return "RECLAIM_CONFIRMED"
    if timeline.get("first_touch_at"):
        return "TOUCHED"
    if dict(leg.get("initial_pocket") or {}):
        return "CANDIDATE_PREMAPPED"
    return "NO_ACTIVE_POCKET"


def _fingerprint(payload: dict[str, Any]) -> str:
    material = {
        "role": payload.get("role"),
        "stage": payload.get("stage"),
        "timeline": payload.get("timeline"),
        "latency_minutes": payload.get("latency_minutes"),
        "reaction_ladder": payload.get("reaction_ladder"),
        "initial_pocket": payload.get("initial_pocket"),
        "refined_pocket": payload.get("refined_pocket"),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()[:24]


def _existing_fingerprints(store: SupabaseOperationalStore) -> set[str]:
    response = (
        store.client.table("broker_order_events")
        .select("payload")
        .eq("backend", "CTRADER")
        .eq("account_id", ACCOUNT_ID)
        .eq("event_type", EVENT_TYPE)
        .order("observed_at", desc=True)
        .limit(500)
        .execute()
    )
    output: set[str] = set()
    for row in list(response.data or []):
        payload = dict(dict(row).get("payload") or {})
        fp = str(payload.get("fingerprint") or "")
        if fp:
            output.add(fp)
    return output


def build_events(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for role in ("current_leg", "next_leg"):
        leg = dict(evaluation.get(role) or {})
        signal_key = _stable_signal_key(role, leg)
        if signal_key is None:
            continue
        payload = {
            "contract": CONTRACT,
            "role": role,
            "signal_key": signal_key,
            "direction": leg.get("direction"),
            "stage": _stage(leg),
            "pocket_state": leg.get("pocket_state"),
            "initial_pocket": dict(leg.get("initial_pocket") or {}),
            "refined_pocket": dict(leg.get("refined_pocket") or {}),
            "candidate_evidence": dict(leg.get("candidate_evidence") or {}),
            "refined_evidence": dict(leg.get("refined_evidence") or {}),
            "timeline": dict(leg.get("timeline") or {}),
            "latency_minutes": dict(leg.get("latency_minutes") or {}),
            "reaction_ladder": dict(leg.get("reaction_ladder") or {}),
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        }
        payload["fingerprint"] = _fingerprint(payload)
        output.append(payload)
    return output


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V215_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V215_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    error: str | None = None
    written = 0
    skipped = 0
    events: list[dict[str, Any]] = []

    try:
        source = _latest_heartbeat(store, SOURCE_WORKER)
        evaluation = dict(dict(source.get("details") or {}).get("evaluation") or {})
        events = build_events(evaluation)
        existing = _existing_fingerprints(store)

        for payload in events:
            fingerprint = str(payload.get("fingerprint") or "")
            if fingerprint in existing:
                skipped += 1
                continue
            store.record_order_event(
                backend="CTRADER",
                account_id=ACCOUNT_ID,
                signal_key=str(payload["signal_key"]),
                event_type=EVENT_TYPE,
                accepted=None,
                code=EVENT_CODE,
                message=str(payload.get("stage") or "LIFECYCLE"),
                payload=payload,
            )
            existing.add(fingerprint)
            written += 1
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "source_worker": SOURCE_WORKER,
            "event_type": EVENT_TYPE,
            "events_considered": len(events),
            "events_written": written,
            "events_skipped_unchanged": skipped,
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "observed_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V215_LIFECYCLE_EVIDENCE "
        f"healthy={healthy} written={written} skipped={skipped} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
