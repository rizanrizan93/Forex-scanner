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


@st.cache_data(ttl=2, show_spinner=False)
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
        help="Refresh the read-only dashboard every 5 seconds. Scanner/order runtime is independent.",
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


@st.fragment(run_every="5s")
def _dashboard_auto_refresh_tick() -> None:
    if not auto_refresh_enabled:
        return
    now = datetime.now(tz=UTC)
    last = st.session_state.get("dashboard_auto_refresh_at")
    if not isinstance(last, datetime) or (now - last).total_seconds() >= 4.5:
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
    move_hb = _latest_heartbeat(
        heartbeats, "ctrader_xau_expected_move_envelope_v170"
    )
    forecast_rows = [] if backend is None else backend.get("afic_forecast_states", [])
    prepared_rows = [] if backend is None else backend.get("afic_prepared_plans", [])
    geometry_rows = [] if backend is None else backend.get("afic_execution_geometry", [])

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

    f1, f2, f3, f4, f5, f6 = st.columns(6)
    f1.metric("Forecast", direction)
    f2.metric("State", state)
    f3.metric("Selector", grade)
    f4.metric("Live XAU", _fmt_price(live_price))
    f5.metric("Distance to zone", _fmt_distance(distance_points, " pts"))
    f6.metric("AFIC scan", f"{int(scan_seconds)}s" if scan_seconds else "—")

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
    current_map = hb_details.get("map_at") or state_payload.get("map_at")
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
        p3.metric("TP1", _fmt_price(prepared_plan.get("tp1")))
        p4.metric("TP2", _fmt_price(prepared_plan.get("tp2")))
        p5.metric("RR TP2", _fmt_distance(prepared_plan.get("rr2"), "R"))
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
        st.caption(
            "No current-map executable blueprint. Zone and direction remain visible for "
            "manual monitoring."
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
            st.error("Broker telemetry reports the MT5 connection as unhealthy.")
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
            st.info("No open MT5 positions in the latest broker snapshot.")
    else:
        st.info(
            "No broker telemetry yet. Streamlit is only the monitor; start the "
            "Windows MT5 telemetry worker to publish balance and open positions."
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
                    "tier": pair.tier,
                    "pip_size": pair.pip_size,
                    "status": "WAITING_RUNTIME_DATA",
                }
                for pair in cfg.pairs
            ]
        )
        st.dataframe(configured, hide_index=True, use_container_width=True)
        st.caption(
            "No durable pair-ranking snapshot is available yet. The configured "
            "15-pair universe is shown instead."
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
