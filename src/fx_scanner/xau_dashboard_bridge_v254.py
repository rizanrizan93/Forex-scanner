from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .dashboard import SupabaseDashboardReader
from .storage.supabase_operational import SupabaseOperationalStore

CONTRACT = "XAU_RIZAN_DASHBOARD_BRIDGE_V254"
DEFAULT_SNAPSHOT_URL = (
    "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
    "dashboard-snapshots/runtime/xau_dashboard_snapshot.json"
)
FRESH_SECONDS = 180.0

CRITICAL_HEARTBEATS = (
    "ctrader_demo_xau_rizan_prepared_plan_producer",
    "ctrader_demo_xau_rizan_fast_handoff",
    "ctrader_demo_xau_afic_prepared_plan_producer",
    "ctrader_demo_xau_afic_fast_handoff",
    "ctrader_demo_xau_dom_v191",
    "ctrader_demo_xau_event_risk_v192",
    "ctrader_demo_xau_premap_candidate_v181",
    "ctrader_demo_xau_supply_demand_atlas_v182",
    "ctrader_demo_xau_supply_demand_prospective_v184",
    "ctrader_xau_supply_demand_reaction_v183",
    "ctrader_xau_supply_demand_timeframe_v185",
    "ctrader_demo_xau_v196_shadow_evidence",
    "ctrader_demo_xau_v198_evidence_analytics",
    "ctrader_demo_xau_v201_reaction_ladder",
    "ctrader_demo_xau_v203_volatility_shock_guard",
    "ctrader_demo_xau_v212_zone_reaction_probability",
    "ctrader_demo_xau_v213_post_zone_path",
    "ctrader_demo_xau_v214_pocket_lifecycle",
    "ctrader_demo_xau_v216_lifecycle_calibration",
    "ctrader_demo_xau_v217_direction_probability",
    "ctrader_demo_xau_v220_direction_prospective_calibration",
    "ctrader_demo_xau_v222_m5_pocket_quality",
    "ctrader_demo_xau_v223_m5_pocket_cluster_selector",
    "ctrader_demo_xau_v224_primary_pocket_prospective",
    "ctrader_demo_xau_v226_rizan_depth_map",
    "ctrader_demo_xau_v227_depth_map_prospective",
    "ctrader_demo_xau_v229_depth_execution",
    "ctrader_demo_xau_v229_child_executor",
    "ctrader_xau_expected_move_envelope_v170",
    "ctrader_xau_forecast_ensemble_v171",
    "ctrader_xau_htf_strategic_regime_v180",
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


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            lowered = key_s.lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
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


def build_snapshot() -> dict[str, Any]:
    from supabase import create_client

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

    run = reader.latest_run()
    account = reader.latest_broker_account()
    compact_heartbeats = reader.heartbeat_summaries()
    critical_heartbeats = reader.heartbeats_for_workers(list(CRITICAL_HEARTBEATS))

    backend = {
        "latest_run": run,
        "rankings": list(
            reader.rankings_for_run(None if run is None else run.get("id"))
        ),
        "signals": list(reader.latest_signals()),
        "xau_signals": list(reader.latest_signals_for_symbol("XAUUSD")),
        "heartbeats": _merge_heartbeats(compact_heartbeats, critical_heartbeats),
        "macro": list(reader.latest_macro()),
        "performance": list(reader.latest_performance()),
        "broker_account": account,
        "broker_positions": list(reader.broker_positions_for_account(account)),
        "afic_forecast_states": list(reader.latest_afic_forecast_states()),
        "afic_prepared_plans": list(reader.latest_afic_prepared_plans()),
        "afic_execution_geometry": list(reader.latest_afic_execution_geometry()),
        "xau_execution_events": list(reader.latest_xau_execution_events()),
        "xau_geometry_events": list(reader.latest_xau_geometry_events()),
        "xau_outcomes": list(reader.latest_xau_outcomes()),
        "xau_prepared_plan_lifecycle": list(
            reader.latest_xau_prepared_plan_lifecycle()
        ),
        "control": asdict(store.get_execution_control()),
    }

    project_ref = urlsplit(url).hostname or ""
    project_ref = project_ref.split(".", 1)[0]
    payload = {
        "contract": CONTRACT,
        "as_of": datetime.now(tz=UTC).isoformat(),
        "source": {
            "project_ref": project_ref,
            "mode": "SUPABASE_SERVICE_ROLE_TO_PUBLIC_READ_ONLY_BRIDGE",
            "dashboard_refresh_seconds": 60,
            "execution_authority": False,
            "mutates_database": False,
        },
        "backend": _sanitize(backend),
    }
    return payload


def write_snapshot(output: Path) -> dict[str, Any]:
    payload = build_snapshot()
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
    if not fresh:
        raise ValueError(
            "dashboard bridge snapshot stale"
            if age is not None
            else "dashboard bridge snapshot timestamp missing"
        )
    return data


def fetch_snapshot(
    url: str = DEFAULT_SNAPSHOT_URL,
    *,
    timeout_seconds: float = 8.0,
    now: datetime | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    request = Request(
        _cache_busted_url(str(url), now=now),
        headers={
            "Accept": "application/json",
            "User-Agent": "RIZAN-XAU-Dashboard/1.0",
            "Cache-Control": "no-cache",
        },
    )
    with opener(request, timeout=float(timeout_seconds)) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    return validate_snapshot(payload, now=now)


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
        f"new_orders_enabled={bool(control.get('new_orders_enabled'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
