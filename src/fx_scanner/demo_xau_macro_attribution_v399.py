from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .config import load_project_config
from .demo_xau_macro_attribution_v357 import (
    DAILY_CROSS_ASSET_REFRESH_SECONDS,
    FRED_SPECS,
    WORKER_NAME,
    _cross_asset_row,
    _dt,
    _event_context,
    _latest_worker_details,
    build_dashboard_projection,
)
from .demo_xau_macro_attribution_v398 import _fetch_intraday_market, _market_error
from .providers.factory import build_provider_runtime
from .storage.supabase_operational import SupabaseOperationalStore
from .xau_intraday_macro_v398 import (
    CONTRACT as INTRADAY_MACRO_CONTRACT,
    build_intraday_macro_confirmation,
    evaluate_dxy_pressure,
    evaluate_fed_funds_futures_pressure,
)
from .xau_intraday_yield_v367 import (
    evaluate_intraday_yield_pressure,
    evaluate_post_event_yield_reversal,
    fetch_intraday_us10y,
    select_latest_post_release_event,
)
from .xau_macro_attribution_v357 import CONTRACT as BASE_CONTRACT, evaluate_broader_macro_bias
from .xau_treasury_session_v399 import (
    CONTRACT as TREASURY_SESSION_CONTRACT,
    evaluate_treasury_futures_pressure,
    resolve_us10y_session_context,
)

CONTRACT = "XAU_MACRO_ATTRIBUTION_V399"


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

    cash_cfg = dict(
        dict(cfg.providers.get("intraday_market") or {}).get("US10Y_YAHOO_TNX") or {}
    )
    anchor = select_latest_post_release_event(
        event_context,
        now=now,
        max_age_hours=float(cash_cfg.get("post_event_window_hours") or 8.0),
    )
    cash_us10y: dict[str, Any]
    cash_source_status = "DISABLED"
    if bool(cash_cfg.get("enabled", False)):
        try:
            points = fetch_intraday_us10y(
                base_url=str(cash_cfg["base_url"]),
                allowed_host=str(cash_cfg["allowed_host"]),
                interval=str(cash_cfg.get("interval") or "1m"),
                range_name=str(cash_cfg.get("range") or "1d"),
                timeout_seconds=float(
                    dict(cfg.providers.get("transport") or {}).get("timeout_seconds") or 10.0
                ),
            )
            cash_us10y = evaluate_intraday_yield_pressure(
                points,
                now=now,
                max_age_seconds=float(cash_cfg.get("max_age_seconds") or 1200.0),
                window_minutes=float(cash_cfg.get("pressure_window_minutes") or 120.0),
                flat_threshold_bps=float(cash_cfg.get("flat_threshold_bps") or 1.0),
            )
            cash_us10y["freshness"] = "FRESH" if cash_us10y.get("available") else (
                "STALE" if cash_us10y.get("current") is not None else "MISSING"
            )
            if anchor:
                cash_us10y["post_event_diagnostic"] = evaluate_post_event_yield_reversal(
                    points,
                    event=anchor,
                    now=now,
                    max_age_seconds=float(cash_cfg.get("max_age_seconds") or 1200.0),
                    minimum_initial_drop_bps=float(
                        cash_cfg.get("minimum_initial_drop_bps") or 1.5
                    ),
                    reversal_threshold_bps=float(
                        cash_cfg.get("reversal_threshold_bps") or 3.0
                    ),
                    strong_reversal_threshold_bps=float(
                        cash_cfg.get("strong_reversal_threshold_bps") or 5.0
                    ),
                )
            cash_source_status = "OK:" + str(cash_us10y.get("state") or "UNKNOWN")
        except Exception as exc:
            cash_us10y = _market_error(
                state="INTRADAY_YIELD_SOURCE_ERROR",
                source="YAHOO_FINANCE_TNX_INTRADAY_PROXY",
                exc=exc,
            )
            cash_source_status = f"ERROR:{type(exc).__name__}:{exc}"
    else:
        cash_us10y = _market_error(
            state="INTRADAY_YIELD_DISABLED",
            source="YAHOO_FINANCE_TNX_INTRADAY_PROXY",
        )

    treasury_futures, treasury_futures_status = _fetch_intraday_market(
        cfg,
        key="US10Y_FUTURES_YAHOO_ZN",
        evaluator=evaluate_treasury_futures_pressure,
        now=now,
        source="YAHOO_FINANCE_ZN_FRONT_PROXY",
        threshold_name="flat_threshold_points",
        default_threshold=0.03125,
    )
    treasury_context = resolve_us10y_session_context(
        cash_yield=cash_us10y,
        treasury_futures=treasury_futures,
    )

    dxy_intraday, dxy_source_status = _fetch_intraday_market(
        cfg,
        key="DXY_YAHOO_ICE",
        evaluator=evaluate_dxy_pressure,
        now=now,
        source="YAHOO_FINANCE_ICE_DXY_PROXY",
        threshold_name="flat_threshold_pct",
        default_threshold=0.05,
    )
    fed_funds_intraday, fed_funds_source_status = _fetch_intraday_market(
        cfg,
        key="FED_FUNDS_YAHOO_ZQ",
        evaluator=evaluate_fed_funds_futures_pressure,
        now=now,
        source="YAHOO_FINANCE_ZQ_FRONT_PROXY",
        threshold_name="flat_threshold_bps",
        default_threshold=1.0,
    )

    evaluation = evaluate_broader_macro_bias(
        cross_asset=cross_asset,
        event_context=event_context,
        intraday_yield_context=treasury_context,
    )
    intraday_confirmation = build_intraday_macro_confirmation(
        dxy=dxy_intraday,
        fed_funds=fed_funds_intraday,
        us10y=treasury_context,
        broader_macro_bias=str(evaluation.get("broader_macro_bias") or "UNAVAILABLE"),
    )

    evaluation["contract_base"] = BASE_CONTRACT
    evaluation["contract"] = CONTRACT
    evaluation["intraday_macro_contract"] = INTRADAY_MACRO_CONTRACT
    evaluation["treasury_session_contract"] = TREASURY_SESSION_CONTRACT
    evaluation["intraday_macro_confirmation"] = intraday_confirmation
    evaluation["intraday_macro_bias"] = intraday_confirmation.get("intraday_macro_bias")
    evaluation["macro_confirmation_state"] = intraday_confirmation.get("state")
    evaluation["macro_confirmation_eligible"] = bool(
        intraday_confirmation.get("confirmation_eligible")
    )
    evaluation["macro_confirmation_relationship"] = intraday_confirmation.get(
        "relationship_to_broader_macro"
    )
    evaluation["dxy_intraday"] = dxy_intraday
    evaluation["fed_funds_futures"] = fed_funds_intraday
    evaluation["us10y_cash"] = cash_us10y
    evaluation["treasury_futures"] = treasury_futures
    evaluation["treasury_session"] = treasury_context

    projection = build_dashboard_projection(evaluation)
    projection.update(
        {
            "contract": CONTRACT,
            "intraday_macro_bias": evaluation.get("intraday_macro_bias"),
            "macro_confirmation_state": evaluation.get("macro_confirmation_state"),
            "macro_confirmation_eligible": evaluation.get("macro_confirmation_eligible"),
            "macro_confirmation_relationship": evaluation.get(
                "macro_confirmation_relationship"
            ),
            "dxy_intraday": {
                key: dxy_intraday.get(key)
                for key in (
                    "available",
                    "freshness",
                    "state",
                    "gold_implication",
                    "current",
                    "reference",
                    "net_pct",
                    "current_at",
                    "age_seconds",
                    "source",
                )
                if key in dxy_intraday
            },
            "fed_funds_futures": {
                key: fed_funds_intraday.get(key)
                for key in (
                    "available",
                    "freshness",
                    "state",
                    "gold_implication",
                    "current",
                    "reference",
                    "implied_rate_pct",
                    "implied_rate_change_bps",
                    "current_at",
                    "age_seconds",
                    "source",
                )
                if key in fed_funds_intraday
            },
            "us10y_cash": {
                key: cash_us10y.get(key)
                for key in (
                    "available",
                    "freshness",
                    "state",
                    "gold_implication",
                    "current",
                    "current_at",
                    "age_seconds",
                    "source",
                )
                if key in cash_us10y
            },
            "treasury_futures": {
                key: treasury_futures.get(key)
                for key in (
                    "available",
                    "freshness",
                    "state",
                    "yield_pressure",
                    "gold_implication",
                    "current",
                    "reference",
                    "change_points",
                    "change_pct",
                    "current_at",
                    "age_seconds",
                    "source",
                )
                if key in treasury_futures
            },
            "treasury_session": {
                key: treasury_context.get(key)
                for key in (
                    "available",
                    "freshness",
                    "state",
                    "session_state",
                    "gold_implication",
                    "current",
                    "current_at",
                    "last_cash_yield",
                    "last_cash_at",
                    "futures_price",
                    "futures_at",
                    "futures_change_points",
                    "futures_yield_pressure",
                    "effective_source",
                    "source",
                )
                if key in treasury_context
            },
            "macro_fresh_components": intraday_confirmation.get("fresh_components"),
            "macro_stale_or_missing_components": intraday_confirmation.get(
                "stale_or_missing_components"
            ),
        }
    )

    healthy = bool(evaluation.get("available_components"))
    details = {
        "contract": CONTRACT,
        "symbol": "XAUUSD",
        "observed_at": now.isoformat(),
        "evaluation": evaluation,
        "dashboard_projection": projection,
        "cross_asset": cross_asset,
        "cross_asset_refreshed_at": cross_asset_refreshed_at,
        "cross_asset_refresh_mode": cross_asset_refresh_mode,
        "intraday_us10y": treasury_context,
        "us10y_cash": cash_us10y,
        "treasury_futures": treasury_futures,
        "treasury_session": treasury_context,
        "dxy_intraday": dxy_intraday,
        "fed_funds_futures": fed_funds_intraday,
        "intraday_macro_confirmation": intraday_confirmation,
        "source_status": {
            "us10y_cash": cash_source_status,
            "treasury_futures": treasury_futures_status,
            "dxy": dxy_source_status,
            "fed_funds": fed_funds_source_status,
        },
        "event_observed_at": event_observed_at,
        "data_policy": {
            "cross_asset_frequency": "DAILY_WITH_15M_REUSE",
            "intraday_runtime_target": "15_MINUTES",
            "us10y_cash_source": "YAHOO_FINANCE_TNX_SECONDARY_PROXY",
            "us10y_cash_policy": "LAST_VALID_VISIBLE_BUT_NOT_LIVE_WHEN_STALE",
            "treasury_futures_source": "YAHOO_FINANCE_ZN_FRONT_CME_10Y_NOTE_FUTURES_PROXY",
            "treasury_session_policy": "PREFER_FRESH_CASH_ELSE_FRESH_ZN_DIRECTION_PROXY",
            "dxy_source": "YAHOO_FINANCE_DX-Y.NYB_ICE_INDEX_SECONDARY_FEED",
            "fed_repricing": "YAHOO_FINANCE_ZQ_FRONT_30D_FED_FUNDS_FUTURES_PROXY",
            "fedwatch_note": "NOT_CME_FEDWATCH_PROBABILITY_OUTPUT",
            "stale_policy": "FAIL_CLOSED_FOR_CONFIRMATION",
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
        "CTRADER_DEMO_XAU_MACRO_ATTRIBUTION_V399 "
        f"healthy={int(healthy)} "
        f"broad={evaluation.get('broader_macro_bias')} "
        f"intraday={evaluation.get('intraday_macro_bias')} "
        f"confirm={evaluation.get('macro_confirmation_state')} "
        f"eligible={int(bool(evaluation.get('macro_confirmation_eligible')))} "
        f"treasury={treasury_context.get('state')} "
        f"cash={cash_us10y.get('state')} "
        f"zn={treasury_futures.get('state')} "
        f"dxy={dxy_intraday.get('state')} "
        f"fed={fed_funds_intraday.get('state')}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
