from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_forecast_ensemble_v171 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    build_forecast_ensemble,
    empirical_conditional_probability,
    fisher_acd_session_path,
    parse_cftc_gold_cot,
)
from .research_xau_m15_dual_strategy_runtime import _fetch_history
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_forecast_ensemble_v171"
HISTORY_TARGET = 20_000
CFTC_GOLD_URL = "https://www.cftc.gov/dea/futures/other_lf.htm"


def _rows(response: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in (getattr(response, "data", None) or [])]


def _latest_heartbeat(client: Any, worker_name: str) -> dict[str, Any] | None:
    response = (
        client.table("runtime_heartbeats")
        .select("worker_name,observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = _rows(response)
    return rows[0] if rows else None


def _latest_event(
    client: Any,
    *,
    event_type: str,
    code: str,
) -> dict[str, Any] | None:
    response = (
        client.table("broker_order_events")
        .select("observed_at,event_type,code,message,payload")
        .eq("event_type", event_type)
        .eq("code", code)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = _rows(response)
    return rows[0] if rows else None


def _load_afic_component(client: Any) -> dict[str, Any]:
    hb = _latest_heartbeat(
        client, "ctrader_demo_xau_afic_prepared_plan_producer"
    )
    event = _latest_event(
        client,
        event_type="DEMO_XAU_AFIC_FORECAST_STATE",
        code="XAU_AFIC_PATH_STATE_V1",
    )
    plan_event = _latest_event(
        client,
        event_type="DEMO_XAU_AFIC_PREPARED_PLAN",
        code="XAU_AFIC_PATH_PREPARED_V1",
    )

    details = {} if hb is None else dict(hb.get("details") or {})
    forecast = (
        {}
        if event is None
        else dict(dict(event.get("payload") or {}).get("forecast") or {})
    )
    plan_payload = {} if plan_event is None else dict(plan_event.get("payload") or {})
    prepared = dict(plan_payload.get("prepared_plan") or {})

    direction = str(
        details.get("continuation_direction")
        or forecast.get("continuation_direction")
        or ""
    ).upper()
    first_leg = str(forecast.get("first_leg_direction") or "").upper()
    zone = dict(forecast.get("zone") or {})
    zone_low = details.get("zone_low", zone.get("low"))
    zone_high = details.get("zone_high", zone.get("high"))
    grade = str(
        details.get("forecast_selector_grade")
        or prepared.get("selector_grade")
        or ""
    ).upper()
    state = str(
        details.get("forecast_state")
        or forecast.get("state")
        or ""
    ).upper()
    invalidation = prepared.get("invalidation_close")
    if invalidation is None:
        # This fallback is only a displayed structural boundary, not an
        # execution stop. The AFIC producer remains authoritative for orders.
        if direction == "LONG":
            invalidation = zone_low
        elif direction == "SHORT":
            invalidation = zone_high

    available = direction in {"LONG", "SHORT"}
    return {
        "available": available,
        "direction": direction if available else "NEUTRAL",
        "grade": grade or None,
        "state": state or None,
        "map_at": details.get("map_at") or forecast.get("map_at"),
        "observed_at": None if hb is None else hb.get("observed_at"),
        "zone": {"low": zone_low, "high": zone_high},
        "invalidation": invalidation,
        "path": {
            "first_leg": first_leg or None,
            "reaction_zone": {"low": zone_low, "high": zone_high},
            "continuation": direction if available else None,
        },
        "execution_influence": False,
        "note": (
            "V171 reads AFIC state for dashboard consensus only. "
            "AFIC V161 remains the sole structural execution authority."
        ),
    }


def _load_v170(client: Any) -> dict[str, Any]:
    hb = _latest_heartbeat(client, "ctrader_xau_expected_move_envelope_v170")
    if hb is None:
        return {"available": False, "reason": "V170_HEARTBEAT_MISSING"}
    details = dict(hb.get("details") or {})
    evaluation = dict(details.get("evaluation") or {})
    current = dict(evaluation.get("current_envelope") or {})
    if not current:
        return {
            "available": False,
            "reason": "V170_CURRENT_ENVELOPE_MISSING",
            "observed_at": hb.get("observed_at"),
        }
    return {
        "available": True,
        "observed_at": hb.get("observed_at"),
        "as_of": current.get("as_of"),
        "price": current.get("price"),
        "lookback_matches": current.get("lookback_matches"),
        "horizons": current.get("horizons"),
        "validation": evaluation.get("validation"),
        "method": "XAU_EXPECTED_MOVE_ENVELOPE_V170",
        "directional_vote": False,
    }


def _load_cot() -> dict[str, Any]:
    request = Request(
        CFTC_GOLD_URL,
        headers={
            "User-Agent": (
                "ForexScannerResearch/1.0 "
                "(official CFTC public report; shadow research only)"
            )
        },
    )
    try:
        with urlopen(request, timeout=12) as response:
            text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {
            "available": False,
            "reason": f"CFTC_FETCH_FAILED:{type(exc).__name__}",
            "source": CFTC_GOLD_URL,
        }
    result = parse_cftc_gold_cot(text)
    result["source_url"] = CFTC_GOLD_URL
    return result


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_FORECAST_ENSEMBLE_V171_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_FORECAST_ENSEMBLE_V171_REQUIRE_DEMO")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("XAU_FORECAST_ENSEMBLE_V171_SYMBOL_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    store = SupabaseOperationalStore.from_env()
    afic = _load_afic_component(store.client)
    v170 = _load_v170(store.client)

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_history(feed, target=HISTORY_TARGET, as_of=now)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    conditional = empirical_conditional_probability(bars)
    acd = fisher_acd_session_path(bars)
    cot = _load_cot()

    ensemble = build_forecast_ensemble(
        afic=afic,
        expected_move=v170,
        conditional=conditional,
        acd=acd,
        cot=cot,
    )
    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "live_execution_enabled": False,
        "observed_at": now.isoformat(),
        "history_target_bars": HISTORY_TARGET,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
        "ensemble": ensemble,
        "source_freshness": {
            "afic_observed_at": afic.get("observed_at"),
            "v170_observed_at": v170.get("observed_at"),
            "cot_report_label": cot.get("report_label"),
        },
        "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
    }
    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )

    path = Path(
        os.getenv(
            "V171_OUTPUT",
            "artifacts/xau-forecast-ensemble-v171.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": details,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )

    primary = dict(ensemble.get("primary_scenario") or {})
    print(
        "V171_RESULT "
        f"bars={len(bars)} primary={primary.get('direction')} "
        f"confidence={primary.get('confidence')} coverage={ensemble.get('coverage')} "
        f"cot_available={cot.get('available')} execution_influence=0 artifact={path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
