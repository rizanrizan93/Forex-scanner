from __future__ import annotations

import argparse
import gzip
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .dashboard import SupabaseDashboardReader, merge_runtime_heartbeat_rows
from .storage.supabase_operational import SupabaseOperationalStore

CONTRACT = "XAU_RIZAN_DASHBOARD_BRIDGE_V254"
DEFAULT_SNAPSHOT_URL = (
    "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
    "dashboard-snapshots-v344/runtime/xau_dashboard_snapshot.json"
)
FRESH_SECONDS = 180.0
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024

HOT_REFRESH_SECONDS = 60.0
STRUCTURAL_REFRESH_SECONDS = 2400.0
SUPPORT_REFRESH_SECONDS = 3600.0
COLD_REFRESH_SECONDS = 900.0
OUTCOME_REFRESH_SECONDS = 21600.0

HOT_HEARTBEATS = (
    # Only small, truly minute-sensitive payloads stay in the generic hot set.
    # V296 and V328 are projected separately below so their large research
    # details do not consume minute-level Supabase egress.
    # V342/V343 are the only market-opinion engines exposed by the V344 UI and
    # must retain details.evaluation in the public bridge snapshot.
    "ctrader_demo_xau_sd_liquidity_v342",
    "ctrader_demo_xau_friend_entry_v343",
    "ctrader_demo_xau_rizan_fast_handoff",
    "ctrader_demo_xau_afic_fast_handoff",
    "ctrader_demo_xau_dom_v191",
    "ctrader_demo_xau_event_risk_v192",
    "ctrader_demo_xau_meta_research_sampler_v297",
    "ctrader_demo_xau_structural_research_probe_v318",
)

STRUCTURAL_HEARTBEATS = (
    # Full V182/V226 historical/detail payloads stay on the ten-minute budget.
    # Their decision-critical path/candidate identity is projected separately
    # every 60 seconds so the dashboard cannot show an old leg or old locator.
    "ctrader_demo_xau_supply_demand_atlas_v182",
    "ctrader_demo_xau_v226_rizan_depth_map",
)

SUPPORT_HEARTBEATS = (
    # Research/evidence layers shown in detail panels. They do not authorize
    # broker orders and therefore must not consume minute-level Data API egress.
    # Full V296/V328/micro payloads are retained here for expandable diagnostics;
    # compact current-state projections are overlaid every minute.
    "ctrader_demo_xau_decision_center_v296",
    "ctrader_demo_xau_micro_entry_refinement_v320",
    "ctrader_demo_xau_micro_entry_dual_cycle_v321",
    "ctrader_demo_xau_micro_handoff_v322",
    "ctrader_demo_xau_micro_destination_v328",
    "ctrader_demo_xau_v203_volatility_shock_guard",
    "ctrader_demo_xau_premap_candidate_v181",
    "ctrader_demo_xau_supply_demand_prospective_v184",
    "ctrader_xau_supply_demand_reaction_v183",
    "ctrader_xau_supply_demand_timeframe_v185",
    "ctrader_demo_xau_v196_shadow_evidence",
    "ctrader_demo_xau_v198_evidence_analytics",
    "ctrader_demo_xau_v201_reaction_ladder",
    "ctrader_demo_xau_v212_zone_reaction_probability",
    "ctrader_demo_xau_v213_post_zone_path",
    "ctrader_demo_xau_v214_pocket_lifecycle",
    "ctrader_demo_xau_v216_lifecycle_calibration",
    "ctrader_demo_xau_v217_direction_probability",
    "ctrader_demo_xau_v220_direction_prospective_calibration",
    "ctrader_demo_xau_v222_m5_pocket_quality",
    "ctrader_demo_xau_v223_m5_pocket_cluster_selector",
    "ctrader_demo_xau_v224_primary_pocket_prospective",
    "ctrader_demo_xau_v227_depth_map_prospective",
    "ctrader_xau_expected_move_envelope_v170",
    "ctrader_xau_forecast_ensemble_v171",
    "ctrader_xau_htf_strategic_regime_v180",
)

COLD_BACKEND_KEYS = (
    "latest_run",
    "rankings",
    "signals",
    "macro",
    "performance",
)

SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "apikey",
    "api_key",
    "refresh_token",
    "access_token",
    "client_secret",
)


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _mask_identifier(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) <= 4:
        return "*" * len(raw)
    return "*" * max(4, len(raw) - 4) + raw[-4:]


PRIVATE_ACCOUNT_FIELDS = {
    "balance", "equity", "floating_profit", "margin", "margin_free", "margin_level",
    "account_balance", "account_equity", "free_margin",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            lowered = key_s.lower()
            if lowered in PRIVATE_ACCOUNT_FIELDS or any(part in lowered for part in SENSITIVE_KEY_PARTS):
                continue
            if lowered in {"account_id", "trader_login", "ctidtraderaccountid"}:
                out[key_s] = _mask_identifier(item)
                continue
            if lowered in {"broker_order_id", "position_id"}:
                out[key_s] = _mask_identifier(item)
                continue
            out[key_s] = _sanitize(item)
        return out
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return value


def _json_size(value: Any) -> int:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        return 0
    return len(raw.encode("utf-8"))


def _merge_heartbeats(
    compact_rows: tuple[dict[str, Any], ...],
    critical_rows: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    by_worker: dict[str, dict[str, Any]] = {}
    for row in compact_rows:
        worker = str(row.get("worker_name") or "")
        if worker:
            by_worker[worker] = dict(row)
    for row in critical_rows:
        worker = str(row.get("worker_name") or "")
        if worker:
            by_worker[worker] = dict(row)
    return sorted(
        by_worker.values(),
        key=lambda row: str(row.get("observed_at") or ""),
        reverse=True,
    )


def _load_previous_snapshot(output: Path) -> dict[str, Any]:
    try:
        raw = json.loads(output.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if str(raw.get("contract") or "") != CONTRACT:
        return {}
    return dict(raw)


def _tier_is_fresh(
    previous: dict[str, Any],
    *,
    source_key: str,
    max_age_seconds: float,
    now: datetime,
) -> bool:
    source = dict(previous.get("source") or {})
    observed = _timestamp(source.get(source_key))
    if observed is None:
        return False
    return max(0.0, (now - observed).total_seconds()) < float(max_age_seconds)


def _overlay_heartbeat_rows(
    base_rows: list[dict[str, Any]],
    fresh_rows: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    by_worker: dict[str, dict[str, Any]] = {}
    for raw in base_rows:
        row = dict(raw or {})
        worker = str(row.get("worker_name") or "")
        if worker:
            by_worker[worker] = row
    for raw in fresh_rows:
        row = dict(raw or {})
        worker = str(row.get("worker_name") or "")
        if worker:
            by_worker[worker] = row
    return sorted(
        by_worker.values(),
        key=lambda row: str(row.get("observed_at") or ""),
        reverse=True,
    )


def build_snapshot(
    *,
    previous: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    from supabase import create_client

    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    previous_payload = dict(previous or {})
    previous_backend = dict(previous_payload.get("backend") or {})
    previous_source = dict(previous_payload.get("source") or {})
    has_previous = bool(previous_backend)

    url = _required("SUPABASE_URL").rstrip("/")
    secret = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
    )
    if not secret:
        raise RuntimeError("missing Supabase service-role backend credential")

    client = create_client(url, secret)
    reader = SupabaseDashboardReader(client)
    store = SupabaseOperationalStore(url, secret, client=client)

    previous_budget = dict(previous_source.get("egress_budget") or {})
    tier_bytes = {
        "structural": int(previous_budget.get("structural_payload_bytes") or 0),
        "support": int(previous_budget.get("support_payload_bytes") or 0),
        "cold": int(previous_budget.get("cold_payload_bytes") or 0),
        "outcomes": int(previous_budget.get("outcome_payload_bytes") or 0),
    }
    cycle_bytes = 0

    structural_reused = has_previous and _tier_is_fresh(
        previous_payload,
        source_key="structural_as_of",
        max_age_seconds=STRUCTURAL_REFRESH_SECONDS,
        now=current,
    )
    support_reused = has_previous and _tier_is_fresh(
        previous_payload,
        source_key="support_as_of",
        max_age_seconds=SUPPORT_REFRESH_SECONDS,
        now=current,
    )
    cold_reused = has_previous and _tier_is_fresh(
        previous_payload,
        source_key="cold_as_of",
        max_age_seconds=COLD_REFRESH_SECONDS,
        now=current,
    )
    outcomes_reused = has_previous and _tier_is_fresh(
        previous_payload,
        source_key="outcomes_as_of",
        max_age_seconds=OUTCOME_REFRESH_SECONDS,
        now=current,
    )

    # Minute-level state: small projected/operational payloads only.
    #
    # V330 resilience: the dashboard transport must not stop publishing merely
    # because one projected Supabase read times out. When a previous public
    # snapshot exists, retain its last-known heartbeat for that worker and
    # publish explicit degraded-read metadata. Individual heartbeat timestamps
    # remain authoritative, so Streamlit still marks stale components as stale.
    operational_read_errors: list[str] = []
    previous_heartbeats = [
        dict(row or {})
        for row in list(previous_backend.get("heartbeats") or [])
    ]
    previous_by_worker = {
        str(row.get("worker_name") or ""): row
        for row in previous_heartbeats
        if str(row.get("worker_name") or "")
    }

    try:
        hot_heartbeats = list(
            reader.heartbeats_for_workers(list(HOT_HEARTBEATS))
        )
    except Exception as exc:
        operational_read_errors.append(
            f"HOT_HEARTBEATS:{type(exc).__name__}"
        )
        hot_heartbeats = [
            dict(previous_by_worker[name])
            for name in HOT_HEARTBEATS
            if name in previous_by_worker
        ]
        if not hot_heartbeats and not has_previous:
            raise

    def _append_operational(
        *,
        label: str,
        worker_name: str,
        fetcher: Callable[[], dict[str, Any] | None],
    ) -> None:
        try:
            row = fetcher()
        except Exception as exc:
            operational_read_errors.append(
                f"{label}:{type(exc).__name__}"
            )
            row = previous_by_worker.get(worker_name)
        if row is not None:
            hot_heartbeats.append(dict(row))

    _append_operational(
        label="PREPARED",
        worker_name="ctrader_demo_xau_rizan_prepared_plan_producer",
        fetcher=lambda: reader.latest_rizan_prepared_heartbeat(),
    )
    _append_operational(
        label="V229_EXECUTION",
        worker_name="ctrader_demo_xau_v229_depth_execution",
        fetcher=lambda: reader.latest_rizan_v229_execution_heartbeat(),
    )
    _append_operational(
        label="V229_CHILD",
        worker_name="ctrader_demo_xau_v229_child_executor",
        fetcher=lambda: reader.latest_rizan_child_executor_heartbeat(),
    )

    # Current V182 path/M5 and V226 candidate identity must not wait for the
    # ten-minute historical-detail tier. These projected rows are deliberately
    # compact and are merged into cached full heartbeats. A transient timeout
    # falls back to the last public snapshot instead of freezing the bridge.
    _append_operational(
        label="V182_OPERATIONAL",
        worker_name="ctrader_demo_xau_supply_demand_atlas_v182",
        fetcher=lambda: reader.latest_xau_atlas_operational_heartbeat(),
    )
    _append_operational(
        label="V226_OPERATIONAL",
        worker_name="ctrader_demo_xau_v226_rizan_depth_map",
        fetcher=lambda: reader.latest_xau_v226_operational_heartbeat(),
    )
    _append_operational(
        label="V296_OPERATIONAL",
        worker_name="ctrader_demo_xau_decision_center_v296",
        fetcher=lambda: reader.latest_xau_decision_center_operational_heartbeat(),
    )
    _append_operational(
        label="V328_OPERATIONAL",
        worker_name="ctrader_demo_xau_micro_destination_v328",
        fetcher=lambda: reader.latest_xau_micro_destination_operational_heartbeat(),
    )

    hot_heartbeat_bytes = _json_size(hot_heartbeats)
    cycle_bytes += hot_heartbeat_bytes

    # Preserve previously published detail rows and overlay only tiers that are
    # due. This keeps every dashboard panel populated without re-reading the DB.
    heartbeats = list(previous_backend.get("heartbeats") or [])
    if not heartbeats:
        heartbeats = list(reader.heartbeat_summaries())

    if not structural_reused:
        structural_rows = reader.heartbeats_for_workers(
            list(STRUCTURAL_HEARTBEATS)
        )
        tier_bytes["structural"] = _json_size(structural_rows)
        cycle_bytes += tier_bytes["structural"]
        heartbeats = _overlay_heartbeat_rows(heartbeats, structural_rows)
        structural_as_of = current.isoformat()
    else:
        structural_as_of = str(
            previous_source.get("structural_as_of") or current.isoformat()
        )

    if not support_reused:
        summary_rows = reader.heartbeat_summaries()
        support_rows = reader.heartbeats_for_workers(list(SUPPORT_HEARTBEATS))
        tier_bytes["support"] = _json_size(summary_rows) + _json_size(support_rows)
        cycle_bytes += tier_bytes["support"]
        heartbeats = _overlay_heartbeat_rows(list(summary_rows), tuple(heartbeats))
        heartbeats = _overlay_heartbeat_rows(heartbeats, support_rows)
        support_as_of = current.isoformat()
    else:
        support_as_of = str(
            previous_source.get("support_as_of") or current.isoformat()
        )

    heartbeats = merge_runtime_heartbeat_rows(
        heartbeats,
        hot_heartbeats,
    )

    if cold_reused:
        cold_values = {
            key: previous_backend.get(key)
            for key in COLD_BACKEND_KEYS
        }
        cold_as_of = str(
            previous_source.get("cold_as_of") or current.isoformat()
        )
    else:
        run = reader.latest_run()
        cold_values = {
            "latest_run": run,
            "rankings": list(
                reader.rankings_for_run(None if run is None else run.get("id"))
            ),
            "signals": list(reader.latest_signals()),
            "macro": list(reader.latest_macro()),
            "performance": list(reader.latest_performance()),
        }
        tier_bytes["cold"] = _json_size(cold_values)
        cycle_bytes += tier_bytes["cold"]
        cold_as_of = current.isoformat()

    if outcomes_reused:
        xau_outcomes = list(previous_backend.get("xau_outcomes") or [])
        outcomes_as_of = str(
            previous_source.get("outcomes_as_of") or current.isoformat()
        )
    else:
        xau_outcomes = list(reader.latest_xau_outcomes())
        tier_bytes["outcomes"] = _json_size(xau_outcomes)
        cycle_bytes += tier_bytes["outcomes"]
        outcomes_as_of = current.isoformat()

    # Public GitHub snapshots must not export private broker telemetry.
    account = None
    broker_positions = []
    xau_signals = list(reader.latest_signals_for_symbol("XAUUSD", limit=8))
    forecast_states = list(reader.latest_afic_forecast_states(limit=6))
    prepared_plans = list(reader.latest_afic_prepared_plans(limit=1))
    geometry_events = list(reader.latest_xau_geometry_events_compact(limit=2))
    execution_events = list(reader.latest_xau_execution_events(limit=4))
    lifecycle = list(reader.latest_xau_prepared_plan_lifecycle(limit=4))
    control_snapshot = asdict(store.get_execution_control())
    # V240 needs the newest saved RIZAN geometry for parity/mismatch checks.
    # Fetch exactly one dedicated row so the generic geometry timeline can stay tiny.
    rizan_geometry = list(reader.latest_rizan_execution_geometry_compact(limit=1))

    # Keep minute-level egress bounded. The UI needs current admission plus a
    # short audit trail; older history remains in Supabase and is not deleted.
    # These limits deliberately preserve enough rows for current-state geometry
    # matching while preventing historical JSON from being retransmitted every minute.
    hot_backend_values = {
        "xau_signals": xau_signals,
        "broker_account": account,
        "broker_positions": broker_positions,
        "afic_forecast_states": forecast_states,
        "afic_prepared_plans": prepared_plans,
        "afic_execution_geometry": rizan_geometry,
        "xau_execution_events": execution_events,
        "xau_geometry_events": geometry_events,
        "xau_prepared_plan_lifecycle": lifecycle,
        "control": control_snapshot,
    }
    hot_component_bytes = {
        "heartbeats": int(hot_heartbeat_bytes),
        **{
            key: int(_json_size(value))
            for key, value in hot_backend_values.items()
        },
    }
    hot_backend_bytes = _json_size(hot_backend_values)
    cycle_bytes += hot_backend_bytes
    hot_payload_bytes = hot_heartbeat_bytes + hot_backend_bytes

    steady_state_bytes_per_minute = (
        hot_payload_bytes
        + tier_bytes["structural"] / (STRUCTURAL_REFRESH_SECONDS / 60.0)
        + tier_bytes["support"] / (SUPPORT_REFRESH_SECONDS / 60.0)
        + tier_bytes["cold"] / (COLD_REFRESH_SECONDS / 60.0)
        + tier_bytes["outcomes"] / (OUTCOME_REFRESH_SECONDS / 60.0)
    )
    conservative_24x5_month_minutes = 60.0 * 24.0 * 22.0
    projected_month_gib = (
        steady_state_bytes_per_minute * conservative_24x5_month_minutes
        / (1024.0 ** 3)
    )

    backend = {
        **cold_values,
        "account_telemetry_redacted": True,
        "xau_signals": xau_signals,
        "heartbeats": heartbeats,
        "broker_account": account,
        "broker_positions": broker_positions,
        "afic_forecast_states": forecast_states,
        "afic_prepared_plans": prepared_plans,
        # Same semantics as the old feed, but reuse the already-fetched geometry
        # rows instead of issuing a duplicate broker_order_events query.
        "afic_execution_geometry": rizan_geometry,
        "xau_execution_events": execution_events,
        "xau_geometry_events": geometry_events,
        "xau_outcomes": xau_outcomes,
        "xau_prepared_plan_lifecycle": lifecycle,
        "control": control_snapshot,
    }

    project_ref = urlsplit(url).hostname or ""
    project_ref = project_ref.split(".", 1)[0]
    payload = {
        "contract": CONTRACT,
        "as_of": current.isoformat(),
        "source": {
            "project_ref": project_ref,
            "account_telemetry_public": False,
            "mode": "SUPABASE_SERVICE_ROLE_TO_PUBLIC_READ_ONLY_BRIDGE",
            "dashboard_refresh_seconds": int(HOT_REFRESH_SECONDS),
            "operational_structure_refresh_seconds": int(HOT_REFRESH_SECONDS),
            "structural_refresh_seconds": int(STRUCTURAL_REFRESH_SECONDS),
            "support_refresh_seconds": int(SUPPORT_REFRESH_SECONDS),
            "cold_refresh_seconds": int(COLD_REFRESH_SECONDS),
            "outcome_refresh_seconds": int(OUTCOME_REFRESH_SECONDS),
            "structural_as_of": structural_as_of,
            "support_as_of": support_as_of,
            "cold_as_of": cold_as_of,
            "outcomes_as_of": outcomes_as_of,
            "structural_reused": structural_reused,
            "support_reused": support_reused,
            "cold_reused": cold_reused,
            "outcomes_reused": outcomes_reused,
            "operational_read_degraded": bool(operational_read_errors),
            "operational_read_errors": operational_read_errors,
            "egress_budget": {
                "cycle_payload_bytes": int(cycle_bytes),
                "hot_payload_bytes": int(hot_payload_bytes),
                "hot_component_bytes": hot_component_bytes,
                "structural_payload_bytes": int(tier_bytes["structural"]),
                "support_payload_bytes": int(tier_bytes["support"]),
                "cold_payload_bytes": int(tier_bytes["cold"]),
                "outcome_payload_bytes": int(tier_bytes["outcomes"]),
                "steady_state_estimated_bytes_per_minute": round(
                    steady_state_bytes_per_minute, 1
                ),
                "projected_24x5_month_gib": round(projected_month_gib, 3),
                "target_month_gib": 3.5,
            },
            "execution_authority": False,
            "mutates_database": False,
        },
        "backend": _sanitize(backend),
    }
    return payload

def write_snapshot(output: Path) -> dict[str, Any]:
    previous = _load_previous_snapshot(output)
    payload = build_snapshot(previous=previous)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return payload


def _cache_busted_url(url: str, *, now: datetime | None = None) -> str:
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    bucket = int(current.timestamp() // 30)
    parts = urlsplit(str(url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_rizan_dashboard"] = str(bucket)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def validate_snapshot(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    fresh_seconds: float = FRESH_SECONDS,
    require_fresh: bool = True,
) -> dict[str, Any]:
    data = dict(payload or {})
    if str(data.get("contract") or "") != CONTRACT:
        raise ValueError("dashboard bridge snapshot contract mismatch")
    backend = dict(data.get("backend") or {})
    required = {
        "control",
        "heartbeats",
        "xau_signals",
        "afic_forecast_states",
        "afic_prepared_plans",
        "xau_execution_events",
        "xau_geometry_events",
    }
    missing = sorted(required.difference(backend))
    if missing:
        raise ValueError("dashboard bridge missing fields: " + ",".join(missing))

    observed = _timestamp(data.get("as_of"))
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    age = None if observed is None else max(
        0.0, (current - observed).total_seconds()
    )
    fresh = bool(age is not None and age <= float(fresh_seconds))
    data["bridge"] = {
        "source": "GITHUB_FOREXRIZAN_DASHBOARD_SNAPSHOT",
        "observed_at": None if observed is None else observed.isoformat(),
        "age_seconds": age,
        "fresh": fresh,
        "fresh_seconds": float(fresh_seconds),
    }
    if require_fresh and not fresh:
        raise ValueError(
            "dashboard bridge snapshot stale"
            if age is not None
            else "dashboard bridge snapshot timestamp missing"
        )
    return data


def fetch_snapshot(
    url: str = DEFAULT_SNAPSHOT_URL,
    *,
    timeout_seconds: float = 20.0,
    now: datetime | None = None,
    opener: Callable[..., Any] = urlopen,
    require_fresh: bool = True,
) -> dict[str, Any]:
    request = Request(
        _cache_busted_url(str(url), now=now),
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": "RIZAN-XAU-Dashboard/1.0",
            "Cache-Control": "no-cache",
        },
    )
    with opener(request, timeout=float(timeout_seconds)) as response:
        try:
            raw = response.read(MAX_SNAPSHOT_BYTES + 1)
        except TypeError:
            # Lightweight test/custom openers may implement read() without a size argument.
            raw = response.read()
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise ValueError("dashboard bridge snapshot exceeds safety size limit")
        headers = getattr(response, "headers", None)
        encoding = ""
        if headers is not None:
            try:
                encoding = str(headers.get("Content-Encoding") or "").lower()
            except Exception:
                encoding = ""
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    return validate_snapshot(payload, now=now, require_fresh=require_fresh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="runtime/xau_dashboard_snapshot.json",
    )
    args = parser.parse_args(argv)
    output = Path(args.output)
    payload = write_snapshot(output)
    backend = dict(payload.get("backend") or {})
    control = dict(backend.get("control") or {})
    print(
        "RIZAN_DASHBOARD_BRIDGE_V254 "
        f"as_of={payload.get('as_of')} "
        f"heartbeats={len(list(backend.get('heartbeats') or []))} "
        f"xau_signals={len(list(backend.get('xau_signals') or []))} "
        f"execution_mode={control.get('execution_mode') or 'UNKNOWN'} "
        f"new_orders_enabled={bool(control.get('new_orders_enabled'))} "
        f"structural_reused={bool(dict(payload.get('source') or {}).get('structural_reused'))} "
        f"support_reused={bool(dict(payload.get('source') or {}).get('support_reused'))} "
        f"cold_reused={bool(dict(payload.get('source') or {}).get('cold_reused'))} "
        f"outcomes_reused={bool(dict(payload.get('source') or {}).get('outcomes_reused'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
