from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import os
from typing import Any, Iterable, Sequence

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_event_reaction_v193 import (
    HistoricalEvent,
    cluster_events,
    reaction_for_cluster,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_event_prospective_v193"
HISTORICAL_WORKER = "ctrader_xau_event_reaction_v193_full"
EVENT_WORKER = "ctrader_demo_xau_event_risk_v192"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
DOM_WORKER = "ctrader_demo_xau_dom_v191"
REGIME_WORKER = "ctrader_xau_htf_strategic_regime_v180"

CONTRACT = "XAU_EVENT_REACTION_PROSPECTIVE_V193_1"
STRATEGY_ID = "XAU_EVENT_REACTION_V193_PROSPECTIVE_SHADOW"
EPISODE_TYPE = "EVENT_REACTION_V193"

CAPTURE_LEAD_MINUTES = 90
CLUSTER_TOLERANCE_SECONDS = 90
MAX_RESOLUTION_MINUTES = 180
SYMBOL = "XAUUSD"

CATEGORY_TO_FAMILY = {
    "EMPLOYMENT": "NFP_EMPLOYMENT",
    "JOBLESS_CLAIMS": "JOBLESS_CLAIMS",
    "CPI": "CPI",
    "PPI": "PPI",
    "PCE": "PCE",
    "GDP": "GDP",
    "CURRENT_ACCOUNT": "CURRENT_ACCOUNT",
    "TRADE": "TRADE",
    "FED_SPEECH": "FED_SPEECH",
    "FOMC": "FOMC_DECISION",
    "JOLTS": "JOLTS",
    "OTHER_USD": "OTHER_USD",
}


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _family(category: Any) -> str:
    return CATEGORY_TO_FAMILY.get(
        str(category or "OTHER_USD").upper(),
        str(category or "OTHER_USD").upper(),
    )


def cluster_upcoming_events(
    rows: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    parsed: list[dict[str, Any]] = []
    for row in rows:
        at = _dt(row.get("scheduled_at"))
        if at is None:
            continue
        parsed.append({**dict(row), "_scheduled_at": at})
    parsed.sort(key=lambda row: (row["_scheduled_at"], str(row.get("title") or "")))

    groups: list[list[dict[str, Any]]] = []
    for row in parsed:
        if not groups:
            groups.append([row])
            continue
        anchor = groups[-1][0]["_scheduled_at"]
        if abs((row["_scheduled_at"] - anchor).total_seconds()) <= CLUSTER_TOLERANCE_SECONDS:
            groups[-1].append(row)
        else:
            groups.append([row])

    output: list[dict[str, Any]] = []
    for group in groups:
        at = min(row["_scheduled_at"] for row in group)
        families = sorted({_family(row.get("category")) for row in group})
        titles = [str(row.get("title") or "") for row in group]
        raw = at.isoformat() + "|" + "|".join(sorted(titles))
        key = "v193-event-" + sha256(raw.encode("utf-8")).hexdigest()[:24]
        clean_events = []
        for row in group:
            item = dict(row)
            item.pop("_scheduled_at", None)
            clean_events.append(item)
        output.append(
            {
                "episode_key": key,
                "scheduled_at": at.isoformat(),
                "events": clean_events,
                "families": families,
                "event_count": len(clean_events),
                "attribution": (
                    "SINGLE_EVENT" if len(clean_events) == 1 else "MULTI_EVENT_CLUSTER"
                ),
            }
        )
    return tuple(output)


def historical_ready(details: dict[str, Any] | None) -> bool:
    return str(dict(details or {}).get("decision") or "") == "FULL_BACKFILL_RESEARCH_READY"


def resolution_state(reaction: dict[str, Any]) -> str:
    if reaction.get("r60m_atr") is not None:
        return "RESOLVED_60M"
    if reaction.get("r30m_atr") is not None:
        return "RESOLVED_30M"
    if reaction.get("r15m_atr") is not None:
        return "RESOLVED_15M"
    if reaction.get("r5m_atr") is not None:
        return "RESOLVED_5M"
    return "EVENT_OCCURRED_WAIT_REACTION"


def _latest_worker_details(
    store: SupabaseOperationalStore,
    worker_name: str,
) -> tuple[datetime | None, dict[str, Any]]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None, {}
    row = dict(rows[0])
    return _dt(row.get("observed_at")), dict(row.get("details") or {})


def _latest_m15_signal(store: SupabaseOperationalStore) -> dict[str, Any]:
    response = (
        store.client.table("signals")
        .select(
            "observed_at,direction,setup_type,state,final_score,entry_low,entry_high,"
            "sl,tp1,tp2,tp3,active_guards,expires_at"
        )
        .eq("symbol", SYMBOL)
        .order("observed_at", desc=True)
        .limit(20)
        .execute()
    )
    now = datetime.now(tz=UTC)
    for raw in list(response.data or []):
        row = dict(raw)
        if "M15" not in str(row.get("setup_type") or "").upper():
            continue
        expires = _dt(row.get("expires_at"))
        if expires is not None and expires < now:
            continue
        return row
    return {}


def _context_snapshot(store: SupabaseOperationalStore) -> dict[str, Any]:
    atlas_at, atlas = _latest_worker_details(store, ATLAS_WORKER)
    dom_at, dom = _latest_worker_details(store, DOM_WORKER)
    regime_at, regime = _latest_worker_details(store, REGIME_WORKER)

    atlas_eval = dict(atlas.get("evaluation") or {})
    path_map = dict(atlas_eval.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    micro = dict(atlas_eval.get("micro_refinement") or {})
    dom_analysis = dict(dom.get("analysis") or {})
    regime_eval = dict(regime.get("evaluation") or {})
    regime_current = dict(regime_eval.get("current") or {})

    return {
        "captured_at": datetime.now(tz=UTC).isoformat(),
        "reference_price": atlas_eval.get("last_closed_m15_price"),
        "supply_demand": {
            "observed_at": None if atlas_at is None else atlas_at.isoformat(),
            "state": atlas_eval.get("state"),
            "active_path": active_path,
            "micro_refinement": micro,
        },
        "dom": {
            "observed_at": None if dom_at is None else dom_at.isoformat(),
            "state": dom_analysis.get("state"),
            "pressure_score": dom_analysis.get("dom_pressure_score"),
            "last_imbalance": dom_analysis.get("last_imbalance"),
        },
        "regime": {
            "observed_at": None if regime_at is None else regime_at.isoformat(),
            "strategic_bias": regime_current.get("strategic_bias"),
            "tactical_first_leg": regime_current.get("tactical_first_leg"),
        },
        "m15_signal": _latest_m15_signal(store),
    }


def _open_episodes(store: SupabaseOperationalStore) -> list[dict[str, Any]]:
    response = (
        store.client.table("xau_outcome_ledger")
        .select(
            "episode_key,observed_at,status,direction,metadata,created_at,updated_at"
        )
        .eq("episode_type", EPISODE_TYPE)
        .eq("strategy_id", STRATEGY_ID)
        .order("observed_at", desc=True)
        .limit(100)
        .execute()
    )
    return [
        dict(row)
        for row in (response.data or [])
        if str(row.get("status") or "") not in {
            "RESOLVED_60M",
            "RESOLUTION_DATA_MISSING",
        }
    ]


def _capture_new_episodes(
    store: SupabaseOperationalStore,
    *,
    upcoming: Sequence[dict[str, Any]],
    now: datetime,
    historical_details: dict[str, Any],
) -> int:
    captured = 0
    context = None
    for cluster in cluster_upcoming_events(upcoming):
        scheduled = _dt(cluster.get("scheduled_at"))
        if scheduled is None:
            continue
        lead = (scheduled - now).total_seconds() / 60.0
        if lead <= 0 or lead > CAPTURE_LEAD_MINUTES:
            continue

        if context is None:
            context = _context_snapshot(store)

        metadata = {
            "contract": CONTRACT,
            "scheduled_at": scheduled.isoformat(),
            "events": cluster["events"],
            "families": cluster["families"],
            "event_count": cluster["event_count"],
            "attribution": cluster["attribution"],
            "capture_lead_minutes": lead,
            "pre_event_context": context,
            "historical_gate": {
                "worker": HISTORICAL_WORKER,
                "decision": historical_details.get("decision"),
                "year_min": historical_details.get("year_min"),
                "year_max": historical_details.get("year_max"),
                "reaction_count": historical_details.get("reaction_count"),
            },
            "execution_influence": False,
            "execution_authority": False,
        }
        row = {
            "episode_key": cluster["episode_key"],
            "episode_type": EPISODE_TYPE,
            "strategy_id": STRATEGY_ID,
            "observed_at": now.isoformat(),
            "status": "PRE_EVENT_CAPTURED",
            "execution_authority": "NONE",
            "metadata": metadata,
            "updated_at": now.isoformat(),
        }
        (
            store.client.table("xau_outcome_ledger")
            .upsert(row, on_conflict="episode_key", ignore_duplicates=True)
            .execute()
        )
        captured += 1
    return captured


def _historical_events_from_metadata(metadata: dict[str, Any]) -> tuple[HistoricalEvent, ...]:
    output: list[HistoricalEvent] = []
    scheduled = _dt(metadata.get("scheduled_at"))
    if scheduled is None:
        return ()
    for i, row in enumerate(list(metadata.get("events") or [])):
        output.append(
            HistoricalEvent(
                event_id=str(row.get("event_id") or f"prospective-{i}"),
                scheduled_at=scheduled,
                title=str(row.get("title") or "USD event"),
                family=_family(row.get("category")),
                impact=str(row.get("impact") or "UNKNOWN"),
                source=str(row.get("source") or "UNKNOWN"),
                source_tier=str(row.get("source_tier") or "UNKNOWN"),
            )
        )
    return tuple(output)


def _resolve_episode(
    store: SupabaseOperationalStore,
    feed,
    episode: dict[str, Any],
    *,
    now: datetime,
) -> str:
    metadata = dict(episode.get("metadata") or {})
    scheduled = _dt(metadata.get("scheduled_at"))
    if scheduled is None:
        return "INVALID_EPISODE"
    age_minutes = (now - scheduled).total_seconds() / 60.0
    if age_minutes < 5:
        return "WAIT_EVENT_HORIZON"

    events = _historical_events_from_metadata(metadata)
    if not events:
        return "INVALID_EPISODE"

    try:
        bars = tuple(
            feed.historical_bars(
                SYMBOL,
                "M5",
                from_time=scheduled - timedelta(hours=3),
                to_time=min(now, scheduled + timedelta(minutes=80)),
                count=240,
            )
        )
        cluster = cluster_events(events)[0]
        reaction = reaction_for_cluster(cluster, bars)
    except Exception as exc:
        if age_minutes > MAX_RESOLUTION_MINUTES:
            (
                store.client.table("xau_outcome_ledger")
                .update(
                    {
                        "status": "RESOLUTION_DATA_MISSING",
                        "updated_at": now.isoformat(),
                        "metadata": {
                            **metadata,
                            "resolution_error": f"{type(exc).__name__}:{exc}",
                            "resolution_checked_at": now.isoformat(),
                        },
                    }
                )
                .eq("episode_key", str(episode["episode_key"]))
                .execute()
            )
            return "RESOLUTION_DATA_MISSING"
        return "WAIT_DATA"

    if reaction is None:
        return "WAIT_DATA"

    state = resolution_state(reaction)
    r15 = reaction.get("r15m_atr")
    direction = None
    if r15 is not None:
        direction = "LONG" if float(r15) > 0 else "SHORT" if float(r15) < 0 else None

    merged_metadata = {
        **metadata,
        "resolution": reaction,
        "resolution_state": state,
        "resolution_checked_at": now.isoformat(),
        "execution_influence": False,
        "execution_authority": False,
    }
    update = {
        "status": state,
        "direction": direction,
        "outcome_class": (
            None
            if r15 is None
            else ("UP_15M" if float(r15) > 0 else "DOWN_15M" if float(r15) < 0 else "FLAT_15M")
        ),
        "outcome_at": now.isoformat() if state == "RESOLVED_60M" else None,
        "updated_at": now.isoformat(),
        "metadata": merged_metadata,
    }
    (
        store.client.table("xau_outcome_ledger")
        .update(update)
        .eq("episode_key", str(episode["episode_key"]))
        .execute()
    )
    return state


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V193_PROSPECTIVE_DEMO_ONLY")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_V193_PROSPECTIVE_SYMBOL_NOT_CONFIGURED")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    hist_at, historical = _latest_worker_details(store, HISTORICAL_WORKER)

    if not historical_ready(historical):
        details = {
            "contract": CONTRACT,
            "state": "WAIT_HISTORICAL_ATLAS",
            "historical_worker_observed_at": None if hist_at is None else hist_at.isoformat(),
            "historical_decision": historical.get("decision"),
            "captured": 0,
            "resolved": 0,
            "execution_influence": False,
            "execution_authority": False,
        }
        store.write_heartbeat(WORKER_NAME, healthy=True, lag_seconds=0.0, details=details)
        print(
            "XAU_EVENT_PROSPECTIVE_V193 state=WAIT_HISTORICAL_ATLAS "
            "execution_authority=0"
        )
        return 0

    event_at, event_details = _latest_worker_details(store, EVENT_WORKER)
    event_age = None if event_at is None else (now - event_at).total_seconds()
    if event_at is None or event_age is None or event_age > 600:
        details = {
            "contract": CONTRACT,
            "state": "WAIT_FRESH_EVENT_RISK",
            "event_worker_observed_at": None if event_at is None else event_at.isoformat(),
            "event_age_seconds": event_age,
            "execution_influence": False,
            "execution_authority": False,
        }
        store.write_heartbeat(WORKER_NAME, healthy=True, lag_seconds=0.0, details=details)
        return 0

    risk = dict(event_details.get("risk") or {})
    upcoming = list(risk.get("upcoming_events") or [])
    captured = _capture_new_episodes(
        store,
        upcoming=upcoming,
        now=now,
        historical_details=historical,
    )

    open_rows = _open_episodes(store)
    resolvable = [
        row
        for row in open_rows
        if (_dt(dict(row.get("metadata") or {}).get("scheduled_at")) or now) <= now
    ]

    resolved_states: dict[str, int] = {}
    if resolvable:
        feed = build_ctrader_research_feed(policy, (SYMBOL,))
        try:
            feed.ensure_connected()
            for episode in resolvable:
                state = _resolve_episode(store, feed, episode, now=now)
                resolved_states[state] = resolved_states.get(state, 0) + 1
        finally:
            try:
                feed.close()
            except Exception:
                pass

    details = {
        "contract": CONTRACT,
        "state": "PROSPECTIVE_SHADOW_ACTIVE",
        "historical_decision": historical.get("decision"),
        "historical_year_min": historical.get("year_min"),
        "historical_year_max": historical.get("year_max"),
        "historical_reaction_count": historical.get("reaction_count"),
        "event_risk_state": risk.get("state"),
        "captured_this_run": captured,
        "open_episode_count": len(open_rows),
        "resolved_states_this_run": resolved_states,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    store.write_heartbeat(WORKER_NAME, healthy=True, lag_seconds=0.0, details=details)
    print(
        "XAU_EVENT_PROSPECTIVE_V193 "
        f"state=PROSPECTIVE_SHADOW_ACTIVE captured={captured} "
        f"open={len(open_rows)} resolved={resolved_states} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
