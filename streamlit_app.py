from __future__ import annotations

import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_scanner import __version__
from fx_scanner.config import ProjectConfig, load_project_config
from fx_scanner.dashboard import DashboardReadError, SupabaseDashboardReader
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.providers.factory import build_provider_runtime
from fx_scanner.storage.supabase_operational import (
    OperationalStoreUnavailable,
    SupabaseOperationalStore,
)

UTC = timezone.utc

st.set_page_config(
    page_title="FX Institutional Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        raw = st.secrets.get(name, "")
    except Exception:
        raw = ""
    return str(raw).strip()


@st.cache_resource(show_spinner=False)
def _supabase_client(url: str, secret_key: str):
    from supabase import create_client

    return create_client(url, secret_key)


@st.cache_data(ttl=15, show_spinner=False)
def _load_backend_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    snapshot = reader.snapshot()
    store = SupabaseOperationalStore(url, secret_key, client=client)
    control = store.get_execution_control()

    return {
        "latest_run": snapshot.latest_run,
        "rankings": list(snapshot.rankings),
        "signals": list(snapshot.signals),
        "heartbeats": list(snapshot.heartbeats),
        "macro": list(snapshot.macro),
        "performance": list(snapshot.performance),
        "control": asdict(control),
        "broker_account": snapshot.broker_account,
        "broker_positions": list(snapshot.broker_positions),
        "afic_forecast_states": list(snapshot.afic_forecast_states),
        "afic_prepared_plans": list(snapshot.afic_prepared_plans),
        "afic_execution_geometry": list(snapshot.afic_execution_geometry),
        "xau_execution_events": list(snapshot.xau_execution_events),
    }


@st.cache_data(ttl=60, show_spinner=False)
def _provider_smoke_rows() -> list[dict[str, Any]]:
    cfg = load_project_config(ROOT)
    runtime = build_provider_runtime(cfg.providers)
    rows: list[dict[str, Any]] = []
    for smoke_name, item in cfg.providers["smoke_series"].items():
        provider_name = str(item["provider"])
        provider = runtime.providers[provider_name]
        result = runtime.orchestrator.fetch(
            provider,
            str(item["series"]),
            max_age_seconds=float(item["max_age_seconds"]),
        )
        observation = result.value
        freshness = result.freshness
        rows.append(
            {
                "check": smoke_name,
                "provider": provider_name,
                "series": item["series"],
                "status": result.status.value,
                "value": None if observation is None else observation.value,
                "observed_at": None
                if observation is None
                else observation.observed_at.isoformat(),
                "age_seconds": None
                if freshness is None
                else round(float(freshness.age_seconds), 1),
                "message": result.message,
            }
        )
    return rows


def _safe_config() -> tuple[ProjectConfig | None, str | None]:
    try:
        return load_project_config(ROOT), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _frame(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _state_rank(state: str) -> int:
    order = {
        "EXECUTION_READY": 0,
        "ARMED": 1,
        "SETUP_FORMING": 2,
        "WATCH": 3,
        "NO_TRADE": 4,
        "MISSED": 5,
        "INVALIDATED": 6,
        "COOLDOWN": 7,
    }
    return order.get(str(state).upper(), 99)



def _latest_heartbeat(rows: list[dict[str, Any]], worker_name: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("worker_name") or "") == worker_name:
            return row
    return None


def _fmt_price(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_distance(value: Any, suffix: str = "") -> str:
    try:
        return f"{float(value):,.2f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def _afic_path_text(direction: str, state: str) -> str:
    side = str(direction or "").upper()
    current = str(state or "").upper()
    if side == "LONG":
        base = "First leg turun → reaction zone → M15 rejection → continuation naik"
    elif side == "SHORT":
        base = "First leg naik → reaction zone → M15 rejection → continuation turun"
    else:
        base = "Menunggu map H4 yang valid"
    if "INVALID" in current or "REMAP" in current:
        return base + " • map sebelumnya invalid/remap"
    if "CONFIRMED" in current:
        return base + " • confirmation selesai"
    if "TOUCHED" in current:
        return base + " • zone sudah disentuh, menunggu confirmation"
    if "APPROACH" in current:
        return base + " • harga sedang mendekati zone"
    return base




def _age_seconds(value: Any) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return max(0.0, (datetime.now(tz=UTC) - parsed.astimezone(UTC)).total_seconds())


def _afic_next_action(
    *,
    state: str,
    grade: str,
    proximity: str,
    auto_enabled: bool,
    latest_execution_event: str | None,
) -> tuple[str, str]:
    state_u = str(state or "").upper()
    grade_u = str(grade or "").upper()
    proximity_u = str(proximity or "").upper()
    event_u = str(latest_execution_event or "").upper()

    if event_u == "POSITION_PROTECTION_FAILED":
        return "PROTECTION ALERT", "Order side-effect exists; new AFIC orders must remain blocked until SL/TP is reconciled."
    if event_u == "POSITION_PROTECTION_VERIFIED":
        return "POSITION MANAGED", "Broker position exists and server-side protection has been verified."
    if event_u == "ORDER_ACCEPTED":
        return "VERIFYING SL/TP", "Broker accepted the order; scanner is waiting for protection verification."
    if "INVALID" in state_u or "REMAP" in state_u:
        return "WAIT NEW H4 MAP", "Current path is invalidated; no order should be sent until H4 remaps."
    if grade_u not in {"A"}:
        return "WATCH ONLY", f"Selector grade {grade_u or '—'} is not execution-authorized."
    if not auto_enabled:
        return "AUTO BLOCKED", "DEMO execution authority or exact handoff is not active."
    if "CONFIRMED" in state_u:
        return "EXECUTION HANDOFF", "M15 confirmation is complete; fresh quote/risk/protection checks decide the order now."
    if "TOUCHED" in state_u or proximity_u == "IN_ZONE":
        return "WAIT M15 CONFIRM", "Price is in the reaction zone; do not enter before the completed M15 trigger."
    if proximity_u == "NEAR_ZONE":
        return "PREPARED / 60S WATCH", "Price is near the zone; scanner is armed and checks every minute."
    if proximity_u == "FAR":
        return "TRACK TO ZONE", "Forecast is mapped; scanner is waiting for price to approach the reaction zone."
    return "WAIT FORECAST", "No execution-ready AFIC path is active yet."


cfg, config_error = _safe_config()
policy = None
policy_error = None
try:
    policy = load_execution_policy(ROOT)
except Exception as exc:
    policy_error = f"{type(exc).__name__}: {exc}"

supabase_url = _secret("SUPABASE_URL")
supabase_secret = _secret("SUPABASE_SECRET_KEY") or _secret(
    "SUPABASE_SERVICE_ROLE_KEY"
)
backend_configured = bool(supabase_url and supabase_secret)

backend: dict[str, Any] | None = None
backend_error: str | None = None
if backend_configured:
    try:
        backend = _load_backend_snapshot(supabase_url, supabase_secret)
    except (DashboardReadError, OperationalStoreUnavailable, Exception) as exc:
        backend_error = f"{type(exc).__name__}: {exc}"

with st.sidebar:
    st.title("FX Scanner")
    st.caption(f"Engine v{__version__}")

    if st.button("Refresh dashboard", use_container_width=True):
        _load_backend_snapshot.clear()
        st.rerun()
    auto_refresh_enabled = st.toggle(
        "Auto refresh monitor",
        value=True,
        help="Refresh the read-only dashboard every 15 seconds. Scanner/order runtime is independent.",
    )

    st.divider()
    st.markdown("**Runtime model**")
    st.write("Research/decision engine runs outside Streamlit.")
    st.write("Streamlit only reads durable snapshots and health state.")

    st.divider()
    st.markdown("**Backend**")
    if backend_configured and backend is not None:
        st.success("Supabase connected")
    elif backend_configured:
        st.error("Supabase connection error")
    else:
        st.warning("Supabase Secret not configured")

    st.markdown("**Execution safety**")
    if policy is not None and str(policy.ctrader.get("environment", "")).upper() == "DEMO":
        st.code("DEMO AUTO CAPABLE / LIVE OFF", language=None)
    else:
        st.code("LIVE EXECUTION NOT AUTHORIZED", language=None)


if "dashboard_auto_refresh_at" not in st.session_state:
    st.session_state["dashboard_auto_refresh_at"] = datetime.now(tz=UTC)


@st.fragment(run_every="15s")
def _dashboard_auto_refresh_tick() -> None:
    if not auto_refresh_enabled:
        return
    now = datetime.now(tz=UTC)
    last = st.session_state.get("dashboard_auto_refresh_at")
    if not isinstance(last, datetime) or (now - last).total_seconds() >= 14.5:
        st.session_state["dashboard_auto_refresh_at"] = now
        _load_backend_snapshot.clear()
        st.rerun()


_dashboard_auto_refresh_tick()


st.title("FX Institutional Scanner")
st.caption(
    "Fast research dashboard • Top-8 macro shortlist • Top-5 MTF deep scan • "
    "Streamlit is not in the quote/order hot path."
)

if config_error:
    st.error(f"Configuration invalid: {config_error}")
if policy_error:
    st.error(f"Execution policy invalid: {policy_error}")
if backend_error:
    st.warning(f"Backend snapshot unavailable: {backend_error}")

mode = "—" if cfg is None else str(cfg.risk.get("mode", "—"))
pairs = 0 if cfg is None else len(cfg.pairs)
fast_setup = "—"
execution_watch = "—"
if policy is not None:
    fast_setup = f"{policy.scheduler['fast_setup_seconds']:.0f}s"
    execution_watch = f"{policy.scheduler['execution_watch_seconds'] * 1000:.0f} ms"

backend_label = (
    "CONNECTED"
    if backend is not None
    else "ERROR"
    if backend_configured
    else "OFFLINE"
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Risk Mode", mode)
m2.metric("Pairs", pairs)
m3.metric("Top-5 Scan Cadence", fast_setup)
m4.metric("Execution Watch", execution_watch)
m5.metric("Dashboard Backend", backend_label)

if backend is not None:
    control = backend["control"]
    demo_locked = bool(
        policy is not None
        and str(policy.ctrader.get("environment", "")).upper() == "DEMO"
        and bool(policy.ctrader.get("require_demo", False))
    )
    mode_now = str(control.get("execution_mode", "")).upper()
    orders_now = bool(control.get("new_orders_enabled"))
    emergency_now = bool(control.get("emergency_stop"))
    if demo_locked and mode_now == "AUTO" and orders_now and not emergency_now:
        st.success(
            "DEMO automation armed • new orders ON • server-side SL/TP required • "
            "LIVE-money execution remains locked out by cTrader DEMO policy."
        )
    elif mode_now == "DISABLED" or emergency_now or not orders_now:
        st.info(
            f"Execution control: {mode_now or 'UNKNOWN'} • "
            f"new orders {'ON' if orders_now else 'OFF'} • "
            f"emergency stop {'ON' if emergency_now else 'OFF'}"
        )
    else:
        st.warning("Execution-control state is not the expected bounded DEMO profile.")
else:
    st.info(
        "Dashboard can be deployed now. Durable ranking/signal data will appear "
        "after Supabase backend credentials and runtime snapshots are available."
    )

forecast_tab, account_tab, scanner_tab, data_tab, system_tab, validation_tab = st.tabs(
    ["XAU Forecast", "Account & Positions", "Scanner", "Macro & Data", "System", "Validation"]
)

with forecast_tab:
    st.subheader("XAUUSD Forecast & Reaction Zone")

    heartbeats = [] if backend is None else backend.get("heartbeats", [])
    prepared_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_afic_prepared_plan_producer"
    )
    fast_handoff_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_afic_fast_handoff"
    )
    move_hb = _latest_heartbeat(
        heartbeats, "ctrader_xau_expected_move_envelope_v170"
    )
    ensemble_hb = _latest_heartbeat(
        heartbeats, "ctrader_xau_forecast_ensemble_v171"
    )
    forecast_rows = [] if backend is None else backend.get("afic_forecast_states", [])
    prepared_rows = [] if backend is None else backend.get("afic_prepared_plans", [])
    geometry_rows = [] if backend is None else backend.get("afic_execution_geometry", [])
    execution_events = [] if backend is None else backend.get("xau_execution_events", [])
    all_signal_rows = [] if backend is None else backend.get("signals", [])
    xau_technical_signal_rows = [
        dict(row) for row in all_signal_rows
        if str(row.get("symbol") or "").upper() == "XAUUSD"
        and not str(row.get("setup_type") or "").upper().startswith("AFIC_")
    ]

    state_event = forecast_rows[0] if forecast_rows else None
    state_payload = {}
    if state_event:
        state_payload = dict(dict(state_event.get("payload") or {}).get("forecast") or {})

    hb_details = {} if prepared_hb is None else dict(prepared_hb.get("details") or {})
    state = str(hb_details.get("forecast_state") or state_payload.get("state") or "NO_MAP")
    direction = str(
        hb_details.get("continuation_direction")
        or state_payload.get("continuation_direction")
        or "—"
    ).upper()
    zone = dict(state_payload.get("zone") or {})
    zone_low = hb_details.get("zone_low", zone.get("low"))
    zone_high = hb_details.get("zone_high", zone.get("high"))
    grade = str(hb_details.get("forecast_selector_grade") or "—")
    live_price = hb_details.get("live_price")
    distance_points = hb_details.get("distance_to_zone_points")
    distance_atr = hb_details.get("distance_to_zone_atr")
    proximity = str(hb_details.get("proximity_state") or "UNKNOWN")
    scan_seconds = hb_details.get("effective_scan_seconds", 60)
    auto_enabled = bool(
        hb_details.get("execution_enabled_env")
        and hb_details.get("handoff_allowlisted")
    )
    latest_exec_event = None
    latest_exec_row = None
    for event_row in execution_events:
        event_payload = dict(event_row.get("payload") or {})
        if (
            str(event_row.get("code") or "") == "XAU_AFIC_PATH_EXECUTION_V1"
            or str(event_payload.get("strategy_id") or "") == "XAU_AFIC_PATH_EXECUTION_V1"
            or (
                str(event_payload.get("symbol") or "").upper() == "XAUUSD"
                and str(event_row.get("signal_key") or "") == str(hb_details.get("signal_id") or "")
            )
        ):
            latest_exec_row = event_row
            latest_exec_event = str(event_row.get("event_type") or "")
            break
    next_action, next_reason = _afic_next_action(
        state=state,
        grade=grade,
        proximity=proximity,
        auto_enabled=auto_enabled,
        latest_execution_event=latest_exec_event,
    )

    current_map = hb_details.get("map_at") or state_payload.get("map_at")
    prep_event_now = prepared_rows[0] if prepared_rows else None
    prep_payload_now = {} if prep_event_now is None else dict(prep_event_now.get("payload") or {})
    prep_plan_now = dict(prep_payload_now.get("prepared_plan") or {})
    prep_forecast_now = dict(prep_payload_now.get("forecast") or {})
    prep_current_now = bool(
        prep_plan_now
        and current_map
        and str(prep_forecast_now.get("map_at") or "") == str(current_map)
    )
    reference_entry_now = prep_plan_now.get("entry") if prep_current_now else None

    zone_diagnostics = dict(
        hb_details.get("zone_diagnostics")
        or state_payload.get("zone_diagnostics")
        or {}
    )

    valid_zone_now = bool(
        zone_low is not None
        and zone_high is not None
        and str(state).upper() not in {
            "NO_MAP_ZONE",
            "NO_ORIGIN_ZONE",
            "NO_DIRECTION",
            "INSUFFICIENT_HISTORY",
            "INSUFFICIENT_H4",
        }
        and "INVALID" not in str(state).upper()
        and "REMAP" not in str(state).upper()
    )
    zone_side = (
        "BUY" if direction == "LONG"
        else "SELL" if direction == "SHORT"
        else "—"
    )

    st.markdown("### Trade Preparation")
    if not valid_zone_now:
        st.error(
            "NO VALID ENTRY ZONE — DO NOT ORDER YET. "
            "Scanner is waiting for a new H4 structural map/reaction zone."
        )
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Waiting for", "NEW H4 MAP")
        t2.metric("Reaction zone", "—")
        t3.metric("Reference entry", "—")
        t4.metric("Manual action", "WAIT")
    else:
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Waiting for", f"{zone_side} REACTION")
        t2.metric("Reaction zone", f"{_fmt_price(zone_low)}–{_fmt_price(zone_high)}")
        t3.metric("Reference entry", _fmt_price(reference_entry_now))
        if grade != "A":
            manual_action = f"WATCH ONLY (GRADE {grade})"
        elif "CONFIRMED" in str(state).upper():
            manual_action = "CONFIRMED / FRESH QUOTE"
        elif proximity == "IN_ZONE":
            manual_action = "WAIT M15 CONFIRM"
        elif proximity == "NEAR_ZONE":
            manual_action = "PREPARE"
        else:
            manual_action = "WAIT PRICE TO ZONE"
        t4.metric("Manual action", manual_action)
        st.info(
            f"Current plan: wait for XAUUSD to enter {_fmt_price(zone_low)}–"
            f"{_fmt_price(zone_high)}. "
            + (
                f"Prepared/reference entry ≈ {_fmt_price(reference_entry_now)}. "
                if reference_entry_now is not None
                else "Reference entry is not executable yet. "
            )
            + "Do not enter merely because price touches the zone; completed M15 "
              "confirmation is still required for the AFIC auto path."
        )

    st.markdown("#### Cross-engine XAU technical signals")
    st.caption(
        "Separate from the AFIC H4 map. These rows come from other XAU technical engines. "
        "CURRENT/EXPIRED is determined from expires_at; an expired setup is historical "
        "context only and must not be treated as a current AFIC order blueprint."
    )
    if xau_technical_signal_rows:
        now_utc = datetime.now(tz=UTC)
        technical_rows = []
        for row in xau_technical_signal_rows[:5]:
            expires_raw = row.get("expires_at")
            expires_dt = None
            if expires_raw:
                try:
                    expires_dt = datetime.fromisoformat(
                        str(expires_raw).replace("Z", "+00:00")
                    )
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=UTC)
                    else:
                        expires_dt = expires_dt.astimezone(UTC)
                except (TypeError, ValueError):
                    expires_dt = None
            runtime_status = (
                "CURRENT"
                if expires_dt is not None and expires_dt >= now_utc
                else "EXPIRED"
            )
            technical_rows.append(
                {
                    "runtime": runtime_status,
                    "observed_at": row.get("observed_at"),
                    "setup": row.get("setup_type"),
                    "direction": row.get("direction"),
                    "state": row.get("state"),
                    "score": row.get("final_score"),
                    "entry": (
                        f"{_fmt_price(row.get('entry_low'))}–{_fmt_price(row.get('entry_high'))}"
                        if row.get("entry_low") is not None or row.get("entry_high") is not None
                        else "—"
                    ),
                    "SL": _fmt_price(row.get("sl")),
                    "TP1": _fmt_price(row.get("tp1")),
                    "TP2": _fmt_price(row.get("tp2")),
                    "guards": ", ".join(str(x) for x in (row.get("active_guards") or [])) or "—",
                    "expires_at": expires_raw,
                }
            )
        latest_technical = technical_rows[0]
        if latest_technical["runtime"] == "CURRENT":
            st.info(
                "Latest non-AFIC XAU technical setup is CURRENT. "
                "Its geometry is shown below, but AFIC authority remains a separate gate."
            )
        else:
            st.warning(
                "Latest non-AFIC XAU technical setup is EXPIRED. "
                "Its entry/SL/TP are historical geometry only, not a current instruction."
            )
        st.dataframe(
            pd.DataFrame(technical_rows),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("No non-AFIC XAU technical signal rows are available yet.")

    st.markdown("#### Reaction-zone diagnostics")
    if zone_diagnostics:
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Origin zones", zone_diagnostics.get("origin_zones_total", "—"))
        d2.metric("Fresh ≤24h", zone_diagnostics.get("fresh_within_24h", "—"))
        d3.metric(
            f"{direction or 'Map'} direction",
            zone_diagnostics.get("matching_direction_fresh", "—"),
        )
        d4.metric("Wrong side of anchor", zone_diagnostics.get("wrong_side_of_anchor", "—"))
        d5.metric("Eligible reaction zones", zone_diagnostics.get("eligible_correct_side", "—"))
        result = str(zone_diagnostics.get("selection_result") or "")
        if result == "NO_ELIGIBLE_MAP_ZONE":
            st.warning(
                "NO_MAP_ZONE is explained by the current structure: origin zones exist, "
                "but zero candidates satisfy direction + freshness + correct side of the "
                "current H4 anchor. This is a no-setup state, not an execution signal."
            )
        elif result == "ELIGIBLE_ZONE_FOUND":
            nearest = dict(zone_diagnostics.get("nearest_eligible") or {})
            st.success(
                "Eligible reaction zone found: "
                f"{_fmt_price(nearest.get('low'))}–{_fmt_price(nearest.get('high'))} • "
                f"distance {_fmt_distance(nearest.get('distance_points'), ' pts')}."
            )
        elif result == "NO_ORIGIN_ZONE":
            st.warning(
                "No H1 origin zone currently satisfies the displacement/BOS/origin "
                "construction rules. Scanner is waiting for a new structural setup."
            )
        st.caption(
            "Diagnostics are descriptive only; they do not relax the AFIC selector or "
            "create broker authority."
        )
    else:
        st.caption(
            "Zone diagnostics are not available for this heartbeat yet; the next AFIC "
            "cycle will populate candidate/rejection counts."
        )

    st.markdown("#### Alternative / reversal watch zones")
    reversal_watch = list(zone_diagnostics.get("alternative_reversal_watch_zones") or [])
    active_watch = [
        dict(item) for item in reversal_watch
        if str(item.get("status") or "") != "INVALIDATED"
    ]
    if active_watch:
        st.caption(
            "Opposite-direction origin zones are potential destinations/reversal areas only. "
            "They cannot auto-order against the active H4 map; a structural remap plus "
            "H1/M15 reversal confirmation is required."
        )
        watch_rows = []
        for item in active_watch:
            watch_rows.append(
                {
                    "role": item.get("role"),
                    "direction": item.get("direction"),
                    "zone": f"{_fmt_price(item.get('low'))}–{_fmt_price(item.get('high'))}",
                    "status": item.get("status"),
                    "distance now": _fmt_distance(
                        item.get("distance_from_live_price_points")
                        if item.get("distance_from_live_price_points") is not None
                        else item.get("distance_from_latest_price_points"),
                        " pts",
                    ),
                    "age": _fmt_distance(item.get("current_age_hours"), "h"),
                    "displacement ATR": item.get("displacement_range_atr"),
                    "body fraction": item.get("displacement_body_fraction"),
                    "touch": item.get("live_touch_at") or item.get("first_touch_at"),
                    "required": item.get("required_confirmation"),
                }
            )
        st.dataframe(pd.DataFrame(watch_rows), hide_index=True, use_container_width=True)
        nearest_watch = active_watch[0]
        watch_side = str(nearest_watch.get("direction") or "—")
        watch_role = str(nearest_watch.get("role") or "")
        watch_status = str(nearest_watch.get("status") or "")
        if watch_role == "UPSIDE_DESTINATION_SHORT_REVERSAL_WATCH":
            path_hint = (
                "Path watch: rebound/upside leg → SHORT reaction zone → wait for "
                "completed H1/M15 bearish reversal/remap before any SELL authority."
            )
        elif watch_role == "DOWNSIDE_DESTINATION_LONG_REVERSAL_WATCH":
            path_hint = (
                "Path watch: selloff/downside leg → LONG reaction zone → wait for "
                "completed H1/M15 bullish reversal/remap before any BUY authority."
            )
        else:
            path_hint = (
                "Countertrend reaction watch only; wait for completed H1/M15 reversal/remap."
            )
        st.info(
            f"Nearest reversal watch: {watch_side} "
            f"{_fmt_price(nearest_watch.get('low'))}–{_fmt_price(nearest_watch.get('high'))} "
            f"• {watch_status}. {path_hint}"
        )
    elif reversal_watch:
        st.caption(
            "Opposite-direction zones were found, but all current reversal-watch candidates "
            "have already been invalidated."
        )
    else:
        st.caption("No active opposite-direction reversal-watch zone is available.")

    f1, f2, f3, f4, f5, f6 = st.columns(6)
    f1.metric("Forecast", direction)
    f2.metric("State", state)
    f3.metric("Selector", grade)
    f4.metric("Live XAU", _fmt_price(live_price))
    f5.metric("Distance to zone", _fmt_distance(distance_points, " pts"))
    f6.metric("AFIC scan", f"{int(scan_seconds)}s" if scan_seconds else "—")

    h1, h2, h3, h4, h5 = st.columns(5)
    hb_age = None if prepared_hb is None else _age_seconds(prepared_hb.get("observed_at"))
    fast_age = None if fast_handoff_hb is None else _age_seconds(fast_handoff_hb.get("observed_at"))
    fast_ok = bool(fast_handoff_hb and fast_handoff_hb.get("healthy"))
    fast_label = "WAITING"
    if fast_handoff_hb is not None:
        fast_label = "OK" if fast_ok and fast_age is not None and fast_age <= 180 else "STALE/ERROR"
    h1.metric("Next action", next_action)
    h2.metric("DEMO auto", "ON" if auto_enabled else "OFF")
    h3.metric("Forecast heartbeat", "—" if hb_age is None else f"{hb_age:.0f}s ago")
    h4.metric("Fast handoff", fast_label)
    h5.metric("Last AFIC broker event", latest_exec_event or "NONE")
    st.caption(next_reason)
    if fast_handoff_hb is not None:
        fast_details = dict(fast_handoff_hb.get("details") or {})
        st.caption(
            "AFIC fast handoff • "
            f"age={'—' if fast_age is None else f'{fast_age:.0f}s'} • "
            f"duration={_fmt_distance(fast_details.get('duration_seconds'), 's')} • "
            f"exit={fast_details.get('exit_code', '—')} • "
            f"code={str(fast_details.get('code_version') or '—')[:12]}"
        )

    st.markdown("#### Forecast Ensemble V171")
    ensemble_details = {} if ensemble_hb is None else dict(ensemble_hb.get("details") or {})
    ensemble = dict(ensemble_details.get("ensemble") or {})
    primary = dict(ensemble.get("primary_scenario") or {})
    alternative = dict(ensemble.get("alternative_scenario") or {})
    ensemble_age = None if ensemble_hb is None else _age_seconds(ensemble_hb.get("observed_at"))
    ensemble_components = dict(ensemble.get("components") or {})

    if ensemble:
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Primary scenario", str(primary.get("direction") or "—"))
        e2.metric(
            "Confidence",
            "—"
            if primary.get("confidence") is None
            else _fmt_pct(primary.get("confidence")),
        )
        e3.metric(
            "Alternative",
            str(alternative.get("type") or "—"),
        )
        e4.metric(
            "Invalidation",
            _fmt_price(ensemble.get("invalidation")),
        )
        st.caption(
            "Shadow-only ensemble • "
            f"coverage={_fmt_pct(ensemble.get('coverage'))} • "
            f"age={'—' if ensemble_age is None else f'{ensemble_age:.0f}s'} • "
            "does not alter AFIC Grade-A execution authority."
        )
        directional_prior = dict(ensemble.get("directional_prior") or {})
        if directional_prior:
            st.caption(
                "Directional prior: "
                f"{directional_prior.get('direction', '—')} • "
                f"score={_fmt_distance(directional_prior.get('score'), '')} • "
                f"prior confidence={_fmt_pct(directional_prior.get('confidence'))}. "
                "A valid AFIC H4 map/reaction zone is still required before this can "
                "become a Primary LONG/SHORT structural scenario."
            )

        path = dict(primary.get("structural_path") or {})
        if path:
            reaction = dict(path.get("reaction_zone") or {})
            st.info(
                "Primary path: "
                f"{path.get('first_leg') or '—'} → "
                f"reaction {_fmt_price(reaction.get('low'))}–{_fmt_price(reaction.get('high'))} → "
                f"{path.get('continuation') or primary.get('direction') or '—'}"
            )

        component_rows = []
        for name, label in (
            ("afic", "AFIC structural"),
            ("conditional", "Empirical conditional"),
            ("acd", "Fisher/ACD session"),
            ("cot", "Weekly COT prior"),
            ("v170", "V170 expected move"),
        ):
            component = dict(ensemble_components.get(name) or {})
            available = component.get("available")
            direction_value = component.get("direction")
            if name == "v170":
                direction_value = "MAGNITUDE ONLY"
            component_rows.append(
                {
                    "component": label,
                    "available": available,
                    "direction / role": direction_value or "—",
                    "confidence": component.get("confidence"),
                    "state / method": component.get("state")
                    or component.get("method")
                    or component.get("reason")
                    or "—",
                }
            )
        component_frame = pd.DataFrame(component_rows)
        if "confidence" in component_frame.columns:
            component_frame["confidence"] = component_frame["confidence"].apply(
                lambda x: "—" if pd.isna(x) else _fmt_pct(x)
            )
        st.dataframe(component_frame, hide_index=True, use_container_width=True)

        conditional_component = dict(ensemble_components.get("conditional") or {})
        horizons_conditional = dict(conditional_component.get("horizons") or {})
        if horizons_conditional:
            probability_rows = []
            for label in ("1h", "4h", "8h"):
                row = dict(horizons_conditional.get(label) or {})
                if row:
                    probability_rows.append(
                        {
                            "horizon": label,
                            "P(up)": row.get("p_up"),
                            "P(down)": row.get("p_down"),
                            "bias": row.get("direction"),
                            "samples": row.get("samples"),
                            "median close Δ": row.get("median_close_delta"),
                        }
                    )
            if probability_rows:
                probability_frame = pd.DataFrame(probability_rows)
                for col in ("P(up)", "P(down)"):
                    probability_frame[col] = probability_frame[col].apply(
                        lambda x: "—" if pd.isna(x) else _fmt_pct(x)
                    )
                st.dataframe(
                    probability_frame,
                    hide_index=True,
                    use_container_width=True,
                )
    else:
        st.caption(
            "Forecast Ensemble V171 has not produced a durable shadow snapshot yet. "
            "AFIC and V170 remain independently visible below."
        )

    if zone_low is not None and zone_high is not None:
        st.markdown(
            f"**Reaction zone:** {_fmt_price(zone_low)} – {_fmt_price(zone_high)}  "
            f"• **Proximity:** {proximity}  "
            f"• **Distance:** {_fmt_distance(distance_atr, ' ATR')}"
        )
    st.info(_afic_path_text(direction, state))

    if grade == "A":
        st.success(
            "Canonical V161 selector PASS: grade A map eligible for DEMO auto execution "
            "after completed M15 confirmation."
        )
    elif grade in {"B", "C"}:
        st.warning(
            f"Grade {grade}: dashboard/watch only. Scanner will not auto-order this AFIC "
            "map even if the zone is touched."
        )
    else:
        st.caption("No canonical AFIC selector grade available yet.")

    plan_event = prepared_rows[0] if prepared_rows else None
    plan_payload = {} if plan_event is None else dict(plan_event.get("payload") or {})
    prepared_plan = dict(plan_payload.get("prepared_plan") or {})
    plan_forecast = dict(plan_payload.get("forecast") or {})
    plan_current = bool(
        prepared_plan
        and current_map
        and str(plan_forecast.get("map_at") or "") == str(current_map)
    )

    st.markdown("#### Prepared order blueprint")
    if plan_current:
        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("Reference / Limit", _fmt_price(prepared_plan.get("entry")))
        p2.metric("Stop Loss", _fmt_price(prepared_plan.get("stop")))
        p3.metric("First scale-out", _fmt_price(prepared_plan.get("tp1")))
        p4.metric("Terminal target", _fmt_price(prepared_plan.get("tp2")))
        p5.metric("RR terminal", _fmt_distance(prepared_plan.get("rr2"), "R"))
        target_ladder = list(prepared_plan.get("tp_ladder") or [])
        if target_ladder:
            st.caption(
                "Target ladder: "
                + " → ".join(
                    f"TP{i} {_fmt_price(level)}"
                    for i, level in enumerate(target_ladder, start=1)
                )
                + f" • Terminal target = TP{len(target_ladder)}"
            )
        if "CONFIRMED" in state.upper() and grade == "A" and auto_enabled:
            st.success(
                "Automation: confirmation detected → fresh broker quote revalidated → "
                "MARKET DEMO eligible. SL/TP must be attached server-side."
            )
        else:
            st.caption(
                "Reference level is also the manual LIMIT blueprint. Automatic pending "
                "LIMIT stays disabled until expiry/cancel-on-invalidation reconciliation "
                "is implemented."
            )
    else:
        if valid_zone_now:
            st.warning(
                "Reaction zone exists, but no executable prepared/reference entry is valid "
                "for the current map yet. Wait for the blueprint/confirmation."
            )
        else:
            st.error(
                "No valid reaction zone or prepared/reference entry for the current H4 map. "
                "Do not reuse an older zone from Forecast State History."
            )

    auto_label = "ARMED FOR GRADE-A CONFIRMATION" if auto_enabled else "MONITOR ONLY"
    if grade != "A":
        auto_label = f"BLOCKED BY SELECTOR GRADE {grade}"
    st.markdown(f"**Automation status:** {auto_label}")
    if hb_details.get("blueprint_block_reason"):
        st.caption(f"Current block: {hb_details.get('blueprint_block_reason')}")

    if geometry_rows:
        latest_geometry = dict(geometry_rows[0].get("payload") or {})
        st.caption(
            "Latest AFIC broker-authorized geometry: "
            f"{latest_geometry.get('direction', '—')} • "
            f"entry mode {latest_geometry.get('entry_mode', '—')} • "
            f"SL {_fmt_price(latest_geometry.get('planned_sl'))} • "
            f"TP2 {_fmt_price(latest_geometry.get('planned_tp2'))}"
        )

    st.markdown("#### Automation / broker timeline")
    if execution_events:
        timeline_rows = []
        for row in execution_events[:20]:
            payload = dict(row.get("payload") or {})
            timeline_rows.append(
                {
                    "time": row.get("observed_at"),
                    "event": row.get("event_type"),
                    "accepted": row.get("accepted"),
                    "strategy": row.get("code") or payload.get("strategy_id"),
                    "signal": row.get("signal_key"),
                    "order": row.get("broker_order_id"),
                    "entry": payload.get("executed_price") or payload.get("requested_entry") or payload.get("planned_entry"),
                    "sl": payload.get("attached_stop_loss") or payload.get("requested_stop_loss") or payload.get("planned_sl"),
                    "tp": payload.get("attached_take_profit") or payload.get("requested_take_profit") or payload.get("planned_tp2"),
                    "message": row.get("message"),
                }
            )
        st.dataframe(pd.DataFrame(timeline_rows), hide_index=True, use_container_width=True)
    else:
        st.caption("No XAU execution event yet. Forecast monitoring can still be active without an order.")

    st.markdown("#### Expected-move envelope")
    move_details = {} if move_hb is None else dict(move_hb.get("details") or {})
    move_eval = dict(move_details.get("evaluation") or {})
    envelope = dict(move_eval.get("current_envelope") or {})
    horizons = dict(envelope.get("horizons") or {})
    if envelope and horizons:
        st.caption(
            "Magnitude forecast only — excursion quantiles, not bullish/bearish probabilities."
        )
        move_rows = []
        for label in ("1h", "4h", "8h"):
            row = dict(horizons.get(label) or {})
            levels = dict(row.get("levels") or {})
            if levels:
                move_rows.append(
                    {
                        "horizon": label,
                        "anchor": envelope.get("price"),
                        "down q50": levels.get("down_q50"),
                        "down q75": levels.get("down_q75"),
                        "down q90": levels.get("down_q90"),
                        "up q50": levels.get("up_q50"),
                        "up q75": levels.get("up_q75"),
                        "up q90": levels.get("up_q90"),
                    }
                )
        if move_rows:
            st.dataframe(pd.DataFrame(move_rows), hide_index=True, use_container_width=True)
    else:
        st.caption("Expected-move V170 heartbeat is not available in this snapshot.")

    st.markdown("#### Forecast state history")
    history_rows = []
    for row in forecast_rows[:12]:
        payload = dict(dict(row.get("payload") or {}).get("forecast") or {})
        z = dict(payload.get("zone") or {})
        history_rows.append(
            {
                "observed_at": row.get("observed_at"),
                "map_at": payload.get("map_at"),
                "state": payload.get("state"),
                "direction": payload.get("continuation_direction"),
                "zone_low": z.get("low"),
                "zone_high": z.get("high"),
                "touch_at": payload.get("first_touch_at"),
                "confirm_at": payload.get("confirm_at"),
                "invalidated_at": payload.get("invalidated_at"),
            }
        )
    if history_rows:
        st.dataframe(pd.DataFrame(history_rows), hide_index=True, use_container_width=True)
    else:
        st.caption("No durable AFIC forecast transitions have been recorded yet.")

with account_tab:
    st.subheader("Broker Account Monitor")
    account = None if backend is None else backend.get("broker_account")
    positions = [] if backend is None else backend.get("broker_positions", [])

    if account:
        observed = str(account.get("observed_at") or "")
        age_seconds = None
        try:
            observed_dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            age_seconds = max(
                0.0,
                (datetime.now(tz=UTC) - observed_dt.astimezone(UTC)).total_seconds(),
            )
        except (TypeError, ValueError):
            pass

        connected = bool(account.get("connection_healthy"))
        stale = age_seconds is None or age_seconds > 60
        if not connected:
            st.error("Broker telemetry reports the cTrader DEMO connection as unhealthy.")
        elif stale:
            st.warning("Broker telemetry is stale (>60 seconds).")
        else:
            st.success("Broker telemetry is live and read-only.")

        currency = str(account.get("currency") or "")

        def money(value):
            try:
                return f"{float(value):,.2f} {currency}".strip()
            except (TypeError, ValueError):
                return "—"

        a1, a2, a3, a4, a5, a6 = st.columns(6)
        a1.metric("Balance", money(account.get("balance")))
        a2.metric("Equity", money(account.get("equity")))
        a3.metric("Floating P/L", money(account.get("floating_profit")))
        a4.metric("Free Margin", money(account.get("margin_free")))
        margin_level = account.get("margin_level")
        a5.metric(
            "Margin Level",
            "—" if margin_level is None else f"{float(margin_level):,.1f}%",
        )
        a6.metric("Open Positions", len(positions))

        st.caption(
            f"Backend: {account.get('backend', '—')} • "
            f"Account: {account.get('account_id', '—')} • "
            f"Currency: {currency or '—'} • "
            f"Telemetry age: {'—' if age_seconds is None else f'{age_seconds:.0f}s'}"
        )
        if currency.upper() == "USC":
            st.info(
                "Broker reports this Cent account in USC. Values are shown in "
                "the broker's native unit and are not silently converted."
            )

        if positions:
            position_frame = _frame(positions)
            display_cols = [
                col
                for col in [
                    "symbol", "side", "volume", "open_price", "current_price",
                    "sl", "tp", "profit", "swap", "opened_at", "position_id",
                ]
                if col in position_frame.columns
            ]
            st.dataframe(
                position_frame[display_cols],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No open cTrader DEMO positions in the latest broker snapshot.")
    else:
        st.info(
            "No broker telemetry yet. Streamlit is read-only; the cloud cTrader DEMO "
            "runtime will publish balance and positions when the next broker snapshot arrives."
        )

with scanner_tab:
    st.subheader("Pair Ranking")

    if backend is not None and backend["rankings"]:
        rankings = _frame(backend["rankings"])
        if "coverage" in rankings.columns:
            rankings["coverage"] = rankings["coverage"].apply(_fmt_pct)
        display_cols = [
            col
            for col in [
                "rank",
                "symbol",
                "direction",
                "pair_opportunity_score",
                "macro_edge",
                "technical_edge",
                "cross_asset_score",
                "coverage",
                "observed_at",
            ]
            if col in rankings.columns
        ]
        st.dataframe(
            rankings[display_cols],
            hide_index=True,
            use_container_width=True,
        )
        st.caption("Rank 1–8 = macro-compatible shortlist; rank 1–5 receives deep MTF analysis.")
    elif cfg is not None:
        configured = pd.DataFrame(
            [
                {
                    "symbol": pair.symbol,
                    "universe_tier": pair.tier,
                    "pip_size": pair.pip_size,
                    "status": "CONFIGURED_ONLY_WAITING_RUNTIME_DATA",
                }
                for pair in cfg.pairs
            ]
        )
        st.dataframe(configured, hide_index=True, use_container_width=True)
        st.caption(
            "No durable pair-ranking snapshot is available yet. This table shows the "
            "configured trading universe only. universe_tier A/B is a static instrument "
            "priority class, NOT an execution grade and NOT EXECUTION_READY."
        )

    st.subheader("Latest Signals")
    if backend is not None and backend["signals"]:
        signals = _frame(backend["signals"])
        signals["_state_order"] = signals["state"].map(_state_rank)
        signals = signals.sort_values(
            ["_state_order", "observed_at"],
            ascending=[True, False],
        ).drop(columns=["_state_order"])

        if "data_coverage" in signals.columns:
            signals["data_coverage"] = signals["data_coverage"].apply(_fmt_pct)

        states = [
            "EXECUTION_READY",
            "ARMED",
            "SETUP_FORMING",
            "WATCH",
            "NO_TRADE",
        ]
        selected_states = st.multiselect(
            "Signal state",
            states,
            default=states,
        )
        if selected_states:
            signals = signals[signals["state"].isin(selected_states)]

        display_cols = [
            col
            for col in [
                "observed_at",
                "symbol",
                "direction",
                "setup_type",
                "state",
                "final_score",
                "entry_low",
                "entry_high",
                "sl",
                "tp1",
                "tp2",
                "rr1",
                "rr2",
                "data_coverage",
                "active_guards",
            ]
            if col in signals.columns
        ]
        st.dataframe(
            signals[display_cols],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No signal snapshots have been written yet.")

with data_tab:
    st.subheader("Currency Macro")
    if backend is not None and backend["macro"]:
        macro = _frame(backend["macro"])
        if "coverage" in macro.columns:
            macro["coverage"] = macro["coverage"].apply(_fmt_pct)
        st.dataframe(macro, hide_index=True, use_container_width=True)
    else:
        st.info("No durable macro snapshots are available yet.")

    if cfg is not None:
        st.subheader("Official Providers")
        providers = pd.DataFrame(
            [
                {
                    "provider": name,
                    "official": source.get("official"),
                    "enabled": source.get("enabled"),
                    "host": source.get("allowed_host"),
                    "max_age_s": source.get("default_max_age_seconds"),
                }
                for name, source in cfg.providers["sources"].items()
            ]
        )
        st.dataframe(providers, hide_index=True, use_container_width=True)

        if st.button("Check official providers"):
            with st.spinner("Checking configured official sources..."):
                try:
                    rows = _provider_smoke_rows()
                    st.dataframe(
                        pd.DataFrame(rows),
                        hide_index=True,
                        use_container_width=True,
                    )
                except Exception as exc:
                    st.error(f"Provider check failed safely: {type(exc).__name__}: {exc}")

with system_tab:
    st.subheader("Execution Control")
    if backend is not None:
        control = backend["control"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mode", control.get("execution_mode", "—"))
        c2.metric(
            "New Orders",
            "ON" if control.get("new_orders_enabled") else "OFF",
        )
        c3.metric(
            "Emergency Stop",
            "ON" if control.get("emergency_stop") else "OFF",
        )
        c4.metric(
            "Close All Requested",
            "YES" if control.get("close_all_requested") else "NO",
        )
        st.caption(f"Control version: {control.get('version', '—')}")
    else:
        st.info("Execution-control snapshot requires backend connection.")

    st.subheader("Runtime Heartbeats")
    if backend is not None and backend["heartbeats"]:
        heartbeats = _frame(backend["heartbeats"])
        st.dataframe(heartbeats, hide_index=True, use_container_width=True)
    else:
        st.info("No runtime heartbeat snapshots are available.")

    if backend is not None and backend.get("latest_run"):
        st.subheader("Latest Scanner Run")
        run = backend["latest_run"]
        st.json(run, expanded=False)

with validation_tab:
    st.subheader("Acceptance Gates")
    if cfg is not None:
        acceptance = cfg.risk["acceptance"]
        gates = pd.DataFrame(
            [
                {
                    "gate": "Final OOS win rate",
                    "minimum": f"{float(acceptance['oos_win_rate_min']) * 100:.0f}%",
                },
                {
                    "gate": "Profit factor",
                    "minimum": acceptance["profit_factor_min"],
                },
                {
                    "gate": "Expectancy",
                    "minimum": f"{acceptance['expectancy_r_min']}R",
                },
                {
                    "gate": "Final OOS completed trades",
                    "minimum": acceptance["aggregate_oos_trades_min"],
                },
                {"gate": "Walk-forward", "minimum": "REQUIRED"},
                {"gate": "Cost/spread/slippage stress", "minimum": "REQUIRED"},
                {"gate": "Multi-regime", "minimum": "REQUIRED"},
                {"gate": "Monte Carlo", "minimum": "REQUIRED"},
                {"gate": "Parameter perturbation", "minimum": "REQUIRED"},
                {"gate": "Demo forward", "minimum": "REQUIRED"},
            ]
        )
        st.dataframe(gates, hide_index=True, use_container_width=True)

        perf = cfg.validation["performance_budget"]
        st.subheader("Hot-path Performance Budget")
        p1, p2, p3 = st.columns(3)
        p1.metric("Top-5 Deep Scan", f"≤ {perf['deep_scan_top5_target_ms']} ms")
        p2.metric("Per-pair MTF", f"≤ {perf['per_pair_mtf_target_ms']} ms")
        p3.metric(
            "Execution Revalidation",
            f"≤ {perf['execution_revalidation_max_ms']} ms",
        )
        st.caption(
            "Backtest, walk-forward and Monte Carlo are explicitly excluded "
            "from the live scanner hot path."
        )

    st.subheader("Latest Persisted Performance")
    if backend is not None and backend["performance"]:
        performance = _frame(backend["performance"])
        if "win_rate" in performance.columns:
            performance["win_rate"] = performance["win_rate"].apply(
                lambda x: "—" if pd.isna(x) else f"{float(x) * 100:.1f}%"
            )
        st.dataframe(performance, hide_index=True, use_container_width=True)
    else:
        st.info(
            "No persisted OOS/performance rows are available yet. "
            "The dashboard does not fabricate validation results."
        )

st.divider()
st.caption(
    "Rendered at "
    + datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    + " • Main file: main.py • Dashboard implementation: streamlit_app.py"
)
