from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
from fx_scanner.trade_management_v195 import (
    evaluate_position,
    summarize_positions,
)

UTC = timezone.utc
WIB = ZoneInfo("Asia/Jakarta")

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
def _load_backend_fast_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    """Fast dashboard state needed for manual execution awareness.

    V209 keeps the user-facing 15-second refresh contract for broker state,
    execution control, current signals, and recent XAU execution events.
    """
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    store = SupabaseOperationalStore(url, secret_key, client=client)
    broker_account = reader.latest_broker_account()

    return {
        "signals": list(reader.latest_signals()),
        "xau_signals": list(reader.latest_signals_for_symbol("XAUUSD")),
        "control": asdict(store.get_execution_control()),
        "broker_account": broker_account,
        "broker_positions": list(reader.broker_positions_for_account(broker_account)),
        "xau_execution_events": list(reader.latest_xau_execution_events()),
    }


@st.cache_data(ttl=60, show_spinner=False)
def _load_backend_slow_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    """Slower observability/research state.

    These producers run at roughly one-to-five minute cadence and do not need
    to reread wide heartbeat/event JSON on every 15-second Streamlit rerun.
    """
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    run = reader.latest_run()

    return {
        "latest_run": run,
        "rankings": list(reader.rankings_for_run(None if run is None else run.get("id"))),
        "heartbeats": list(reader.heartbeats()),
        "macro": list(reader.latest_macro()),
        "performance": list(reader.latest_performance()),
        "afic_forecast_states": list(reader.latest_afic_forecast_states()),
        "afic_prepared_plans": list(reader.latest_afic_prepared_plans()),
        "afic_execution_geometry": list(reader.latest_afic_execution_geometry()),
        "xau_prepared_plan_lifecycle": list(reader.latest_xau_prepared_plan_lifecycle()),
    }


def _load_backend_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    # V209 tiered cache: preserve 15-second trading visibility while reducing
    # wide observability reads (especially runtime_heartbeats/details) by ~4x.
    merged = dict(_load_backend_slow_snapshot(url, secret_key))
    merged.update(_load_backend_fast_snapshot(url, secret_key))
    return merged


def _clear_backend_snapshot_cache(*, include_slow: bool) -> None:
    """Clear the actual cached V209 readers, not the uncached merge wrapper."""
    _load_backend_fast_snapshot.clear()
    if include_slow:
        _load_backend_slow_snapshot.clear()


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


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _fmt_wib_datetime(value: Any, *, seconds: bool = True) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return "—"
    pattern = "%d-%m-%Y %H:%M:%S WIB" if seconds else "%d-%m-%Y %H:%M WIB"
    return parsed.astimezone(WIB).strftime(pattern)


def _convert_frame_times_to_wib(
    frame: pd.DataFrame,
    columns: tuple[str, ...] | list[str],
) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    for column in columns:
        if column in out.columns:
            out[column] = out[column].apply(_fmt_wib_datetime)
    return out


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
    if grade_u not in {"A","B"}:
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

    if st.button("Refresh dashboard", width="stretch"):
        _clear_backend_snapshot_cache(include_slow=True)
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
        _clear_backend_snapshot_cache(include_slow=False)
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
    [
        "Prakiraan XAU (XAU Forecast)",
        "Akun & Posisi (Account & Positions)",
        "Pemindai (Scanner)",
        "Makro & Data",
        "Sistem (System)",
        "Validasi (Validation)",
    ]
)

with forecast_tab:
    st.subheader("Prakiraan XAUUSD & Zona Reaksi (XAUUSD Forecast & Reaction Zone)")
    st.caption(
        "Halaman ini memisahkan gambaran besar, arah taktis, kandidat zona, zona "
        "persiapan canonical, dan izin eksekusi. Zona reaksi adalah area harga yang "
        "diperkirakan dapat memicu respons; menyentuh zona saja belum berarti entry. "
        "Semua waktu trading yang ditampilkan menggunakan WIB (Asia/Jakarta, UTC+7); "
        "runtime internal tetap UTC."
    )
    with st.expander("Kamus istilah pada halaman ini", expanded=False):
        st.markdown(
            """
- **Strategic Bias / Bias Strategis:** konteks D1+H4 yang dibuat lebih stabil; bukan sinyal entry.
- **Tactical First Leg / Gerak Taktis Pertama:** arah perjalanan harga menuju zona sebelum continuation/reversal utama.
- **Reaction Zone / Zona Reaksi:** area harga berbasis struktur yang dipantau untuk respons, bukan titik entry otomatis.
- **Supply/Demand HTF:** zona D1/H4/H1 berbasis base→departure atau structural origin. Demand memantau potensi reaksi naik; Supply memantau potensi reaksi turun. V182 hanya PREPARE/RESEARCH dan tidak memberi izin eksekusi.
- **Pre-map Candidate / Kandidat Pra-H4:** H1 origin baru setelah H4 map saat ini; hanya untuk persiapan dan belum punya izin eksekusi.
- **Prepared/Reference Entry / Entry Acuan:** geometry entry yang sudah disiapkan setelah zone canonical tersedia; tetap memerlukan konfirmasi.
- **Execution Admission / Kelayakan Eksekusi:** pemeriksaan apakah signal benar-benar boleh diteruskan ke broker DEMO.
- **Liquidity / Likuiditas:** area dengan potensi konsentrasi order/minat transaksi; pada scanner ini hanya confluence/ranking, bukan pembentuk zone tunggal.
- **BOS (Break of Structure):** penembusan struktur swing yang dipakai untuk mengaitkan displacement dengan origin zone.
- **Displacement:** gerakan impulsif yang cukup kuat setelah origin; digunakan untuk membuktikan bahwa origin berhubungan dengan perubahan struktur.
- **Freshness / Kesegaran:** umur dan riwayat sentuhan zone; makin tua/sering disentuh, evidence reaksinya dapat melemah.
"""
        )

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
    regime_hb = _latest_heartbeat(
        heartbeats, "ctrader_xau_htf_strategic_regime_v180"
    )
    premap_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_premap_candidate_v181"
    )
    supply_demand_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_supply_demand_atlas_v182"
    )
    dom_v191_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_dom_v191"
    )
    event_risk_v192_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_event_risk_v192"
    )
    supply_demand_research_hb = _latest_heartbeat(
        heartbeats, "ctrader_xau_supply_demand_reaction_v183"
    )
    supply_demand_prospective_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_supply_demand_prospective_v184"
    )
    supply_demand_timeframe_hb = _latest_heartbeat(
        heartbeats, "ctrader_xau_supply_demand_timeframe_v185"
    )
    v197_evidence_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v196_shadow_evidence"
    )
    v198_analytics_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v198_evidence_analytics"
    )
    v201_reaction_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v201_reaction_ladder"
    )
    v203_shock_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v203_volatility_shock_guard"
    )
    v212_probability_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v212_zone_reaction_probability"
    )
    v213_path_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v213_post_zone_path"
    )
    forecast_rows = [] if backend is None else backend.get("afic_forecast_states", [])
    prepared_rows = [] if backend is None else backend.get("afic_prepared_plans", [])
    geometry_rows = [] if backend is None else backend.get("afic_execution_geometry", [])
    execution_events = [] if backend is None else backend.get("xau_execution_events", [])
    lifecycle_rows = [] if backend is None else backend.get("xau_prepared_plan_lifecycle", [])
    dedicated_xau_rows = [] if backend is None else backend.get("xau_signals", [])
    xau_technical_signal_rows = [
        dict(row) for row in dedicated_xau_rows
        if not str(row.get("setup_type") or "").upper().startswith("AFIC_")
    ]

    broker_account = {} if backend is None else dict(backend.get("broker_account") or {})
    broker_positions = [] if backend is None else [
        dict(row) for row in backend.get("broker_positions", [])
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

    afic_sd_context = dict(
        hb_details.get("supply_demand_context")
        or state_payload.get("supply_demand_context")
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

    # V194: mobile-first decision center. Keep the full diagnostic sections below,
    # but surface the trading hierarchy in one fixed top-to-bottom sequence.
    dc_regime_details = {} if regime_hb is None else dict(regime_hb.get("details") or {})
    dc_regime_eval = dict(dc_regime_details.get("evaluation") or {})
    dc_regime_current = dict(dc_regime_eval.get("current") or {})
    dc_strategic_bias = str(dc_regime_current.get("strategic_bias") or "NEUTRAL")
    dc_tactical_first_leg = str(
        dc_regime_current.get("tactical_first_leg")
        or direction
        or "NEUTRAL"
    ).upper()

    dc_path = dict(
        afic_sd_context.get("first_leg_path")
        or afic_sd_context.get("active_reaction_path")
        or {}
    )
    dc_source = dict(dc_path.get("source_zone") or {})
    dc_target = dict(
        dc_path.get("terminal_target_zone")
        or dc_path.get("primary_opposing_zone")
        or {}
    )
    dc_reaction_target = dict(dc_path.get("reaction_target") or {})
    dc_projection = dict(
        afic_sd_context.get("first_leg_m5_path_projection")
        or afic_sd_context.get("m5_path_projection")
        or {}
    )
    if not dc_projection and supply_demand_hb is not None:
        dc_projection_details = dict(supply_demand_hb.get("details") or {})
        dc_projection_eval = dict(dc_projection_details.get("evaluation") or {})
        dc_projection = dict(
            dc_projection_eval.get("m5_path_projection")
            or dict(dc_projection_eval.get("path_map") or {}).get("m5_path_projection")
            or {}
        )
    dc_projection_current = dict(dc_projection.get("current_leg") or {})
    dc_projection_next = dict(dc_projection.get("next_leg") or {})
    dc_micro = dict(
        dc_projection_current.get("micro_refinement")
        or afic_sd_context.get("first_leg_micro_refinement")
        or afic_sd_context.get("micro_refinement")
        or {}
    )
    dc_current_pocket_state = str(
        dc_projection_current.get("pocket_state") or ""
    ).upper()
    dc_current_projected_pocket = dict(
        dc_projection_current.get("m5_pocket") or {}
    )
    if dc_projection_current:
        dc_refined = (
            dc_current_projected_pocket
            if dc_current_pocket_state == "REFINED_M5_POCKET"
            else {}
        )
        dc_candidate = (
            dc_current_projected_pocket
            if dc_current_pocket_state == "CANDIDATE_M5_POCKET"
            else {}
        )
    else:
        dc_refined = dict(dc_micro.get("refined_entry_pocket") or {})
        dc_candidate = dict(dc_micro.get("candidate_entry_pocket") or {})
    dc_current_leg_direction = str(
        dc_projection_current.get("direction")
        or dc_micro.get("direction")
        or dc_path.get("reaction_direction")
        or dc_tactical_first_leg
        or "—"
    ).upper()
    dc_current_leg_target = dict(
        dc_projection_current.get("reaction_target")
        or dc_reaction_target
        or {}
    )
    dc_current_leg_terminal = dict(
        dc_projection_current.get("terminal_target_zone")
        or dc_target
        or {}
    )
    dc_next_micro = dict(dc_projection_next.get("micro_refinement") or {})
    dc_next_pocket_state = str(
        dc_projection_next.get("pocket_state") or ""
    ).upper()
    dc_next_projected_pocket = dict(dc_projection_next.get("m5_pocket") or {})
    dc_next_refined = (
        dc_next_projected_pocket
        if dc_next_pocket_state == "REFINED_M5_POCKET"
        else {}
    )
    dc_next_candidate = (
        dc_next_projected_pocket
        if dc_next_pocket_state == "CANDIDATE_M5_POCKET"
        else {}
    )
    dc_next_leg_direction = str(
        dc_projection_next.get("direction")
        or ("SHORT" if dc_current_leg_direction == "LONG" else "LONG")
        if dc_current_leg_direction in {"LONG", "SHORT"}
        else "—"
    ).upper()
    dc_next_leg_source = dict(dc_projection_next.get("source_zone") or {})
    dc_next_leg_target = dict(dc_projection_next.get("reaction_target") or {})
    dc_next_leg_terminal = dict(dc_projection_next.get("terminal_target_zone") or {})
    dc_current_reuse = dict(dc_projection_current.get("zone_reuse_v200") or {})
    dc_next_reuse = dict(dc_projection_next.get("zone_reuse_v200") or {})

    dc_dom = dict(afic_sd_context.get("dom_context") or {})
    if not dc_dom and dom_v191_hb is not None:
        dc_dom_details = dict(dom_v191_hb.get("details") or {})
        dc_dom = dict(dc_dom_details.get("analysis") or {})
        dc_dom["stale"] = bool(
            (_age_seconds(dom_v191_hb.get("observed_at")) or 0.0) > 180.0
        )

    dc_event = dict(afic_sd_context.get("event_risk_context") or {})
    if not dc_event and event_risk_v192_hb is not None:
        dc_event_details = dict(event_risk_v192_hb.get("details") or {})
        dc_event = dict(dc_event_details.get("risk") or {})
        dc_event["stale"] = bool(
            (_age_seconds(event_risk_v192_hb.get("observed_at")) or 0.0) > 600.0
        )

    dc_sd_details = (
        {}
        if supply_demand_hb is None
        else dict(supply_demand_hb.get("details") or {})
    )
    dc_sd_eval = dict(dc_sd_details.get("evaluation") or {})
    dc_path_map = dict(dc_sd_eval.get("path_map") or {})
    dc_reaction_direction = str(
        dc_path.get("reaction_direction")
        or dc_micro.get("direction")
        or dc_tactical_first_leg
        or ""
    ).upper()
    dc_source_stack = list(
        dc_path_map.get(
            "demand_source_stack"
            if dc_reaction_direction == "LONG"
            else "supply_source_stack"
        )
        or []
    )
    dc_h4_parent = next(
        (
            dict(item)
            for item in dc_source_stack
            if str(item.get("timeframe") or "").upper() == "H4"
        ),
        {},
    )
    dc_d1_parent = next(
        (
            dict(item)
            for item in dc_source_stack
            if str(item.get("timeframe") or "").upper() == "D1"
        ),
        {},
    )
    dc_reference_price = (
        live_price
        if live_price is not None
        else dc_sd_eval.get("last_closed_m15_price")
    )

    dc_m15_row = None
    dc_now = datetime.now(tz=UTC)
    for dc_row in xau_technical_signal_rows:
        dc_setup = str(dc_row.get("setup_type") or "").upper()
        if "M15" not in dc_setup:
            continue
        dc_expires = _parse_timestamp(dc_row.get("expires_at"))
        if dc_expires is not None and dc_expires < dc_now:
            continue
        if str(dc_row.get("state") or "").upper() == "INVALIDATED":
            continue
        dc_m15_row = dict(dc_row)
        break

    dc_m15_state = (
        "BELUM ADA SIGNAL M15 AKTIF"
        if dc_m15_row is None
        else str(dc_m15_row.get("state") or "—").upper()
    )
    dc_m15_direction = (
        "—"
        if dc_m15_row is None
        else str(dc_m15_row.get("direction") or "—").upper()
    )
    dc_m15_score = None if dc_m15_row is None else dc_m15_row.get("final_score")
    dc_m15_guards = [] if dc_m15_row is None else list(dc_m15_row.get("active_guards") or [])
    dc_m15_ready = bool(
        dc_m15_row is not None
        and dc_m15_state == "EXECUTION_READY"
        and not dc_m15_guards
    )

    dc_entry_status = "BELUM ADA ENTRY RESMI SCANNER"
    if valid_zone_now and grade in {"A", "B"} and "CONFIRMED" in str(state).upper():
        dc_entry_status = "CANONICAL CONFIRMED — CEK EXECUTION ADMISSION"
    elif valid_zone_now:
        dc_entry_status = "CANONICAL PREPARE — TUNGGU KONFIRMASI"
    elif dc_refined:
        dc_entry_status = "M5 POCKET TERSEDIA — SHADOW/PREPARE, BUKAN ENTRY RESMI"

    dc_tm_account_env = str(broker_account.get("environment") or "UNKNOWN").upper()
    dc_tm_account_age = _age_seconds(broker_account.get("observed_at"))
    dc_tm_snapshot_fresh = bool(
        broker_account
        and dc_tm_account_env == "DEMO"
        and dc_tm_account_age is not None
        and dc_tm_account_age <= 180.0
    )
    dc_active_demo_positions = [
        row
        for row in broker_positions
        if dc_tm_snapshot_fresh and str(row.get("symbol") or "").upper() == "XAUUSD"
    ]
    dc_position_mode = bool(dc_active_demo_positions)

    v203_details = {} if v203_shock_hb is None else dict(v203_shock_hb.get("details") or {})
    v203_latest = dict(v203_details.get("latest_completed_m5") or {})
    v203_state = str(v203_details.get("state") or "NO_HEARTBEAT").upper()
    v203_action = str(v203_details.get("shadow_action") or "OBSERVE_ONLY")
    v203_age = (
        None if v203_shock_hb is None else _age_seconds(v203_shock_hb.get("observed_at"))
    )
    v203_fresh = bool(v203_age is not None and v203_age <= 600.0)
    v203_range_ratio = v203_latest.get("range_ratio")
    v203_spread_ratio = v203_latest.get("spread_ratio")
    v203_tick_ratio = v203_latest.get("tick_ratio")
    v203_range_text = (
        "—" if v203_range_ratio is None else f"{float(v203_range_ratio):.2f}×"
    )
    v203_spread_text = (
        "—" if v203_spread_ratio is None else f"{float(v203_spread_ratio):.2f}×"
    )
    v203_tick_text = (
        "—" if v203_tick_ratio is None else f"{float(v203_tick_ratio):.2f}×"
    )
    v203_reasons = ", ".join(v203_latest.get("shock_reasons") or []) or "—"

    st.markdown("## Pusat Keputusan XAUUSD (Decision Center)")
    if dc_position_mode:
        st.success(
            f"**MODE: POSITION FILLED / MANAGE TRADE** • "
            f"{len(dc_active_demo_positions)} posisi XAUUSD DEMO aktif. "
            "Prioritas dashboard sekarang: proteksi SL → BE/partial review → target reaksi → "
            "opposing zone/target berikutnya. Entry discovery tetap terlihat sebagai context sekunder."
        )
    else:
        st.caption(
            "Baca dari atas ke bawah. Urutannya tetap: D1/H4 konteks → H1 zona → "
            "M5 pocket → M15 konfirmasi → DOM/Event → Execution. "
            "Bagian diagnostik lengkap dipindahkan ke expander di bawah agar tampilan HP lebih ringkas."
        )

    dc1, dc2, dc3 = st.columns(3)
    dc1.metric("Harga referensi", _fmt_price(dc_reference_price))
    dc2.metric("Arah taktis", dc_tactical_first_leg)
    dc3.metric(
        "Mode",
        "MANAGE POSITION" if dc_position_mode else "ENTRY DISCOVERY",
    )

    if v203_shock_hb is None:
        st.info(
            "V203 Volatility Shock Guard: belum ada heartbeat. "
            "Layer ini SHADOW/RISET dan tidak memiliki execution authority."
        )
    elif not v203_fresh:
        st.warning(
            "V203 Volatility Shock Guard: heartbeat stale. Perlakukan shock-state sebagai "
            "tidak terverifikasi sampai snapshot baru muncul. Tidak ada perubahan ke execution router."
        )
    else:
        v203_message = (
            f"**V203 SHADOW: {v203_state}** • action={v203_action} • "
            f"range={v203_range_text} • spread={v203_spread_text} • "
            f"tick={v203_tick_text} • reason={v203_reasons}. "
            "Ini advisory research-only; effective execution block tetap OFF."
        )
        if v203_state == "SHOCK":
            st.error(v203_message)
        elif v203_state in {"STABILIZING", "ELEVATED", "INSUFFICIENT_DATA"}:
            st.warning(v203_message)
        else:
            st.success(v203_message)

        with st.expander("Detail V203 Volatility Shock Guard", expanded=False):
            st.json(
                {
                    "observed_at": v203_shock_hb.get("observed_at"),
                    "state": v203_state,
                    "shadow_action": v203_action,
                    "latest_completed_m5": v203_latest,
                    "stable_completed_m5_run": v203_details.get("stable_completed_m5_run"),
                    "stabilization_bars_required": v203_details.get("stabilization_bars_required"),
                    "last_recent_shock": v203_details.get("last_recent_shock"),
                    "data_quality": v203_details.get("data_quality"),
                    "execution_influence": v203_details.get("execution_influence"),
                    "execution_authority": v203_details.get("execution_authority"),
                }
            )

    st.markdown("#### 1. D1 / H4 — Arah & Parent Zone")
    dc_h4_text = (
        f"{_fmt_price(dc_h4_parent.get('low'))}–{_fmt_price(dc_h4_parent.get('high'))}"
        if dc_h4_parent else "—"
    )
    dc_d1_text = (
        f"{_fmt_price(dc_d1_parent.get('low'))}–{_fmt_price(dc_d1_parent.get('high'))}"
        if dc_d1_parent else "—"
    )
    st.info(
        f"Bias strategis: **{dc_strategic_bias}** • "
        f"first-leg taktis: **{dc_tactical_first_leg}** • "
        f"H4 parent zone: **{dc_h4_text}** • "
        f"D1 parent: {dc_d1_text} • "
        f"H4 map: {_fmt_wib_datetime(current_map, seconds=False)}. "
        "H4/D1 menentukan parent context; entry dipersempit di H1 lalu M5."
    )

    st.markdown("#### 2. H1 — Zona Reaksi Utama")
    if dc_source:
        dc_source_freshness = str(
            dict(dc_source.get("lifecycle") or {}).get("freshness") or "—"
        )
        st.info(
            f"{dc_source.get('timeframe','H1')} {dc_source.get('direction','—')} "
            f"{dc_source.get('pattern','—')} • "
            f"zona **{_fmt_price(dc_source.get('low'))}–{_fmt_price(dc_source.get('high'))}** • "
            f"proximal {_fmt_price(dc_source.get('proximal'))} • "
            f"freshness={dc_source_freshness}. "
            "H1 menentukan area reaksi, bukan titik entry akhir."
        )
    else:
        st.warning(
            "Belum ada H1 source zone aktif pada path AFIC/Supply-Demand saat ini."
        )

    st.markdown("#### 3. M5 — Pocket, Target & Opposing Leg")
    dc_current_target_text = (
        _fmt_price(dc_current_leg_target.get("price"))
        if dc_current_leg_target
        else "—"
    )
    dc_current_terminal_text = (
        f"{_fmt_price(dc_current_leg_terminal.get('low'))}–"
        f"{_fmt_price(dc_current_leg_terminal.get('high'))}"
        if dc_current_leg_terminal
        else "—"
    )
    dc_next_target_text = (
        _fmt_price(dc_next_leg_target.get("price"))
        if dc_next_leg_target
        else "—"
    )
    dc_next_terminal_text = (
        f"{_fmt_price(dc_next_leg_terminal.get('low'))}–"
        f"{_fmt_price(dc_next_leg_terminal.get('high'))}"
        if dc_next_leg_terminal
        else "—"
    )

    dc_current_pocket_shown = False
    if dc_candidate:
        dc_current_pocket_shown = True
        st.warning(
            f"M5 **{dc_current_leg_direction}** POCKET: "
            f"**{_fmt_price(dc_candidate.get('low'))}–{_fmt_price(dc_candidate.get('high'))}** • "
            f"state={dc_micro.get('state','—')} • status=CANDIDATE. "
            f"Pocket ini tampil sebelum reclaim/MSS/displacement selesai. "
            f"Reaction target={dc_current_target_text} • opposing zone={dc_current_terminal_text}."
        )

    if dc_refined:
        dc_current_pocket_shown = True
        st.success(
            f"REFINED M5 **{dc_current_leg_direction}** POCKET: "
            f"**{_fmt_price(dc_refined.get('low'))}–{_fmt_price(dc_refined.get('high'))}** • "
            f"state={dc_micro.get('state','—')} • "
            f"sweep={_fmt_price(dict(dc_micro.get('sweep') or {}).get('price'))} • "
            f"reclaim={_fmt_price(dc_micro.get('source_proximal_reclaim_level'))} • "
            f"MSS={_fmt_price(dc_micro.get('mss_level'))}. "
            f"Reaction target={dc_current_target_text} • opposing zone={dc_current_terminal_text}. "
            "**SHADOW/PREPARE — belum otomatis menjadi entry resmi.**"
        )

    if not dc_current_pocket_shown:
        st.info(
            f"Belum ada M5 pocket aktif untuk leg {dc_current_leg_direction}. "
            f"Path target tetap dipetakan: reaction target={dc_current_target_text} • "
            f"opposing zone={dc_current_terminal_text}."
        )

    if dc_next_pocket_state == "INVALIDATED_M5_POCKET":
        st.warning(
            f"M5 **{dc_next_leg_direction}** pocket sebelumnya sudah **INVALIDATED** • "
            f"state={dc_next_micro.get('state','—')}. "
            "Pocket lama tidak lagi ditampilkan sebagai setup aktif. "
            f"Parent watch zone tetap {_fmt_price(dc_next_leg_source.get('low'))}–"
            f"{_fmt_price(dc_next_leg_source.get('high'))}; scanner menunggu fresh M5 pocket baru. "
            f"Projected path jika setup baru nanti valid: reaction target={dc_next_target_text} • "
            f"terminal zone={dc_next_terminal_text}."
        )
    else:
        dc_next_pocket_shown = False

        if dc_next_candidate:
            dc_next_pocket_shown = True
            st.info(
                f"M5 **{dc_next_leg_direction}** POCKET berikutnya: "
                f"**{_fmt_price(dc_next_candidate.get('low'))}–{_fmt_price(dc_next_candidate.get('high'))}** • "
                f"state={dc_next_micro.get('state','—')} • status=CANDIDATE. "
                f"Reaction target={dc_next_target_text} • "
                f"terminal opposing zone={dc_next_terminal_text}."
            )

        if dc_next_refined:
            dc_next_pocket_shown = True
            st.success(
                f"REFINED M5 **{dc_next_leg_direction}** POCKET berikutnya: "
                f"**{_fmt_price(dc_next_refined.get('low'))}–{_fmt_price(dc_next_refined.get('high'))}** • "
                f"state={dc_next_micro.get('state','—')}. "
                f"Reaction target={dc_next_target_text} • "
                f"terminal opposing zone={dc_next_terminal_text}. "
                "Refined pocket tetap tidak menjadi izin broker tanpa admission yang valid."
            )

        if not dc_next_pocket_shown and dc_next_leg_source:
            st.info(
                f"PARENT WATCH ZONE / PRE-M5 **{dc_next_leg_direction}**: "
                f"**{_fmt_price(dc_next_leg_source.get('low'))}–{_fmt_price(dc_next_leg_source.get('high'))}** • "
                f"state={dc_next_micro.get('state','WAIT_SOURCE_TOUCH')} • "
                f"reaction target={dc_next_target_text} • terminal zone={dc_next_terminal_text}. "
                "Belum ada M5 pocket aktual pada tahap ini. Candidate M5 pocket baru dibentuk "
                "setelah fresh M5 touch/sweep pada parent zone."
            )
        elif not dc_next_pocket_shown:
            st.caption("Belum ada opposing leg yang cukup lengkap untuk dipetakan.")

    v212_details = (
        {} if v212_probability_hb is None else dict(v212_probability_hb.get("details") or {})
    )
    v213_details = (
        {} if v213_path_hb is None else dict(v213_path_hb.get("details") or {})
    )
    v213_eval = dict(v213_details.get("evaluation") or {})
    v213_current = dict(v213_eval.get("current_leg") or {})
    v213_hist = dict(v213_current.get("historical_estimate") or {})
    if v213_current:
        st.markdown("##### V212/V213 — Probabilitas Reaksi & Jalur Setelah Zone")
        rp1, rp2, rp3, rp4 = st.columns(4)
        rp1.metric(
            "P touch",
            "—" if v213_hist.get("p_touch") is None else _fmt_pct(v213_hist.get("p_touch")),
        )
        rp2.metric(
            "P reaksi ≥0.50 ATR",
            "—" if v213_hist.get("p_hold_050") is None else _fmt_pct(v213_hist.get("p_hold_050")),
        )
        rp3.metric(
            "P break zone",
            "—" if v213_hist.get("p_break") is None else _fmt_pct(v213_hist.get("p_break")),
        )
        rp4.metric(
            "P lanjut 1.00 ATR | sudah 0.50",
            "—"
            if v213_hist.get("p_100_given_050") is None
            else _fmt_pct(v213_hist.get("p_100_given_050")),
        )
        st.caption(
            f"Stage={v213_current.get('stage','—')} • "
            f"confidence={v213_hist.get('confidence','—')} • "
            f"median outcome={_fmt_distance(v213_hist.get('median_minutes_to_outcome'), ' menit')}. "
            "Angka V212/V213 adalah estimasi historis/shadow untuk sharpening, bukan izin eksekusi."
        )

    if dc_current_reuse or dc_next_reuse:
        current_reuse_state = str(dc_current_reuse.get("state") or "—")
        next_reuse_state = str(dc_next_reuse.get("state") or "—")
        st.caption(
            "V200 Zone Reuse • "
            f"current={current_reuse_state}"
            + (
                f" (touch={dc_current_reuse.get('touch_count')}, "
                f"mitigation={float(dc_current_reuse.get('mitigation_depth') or 0.0)*100:.0f}%)"
                if dc_current_reuse else ""
            )
            + " • "
            f"next={next_reuse_state}"
            + (
                f" (touch={dc_next_reuse.get('touch_count')}, "
                f"mitigation={float(dc_next_reuse.get('mitigation_depth') or 0.0)*100:.0f}%)"
                if dc_next_reuse else ""
            )
            + ". Tidak ada blind reuse dan tidak ada hard touch-limit; "
            "zona deep/multi-tested harus mendapat micro confirmation baru."
        )

    st.markdown("#### 4. M15 — Konfirmasi Eksekusi")
    if dc_m15_ready:
        st.success(
            f"M15 {dc_m15_direction} **EXECUTION_READY** • score={dc_m15_score}. "
            "Tetap lanjut ke canonical/execution admission dan fresh quote."
        )
    elif dc_m15_row is not None:
        st.warning(
            f"M15 {dc_m15_direction} • state={dc_m15_state} • score={dc_m15_score} • "
            f"guards={', '.join(str(x) for x in dc_m15_guards) or '—'}. "
            "**Belum menjadi konfirmasi entry resmi.**"
        )
    else:
        st.warning("Belum ada signal M15 aktif untuk mengesahkan pocket M5.")

    st.markdown("#### 5. DOM V191 & Event Risk V192 — Konteks Saat Entry")
    dc_dom_state = str(dc_dom.get("state") or "UNAVAILABLE")
    dc_dom_score = dc_dom.get("pressure_score", dc_dom.get("dom_pressure_score"))
    dc_event_state = str(dc_event.get("state") or "UNAVAILABLE")
    dc_event_focal = dict(dc_event.get("focal_event") or {})
    dc_event_time = _fmt_wib_datetime(
        dc_event_focal.get("scheduled_at"),
        seconds=False,
    )
    st.info(
        f"DOM: **{dc_dom_state}**"
        + (
            f" / pressure={float(dc_dom_score):.1f}"
            if dc_dom_score is not None
            else ""
        )
        + (" / STALE" if dc_dom.get("stale") else "")
        + " • Event risk: **"
        + dc_event_state
        + "**"
        + (" / STALE" if dc_event.get("stale") else "")
        + (
            f" • berikutnya {dc_event_focal.get('title')} @ {dc_event_time}"
            if dc_event_focal else ""
        )
        + ". DOM/Event hanya confirmation/caution context, bukan pembuat arah."
    )

    st.markdown(
        "#### 6. Posisi Aktif & Target Berikutnya"
        if dc_position_mode
        else "#### 6. Entry Resmi, Target & Status Akhir"
    )
    dc_target_text = (
        _fmt_price(dc_current_leg_target.get("price"))
        if dc_current_leg_target
        else "—"
    )
    dc_terminal_text = (
        f"{_fmt_price(dc_current_leg_terminal.get('low'))}–"
        f"{_fmt_price(dc_current_leg_terminal.get('high'))}"
        if dc_current_leg_terminal else "—"
    )
    if dc_position_mode:
        st.success(
            f"**POSITION FILLED MODE.** Fokus berpindah dari mencari entry ke manajemen posisi. "
            f"Current-leg reaction target={dc_target_text} • terminal opposing zone={dc_terminal_text} • "
            f"next {dc_next_leg_direction} reaction target={dc_next_target_text}. "
            "Detail SL/BE/TP dan R posisi ada langsung di Trade Management Center di bawah."
        )
    elif "BELUM ADA ENTRY RESMI" in dc_entry_status:
        st.error(
            f"**{dc_entry_status}.** "
            f"Reaction target={dc_target_text} • terminal opposing zone={dc_terminal_text}. "
            "Pocket M5 boleh dipakai untuk persiapan/observasi, tetapi jangan disamakan "
            "dengan izin broker scanner."
        )
    else:
        st.success(
            f"**{dc_entry_status}.** "
            f"Reaction target={dc_target_text} • terminal opposing zone={dc_terminal_text}."
        )

    st.markdown("## Manajemen Posisi XAUUSD (Trade Management Center V195)")
    st.caption(
        "Sumber posisi otomatis di panel ini adalah akun cTrader **DEMO scanner**. "
        "Posisi LIVE pribadi dari screenshot/akun terpisah tidak dicampurkan ke telemetry DEMO. "
        "V195 hanya membaca posisi dan memberi status manajemen; tidak memindahkan SL/TP "
        "atau menutup posisi."
    )

    tm_account_env = str(broker_account.get("environment") or "UNKNOWN").upper()
    tm_account_age = _age_seconds(broker_account.get("observed_at"))
    tm_snapshot_fresh = bool(
        broker_account
        and tm_account_env == "DEMO"
        and tm_account_age is not None
        and tm_account_age <= 180.0
    )
    tm_summary = summarize_positions(broker_positions if tm_snapshot_fresh else [])

    tm1, tm2, tm3, tm4 = st.columns(4)
    tm1.metric("Sumber", f"cTrader {tm_account_env}")
    tm2.metric("Posisi XAU aktif", tm_summary.get("count", 0))
    tm3.metric("Total volume", f"{float(tm_summary.get('total_volume') or 0.0):.2f}")
    tm4.metric(
        "Floating P/L",
        "—"
        if tm_summary.get("total_profit") is None
        else f"{float(tm_summary.get('total_profit') or 0.0):+.2f}",
    )

    if broker_account and not tm_snapshot_fresh:
        st.warning(
            "Snapshot broker DEMO tidak cukup fresh untuk Trade Management Center. "
            f"Observed={_fmt_wib_datetime(broker_account.get('observed_at'))} • "
            f"age={'—' if tm_account_age is None else f'{tm_account_age:.0f}s'}. "
            "V195 tidak menggunakan posisi stale sebagai posisi aktif."
        )

    tm_reaction_target = None
    try:
        tm_reaction_target = (
            None
            if not dc_reaction_target
            else float(dc_reaction_target.get("price"))
        )
    except (TypeError, ValueError):
        tm_reaction_target = None
    try:
        tm_terminal_low = (
            None if not dc_target or dc_target.get("low") is None
            else float(dc_target.get("low"))
        )
    except (TypeError, ValueError):
        tm_terminal_low = None
    try:
        tm_terminal_high = (
            None if not dc_target or dc_target.get("high") is None
            else float(dc_target.get("high"))
        )
    except (TypeError, ValueError):
        tm_terminal_high = None

    tm_xau_positions = [
        row
        for row in broker_positions
        if tm_snapshot_fresh and str(row.get("symbol") or "").upper() == "XAUUSD"
    ]

    if tm_xau_positions:
        tm_rows = []
        tm_alerts = []
        for tm_position in tm_xau_positions:
            tm_side = str(tm_position.get("side") or "").upper()
            tm_wanted_direction = (
                "LONG" if tm_side == "BUY"
                else "SHORT" if tm_side == "SELL"
                else ""
            )
            tm_leg = (
                dc_projection_current
                if str(dc_projection_current.get("direction") or "").upper() == tm_wanted_direction
                else dc_projection_next
                if str(dc_projection_next.get("direction") or "").upper() == tm_wanted_direction
                else {}
            )
            tm_leg_target = dict(tm_leg.get("reaction_target") or {})
            tm_leg_terminal = dict(tm_leg.get("terminal_target_zone") or {})
            try:
                tm_position_reaction_target = (
                    float(tm_leg_target.get("price"))
                    if tm_leg_target.get("price") is not None
                    else tm_reaction_target
                )
            except (TypeError, ValueError):
                tm_position_reaction_target = tm_reaction_target
            try:
                tm_position_terminal_low = (
                    float(tm_leg_terminal.get("low"))
                    if tm_leg_terminal.get("low") is not None
                    else tm_terminal_low
                )
            except (TypeError, ValueError):
                tm_position_terminal_low = tm_terminal_low
            try:
                tm_position_terminal_high = (
                    float(tm_leg_terminal.get("high"))
                    if tm_leg_terminal.get("high") is not None
                    else tm_terminal_high
                )
            except (TypeError, ValueError):
                tm_position_terminal_high = tm_terminal_high

            tm_eval = evaluate_position(
                tm_position,
                reaction_target=tm_position_reaction_target,
                terminal_low=tm_position_terminal_low,
                terminal_high=tm_position_terminal_high,
                structure_direction=tm_wanted_direction or dc_reaction_direction,
            )
            tm_rows.append(
                {
                    "ID": tm_eval.get("position_id"),
                    "Side": tm_eval.get("side"),
                    "Volume": tm_eval.get("volume"),
                    "Entry": _fmt_price(tm_eval.get("entry")),
                    "Harga kini": _fmt_price(tm_eval.get("current")),
                    "P/L": tm_eval.get("profit"),
                    "SL": _fmt_price(tm_eval.get("stop")),
                    "TP broker": _fmt_price(tm_eval.get("broker_tp")),
                    "R kini": (
                        "—"
                        if tm_eval.get("current_r") is None
                        else f"{float(tm_eval.get('current_r')):+.2f}R"
                    ),
                    "BE ref": _fmt_price(tm_eval.get("be_reference_price")),
                    "Target reaksi": _fmt_price(tm_eval.get("first_reaction_target")),
                    "Target-1": tm_eval.get("first_target_state"),
                    "Zona terminal": (
                        f"{_fmt_price(tm_position_terminal_low)}–"
                        f"{_fmt_price(tm_position_terminal_high)}"
                    ),
                    "Struktur": tm_eval.get("structure_alignment"),
                    "State manajemen": tm_eval.get("management_state"),
                }
            )
            if tm_eval.get("protection_state") in {
                "SL_TP_MISSING",
                "SL_MISSING_TP_PRESENT",
            }:
                tm_alerts.append(
                    (
                        "error",
                        f"Posisi {tm_eval.get('position_id')} tidak memiliki SL broker. "
                        "Ini harus dianggap PROTECTION REQUIRED.",
                    )
                )
            elif tm_eval.get("first_target_state") == "REACHED":
                tm_alerts.append(
                    (
                        "success",
                        f"Posisi {tm_eval.get('position_id')} sudah mencapai reaction target "
                        f"{_fmt_price(tm_eval.get('first_reaction_target'))}. "
                        "V195 menandai REVIEW PROTECTION; keputusan BE/partial tetap manual "
                        "sampai policy manajemen tervalidasi.",
                    )
                )
            elif (
                tm_eval.get("current_r") is not None
                and float(tm_eval.get("current_r")) >= 1.0
            ):
                tm_alerts.append(
                    (
                        "warning",
                        f"Posisi {tm_eval.get('position_id')} sudah ≥1R. "
                        "V195 hanya menandai REVIEW PROTECTION; tidak memindahkan SL otomatis.",
                    )
                )

        st.dataframe(
            pd.DataFrame(tm_rows),
            hide_index=True,
            width="stretch",
        )
        for tm_level, tm_message in tm_alerts:
            if tm_level == "error":
                st.error(tm_message)
            elif tm_level == "success":
                st.success(tm_message)
            else:
                st.warning(tm_message)

        st.info(
            "Urutan manajemen: **proteksi broker → progress terhadap R → reaction target → "
            "terminal opposing zone → opposing M5 leg berikutnya → alignment struktur terbaru**. "
            "Target sekarang dipilih **per side posisi** dari leg V196 yang sesuai (BUY=LONG, SELL=SHORT), "
            "dengan fallback ke path aktif bila projection belum tersedia. "
            "BE reference = harga entry; net break-even aktual dapat berbeda karena "
            "spread/komisi/swap."
        )
    else:
        st.info(
            "Tidak ada posisi XAUUSD aktif pada snapshot cTrader DEMO scanner. "
            "Jika Anda memiliki posisi LIVE pribadi (misalnya posisi yang terlihat pada screenshot), "
            "posisi tersebut memang tidak akan muncul di panel ini karena sumber LIVE dan DEMO "
            "sengaja dipisahkan."
        )

    st.markdown("## Pusat Bukti XAUUSD (V197–V201)")
    st.caption(
        "Panel ini menilai forecast M5 V196 secara prospective. Order broker **tidak diperlukan** "
        "agar suatu forecast dihitung sebagai shadow evidence, tetapi bukti ini tetap dipisahkan "
        "dari realized trade/PnL. Geometry forecast baru setelah V198 bersifat immutable."
    )
    if v198_analytics_hb is None:
        st.warning(
            "V198 Evidence Analytics belum mempunyai heartbeat runtime. "
            "Panel akan aktif setelah maintenance cycle berikutnya."
        )
    else:
        ev_details = dict(v198_analytics_hb.get("details") or {})
        ev_all = dict(ev_details.get("all_evidence") or {})
        ev_strict = dict(ev_details.get("strict_immutable_evidence") or {})
        ev_legacy = dict(ev_details.get("legacy_pre_freeze_evidence") or {})
        ev_path = dict(ev_details.get("full_path") or {})
        ev_strict_path = dict(ev_details.get("strict_full_path") or {})

        ev1, ev2, ev3, ev4 = st.columns(4)
        ev1.metric("Strict immutable", int(ev_strict.get("enrolled") or 0))
        ev2.metric("Strict touched", int(ev_strict.get("touched") or 0))
        ev3.metric(
            "Reaction hit | touch",
            _fmt_pct(ev_strict.get("reaction_precision_given_touch")),
        )
        ev4.metric(
            "Full Path stage",
            f"{int(ev_strict_path.get('max_stage_score') or 0)}/5",
        )

        st.info(
            f"Strict sample: **{ev_strict.get('sample_state','COLLECTING')}** • "
            f"resolved-after-touch={int(ev_strict.get('resolved_after_touch') or 0)} • "
            f"Wilson LB95 reaction={_fmt_pct(ev_strict.get('reaction_wilson_lower_95'))} • "
            f"80% gate={'LOLOS' if ev_strict.get('target_80pct_gate_met') else 'BELUM'}. "
            "Gate ini hanya diagnostik/statistik dan tidak memberi execution/promotion authority."
        )

        st.caption(
            f"Semua prospective evidence: enrolled={int(ev_all.get('enrolled') or 0)}, "
            f"touched={int(ev_all.get('touched') or 0)}, "
            f"reaction hits={int(ev_all.get('reaction_hits') or 0)}, "
            f"terminal hits={int(ev_all.get('terminal_hits') or 0)}. "
            f"Legacy pre-freeze={int(ev_legacy.get('enrolled') or 0)} episode; "
            "legacy tetap ditampilkan sebagai bukti observasional tetapi dikeluarkan dari "
            "strict promotion-grade statistics karena geometry-nya pernah mutable."
        )

        ev_chains = list(ev_path.get("latest_chains") or [])
        if ev_chains:
            latest_chain = dict(ev_chains[-1])
            st.info(
                f"Full Path terbaru: **stage {int(latest_chain.get('stage_score') or 0)}/5** • "
                f"{latest_chain.get('state','—')} • "
                f"{latest_chain.get('current_direction','—')} → "
                f"{latest_chain.get('reverse_direction') or '—'}. "
                "Urutan stage: touch current → reaction current → touch opposing pocket → "
                "reverse reaction → reverse terminal."
            )

        if v201_reaction_hb is not None:
            v201 = dict(v201_reaction_hb.get("details") or {})
            ladder = list(v201.get("strict_ladder") or [])
            latest_physical = list(v201.get("latest_physical_pockets") or [])
            l1, l2, l3, l4 = st.columns(4)
            l1.metric("Physical pockets", int(v201.get("physical_pockets") or 0))
            l2.metric(
                "Pre-mapped sebelum touch",
                _fmt_pct(v201.get("premap_rate_given_touch")),
            )
            l3.metric(
                "Median lead",
                (
                    "—"
                    if v201.get("median_premap_lead_minutes") is None
                    else f"{float(v201.get('median_premap_lead_minutes')):.0f} mnt"
                ),
            )
            half = next(
                (
                    dict(item)
                    for item in ladder
                    if float(item.get("atr_multiple") or -1) == 0.5
                ),
                {},
            )
            l4.metric(
                "0.50 ATR | decisive",
                _fmt_pct(half.get("precision_decisive")),
            )

            rung_text = []
            for item in ladder:
                rung_text.append(
                    f"{float(item.get('atr_multiple') or 0):.2f}ATR "
                    f"{int(item.get('confirmed_hits') or 0)}/"
                    f"{int(item.get('decisive_n') or 0)} decisive"
                )
            if rung_text:
                st.caption(
                    "V201 Reaction Ladder strict: " + " • ".join(rung_text)
                    + ". Pending yang belum mencapai rung diperlakukan sebagai censored, bukan gagal."
                )

            if latest_physical:
                last_pocket = dict(latest_physical[-1])
                roles = " → ".join(
                    str(item.get("role") or "—")
                    for item in list(last_pocket.get("role_timeline") or [])
                )
                lead_minutes = last_pocket.get("premap_lead_minutes")
                lead_text = (
                    "—"
                    if lead_minutes is None
                    else f"{float(lead_minutes):.0f} mnt"
                )
                st.info(
                    "Pocket fisik terbaru: "
                    f"**{last_pocket.get('direction','—')} "
                    f"{_fmt_price(last_pocket.get('pocket_low'))}–"
                    f"{_fmt_price(last_pocket.get('pocket_high'))}** • "
                    f"role={roles or '—'} • "
                    f"first seen={_fmt_wib_datetime(last_pocket.get('first_seen_at'), seconds=False)} • "
                    f"first touch={_fmt_wib_datetime(last_pocket.get('first_touch_at'), seconds=False)} • "
                    f"lead={lead_text} • "
                    f"status={last_pocket.get('status','—')}."
                )

            if latest_physical:
                last_pocket = dict(latest_physical[-1])
                rung_chronology = []
                for item in list(last_pocket.get("reaction_ladder") or []):
                    multiple = float(item.get("atr_multiple") or 0.0)
                    first_hit = item.get("first_hit_at")
                    state = str(item.get("chronology_state") or "—")
                    if first_hit is not None:
                        minutes = item.get("minutes_from_touch")
                        minute_text = (
                            "—"
                            if minutes is None
                            else f"{float(minutes):.0f} mnt"
                        )
                        rung_chronology.append(
                            f"{multiple:.2f}ATR "
                            f"{_fmt_price(item.get('threshold_price'))} → "
                            f"{_fmt_wib_datetime(first_hit, seconds=False)} "
                            f"({minute_text} setelah touch)"
                        )
                    else:
                        rung_chronology.append(
                            f"{multiple:.2f}ATR "
                            f"{_fmt_price(item.get('threshold_price'))} → {state}"
                        )
                if rung_chronology:
                    st.caption(
                        "Chronology completed-M5: "
                        + " • ".join(rung_chronology)
                        + ". Pre-touch dan M5 yang belum selesai tidak dihitung."
                    )

                versions = list(last_pocket.get("target_versions") or [])
                if versions:
                    latest_target = dict(versions[-1])
                    checkpoint_parts = []
                    for cp in list(latest_target.get("checkpoint_targets") or []):
                        checkpoint_parts.append(
                            f"{_fmt_price(cp.get('price'))}@"
                            f"{_fmt_wib_datetime(cp.get('first_hit_at'), seconds=False)}"
                        )
                    checkpoint_text = (
                        "—" if not checkpoint_parts else ", ".join(checkpoint_parts)
                    )
                    st.caption(
                        "Target chronology versi terbaru: "
                        f"mapped={_fmt_wib_datetime(latest_target.get('mapped_at'), seconds=False)} • "
                        f"checkpoint={checkpoint_text} • "
                        f"reaction={_fmt_price(latest_target.get('reaction_target'))} "
                        f"first hit={_fmt_wib_datetime(latest_target.get('reaction_first_hit_at'), seconds=False)} • "
                        f"terminal={_fmt_price(latest_target.get('terminal_target'))} "
                        f"first hit={_fmt_wib_datetime(latest_target.get('terminal_first_hit_at'), seconds=False)}. "
                        "Target version tidak boleh backfill pergerakan sebelum mapped_at."
                    )

        with st.expander("Detail evidence analytics V198/V201"):
            st.json(
                {
                    "observed_at_v198": v198_analytics_hb.get("observed_at"),
                    "strict_immutable_evidence": ev_strict,
                    "legacy_pre_freeze_evidence": ev_legacy,
                    "strict_segments": ev_details.get("strict_segments"),
                    "full_path": ev_path,
                    "strict_full_path": ev_strict_path,
                    "v201_reaction_ladder": (
                        {}
                        if v201_reaction_hb is None
                        else dict(v201_reaction_hb.get("details") or {})
                    ),
                    "v197_recorder": (
                        {}
                        if v197_evidence_hb is None
                        else dict(v197_evidence_hb.get("details") or {})
                    ),
                }
            )

    st.markdown("---")
    st.caption(
        "Di bawah ini adalah DETAIL / AUDIT / RISET. Untuk keputusan cepat, "
        "gunakan Decision Center dan Trade Management Center di atas."
    )

    with st.expander(
        "Detail Diagnostik AFIC ↔ Supply/Demand / V189 / DOM / Event",
        expanded=False,
    ):
        st.caption(
            "Detail ini tetap tersedia untuk audit. Untuk keputusan cepat gunakan "
            "Pusat Keputusan XAUUSD di atas."
        )
        st.markdown("### Integrasi AFIC ↔ Supply/Demand")
        st.caption(
            "Supply/Demand V182 sekarang menjadi context map untuk AFIC. Context ini dapat "
            "mendukung zona canonical, memberi peringatan zona reversal lawan, atau menyediakan "
            "fallback PREPARE ketika canonical AFIC belum ada. Context ini TIDAK mengubah Grade "
            "A/B, tidak membuat signal broker, dan tidak menggantikan konfirmasi M15."
        )
        if afic_sd_context:
            sd_same = dict(afic_sd_context.get("same_direction_zone") or {})
            sd_opp = dict(afic_sd_context.get("opposite_reversal_zone") or {})
            ic1, ic2, ic3, ic4 = st.columns(4)
            ic1.metric("State integrasi", str(afic_sd_context.get("state") or "—"))
            ic2.metric(
                "Confluence canonical",
                "YA" if afic_sd_context.get("same_direction_confluence") else "TIDAK",
            )
            ic3.metric(
                "Zona lawan dekat harga",
                "YA" if afic_sd_context.get("opposite_zone_near_price") else "TIDAK",
            )
            ic4.metric("Otoritas eksekusi", "TIDAK ADA")
            if sd_same:
                st.info(
                    "Supply/Demand searah AFIC: "
                    f"{sd_same.get('timeframe','—')} {sd_same.get('pattern','—')} "
                    f"{_fmt_price(sd_same.get('low'))}–{_fmt_price(sd_same.get('high'))} • "
                    f"overlap canonical={_fmt_pct(afic_sd_context.get('same_direction_overlap_ratio'))} • "
                    f"jarak ke canonical="
                    f"{_fmt_distance(afic_sd_context.get('same_direction_distance_atr'),' ATR')}."
                )
            if sd_opp:
                st.warning(
                    "Zona reversal lawan: "
                    f"{sd_opp.get('timeframe','—')} {sd_opp.get('pattern','—')} "
                    f"{_fmt_price(sd_opp.get('low'))}–{_fmt_price(sd_opp.get('high'))} • "
                    f"jarak dari harga="
                    f"{_fmt_distance(afic_sd_context.get('opposite_zone_distance_atr'),' ATR')}. "
                    "Ini adalah Plan-B / reaction watch, bukan alasan entry melawan AFIC."
                )
            dom_context = dict(afic_sd_context.get("dom_context") or {})
            if not dom_context and dom_v191_hb is not None:
                dom_details = dict(dom_v191_hb.get("details") or {})
                dom_context = dict(dom_details.get("analysis") or {})
                dom_context["stale"] = False
                dom_context["alignment_with_first_leg"] = "BELUM_DIHUBUNGKAN_KE_SNAPSHOT_AFIC"
            if dom_context:
                d1, d2, d3, d4 = st.columns(4)
                d1.metric("DOM V191", str(dom_context.get("state") or "—"))
                d2.metric(
                    "Pressure score",
                    "—"
                    if dom_context.get("pressure_score") is None
                    and dom_context.get("dom_pressure_score") is None
                    else f"{float(dom_context.get('pressure_score', dom_context.get('dom_pressure_score'))):.1f}",
                )
                d3.metric(
                    "Imbalance top-5",
                    "—"
                    if dom_context.get("last_imbalance") is None
                    else f"{float(dom_context.get('last_imbalance')):+.2f}",
                )
                d4.metric(
                    "Alignment first-leg",
                    str(dom_context.get("alignment_with_first_leg") or "—"),
                )
                st.caption(
                    "DOM berasal dari Level II cTrader broker/venue, bukan consolidated COMEX book. "
                    "V191 hanya context/shadow evidence dan tidak memiliki execution authority."
                )
                bid_wall = dict(dom_context.get("bid_wall") or {})
                ask_wall = dict(dom_context.get("ask_wall") or {})
                if bid_wall or ask_wall:
                    st.caption(
                        "Wall persistence • BID "
                        f"{_fmt_price(bid_wall.get('dominant_wall_price'))} / "
                        f"{_fmt_pct(bid_wall.get('wall_persistence'))} • ASK "
                        f"{_fmt_price(ask_wall.get('dominant_wall_price'))} / "
                        f"{_fmt_pct(ask_wall.get('wall_persistence'))}."
                    )
                resolution = afic_sd_context.get("conflict_resolution_evidence")
                if resolution:
                    st.info(f"Evidence resolusi compression: {resolution}")

            event_context = dict(afic_sd_context.get("event_risk_context") or {})
            if not event_context and event_risk_v192_hb is not None:
                event_details = dict(event_risk_v192_hb.get("details") or {})
                event_context = dict(event_details.get("risk") or {})
                event_context["source_status"] = dict(event_details.get("source_status") or {})
                event_context["official_or_cadence_verified_count"] = event_details.get(
                    "official_or_cadence_verified_count"
                )
                event_context["discovery_unverified_count"] = event_details.get(
                    "discovery_unverified_count"
                )
                event_context["stale"] = False
            if event_context:
                focal_event = dict(event_context.get("focal_event") or {})
                e1, e2, e3, e4 = st.columns(4)
                e1.metric("Event Risk V192", str(event_context.get("state") or "—"))
                e2.metric("Aksi", str(event_context.get("action") or "—"))
                e3.metric(
                    "Event terdekat",
                    str(focal_event.get("title") or "Tidak ada event dekat"),
                )
                e4.metric(
                    "Jarak waktu",
                    "—"
                    if event_context.get("minutes_to_focal") is None
                    else f"{float(event_context.get('minutes_to_focal')):+.0f} menit",
                )
                if focal_event:
                    st.caption(
                        "Focal event: "
                        f"{focal_event.get('title','—')} • "
                        f"{_fmt_wib_datetime(focal_event.get('scheduled_at'), seconds=False)} • "
                        f"{focal_event.get('source_tier','—')} • "
                        f"{focal_event.get('source','—')}."
                    )
                upcoming = list(event_context.get("upcoming_events") or [])
                if upcoming:
                    event_rows = []
                    for item in upcoming[:6]:
                        event_rows.append(
                            {
                                "Waktu WIB": _fmt_wib_datetime(
                                    item.get("scheduled_at"), seconds=False
                                ),
                                "Event": item.get("title"),
                                "Impact": item.get("impact"),
                                "Kategori": item.get("category"),
                                "Tier sumber": item.get("source_tier"),
                                "Sumber": item.get("source"),
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(event_rows),
                        hide_index=True,
                        width="stretch",
                    )
                st.caption(
                    "V192 adalah context risiko waktu, bukan prediksi arah berita. "
                    "PRE_EVENT/EVENT_WINDOW hanya mengubah cara membaca setup menjadi lebih hati-hati; "
                    "tidak memiliki execution authority."
                )
                if event_context.get("stale"):
                    st.warning(
                        "Event-risk snapshot stale. Jangan gunakan kalender ini sebagai context aktif "
                        "sampai heartbeat V192 diperbarui."
                    )

            if afic_sd_context.get("path_direction_conflict"):
                st.warning(
                    "KONFLIK SUPPLY/DEMAND H1: zona LONG dan SHORT saling overlap "
                    f"sekitar {_fmt_pct(afic_sd_context.get('path_overlap_ratio'))}. "
                    "State = COMPRESSION / WAIT MICRO RESOLUTION. Jangan membaca salah satu "
                    "arah sebagai valid hanya karena harga sedang berada di dalam satu zona; "
                    "tunggu V189 M5 reclaim/MSS/displacement."
                )
            afic_first_leg_path = dict(afic_sd_context.get("first_leg_path") or {})
            if afic_first_leg_path:
                path_source = dict(afic_first_leg_path.get("source_zone") or {})
                path_target = dict(afic_first_leg_path.get("primary_opposing_zone") or {})
                path_waypoints = list(afic_first_leg_path.get("internal_targets") or [])
                if path_source:
                    st.success(
                        "Path AFIC saat ini: "
                        f"{afic_first_leg_path.get('reaction_direction','—')} dari "
                        f"{_fmt_price(path_source.get('low'))}–{_fmt_price(path_source.get('high'))}"
                        + (
                            " → target opposing zone "
                            f"{_fmt_price(path_target.get('low'))}–{_fmt_price(path_target.get('high'))}"
                            if path_target else
                            " → opposing zone belum tersedia"
                        )
                        + "."
                    )
                    if path_waypoints:
                        waypoint_text = " → ".join(
                            f"{item.get('source','LEVEL')} {_fmt_price(item.get('price'))}"
                            for item in path_waypoints[:5]
                        )
                        st.caption(
                            "Waypoint internal sebelum opposing zone: " + waypoint_text
                        )
                    reaction_target = dict(
                        afic_first_leg_path.get("reaction_target") or {}
                    )
                    terminal_target = dict(
                        afic_first_leg_path.get("terminal_target_zone") or {}
                    )
                    if reaction_target:
                        st.success(
                            "Target reaction utama: "
                            f"{_fmt_price(reaction_target.get('price'))} "
                            f"({reaction_target.get('source','—')})"
                            + (
                                " → terminal opposing zone "
                                f"{_fmt_price(terminal_target.get('low'))}–"
                                f"{_fmt_price(terminal_target.get('high'))}"
                                if terminal_target else ""
                            )
                        )
                    path_dest_stack = list(
                        afic_first_leg_path.get("destination_stack") or []
                    )
                    if path_dest_stack:
                        st.caption(
                            "Destination stack: "
                            + " | ".join(
                                f"{item.get('timeframe','—')} "
                                f"{_fmt_price(item.get('low'))}–{_fmt_price(item.get('high'))} "
                                f"[{dict(item.get('lifecycle') or {}).get('freshness','—')}]"
                                for item in path_dest_stack[:4]
                            )
                        )
                    afic_micro = dict(
                        afic_sd_context.get("first_leg_micro_refinement") or {}
                    )
                    if afic_micro:
                        micro_candidate = dict(afic_micro.get("candidate_entry_pocket") or {})
                        micro_refined = dict(afic_micro.get("refined_entry_pocket") or {})
                        st.info(
                            "Micro Refinement V189: "
                            f"{afic_micro.get('state','—')} • "
                            f"sweep={_fmt_price(dict(afic_micro.get('sweep') or {}).get('price'))} • "
                            f"reclaim={_fmt_price(afic_micro.get('source_proximal_reclaim_level'))} • "
                            f"MSS={_fmt_price(afic_micro.get('mss_level'))}."
                        )
                        if micro_refined:
                            st.success(
                                "Refined entry pocket M5 (SHADOW): "
                                f"{_fmt_price(micro_refined.get('low'))}–"
                                f"{_fmt_price(micro_refined.get('high'))}. "
                                "Ini belum memberi izin eksekusi."
                            )
                        elif micro_candidate:
                            st.caption(
                                "Candidate M5 pocket: "
                                f"{_fmt_price(micro_candidate.get('low'))}–"
                                f"{_fmt_price(micro_candidate.get('high'))}; "
                                "masih menunggu reclaim/MSS/displacement."
                            )
                    st.caption(
                        "Path ini baru aktif sebagai PREPARE/FORECAST. Reaction tetap harus "
                        "dibuktikan oleh sweep/mitigation lalu reclaim/MSS/displacement M5/M15."
                    )
            if afic_sd_context.get("prepare_only_fallback"):
                st.warning(
                    "Canonical AFIC belum memiliki zona valid, tetapi atlas Supply/Demand "
                    "memiliki context aktif. Scanner boleh menampilkan PERSIAPAN/WATCH lebih awal, "
                    "namun order tetap dilarang sampai canonical AFIC + completed M15 confirmation "
                    "terbentuk."
                )
            if afic_sd_context.get("atlas_stale"):
                st.error(
                    "Snapshot Supply/Demand terlalu lama untuk dipakai sebagai context aktif. "
                    "AFIC tetap berjalan tanpa policy effect dari atlas sampai heartbeat baru tersedia."
                )
        else:
            st.caption(
                "Context integrasi AFIC ↔ Supply/Demand belum tersedia pada snapshot runtime ini."
            )


    st.markdown("### Rezim Strategis HTF (Strategic HTF Regime)")
    regime_details = {} if regime_hb is None else dict(regime_hb.get("details") or {})
    regime_eval = dict(regime_details.get("evaluation") or {})
    regime_current = dict(regime_eval.get("current") or {})
    regime_pool = dict(regime_eval.get("zone_pool") or {})
    if regime_current:
        strategic_bias = str(regime_current.get("strategic_bias") or "NEUTRAL")
        tactical_first_leg = str(regime_current.get("tactical_first_leg") or "NEUTRAL")
        strategic_confidence = regime_current.get("confidence")
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Bias Strategis (Strategic Bias)", strategic_bias)
        r2.metric(
            "Keyakinan HTF (HTF confidence)",
            "—" if strategic_confidence is None else _fmt_pct(strategic_confidence),
        )
        r3.metric("Gerak Taktis Pertama (Tactical First Leg)", tactical_first_leg)
        r4.metric("Zona canonical 0–24j", regime_pool.get("canonical_count", 0))
        r5.metric("Zona shadow 24–48j", regime_pool.get("shadow_count", 0))
        st.caption(
            "Bias strategis V180 hanya memakai D1 + H4 yang sudah selesai dan menggunakan "
            "hysteresis agar arah tidak berubah hanya karena update M15. Contoh: Bias "
            "Strategis SHORT tetap dapat memiliki gerak taktis pertama LONG ketika harga "
            "naik menuju zona jual di atas. Zona shadow 24–48 jam TIDAK memiliki izin eksekusi."
        )
        if strategic_bias in {"LONG", "SHORT"}:
            desired = str(regime_pool.get("desired_reaction_side") or "—")
            st.info(
                f"Rencana HTF: {strategic_bias} • gerak pertama {tactical_first_leg} • "
                f"cari {desired.replace('_', ' ')}. "
                f"Arah candle H4 AFIC saat ini = {direction}. "
                "Keduanya dapat berbeda karena V180 adalah konteks strategis, sedangkan "
                "AFIC V161 tetap merupakan peta taktis canonical untuk eksekusi."
            )
        shadow_zones = list(regime_pool.get("shadow_24_48h") or [])
        if not regime_pool.get("canonical_count") and shadow_zones:
            nearest_shadow = dict(shadow_zones[0])
            st.warning(
                "Tidak ada H1 origin canonical 0–24 jam yang selaras HTF, tetapi terdapat "
                "zona riset 24–48 jam yang masih aktif secara struktural di "
                f"{_fmt_price(nearest_shadow.get('low'))}–"
                f"{_fmt_price(nearest_shadow.get('high'))}. "
                "Zona ini hanya untuk riset sampai validasi forward mendukung perubahan batas umur."
            )
    else:
        st.caption(
            "Rezim Strategis HTF V180 belum menerbitkan snapshot shadow. "
            "AFIC V161 tetap menjadi otoritas eksekusi."
        )

    st.markdown("### Atlas Supply & Demand HTF (V182)")
    st.caption(
        "Atlas riset D1/H4/H1 untuk mendeteksi demand/supply lebih awal dari canonical AFIC. "
        "Zona dibentuk dari structural origin atau base→departure imbalance, lalu dinilai "
        "berdasarkan freshness, touch/mitigation, HTF nesting, liquidity confluence, jarak, "
        "dan kualitas pendekatan harga. V182 SELALU PREPARE ONLY / NO EXECUTION."
    )
    sd_details = {} if supply_demand_hb is None else dict(supply_demand_hb.get("details") or {})
    sd_eval = dict(sd_details.get("evaluation") or {})
    sd_zones = list(sd_eval.get("zones") or [])
    if sd_zones:
        sd1, sd2, sd3, sd4 = st.columns(4)
        sd1.metric("Zona aktif", sd_eval.get("active_count", 0))
        sd2.metric("Zona ditampilkan", sd_eval.get("display_count", len(sd_zones)))
        sd3.metric("Konteks sesi", str(sd_eval.get("session_context") or "—"))
        sd4.metric("Izin eksekusi", "TIDAK ADA")

        nearest_demand = dict(sd_eval.get("nearest_demand") or {})
        nearest_supply = dict(sd_eval.get("nearest_supply") or {})
        sd_path_map = dict(sd_eval.get("path_map") or {})
        sd_active_path = dict(sd_path_map.get("active_path") or {})
        nd_col, ns_col = st.columns(2)
        with nd_col:
            if nearest_demand:
                nd_lifecycle = dict(nearest_demand.get("lifecycle") or {})
                nd_approach = dict(nearest_demand.get("approach") or {})
                st.info(
                    "Demand terdekat: "
                    f"{nearest_demand.get('timeframe','—')} "
                    f"{nearest_demand.get('pattern','—')} • "
                    f"{_fmt_price(nearest_demand.get('low'))}–"
                    f"{_fmt_price(nearest_demand.get('high'))} • "
                    f"freshness={nd_lifecycle.get('freshness','—')} • "
                    f"jarak={_fmt_distance(nearest_demand.get('distance_atr'),' ATR')} • "
                    f"approach={nd_approach.get('state','—')}"
                )
            else:
                st.caption("Demand aktif di sisi harga yang benar belum tersedia.")
        with ns_col:
            if nearest_supply:
                ns_lifecycle = dict(nearest_supply.get("lifecycle") or {})
                ns_approach = dict(nearest_supply.get("approach") or {})
                st.warning(
                    "Supply terdekat: "
                    f"{nearest_supply.get('timeframe','—')} "
                    f"{nearest_supply.get('pattern','—')} • "
                    f"{_fmt_price(nearest_supply.get('low'))}–"
                    f"{_fmt_price(nearest_supply.get('high'))} • "
                    f"freshness={ns_lifecycle.get('freshness','—')} • "
                    f"jarak={_fmt_distance(nearest_supply.get('distance_atr'),' ATR')} • "
                    f"approach={ns_approach.get('state','—')}"
                )
            else:
                st.caption("Supply aktif di sisi harga yang benar belum tersedia.")

        sd_table = []
        for item in sd_zones:
            lifecycle = dict(item.get("lifecycle") or {})
            liquidity = dict(item.get("liquidity") or {})
            approach = dict(item.get("approach") or {})
            sd_table.append(
                {
                    "TF": item.get("timeframe"),
                    "kelas": item.get("zone_class"),
                    "pola": item.get("pattern"),
                    "arah reaksi": item.get("direction"),
                    "zona": (
                        f"{_fmt_price(item.get('low'))}–"
                        f"{_fmt_price(item.get('high'))}"
                    ),
                    "proximal": item.get("proximal"),
                    "distal": item.get("distal"),
                    "dibentuk (WIB)": _fmt_wib_datetime(item.get("available_at")),
                    "umur": item.get("age_bucket"),
                    "freshness": lifecycle.get("freshness"),
                    "touch": lifecycle.get("touch_count"),
                    "mitigation": lifecycle.get("mitigation_depth"),
                    "jarak (ATR)": item.get("distance_atr"),
                    "HTF nesting": item.get("htf_nesting_count"),
                    "likuiditas": liquidity.get("confluence_count"),
                    "approach": approach.get("state"),
                    "displacement (ATR)": item.get("departure_range_atr"),
                    "body displacement": item.get("departure_body_fraction"),
                    "selaras strategis": item.get("strategic_alignment"),
                    "skor riset": item.get("research_score"),
                    "status": item.get("status"),
                }
            )
        st.dataframe(pd.DataFrame(sd_table), hide_index=True, width="stretch")
        demand_source_stack = list(sd_path_map.get("demand_source_stack") or [])
        supply_source_stack = list(sd_path_map.get("supply_source_stack") or [])
        if demand_source_stack:
            st.caption(
                "Demand stack aktif: "
                + " | ".join(
                    f"{item.get('timeframe','—')} "
                    f"{_fmt_price(item.get('low'))}–{_fmt_price(item.get('high'))} "
                    f"[{dict(item.get('lifecycle') or {}).get('freshness','—')}]"
                    for item in demand_source_stack[:4]
                )
            )
        if supply_source_stack:
            st.caption(
                "Supply stack aktif: "
                + " | ".join(
                    f"{item.get('timeframe','—')} "
                    f"{_fmt_price(item.get('low'))}–{_fmt_price(item.get('high'))} "
                    f"[{dict(item.get('lifecycle') or {}).get('freshness','—')}]"
                    for item in supply_source_stack[:4]
                )
            )
        if sd_active_path:
            source = dict(sd_active_path.get("source_zone") or {})
            target = dict(sd_active_path.get("primary_opposing_zone") or {})
            st.info(
                "Rute reaksi V186: "
                f"{sd_active_path.get('reaction_direction','—')} • "
                f"sumber {_fmt_price(source.get('low'))}–{_fmt_price(source.get('high'))}"
                + (
                    f" → opposing zone {_fmt_price(target.get('low'))}–{_fmt_price(target.get('high'))}"
                    if target else
                    " → opposing zone belum tersedia"
                )
            )
            reaction_target = dict(sd_active_path.get("reaction_target") or {})
            if reaction_target:
                st.success(
                    "Target reaction V188: "
                    f"{_fmt_price(reaction_target.get('price'))} • "
                    f"basis={sd_active_path.get('reaction_target_basis','—')}."
                )
            destination_stack = list(sd_active_path.get("destination_stack") or [])
            if destination_stack:
                st.caption(
                    "Opposing-zone stack: "
                    + " | ".join(
                        f"{item.get('timeframe','—')} "
                        f"{_fmt_price(item.get('low'))}–{_fmt_price(item.get('high'))} "
                        f"[{dict(item.get('lifecycle') or {}).get('freshness','—')}]"
                        for item in destination_stack[:4]
                    )
                )
        sd_micro = dict(sd_eval.get("micro_refinement") or {})
        if sd_micro:
            micro1, micro2, micro3, micro4 = st.columns(4)
            micro1.metric("V189 state", str(sd_micro.get("state") or "—"))
            micro2.metric(
                "Sweep M5",
                _fmt_price(dict(sd_micro.get("sweep") or {}).get("price")),
            )
            micro3.metric(
                "Reclaim level",
                _fmt_price(sd_micro.get("source_proximal_reclaim_level")),
            )
            micro4.metric(
                "MSS level",
                _fmt_price(sd_micro.get("mss_level")),
            )
            refined = dict(sd_micro.get("refined_entry_pocket") or {})
            candidate = dict(sd_micro.get("candidate_entry_pocket") or {})
            if refined:
                st.success(
                    "Refined entry pocket M5 (SHADOW ONLY): "
                    f"{_fmt_price(refined.get('low'))}–{_fmt_price(refined.get('high'))}."
                )
            elif candidate:
                st.caption(
                    "Candidate entry pocket M5: "
                    f"{_fmt_price(candidate.get('low'))}–{_fmt_price(candidate.get('high'))}; "
                    "belum confirmed."
                )
        st.caption(
            "Skor riset V182 adalah ranking evidence, BUKAN probabilitas menang. "
            "Liquidity/round number hanya confluence, bukan pembentuk zona tunggal. "
            "Canonical AFIC ≤24 jam, M15 confirmation, fresh quote, risk/margin, dan "
            "server-side SL/TP tetap menjadi jalur eksekusi yang terpisah."
        )
    else:
        st.info(
            "Atlas V182 belum memiliki zona yang dapat ditampilkan pada snapshot terbaru. "
            "Ketiadaan zona V182 tidak memaksa scanner membuat setup."
        )

    st.markdown("### Validasi Historis Supply & Demand (V183)")
    st.caption(
        "Profiler 100K-bar ini memisahkan destination rate dari reaction rate. "
        "Target primer HOLD = +0,50 ATR dalam 16 candle M15 sebelum close menembus distal. "
        "Hasil V183 adalah evidence riset dan TIDAK memberi izin eksekusi."
    )
    v183_details = (
        {} if supply_demand_research_hb is None
        else dict(supply_demand_research_hb.get("details") or {})
    )
    v183_eval = dict(v183_details.get("evaluation") or {})
    if v183_eval:
        v183_holdout = dict(v183_eval.get("holdout_overall") or {})
        v183_destination = dict(v183_eval.get("destination_overall") or {})
        v183_candidates = list(v183_eval.get("candidate_80_precision_subsets") or [])
        vh1, vh2, vh3, vh4, vh5 = st.columns(5)
        vh1.metric("Keputusan riset", str(v183_eval.get("decision") or "—"))
        vh2.metric("Zona historis", v183_eval.get("zones", 0))
        vh3.metric(
            "Destination touch rate",
            "—"
            if v183_destination.get("touch_rate") is None
            else _fmt_pct(v183_destination.get("touch_rate")),
        )
        vh4.metric(
            "Holdout HOLD precision",
            "—"
            if v183_holdout.get("precision_hold") is None
            else _fmt_pct(v183_holdout.get("precision_hold")),
        )
        vh5.metric("Subset ≥80% (riset)", len(v183_candidates))
        st.caption(
            f"Holdout n={v183_holdout.get('n','—')} • "
            f"Wilson lower 95%="
            f"{'—' if v183_holdout.get('wilson_lower_95') is None else _fmt_pct(v183_holdout.get('wilson_lower_95'))} • "
            f"mean MFE={_fmt_distance(v183_holdout.get('mean_mfe_atr'),' ATR')} • "
            f"mean MAE={_fmt_distance(v183_holdout.get('mean_mae_atr'),' ATR')}. "
            "Subset ≥80% tetap eksploratif dan tidak dipromosikan otomatis."
        )
        if v183_candidates:
            candidate_rows = []
            for item in v183_candidates[:10]:
                dims = dict(item.get("dimensions") or {})
                candidate_rows.append(
                    {
                        "kontrak grup": " | ".join(item.get("group_contract") or []),
                        "dimensi": ", ".join(f"{k}={v}" for k, v in dims.items()),
                        "n holdout": item.get("n"),
                        "HOLD precision": item.get("precision_hold"),
                        "Wilson lower 95%": item.get("wilson_lower_95"),
                        "mean MFE (ATR)": item.get("mean_mfe_atr"),
                        "mean MAE (ATR)": item.get("mean_mae_atr"),
                        "otoritas": "RISET SAJA",
                    }
                )
            st.dataframe(
                pd.DataFrame(candidate_rows),
                hide_index=True,
                width="stretch",
            )
        st.info(
            "V183 tidak mengubah V182, V181, canonical AFIC, atau broker lane. "
            "Promosi hanya boleh dipertimbangkan setelah prospective forward lifecycle "
            "mengonfirmasi subset yang sama pada data baru."
        )
    else:
        st.info(
            "V183 belum menerbitkan hasil 100K-bar. Dashboard akan menampilkan hasil "
            "holdout setelah workflow riset selesai."
        )

    st.markdown("### Validasi Timeframe-Aware Supply & Demand (V185)")
    st.caption(
        "V185 menguji reaction dengan horizon yang sesuai timeframe pada touch population "
        "yang sama: H1=4 jam, H4=24 jam, D1=72 jam. Sensitivity: H4 16/24 jam dan "
        "D1 48/72/120 jam. Semua hasil tetap RISET SAJA / NO EXECUTION."
    )
    v185_details = (
        {} if supply_demand_timeframe_hb is None
        else dict(supply_demand_timeframe_hb.get("details") or {})
    )
    v185_eval = dict(v185_details.get("evaluation") or {})
    v185_holdout = dict(v185_eval.get("holdout_by_timeframe") or {})
    if v185_holdout:
        tf_cols = st.columns(3)
        for tf_col, tf_name in zip(tf_cols, ("H1", "H4", "D1")):
            tf_payload = dict(v185_holdout.get(tf_name) or {})
            tf_primary = dict(tf_payload.get("primary") or {})
            with tf_col:
                st.metric(
                    f"{tf_name} HOLD precision",
                    "—"
                    if tf_primary.get("precision_hold") is None
                    else _fmt_pct(tf_primary.get("precision_hold")),
                )
                st.caption(
                    f"horizon={tf_payload.get('primary_horizon_hours','—')} jam • "
                    f"n={tf_primary.get('n',0)} • "
                    f"Wilson lower 95%="
                    f"{'—' if tf_primary.get('wilson_lower_95') is None else _fmt_pct(tf_primary.get('wilson_lower_95'))} • "
                    f"median outcome={tf_primary.get('median_bars_to_outcome','—')} M15."
                )
        sensitivity_rows = []
        for tf_name in ("H4", "D1"):
            tf_payload = dict(v185_holdout.get(tf_name) or {})
            for horizon_key, item in dict(tf_payload.get("sensitivity") or {}).items():
                item = dict(item or {})
                sensitivity_rows.append(
                    {
                        "TF": tf_name,
                        "horizon (jam)": item.get("horizon_hours"),
                        "n": item.get("n"),
                        "HOLD precision": item.get("precision_hold"),
                        "Wilson lower 95%": item.get("wilson_lower_95"),
                        "mean MFE (ATR)": item.get("mean_mfe_atr"),
                        "mean MAE (ATR)": item.get("mean_mae_atr"),
                    }
                )
        if sensitivity_rows:
            st.dataframe(
                pd.DataFrame(sensitivity_rows),
                hide_index=True,
                width="stretch",
            )
        v185_candidates = list(v185_eval.get("candidate_80_precision_subsets") or [])
        st.info(
            f"Keputusan V185: {v185_eval.get('decision','—')} • "
            f"episode={v185_eval.get('episodes','—')} • "
            f"subset holdout ≥80%={len(v185_candidates)}. "
            "Horizon sensitivity memakai touch population yang sama; hasil tidak memiliki "
            "promotion/execution authority."
        )
    else:
        st.info(
            "V185 belum menerbitkan hasil timeframe-aware. Setelah workflow 100K-bar selesai, "
            "dashboard akan menampilkan H1/H4/D1 holdout dan sensitivity horizon."
        )

    st.markdown("### Validasi Prospektif Supply & Demand (V184)")
    st.caption(
        "V184 hanya menghitung touch yang terjadi SETELAH zona didaftarkan oleh engine. "
        "Tidak ada backfill dari touch lama. Kandidat primer yang dibekukan dari V183 adalah "
        "H1 LONG + multi-HTF nesting + aggressive approach. Status tetap SHADOW ONLY."
    )
    v184_details = (
        {} if supply_demand_prospective_hb is None
        else dict(supply_demand_prospective_hb.get("details") or {})
    )
    v184_summary = dict(v184_details.get("summary") or {})
    v184_candidate = dict(v184_summary.get("primary_candidate") or {})
    v184_controls = dict(v184_summary.get("controls") or {})
    if v184_details:
        vp1, vp2, vp3, vp4, vp5 = st.columns(5)
        vp1.metric("Zona H1 dipantau", v184_details.get("h1_registry_rows_this_run", 0))
        vp2.metric("Reaction prospektif resolved", v184_summary.get("resolved_reactions", 0))
        vp3.metric("Reaction pending", v184_summary.get("pending_reactions", 0))
        vp4.metric(
            "Kandidat primer HOLD",
            "—"
            if v184_candidate.get("precision_hold") is None
            else _fmt_pct(v184_candidate.get("precision_hold")),
        )
        vp5.metric(
            "Gate replikasi",
            "TERPENUHI"
            if v184_candidate.get("replication_gate_met")
            else "BELUM",
        )
        st.caption(
            f"Kandidat primer: n={v184_candidate.get('n',0)} • "
            f"Wilson lower 95%="
            f"{'—' if v184_candidate.get('wilson_lower_95') is None else _fmt_pct(v184_candidate.get('wilson_lower_95'))} • "
            f"minimum n={v184_candidate.get('minimum_n','—')} • "
            f"target raw={_fmt_pct(v184_candidate.get('minimum_raw_precision')) if v184_candidate.get('minimum_raw_precision') is not None else '—'} • "
            f"target Wilson={_fmt_pct(v184_candidate.get('minimum_wilson_lower_95')) if v184_candidate.get('minimum_wilson_lower_95') is not None else '—'}."
        )
        c_long = dict(v184_controls.get("all_h1_long") or {})
        c_short = dict(v184_controls.get("all_h1_short") or {})
        st.info(
            f"Keputusan V184: {v184_summary.get('decision','—')}. "
            f"Kontrol H1 LONG={('—' if c_long.get('precision_hold') is None else _fmt_pct(c_long.get('precision_hold')))} "
            f"(n={c_long.get('n',0)}), H1 SHORT="
            f"{('—' if c_short.get('precision_hold') is None else _fmt_pct(c_short.get('precision_hold')))} "
            f"(n={c_short.get('n',0)}). "
            "Bahkan jika gate replikasi terpenuhi, V184 tidak memiliki promotion/execution authority."
        )
    else:
        st.info(
            "V184 belum menerbitkan snapshot prospective. Episode baru akan dihitung "
            "hanya setelah worker pertama kali mendaftarkan zona; touch historis lama tidak di-backfill."
        )

    st.markdown("### Kandidat Zona Pra-H4 (Pre-map Candidate Zone)")
    st.caption(
        "Menampilkan H1 origin baru yang terbentuk setelah H4 map saat ini. Kandidat "
        "ini membantu persiapan lebih awal, tetapi statusnya SELALU tanpa izin eksekusi "
        "sampai H4 map berikutnya selesai dan AFIC canonical memvalidasinya."
    )
    premap_details = {} if premap_hb is None else dict(premap_hb.get("details") or {})
    premap_eval = dict(premap_details.get("evaluation") or {})
    premap_candidates = list(premap_eval.get("candidates") or [])
    if premap_candidates:
        pm1, pm2, pm3, pm4 = st.columns(4)
        pm1.metric("Jumlah kandidat pra-H4", premap_eval.get("candidate_count", len(premap_candidates)))
        pm2.metric("Bias strategis", str(premap_eval.get("strategic_bias") or "—"))
        pm3.metric("Arah H4 taktis", str(premap_eval.get("tactical_h4_direction") or "—"))
        pm4.metric("Izin eksekusi", "TIDAK ADA")
        st.warning(
            "PERSIAPAN SAJA / NO EXECUTION. Kandidat pra-H4 belum menjadi Trade Preparation "
            "canonical. Ia harus bertahan sampai completed H4 map berikutnya dan lolos "
            "pemilihan AFIC A/B sebelum dapat memiliki jalur broker."
        )
        premap_table = []
        for candidate in premap_candidates:
            liquidity = dict(candidate.get("liquidity") or {})
            premap_table.append(
                {
                    "arah": candidate.get("direction"),
                    "tersedia sejak (WIB)": _fmt_wib_datetime(candidate.get("available_at")),
                    "zona": (
                        f"{_fmt_price(candidate.get('low'))}–"
                        f"{_fmt_price(candidate.get('high'))}"
                    ),
                    "jarak (ATR)": candidate.get("distance_atr"),
                    "umur (jam)": candidate.get("age_hours"),
                    "displacement (ATR)": candidate.get("displacement_range_atr"),
                    "body displacement": candidate.get("displacement_body_fraction"),
                    "selaras strategis": candidate.get("strategic_alignment"),
                    "selaras H4 taktis": candidate.get("tactical_alignment"),
                    "confluence likuiditas": liquidity.get("confluence_count"),
                    "sumber likuiditas": ", ".join(liquidity.get("sources") or []) or "—",
                    "skor riset": candidate.get("research_score"),
                    "V175 P(touch) OOS": candidate.get("v175_touch_prior"),
                    "V175 P(reaction|touch) OOS": candidate.get("v175_reaction_prior"),
                    "V177 hold OOS": candidate.get("v177_hold_prior"),
                    "V178 hold M5 OOS": candidate.get("v178_hold_prior"),
                    "V179 reaction OOS": candidate.get("v179_reaction_prior"),
                    "status": candidate.get("status"),
                }
            )
        st.dataframe(pd.DataFrame(premap_table), hide_index=True, width="stretch")
        st.caption(
            "Catatan probabilitas/evidence: nilai V175/V177/V178/V179 adalah prior "
            "out-of-sample berdasarkan arah dari riset historis terbaru, BUKAN probabilitas "
            "terkalibrasi untuk kandidat individual ini. Skor riset 0–100 juga merupakan "
            "ranking evidence, bukan peluang menang."
        )
    else:
        st.info(
            "Belum ada Kandidat Pra-H4 yang valid. Ini berarti belum ada H1 origin baru "
            "setelah H4 map sekarang yang masih aktif, berada di sisi harga yang benar, "
            "dan memenuhi syarat dasar struktur."
        )

    st.markdown("### Persiapan Trading (Trade Preparation)")
    st.caption(
        f"H4 map canonical saat ini: {_fmt_wib_datetime(current_map)}. "
        "Waktu kedaluwarsa setup dan seluruh timestamp trading pada dashboard ini "
        "ditampilkan dalam WIB (Asia/Jakarta)."
    )
    if not valid_zone_now:
        st.error(
            "BELUM ADA ZONA ENTRY VALID — JANGAN PASANG ORDER. "
            "Scanner sedang menunggu H4 map struktural/zona reaksi yang baru."
        )
        if afic_sd_context.get("prepare_only_fallback"):
            sd_fallback_same = dict(afic_sd_context.get("same_direction_zone") or {})
            sd_fallback_opp = dict(afic_sd_context.get("opposite_reversal_zone") or {})
            fallback = sd_fallback_same or sd_fallback_opp
            if fallback:
                st.warning(
                    "Namun ada Supply/Demand PREPARE context di "
                    f"{_fmt_price(fallback.get('low'))}–{_fmt_price(fallback.get('high'))} "
                    f"({fallback.get('timeframe','—')} {fallback.get('pattern','—')}). "
                    "Gunakan hanya untuk bersiap; BELUM menjadi entry zone AFIC."
                )
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Menunggu", "H4 MAP BARU")
        t2.metric("Zona reaksi", "—")
        t3.metric("Entry acuan", "—")
        t4.metric("Tindakan manual", "TUNGGU")
        if lifecycle_rows:
            last_plan = dict(lifecycle_rows[0])
            if str(last_plan.get("lifecycle_state") or "") == "CANCELLED":
                st.caption(
                    "Rencana persiapan terakhir: "
                    f"{last_plan.get('direction') or '—'} "
                    f"{_fmt_price(last_plan.get('entry_price'))} • CANCELLED • "
                    f"alasan={last_plan.get('cancel_reason') or 'UNKNOWN'} • "
                    f"dibuat={_fmt_wib_datetime(last_plan.get('created_at'))} • "
                    f"dibatalkan={_fmt_wib_datetime(last_plan.get('cancelled_at'))}."
                )
    else:
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Menunggu", f"REAKSI {zone_side}")
        t2.metric("Zona reaksi", f"{_fmt_price(zone_low)}–{_fmt_price(zone_high)}")
        t3.metric("Entry acuan", _fmt_price(reference_entry_now))
        if grade not in {"A","B"}:
            manual_action = f"PANTAU SAJA / WATCH ONLY (GRADE {grade})"
        elif "CONFIRMED" in str(state).upper():
            manual_action = "TERKONFIRMASI / QUOTE TERBARU"
        elif proximity == "IN_ZONE":
            manual_action = "TUNGGU KONFIRMASI M15"
        elif proximity == "NEAR_ZONE":
            manual_action = "PERSIAPAN"
        else:
            manual_action = "TUNGGU HARGA KE ZONA"
        t4.metric("Tindakan manual", manual_action)
        st.info(
            f"Rencana saat ini: tunggu XAUUSD masuk ke {_fmt_price(zone_low)}–"
            f"{_fmt_price(zone_high)}. "
            + (
                f"Entry persiapan/acuan ≈ {_fmt_price(reference_entry_now)}. "
                if reference_entry_now is not None
                else "Entry acuan belum boleh dieksekusi. "
            )
            + "Jangan entry hanya karena harga menyentuh zona; candle M15 yang sudah "
              "selesai tetap wajib memberikan konfirmasi untuk jalur otomatis AFIC."
        )

    st.markdown("#### Siklus Rencana Persiapan (Prepared Plan Lifecycle)")
    st.caption(
        "Rencana yang pernah disiapkan tetap disimpan walaupun hilang dari H4 map terbaru. "
        "Ini membedakan WAITING_PRICE, ZONE_ENTERED, CONFIRMED, penyerahan ke broker, dan "
        "CANCELLED. Pembatalan disimpan sebagai evidence, bukan dihapus."
    )
    if lifecycle_rows:
        total_plans = len(lifecycle_rows)
        active_reached_plans = sum(
            bool(dict(row.get("metadata") or {}).get("touch_while_active"))
            for row in lifecycle_rows
        )
        active_confirmed_plans = sum(
            bool(dict(row.get("metadata") or {}).get("confirmation_while_active"))
            and bool(dict(row.get("metadata") or {}).get("touch_while_active"))
            for row in lifecycle_rows
        )
        cancelled_plans = sum(
            str(row.get("lifecycle_state") or "") == "CANCELLED"
            for row in lifecycle_rows
        )
        ordered_plans = sum(row.get("order_accepted_at") is not None for row in lifecycle_rows)
        post_cancel_reached = sum(
            bool(dict(row.get("metadata") or {}).get("post_cancel_touch"))
            for row in lifecycle_rows
            if str(row.get("lifecycle_state") or "") == "CANCELLED"
        )
        post_cancel_terminal = sum(
            bool(row.get("post_cancel_terminal_hit"))
            for row in lifecycle_rows
            if str(row.get("lifecycle_state") or "") == "CANCELLED"
        )
        l1, l2, l3, l4, l5, l6 = st.columns(6)
        l1.metric(
            "Zona tercapai saat aktif",
            "—" if total_plans == 0 else _fmt_pct(active_reached_plans / total_plans),
        )
        l2.metric(
            "Touch aktif → konfirmasi",
            "—"
            if active_reached_plans == 0
            else _fmt_pct(active_confirmed_plans / active_reached_plans),
        )
        l3.metric(
            "Pembatalan",
            "—" if total_plans == 0 else _fmt_pct(cancelled_plans / total_plans),
        )
        l4.metric(
            "Persiapan → order",
            "—" if total_plans == 0 else _fmt_pct(ordered_plans / total_plans),
        )
        l5.metric(
            "Zona tercapai pasca-batal",
            "—"
            if cancelled_plans == 0
            else _fmt_pct(post_cancel_reached / cancelled_plans),
        )
        l6.metric(
            "Kandidat TP2 pasca-batal",
            "—"
            if cancelled_plans == 0
            else _fmt_pct(post_cancel_terminal / cancelled_plans),
        )
        st.caption(
            "Zona tercapai saat aktif hanya menghitung sentuhan ketika rencana masih valid. "
            "Sentuhan setelah pembatalan dipisahkan untuk mengukur apakah aturan pembatalan "
            "terlalu agresif. Kandidat TP2 pasca-batal tetap merupakan evidence diagnostik, "
            "bukan bukti bahwa aturan pembatalan pasti salah."
        )
        lifecycle_table = []
        for row in lifecycle_rows[:20]:
            meta = dict(row.get("metadata") or {})
            lifecycle_table.append(
                {
                    "dibuat (WIB)": _fmt_wib_datetime(row.get("created_at")),
                    "arah": row.get("direction"),
                    "grade": row.get("grade"),
                    "zona": (
                        f"{_fmt_price(row.get('zone_low'))}–"
                        f"{_fmt_price(row.get('zone_high'))}"
                    ),
                    "entry": _fmt_price(row.get("entry_price")),
                    "siklus": row.get("lifecycle_state"),
                    "alasan batal": row.get("cancel_reason") or "—",
                    "dibatalkan (WIB)": _fmt_wib_datetime(row.get("cancelled_at")),
                    "sentuhan pertama": row.get("first_touch_at"),
                    "touch saat aktif": meta.get("touch_while_active"),
                    "touch pasca-batal": meta.get("post_cancel_touch"),
                    "terkonfirmasi": row.get("confirmed_at"),
                    "order diterima": row.get("order_accepted_at"),
                    "proteksi terverifikasi": row.get("protection_verified_at"),
                    "TP1": bool(row.get("tp1_hit")),
                    "TP2": bool(row.get("tp2_hit")),
                    "stop hit": bool(row.get("stop_hit")),
                    "MFE R": row.get("mfe_r"),
                    "MAE R": row.get("mae_r"),
                    "durasi (menit)": meta.get("lifetime_minutes"),
                }
            )
        st.dataframe(
            pd.DataFrame(lifecycle_table),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption(
            "Ledger siklus rencana belum terisi. Worker maintenance akan mengisi ulang "
            "rencana AFIC terbaru tanpa mengubah aturan eksekusi."
        )

    st.markdown("#### Kelayakan Eksekusi XAU (XAU Execution Admission)")
    st.caption(
        "Panel ini memisahkan status signal yang tersimpan dari izin broker yang sebenarnya. "
        "BROKER ELIGIBLE berarti geometry signal termasuk jalur DEMO yang diizinkan, tetapi "
        "quote terbaru, risiko, margin, serta verifikasi SL/TP tetap harus lulus sebelum order."
    )
    authorized_geometry_codes = {
        "XAU_AFIC_PATH_EXECUTION_V1",
        "XAU_M15_EMA_SMC_RECLAIM_V1",
        "XAU_V24_CHAMPION_DEMO_V1",
    }
    geometry_code_by_signal = {}
    for event_row in execution_events:
        if str(event_row.get("event_type") or "") != "DEMO_SIGNAL_GEOMETRY":
            continue
        signal_key = str(event_row.get("signal_key") or "")
        if signal_key and signal_key not in geometry_code_by_signal:
            geometry_code_by_signal[signal_key] = str(event_row.get("code") or "")

    admission_rows = []
    admission_now = datetime.now(tz=UTC)
    for row in dedicated_xau_rows[:10]:
        signal_id = str(row.get("id") or "")
        state_u = str(row.get("state") or "").upper()
        guards = list(row.get("active_guards") or [])
        expires_dt = None
        if row.get("expires_at"):
            try:
                expires_dt = datetime.fromisoformat(
                    str(row.get("expires_at")).replace("Z", "+00:00")
                )
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=UTC)
                else:
                    expires_dt = expires_dt.astimezone(UTC)
            except (TypeError, ValueError):
                expires_dt = None
        geometry_code = geometry_code_by_signal.get(signal_id)
        if state_u == "INVALIDATED":
            admission = "INVALIDATED"
            reason = "Signal/map sudah tidak berlaku"
        elif expires_dt is not None and expires_dt < admission_now:
            admission = "EXPIRED"
            reason = "Masa berlaku (TTL) signal sudah habis"
        elif guards:
            admission = "BLOCKED"
            reason = ", ".join(str(x) for x in guards)
        elif state_u != "EXECUTION_READY":
            admission = "NOT READY"
            reason = f"Status={state_u or '—'}"
        elif geometry_code in authorized_geometry_codes:
            admission = "BROKER ELIGIBLE"
            reason = f"{geometry_code}; menunggu validasi ulang quote/risiko"
        else:
            admission = "SHADOW READY"
            reason = (
                f"{geometry_code or 'NO_AUTHORIZED_GEOMETRY'} tidak memiliki izin broker"
            )
        admission_rows.append({
            "waktu (WIB)": _fmt_wib_datetime(row.get("observed_at")),
            "setup": row.get("setup_type"),
            "arah": row.get("direction"),
            "grade/skor": row.get("final_score"),
            "status tersimpan": row.get("state"),
            "kelayakan": admission,
            "izin geometry": geometry_code or "—",
            "alasan": reason,
            "kedaluwarsa (WIB)": _fmt_wib_datetime(row.get("expires_at")),
        })
    if admission_rows:
        st.dataframe(pd.DataFrame(admission_rows), hide_index=True, width="stretch")
        latest_admission = admission_rows[0]
        if latest_admission["kelayakan"] == "BROKER ELIGIBLE":
            st.success(
                "Signal XAU terbaru memiliki geometry DEMO yang diizinkan broker. "
                "Order tetap bergantung pada quote terbaru, risiko, margin, dan validasi ulang SL/TP."
            )
        elif latest_admission["kelayakan"] == "SHADOW READY":
            st.warning(
                "Signal XAU terbaru dapat berstatus EXECUTION_READY di storage, tetapi hanya "
                "SHADOW READY; jalur broker tidak akan mengeksekusinya."
            )
    else:
        st.caption("Belum ada baris signal XAU untuk diagnostik kelayakan eksekusi.")

    st.markdown("#### Sinyal Teknikal XAU Lintas-Mesin (Cross-engine XAU technical signals)")
    st.caption(
        "Bagian ini terpisah dari AFIC H4 map. Baris berasal dari mesin teknikal XAU lain. "
        "CURRENT/EXPIRED ditentukan dari expires_at; setup yang kedaluwarsa hanya konteks "
        "historis dan tidak boleh dianggap sebagai rancangan order AFIC yang masih aktif."
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
            raw_state = str(row.get("state") or "").upper()
            raw_setup = str(row.get("setup_type") or "").upper()
            if raw_state == "INVALIDATED":
                runtime_status = "INVALIDATED"
            elif expires_dt is not None and expires_dt < now_utc:
                runtime_status = "EXPIRED"
            elif raw_state == "WATCH" or raw_setup in {"", "NONE"}:
                runtime_status = "WATCH"
            else:
                runtime_status = "CURRENT"
            technical_rows.append(
                {
                    "runtime": runtime_status,
                    "waktu (WIB)": _fmt_wib_datetime(row.get("observed_at")),
                    "setup": row.get("setup_type"),
                    "arah": row.get("direction"),
                    "status": row.get("state"),
                    "skor": row.get("final_score"),
                    "entry": (
                        f"{_fmt_price(row.get('entry_low'))}–{_fmt_price(row.get('entry_high'))}"
                        if row.get("entry_low") is not None or row.get("entry_high") is not None
                        else "—"
                    ),
                    "SL": _fmt_price(row.get("sl")),
                    "target pertama": _fmt_price(
                        next(
                            (x for x in (row.get("tp1"), row.get("tp2"), row.get("tp3")) if x is not None),
                            None,
                        )
                    ),
                    "target terminal": _fmt_price(
                        next(
                            (x for x in (row.get("tp3"), row.get("tp2"), row.get("tp1")) if x is not None),
                            None,
                        )
                    ),
                    "raw TP1": _fmt_price(row.get("tp1")),
                    "raw TP2": _fmt_price(row.get("tp2")),
                    "guard/pengaman": ", ".join(str(x) for x in (row.get("active_guards") or [])) or "—",
                    "kedaluwarsa (WIB)": _fmt_wib_datetime(expires_raw),
                }
            )
        latest_technical = technical_rows[0]
        if latest_technical["runtime"] == "CURRENT":
            st.info(
                "Setup teknikal XAU non-AFIC terbaru masih CURRENT. Geometry ditampilkan "
                "di bawah, tetapi izin AFIC tetap merupakan gerbang terpisah."
            )
        elif latest_technical["runtime"] == "WATCH":
            st.info(
                "Baris XAU non-AFIC terbaru hanya WATCH. Ia tidak memiliki izin trading "
                "mandiri dan tidak boleh dibaca sebagai entry aktif."
            )
        elif latest_technical["runtime"] == "INVALIDATED":
            st.warning(
                "Setup XAU non-AFIC terbaru INVALIDATED. Geometry disimpan hanya sebagai "
                "evidence historis."
            )
        else:
            st.warning(
                "Setup teknikal XAU non-AFIC terbaru EXPIRED. Entry/SL/TP hanya geometry "
                "historis, bukan instruksi yang masih aktif."
            )
        st.dataframe(
            pd.DataFrame(technical_rows),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("Belum ada baris signal teknikal XAU non-AFIC.")

    st.markdown("#### Diagnostik Zona Reaksi (Reaction-zone diagnostics)")
    if zone_diagnostics:
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Jumlah origin zone", zone_diagnostics.get("origin_zones_total", "—"))
        d2.metric("Fresh ≤24 jam", zone_diagnostics.get("fresh_within_24h", "—"))
        d3.metric(
            f"Arah {direction or 'Map' }",
            zone_diagnostics.get("matching_direction_fresh", "—"),
        )
        d4.metric("Sisi anchor salah", zone_diagnostics.get("wrong_side_of_anchor", "—"))
        d5.metric("Zona reaksi eligible", zone_diagnostics.get("eligible_correct_side", "—"))
        result = str(zone_diagnostics.get("selection_result") or "")
        if result == "NO_ELIGIBLE_MAP_ZONE":
            st.warning(
                "NO_MAP_ZONE dijelaskan oleh struktur saat ini: origin zone memang ada, "
                "tetapi tidak ada kandidat yang sekaligus memenuhi arah, freshness, dan sisi "
                "anchor H4 yang benar. Ini berarti belum ada setup, bukan signal eksekusi."
            )
        elif result == "ELIGIBLE_ZONE_FOUND":
            nearest = dict(zone_diagnostics.get("nearest_eligible") or {})
            st.success(
                "Zona reaksi eligible ditemukan: "
                f"{_fmt_price(nearest.get('low'))}–{_fmt_price(nearest.get('high'))} • "
                f"jarak {_fmt_distance(nearest.get('distance_points'), ' poin')}."
            )
        elif result == "NO_ORIGIN_ZONE":
            st.warning(
                "Belum ada H1 origin zone yang memenuhi aturan displacement/BOS/origin. "
                "Scanner menunggu struktur baru."
            )
        st.caption(
            "Diagnostik hanya bersifat deskriptif; tidak melonggarkan selector AFIC dan "
            "tidak menciptakan izin broker."
        )
    else:
        st.caption(
            "Diagnostik zona belum tersedia pada heartbeat ini; siklus AFIC berikutnya "
            "akan mengisi jumlah kandidat dan alasan penolakan."
        )

    st.markdown("#### Zona Pantauan Alternatif / Reversal (Alternative / reversal watch zones)")
    reversal_watch = list(zone_diagnostics.get("alternative_reversal_watch_zones") or [])
    active_watch = [
        dict(item) for item in reversal_watch
        if str(item.get("status") or "") != "INVALIDATED"
    ]
    if active_watch:
        st.caption(
            "These are PRIOR ORIGIN REVISITS from structural memory, not current primary "
            "AFIC reaction zones. first durable touch is preserved across H4 remaps; "
            "current-map touch records only a completed M15 touch on the active H4 map. "
            "Live touch is provisional until that M15 candle closes. They cannot auto-order "
            "against the active H4 map; a structural remap plus H1/M15 reversal confirmation "
            "is required."
        )
        watch_rows = []
        for item in active_watch:
            watch_rows.append(
                {
                    "context": "PRIOR_ORIGIN_REVISIT",
                    "role": item.get("role"),
                    "direction": item.get("direction"),
                    "zone": f"{_fmt_price(item.get('low'))}–{_fmt_price(item.get('high'))}",
                    "origin_at": item.get("origin_at"),
                    "available_at": item.get("available_at"),
                    "status": item.get("status"),
                    "zone lifecycle": item.get("zone_lifecycle"),
                    "touch lifecycle": item.get("touch_lifecycle"),
                    "first durable touch": item.get("first_touch_at"),
                    "current-map touch": item.get("map_first_touch_at"),
                    "live touch": item.get("live_touch_at"),
                    "invalidated": item.get("invalidated_at"),
                    "distance now": _fmt_distance(
                        item.get("distance_from_live_price_points")
                        if item.get("distance_from_live_price_points") is not None
                        else item.get("distance_from_latest_price_points"),
                        " pts",
                    ),
                    "age": _fmt_distance(item.get("current_age_hours"), "h"),
                    "displacement ATR": item.get("displacement_range_atr"),
                    "body fraction": item.get("displacement_body_fraction"),
                    "required": item.get("required_confirmation"),
                }
            )
        st.dataframe(pd.DataFrame(watch_rows), hide_index=True, width="stretch")
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
            f"PRIOR ORIGIN REVISIT: {watch_side} "
            f"{_fmt_price(nearest_watch.get('low'))}–{_fmt_price(nearest_watch.get('high'))} "
            f"• {watch_status}. This is not the current primary AFIC zone. {path_hint}"
        )
    elif reversal_watch:
        st.caption(
            "Opposite-direction zones were found, but all current reversal-watch candidates "
            "have already been invalidated."
        )
    else:
        st.caption("No active opposite-direction reversal-watch zone is available.")

    f1, f2, f3, f4, f5, f6 = st.columns(6)
    f1.metric("H4 continuation", direction)
    f2.metric("State", state)
    f3.metric("Selector", grade)
    f4.metric("Live XAU", _fmt_price(live_price))
    f5.metric("Distance to zone", _fmt_distance(distance_points, " pts"))
    f6.metric("AFIC scan", f"{int(scan_seconds)}s" if scan_seconds else "—")
    st.caption(
        "H4 continuation is structural context only. It is not a current BUY/SELL call; "
        "trade authority still requires a valid current AFIC zone/selector/confirmation."
    )
    if hb_details.get("touch_lifecycle"):
        st.caption(
            "Current-zone lifecycle: "
            f"{hb_details.get('zone_lifecycle') or hb_details.get('touch_lifecycle')} • "
            f"first durable touch={hb_details.get('first_touch_at') or '—'} • "
            f"current-map touch={hb_details.get('map_first_touch_at') or '—'}. "
            "Only completed M15 touches are durable lifecycle evidence."
        )

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

    st.markdown("#### Gabungan Prakiraan V171 (Forecast Ensemble V171)")
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
            "does not alter AFIC Grade-A/B execution authority."
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
        st.dataframe(component_frame, hide_index=True, width="stretch")

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
                    width="stretch",
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

    if grade in {"A", "B"}:
        st.success(
            f"Canonical V161 selector Grade {grade}: eligible for DEMO auto execution "
            "only after completed M15 confirmation and fresh broker revalidation."
        )
    elif grade == "C":
        st.warning(
            "Grade C: shadow/watch only. Scanner will not auto-order this AFIC map "
            "even if the zone is touched."
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

    st.markdown("#### Rancangan Order Persiapan (Prepared order blueprint)")
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

    auto_label = "ARMED FOR GRADE-A/B CONFIRMATION" if auto_enabled else "MONITOR ONLY"
    if grade not in {"A","B"}:
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

    st.markdown("#### Linimasa Otomasi / Broker (Automation / broker timeline)")
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
        st.dataframe(pd.DataFrame(timeline_rows), hide_index=True, width="stretch")
    else:
        st.caption("No XAU execution event yet. Forecast monitoring can still be active without an order.")

    st.markdown("#### Rentang Pergerakan yang Diharapkan (Expected-move envelope)")
    move_details = {} if move_hb is None else dict(move_hb.get("details") or {})
    move_eval = dict(move_details.get("evaluation") or {})
    reference_envelope = dict(move_eval.get("current_envelope") or {})
    live_envelope = dict(ensemble_components.get("v170") or {})
    live_horizons = dict(live_envelope.get("horizons") or {})
    reference_horizons = dict(reference_envelope.get("horizons") or {})

    if live_envelope and live_horizons:
        st.caption(
            "LIVE 20K expected-move envelope from the latest V171 cycle. "
            "Magnitude forecast only — excursion quantiles, not bullish/bearish probabilities."
        )
        live_age = None if ensemble_hb is None else _age_seconds(ensemble_hb.get("observed_at"))
        m1, m2, m3 = st.columns(3)
        m1.metric("LIVE anchor", _fmt_price(live_envelope.get("price")))
        m2.metric("LIVE as-of", str(live_envelope.get("as_of") or "—"))
        m3.metric("LIVE age", "—" if live_age is None else f"{live_age:.0f}s")
        move_rows = []
        for label in ("1h", "4h", "8h"):
            row = dict(live_horizons.get(label) or {})
            levels = dict(row.get("levels") or {})
            if levels:
                move_rows.append(
                    {
                        "horizon": label,
                        "anchor": live_envelope.get("price"),
                        "down q50": levels.get("down_q50"),
                        "down q75": levels.get("down_q75"),
                        "down q90": levels.get("down_q90"),
                        "up q50": levels.get("up_q50"),
                        "up q75": levels.get("up_q75"),
                        "up q90": levels.get("up_q90"),
                    }
                )
        if move_rows:
            st.dataframe(pd.DataFrame(move_rows), hide_index=True, width="stretch")
    elif reference_envelope and reference_horizons:
        st.warning(
            "LIVE 20K envelope is unavailable; showing the slower REFERENCE 100K snapshot instead."
        )

    if reference_envelope and reference_horizons:
        with st.expander("REFERENCE 100K V170 snapshot", expanded=False):
            reference_age = None if move_hb is None else _age_seconds(move_hb.get("observed_at"))
            r1, r2, r3 = st.columns(3)
            r1.metric("Reference anchor", _fmt_price(reference_envelope.get("price")))
            r2.metric("Reference as-of (WIB)", _fmt_wib_datetime(reference_envelope.get("as_of")))
            r3.metric("Reference age", "—" if reference_age is None else f"{reference_age:.0f}s")
            reference_rows = []
            for label in ("1h", "4h", "8h"):
                row = dict(reference_horizons.get(label) or {})
                levels = dict(row.get("levels") or {})
                if levels:
                    reference_rows.append(
                        {
                            "horizon": label,
                            "anchor": reference_envelope.get("price"),
                            "down q50": levels.get("down_q50"),
                            "down q75": levels.get("down_q75"),
                            "down q90": levels.get("down_q90"),
                            "up q50": levels.get("up_q50"),
                            "up q75": levels.get("up_q75"),
                            "up q90": levels.get("up_q90"),
                        }
                    )
            if reference_rows:
                st.dataframe(
                    pd.DataFrame(reference_rows),
                    hide_index=True,
                    width="stretch",
                )
    elif not live_envelope:
        st.caption("Expected-move V170 data is not available in this snapshot.")

    st.markdown("#### Riwayat Status Prakiraan (Forecast state history)")
    history_rows = []
    for row in forecast_rows[:12]:
        payload = dict(dict(row.get("payload") or {}).get("forecast") or {})
        z = dict(payload.get("zone") or {})
        history_rows.append(
            {
                "diamati (WIB)": _fmt_wib_datetime(row.get("observed_at")),
                "map H4 (WIB)": _fmt_wib_datetime(payload.get("map_at")),
                "state": payload.get("state"),
                "direction": payload.get("continuation_direction"),
                "zone_low": z.get("low"),
                "zone_high": z.get("high"),
                "sentuh (WIB)": _fmt_wib_datetime(payload.get("first_touch_at")),
                "konfirmasi (WIB)": _fmt_wib_datetime(payload.get("confirm_at")),
                "invalid (WIB)": _fmt_wib_datetime(payload.get("invalidated_at")),
            }
        )
    if history_rows:
        st.dataframe(pd.DataFrame(history_rows), hide_index=True, width="stretch")
    else:
        st.caption("No durable AFIC forecast transitions have been recorded yet.")

with account_tab:
    st.subheader("Pemantauan Akun Broker (Broker Account Monitor)")
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
            f"Telemetry age: {'—' if age_seconds is None else f'{age_seconds:.0f}s'} • "
            f"Update WIB: {_fmt_wib_datetime(account.get('observed_at'))}"
        )
        if currency.upper() == "USC":
            st.info(
                "Broker reports this Cent account in USC. Values are shown in "
                "the broker's native unit and are not silently converted."
            )

        if positions:
            position_frame = _convert_frame_times_to_wib(
                _frame(positions),
                ("opened_at", "observed_at", "updated_at"),
            ).rename(columns={"opened_at": "opened_at (WIB)"})
            display_cols = [
                col
                for col in [
                    "symbol", "side", "volume", "open_price", "current_price",
                    "sl", "tp", "profit", "swap", "opened_at (WIB)", "position_id",
                ]
                if col in position_frame.columns
            ]
            st.dataframe(
                position_frame[display_cols],
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No open cTrader DEMO positions in the latest broker snapshot.")
    else:
        st.info(
            "No broker telemetry yet. Streamlit is read-only; the cloud cTrader DEMO "
            "runtime will publish balance and positions when the next broker snapshot arrives."
        )

with scanner_tab:
    st.subheader("Peringkat Pair (Pair Ranking)")

    if backend is not None and backend["rankings"]:
        rankings = _convert_frame_times_to_wib(
            _frame(backend["rankings"]),
            ("observed_at",),
        ).rename(columns={"observed_at": "observed_at (WIB)"})
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
                "observed_at (WIB)",
            ]
            if col in rankings.columns
        ]
        st.dataframe(
            rankings[display_cols],
            hide_index=True,
            width="stretch",
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
        st.dataframe(configured, hide_index=True, width="stretch")
        st.caption(
            "No durable pair-ranking snapshot is available yet. This table shows the "
            "configured trading universe only. universe_tier A/B is a static instrument "
            "priority class, NOT an execution grade and NOT EXECUTION_READY."
        )

    st.subheader("Sinyal Terbaru (Latest Signals)")
    if backend is not None and backend["signals"]:
        signals = _frame(backend["signals"])
        signals["_state_order"] = signals["state"].map(_state_rank)
        signals = signals.sort_values(
            ["_state_order", "observed_at"],
            ascending=[True, False],
        ).drop(columns=["_state_order"])
        signals = _convert_frame_times_to_wib(
            signals,
            ("observed_at", "expires_at"),
        ).rename(
            columns={
                "observed_at": "observed_at (WIB)",
                "expires_at": "expires_at (WIB)",
            }
        )

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
                "observed_at (WIB)",
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
                "expires_at (WIB)",
            ]
            if col in signals.columns
        ]
        st.dataframe(
            signals[display_cols],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No signal snapshots have been written yet.")

with data_tab:
    st.subheader("Makro Mata Uang (Currency Macro)")
    if backend is not None and backend["macro"]:
        macro = _frame(backend["macro"])
        if "coverage" in macro.columns:
            macro["coverage"] = macro["coverage"].apply(_fmt_pct)
        st.dataframe(macro, hide_index=True, width="stretch")
    else:
        st.info("No durable macro snapshots are available yet.")

    if cfg is not None:
        st.subheader("Sumber Data Resmi (Official Providers)")
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
        st.dataframe(providers, hide_index=True, width="stretch")

        if st.button("Check official providers"):
            with st.spinner("Checking configured official sources..."):
                try:
                    rows = _provider_smoke_rows()
                    st.dataframe(
                        pd.DataFrame(rows),
                        hide_index=True,
                        width="stretch",
                    )
                except Exception as exc:
                    st.error(f"Provider check failed safely: {type(exc).__name__}: {exc}")

with system_tab:
    st.subheader("Kontrol Eksekusi (Execution Control)")
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

    st.subheader("Status Runtime / Heartbeat")
    if backend is not None and backend["heartbeats"]:
        heartbeats = _convert_frame_times_to_wib(
            _frame(backend["heartbeats"]),
            ("observed_at",),
        ).rename(columns={"observed_at": "observed_at (WIB)"})
        if "details" in heartbeats.columns:
            heartbeats["details"] = heartbeats["details"].apply(
                lambda value: json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                if isinstance(value, (dict, list, tuple))
                else value
            )
        st.dataframe(heartbeats, hide_index=True, width="stretch")
    else:
        st.info("No runtime heartbeat snapshots are available.")

    if backend is not None and backend.get("latest_run"):
        st.subheader("Proses Scanner Terbaru (Latest Scanner Run)")
        run = backend["latest_run"]
        st.json(run, expanded=False)

with validation_tab:
    st.subheader("Gerbang Validasi (Acceptance Gates)")
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
                    "minimum": str(acceptance["profit_factor_min"]),
                },
                {
                    "gate": "Expectancy",
                    "minimum": f"{acceptance['expectancy_r_min']}R",
                },
                {
                    "gate": "Final OOS completed trades",
                    "minimum": str(acceptance["aggregate_oos_trades_min"]),
                },
                {"gate": "Walk-forward", "minimum": "REQUIRED"},
                {"gate": "Cost/spread/slippage stress", "minimum": "REQUIRED"},
                {"gate": "Multi-regime", "minimum": "REQUIRED"},
                {"gate": "Monte Carlo", "minimum": "REQUIRED"},
                {"gate": "Parameter perturbation", "minimum": "REQUIRED"},
                {"gate": "Demo forward", "minimum": "REQUIRED"},
            ]
        )
        st.dataframe(gates, hide_index=True, width="stretch")

        perf = cfg.validation["performance_budget"]
        st.subheader("Batas Kinerja Jalur Kritis (Hot-path Performance Budget)")
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

    st.subheader("Kinerja Tersimpan Terbaru (Latest Persisted Performance)")
    if backend is not None and backend["performance"]:
        performance = _frame(backend["performance"])
        if "win_rate" in performance.columns:
            performance["win_rate"] = performance["win_rate"].apply(
                lambda x: "—" if pd.isna(x) else f"{float(x) * 100:.1f}%"
            )
        st.dataframe(performance, hide_index=True, width="stretch")
    else:
        st.info(
            "No persisted OOS/performance rows are available yet. "
            "The dashboard does not fabricate validation results."
        )

st.divider()
st.caption(
    "Rendered at "
    + datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    + " • Waktu tampilan trading: WIB (Asia/Jakarta, UTC+7)"
    + " • Main file: main.py • Dashboard implementation: streamlit_app.py"
)
