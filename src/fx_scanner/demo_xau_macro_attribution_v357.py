from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import load_project_config
from .providers.factory import build_provider_runtime
from .providers.semantics import ProviderStatus
from .storage.supabase_operational import SupabaseOperationalStore
from .xau_intraday_yield_v367 import (
    evaluate_intraday_yield_pressure,
    evaluate_post_event_yield_reversal,
    fetch_intraday_us10y,
    select_latest_post_release_event,
)
from .xau_macro_attribution_v357 import CONTRACT, evaluate_broader_macro_bias

WORKER_NAME = "ctrader_demo_xau_macro_attribution_v357"
EVENT_WORKER = "ctrader_demo_xau_event_risk_v192"
DAILY_CROSS_ASSET_REFRESH_SECONDS = 15 * 60

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


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _latest_worker_details(store: SupabaseOperationalStore) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,details")
        .eq("worker_name", WORKER_NAME)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(dict(rows[0]).get("details") or {})


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
    intraday = dict(evaluation.get("intraday_yield_context") or {})
    return {
        "state": evaluation.get("state"),
        "broader_macro_bias": evaluation.get("broader_macro_bias"),
        "macro_score": evaluation.get("macro_score"),
        "confidence": evaluation.get("confidence"),
        "coverage": evaluation.get("coverage"),
        "components": components,
        "event_consensus_bias": evaluation.get("event_consensus_bias"),
        "consensus_relationship": evaluation.get("consensus_relationship"),
        "intraday_yield_state": evaluation.get("intraday_yield_state"),
        "post_event_macro_state": evaluation.get("post_event_macro_state"),
        "post_event_gold_pressure": evaluation.get("post_event_gold_pressure"),
        "event_intraday_relationship": evaluation.get("event_intraday_relationship"),
        "intraday_yield_context": {
            key: intraday.get(key)
            for key in (
                "available",
                "state",
                "gold_implication",
                "current",
                "current_at",
                "reference",
                "reference_at",
                "window_minutes",
                "window_high",
                "window_low",
                "net_bps",
                "rebound_from_low_bps",
                "pullback_from_high_bps",
                "age_seconds",
                "source",
                "post_event_diagnostic",
            )
            if key in intraday
        },
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

    previous_details = _latest_worker_details(store)
    previous_refresh_at = _dt(previous_details.get("cross_asset_refreshed_at"))
    previous_cross_asset = dict(previous_details.get("cross_asset") or {})
    reuse_daily = bool(
        previous_refresh_at
        and previous_cross_asset
        and 0.0 <= (now - previous_refresh_at).total_seconds()
        <= DAILY_CROSS_ASSET_REFRESH_SECONDS
    )
    if reuse_daily:
        cross_asset = {
            str(name): dict(value or {})
            for name, value in previous_cross_asset.items()
        }
        cross_asset_refreshed_at = previous_refresh_at.isoformat()
        cross_asset_refresh_mode = "REUSED_PRIOR_HEARTBEAT"
    else:
        cross_asset: dict[str, dict[str, Any]] = {}
        for name, spec in FRED_SPECS.items():
            result = runtime.orchestrator.fetch(
                fred,
                str(spec["series"]),
                max_age_seconds=float(spec["max_age_seconds"]),
            )
            cross_asset[name] = _cross_asset_row(result, kind=str(spec["kind"]))
        cross_asset_refreshed_at = now.isoformat()
        cross_asset_refresh_mode = "REFRESHED_FRED"

    event_context, event_observed_at = _event_context(store)
    intraday_cfg = dict(
        dict(cfg.providers.get("intraday_market") or {}).get("US10Y_YAHOO_TNX") or {}
    )
    anchor = select_latest_post_release_event(
        event_context,
        now=now,
        max_age_hours=float(intraday_cfg.get("post_event_window_hours") or 8.0),
    )
    intraday_yield: dict[str, Any]
    intraday_source_status = "DISABLED"
    if bool(intraday_cfg.get("enabled", False)):
        try:
            points = fetch_intraday_us10y(
                base_url=str(intraday_cfg["base_url"]),
                allowed_host=str(intraday_cfg["allowed_host"]),
                interval=str(intraday_cfg.get("interval") or "1m"),
                range_name=str(intraday_cfg.get("range") or "1d"),
                timeout_seconds=float(
                    dict(cfg.providers.get("transport") or {}).get("timeout_seconds") or 10.0
                ),
            )
            intraday_yield = evaluate_intraday_yield_pressure(
                points,
                now=now,
                max_age_seconds=float(intraday_cfg.get("max_age_seconds") or 1200.0),
                window_minutes=float(intraday_cfg.get("pressure_window_minutes") or 120.0),
                flat_threshold_bps=float(intraday_cfg.get("flat_threshold_bps") or 1.0),
            )
            if anchor:
                post_event = evaluate_post_event_yield_reversal(
                    points,
                    event=anchor,
                    now=now,
                    max_age_seconds=float(intraday_cfg.get("max_age_seconds") or 1200.0),
                    minimum_initial_drop_bps=float(
                        intraday_cfg.get("minimum_initial_drop_bps") or 1.5
                    ),
                    reversal_threshold_bps=float(
                        intraday_cfg.get("reversal_threshold_bps") or 3.0
                    ),
                    strong_reversal_threshold_bps=float(
                        intraday_cfg.get("strong_reversal_threshold_bps") or 5.0
                    ),
                )
                intraday_yield["post_event_diagnostic"] = post_event
            intraday_source_status = "OK:" + str(intraday_yield.get("state") or "UNKNOWN")
        except Exception as exc:
            intraday_yield = {
                "available": False,
                "state": "INTRADAY_YIELD_SOURCE_ERROR",
                "gold_implication": "UNAVAILABLE",
                "source": "YAHOO_FINANCE_TNX_INTRADAY_PROXY",
                "error": f"{type(exc).__name__}:{exc}",
                "execution_authority": False,
                "execution_influence": False,
            }
            intraday_source_status = f"ERROR:{type(exc).__name__}:{exc}"
    else:
        intraday_yield = {
            "available": False,
            "state": "INTRADAY_YIELD_DISABLED",
            "gold_implication": "UNAVAILABLE",
            "source": "YAHOO_FINANCE_TNX_INTRADAY_PROXY",
            "execution_authority": False,
            "execution_influence": False,
        }

    evaluation = evaluate_broader_macro_bias(
        cross_asset=cross_asset,
        event_context=event_context,
        intraday_yield_context=intraday_yield,
    )
    healthy = bool(evaluation.get("available_components"))

    details = {
        "contract": CONTRACT,
        "symbol": "XAUUSD",
        "observed_at": now.isoformat(),
        "evaluation": evaluation,
        "dashboard_projection": build_dashboard_projection(evaluation),
        "cross_asset": cross_asset,
        "cross_asset_refreshed_at": cross_asset_refreshed_at,
        "cross_asset_refresh_mode": cross_asset_refresh_mode,
        "intraday_us10y": intraday_yield,
        "intraday_source_status": intraday_source_status,
        "event_observed_at": event_observed_at,
        "data_policy": {
            "cross_asset_frequency": "DAILY_WITH_15M_REUSE",
            "intraday_us10y_frequency": "RUNTIME_CYCLE",
            "intraday_us10y_source": "YAHOO_FINANCE_TNX_SECONDARY_PROXY",
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
        f"coverage={evaluation.get('coverage')} "
        f"intraday_yield={evaluation.get('intraday_yield_state')} "
        f"post_event={evaluation.get('post_event_macro_state')}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())