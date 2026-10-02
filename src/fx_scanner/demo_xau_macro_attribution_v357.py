from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import load_project_config
from .providers.factory import build_provider_runtime
from .providers.semantics import ProviderStatus
from .storage.supabase_operational import SupabaseOperationalStore
from .xau_macro_attribution_v357 import CONTRACT, evaluate_broader_macro_bias

WORKER_NAME = "ctrader_demo_xau_macro_attribution_v357"
EVENT_WORKER = "ctrader_demo_xau_event_risk_v192"

FRED_SPECS = {
    "USD_BROAD_PROXY": {
        "series": "DTWEXBGS",
        "kind": "PCT",
        "max_age_seconds": 7 * 24 * 60 * 60,
    },
    "US2Y": {
        "series": "DGS2",
        "kind": "BPS",
        "max_age_seconds": 5 * 24 * 60 * 60,
    },
    "US10Y": {
        "series": "DGS10",
        "kind": "BPS",
        "max_age_seconds": 5 * 24 * 60 * 60,
    },
    "REAL_YIELD_10Y": {
        "series": "DFII10",
        "kind": "BPS",
        "max_age_seconds": 5 * 24 * 60 * 60,
    },
}


def _event_context(store: SupabaseOperationalStore) -> tuple[dict[str, Any], str | None]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", EVENT_WORKER)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return {}, None
    row = dict(rows[0])
    details = dict(row.get("details") or {})
    return dict(details.get("risk") or {}), row.get("observed_at")


def _cross_asset_row(result: Any, *, kind: str) -> dict[str, Any]:
    status = getattr(result, "status", ProviderStatus.MISSING)
    observation = getattr(result, "value", None)
    freshness = getattr(result, "freshness", None)
    provenance = getattr(result, "provenance", None)

    if status in {ProviderStatus.AVAILABLE, ProviderStatus.PARTIAL}:
        freshness_state = "FRESH"
    elif status == ProviderStatus.STALE:
        freshness_state = "STALE"
    else:
        freshness_state = "MISSING"

    current = None if observation is None else observation.value
    previous = None if observation is None else observation.previous_value
    delta = None
    if current is not None and previous is not None:
        if kind == "PCT":
            delta = None if previous == 0 else (float(current) / float(previous) - 1.0) * 100.0
        elif kind == "BPS":
            delta = (float(current) - float(previous)) * 100.0

    return {
        "series": None if provenance is None else provenance.series,
        "provider": None if provenance is None else provenance.provider,
        "source_url": None if provenance is None else provenance.source_url,
        "provider_status": str(getattr(status, "value", status)),
        "freshness": freshness_state,
        "age_seconds": None if freshness is None else freshness.age_seconds,
        "observed_at": None if observation is None else observation.observed_at.isoformat(),
        "previous_observed_at": (
            None
            if observation is None or observation.previous_observed_at is None
            else observation.previous_observed_at.isoformat()
        ),
        "current": current,
        "previous": previous,
        "delta": delta,
        "delta_unit": "PCT" if kind == "PCT" else "BPS",
    }



MACRO_COMPONENT_DASHBOARD_KEYS = (
    "freshness",
    "current",
    "previous",
    "delta",
    "delta_unit",
    "score",
    "provider",
    "source",
)


def build_dashboard_projection(evaluation: dict[str, Any]) -> dict[str, Any]:
    components = {}
    for name, value in dict(evaluation.get("components") or {}).items():
        row = dict(value or {})
        components[name] = {
            key: row.get(key)
            for key in MACRO_COMPONENT_DASHBOARD_KEYS
            if key in row
        }
    fed_proxy = dict(evaluation.get("fed_repricing_proxy") or {})
    return {
        "state": evaluation.get("state"),
        "broader_macro_bias": evaluation.get("broader_macro_bias"),
        "macro_score": evaluation.get("macro_score"),
        "confidence": evaluation.get("confidence"),
        "coverage": evaluation.get("coverage"),
        "components": components,
        "event_consensus_bias": evaluation.get("event_consensus_bias"),
        "consensus_relationship": evaluation.get("consensus_relationship"),
        "fed_repricing_proxy": {
            key: fed_proxy.get(key)
            for key in ("state", "delta_bps")
            if key in fed_proxy
        },
        "execution_authority": bool(evaluation.get("execution_authority", False)),
        "execution_influence": bool(evaluation.get("execution_influence", False)),
    }

def run() -> int:
    now = datetime.now(tz=UTC)
    cfg = load_project_config(None)
    runtime = build_provider_runtime(cfg.providers)
    fred = runtime.providers["FEDERAL_RESERVE_FRED"]
    store = SupabaseOperationalStore.from_env()

    cross_asset: dict[str, dict[str, Any]] = {}
    for name, spec in FRED_SPECS.items():
        result = runtime.orchestrator.fetch(
            fred,
            str(spec["series"]),
            max_age_seconds=float(spec["max_age_seconds"]),
        )
        cross_asset[name] = _cross_asset_row(result, kind=str(spec["kind"]))

    event_context, event_observed_at = _event_context(store)
    evaluation = evaluate_broader_macro_bias(
        cross_asset=cross_asset,
        event_context=event_context,
    )
    healthy = bool(evaluation.get("available_components"))

    details = {
        "contract": CONTRACT,
        "symbol": "XAUUSD",
        "observed_at": now.isoformat(),
        "evaluation": evaluation,
        "dashboard_projection": build_dashboard_projection(evaluation),
        "cross_asset": cross_asset,
        "event_observed_at": event_observed_at,
        "data_policy": {
            "cross_asset_frequency": "DAILY",
            "dxy_proxy": "DTWEXBGS_NOT_ICE_DXY",
            "fed_repricing": "US2Y_DAILY_DELTA_PROXY_NOT_FUTURES",
            "execution_authority": False,
        },
    }
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "CTRADER_DEMO_XAU_MACRO_ATTRIBUTION_V357 "
        f"healthy={int(healthy)} "
        f"bias={evaluation.get('broader_macro_bias')} "
        f"score={evaluation.get('macro_score')} "
        f"coverage={evaluation.get('coverage')}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
