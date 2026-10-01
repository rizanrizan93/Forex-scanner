from __future__ import annotations

import base64
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
from fx_scanner.dashboard import (
    DashboardReadError,
    SupabaseDashboardReader,
    merge_runtime_heartbeat_rows,
)
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.sessions import session_label
from fx_scanner.providers.factory import build_provider_runtime
from fx_scanner.storage.supabase_operational import (
    OperationalStoreUnavailable,
    SupabaseOperationalStore,
)
from fx_scanner.trade_management_v195 import (
    evaluate_position,
    summarize_positions,
)
from fx_scanner.xau_canonical_decision_v240 import build_canonical_xau_decision
from fx_scanner.xau_rizan_style_path_engine_v303 import build_rizan_style_path_engine
from fx_scanner.xau_profitability_truth_v241 import build_xau_profitability_truth
from fx_scanner.xau_pressure_transition_v249 import evaluate_pressure_transition
from fx_scanner.xau_dynamic_depth_hazard_v251 import (
    build_dynamic_depth_hazard,
    build_geometry_depth_status,
)
from fx_scanner.xau_reversal_stage_v280 import evaluate_reversal_stage
from fx_scanner.xau_competing_risk_prior_v285 import (
    evaluate_v281_competing_risk_prior,
    evaluate_v281_contextual_competing_risk,
)
from fx_scanner.xau_dashboard_bridge_v254 import (
    DEFAULT_SNAPSHOT_URL as DEFAULT_DASHBOARD_SNAPSHOT_URL,
    fetch_snapshot as fetch_dashboard_snapshot,
)
from fx_scanner.xau_standalone_bridge_v253 import (
    DEFAULT_SNAPSHOT_URL,
    fetch_snapshot as fetch_standalone_snapshot,
)

UTC = timezone.utc
WIB = ZoneInfo("Asia/Jakarta")
FOREXRIZAN_PROJECT_REF = "naxvdtvlfatljzzwhrmo"
DASHBOARD_DEGRADED_MAX_AGE_SECONDS = 24 * 60 * 60.0
DASHBOARD_BUILD_ID = "RIZAN_V325_BRIDGE_ENTRY_CLARITY_20261001"

RIZAN_DASHBOARD_HOT_HEARTBEATS = (
    # 60-second decision/admission path. Keep V182 + V226 fresh because V240
    # rebuilds the canonical parent ladder from both layers.
    "ctrader_demo_xau_rizan_prepared_plan_producer",
    "ctrader_demo_xau_rizan_fast_handoff",
    "ctrader_demo_xau_dom_v191",
    "ctrader_demo_xau_event_risk_v192",
    "ctrader_demo_xau_v203_volatility_shock_guard",
    "ctrader_demo_xau_decision_center_v296",
    "ctrader_demo_xau_meta_research_sampler_v297",
    "ctrader_demo_xau_structural_research_probe_v318",
    "ctrader_demo_xau_micro_entry_refinement_v320",
    "ctrader_demo_xau_micro_entry_dual_cycle_v321",
    "ctrader_demo_xau_micro_handoff_v322",
)

RIZAN_DASHBOARD_STRUCTURAL_HEARTBEATS = (
    "ctrader_demo_xau_supply_demand_atlas_v182",
    "ctrader_demo_xau_v226_rizan_depth_map",
)

RIZAN_DASHBOARD_SUPPORT_HEARTBEATS = (
    # Full details remain available exactly as before, but these evidence/research
    # layers do not authorize a broker order and therefore use the hourly
    # observability budget.
    "ctrader_demo_xau_afic_prepared_plan_producer",
    "ctrader_demo_xau_afic_fast_handoff",
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
    "ctrader_demo_xau_prepared_plan_lifecycle",
    "ctrader_xau_expected_move_envelope_v170",
    "ctrader_xau_forecast_ensemble_v171",
    "ctrader_xau_htf_strategic_regime_v180",
)

st.set_page_config(
    page_title="RIZAN XAU Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.0rem; padding-bottom: 2rem; max-width: 1500px;}
    div[data-testid="stMetric"] {
        border: 1px solid rgba(128,128,128,.22);
        border-radius: 12px;
        padding: .55rem .7rem;
    }
    div[data-testid="stMetricLabel"] {font-size: .82rem;}
    div[data-testid="stMetricValue"] {
        font-size: 1.75rem;
        line-height: 1.15;
        white-space: normal;
        overflow-wrap: anywhere;
        word-break: break-word;
    }
    .rizan-kicker {font-size:.82rem; opacity:.68; margin-bottom:.2rem;}
    .rizan-title {font-size:1.55rem; font-weight:700; margin-bottom:.15rem;}
    .rizan-note {font-size:.86rem; opacity:.78;}
    .rizan-flow-note {
        border-left: 3px solid rgba(128,128,128,.35);
        padding: .55rem .8rem;
        margin: .35rem 0 .85rem 0;
        border-radius: 0 10px 10px 0;
        background: rgba(128,128,128,.055);
        font-size: .88rem;
    }
    div[data-testid="stExpander"] {
        border-radius: 12px;
        border-color: rgba(128,128,128,.18);
    }
    @media (max-width: 768px) {
        .block-container {padding-top:.55rem; padding-left:.75rem; padding-right:.75rem;}
        .rizan-title {font-size:1.28rem;}
        .rizan-kicker, .rizan-note {font-size:.78rem;}
        div[data-testid="stMetric"] {padding:.45rem .55rem;}
        div[data-testid="stMetricValue"] {
            font-size:1.20rem;
            line-height:1.18;
            overflow:visible;
            text-overflow:clip;
        }
        div[data-testid="stMetricLabel"] {
            font-size:.78rem;
            line-height:1.18;
            white-space:normal;
        }
        h1 {font-size:2rem !important;}
    }
    </style>
    """,
    unsafe_allow_html=True,
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


def _supabase_project_ref(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    host = raw.split("://", 1)[-1].split("/", 1)[0].strip().lower()
    return host.split(".", 1)[0] if host else ""

def _supabase_key_role(value: str) -> str:
    """Identify legacy JWT anon/service_role keys without verifying the token."""
    token = str(value or "").strip()
    if token.startswith("sb_publishable_"):
        return "anon"
    parts = token.split(".")
    if len(parts) != 3:
        return ""
    try:
        payload_raw = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(payload_raw.encode("ascii")).decode("utf-8")
        )
    except Exception:
        return ""
    return str(payload.get("role") or "").strip().lower()


@st.cache_resource(show_spinner=False)
def _supabase_client(url: str, secret_key: str):
    from supabase import create_client

    return create_client(url, secret_key)


@st.cache_data(ttl=45, show_spinner=False)
def _load_standalone_bridge(url: str) -> dict[str, Any]:
    return fetch_standalone_snapshot(url)


@st.cache_data(ttl=45, show_spinner=False)
def _load_dashboard_bridge(
    url: str,
    *,
    require_fresh: bool = True,
) -> dict[str, Any]:
    return fetch_dashboard_snapshot(url, require_fresh=require_fresh)


@st.cache_data(ttl=60, show_spinner=False)
def _load_backend_fast_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    """Fast dashboard state needed for manual execution awareness.

    The user-facing dashboard refresh contract is 60 seconds. Broker execution
    workers remain independent and continue at their own faster runtime cadence.
    """
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    store = SupabaseOperationalStore(url, secret_key, client=client)
    broker_account = reader.latest_broker_account()

    return {
        "xau_signals": list(reader.latest_signals_for_symbol("XAUUSD", limit=8)),
        "control": asdict(store.get_execution_control()),
        "broker_account": broker_account,
        "broker_positions": list(reader.broker_positions_for_account(broker_account)),
        "xau_execution_events": list(reader.latest_xau_execution_events(limit=4)),
        "xau_geometry_events": list(reader.latest_xau_geometry_events_compact(limit=2)),
    }


@st.cache_data(ttl=60, show_spinner=False)
def _load_backend_decision_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    """60-second XAU decision state.

    V240/V249/V251 and execution-admission inputs stay on the original
    user-facing cadence. Only the bounded set of heartbeat payloads required by
    the decision dashboard is retransmitted every minute.
    """
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    prepared_worker_names = {
        "ctrader_demo_xau_rizan_prepared_plan_producer",
        "ctrader_demo_xau_afic_prepared_plan_producer",
    }
    hot_workers = [
        name for name in RIZAN_DASHBOARD_HOT_HEARTBEATS
        if name not in prepared_worker_names
    ]
    critical_heartbeats = list(reader.heartbeats_for_workers(hot_workers))
    prepared_heartbeat = reader.latest_rizan_prepared_heartbeat()
    if prepared_heartbeat is not None:
        critical_heartbeats.append(prepared_heartbeat)
    v229_heartbeat = reader.latest_rizan_v229_execution_heartbeat()
    if v229_heartbeat is not None:
        critical_heartbeats.append(v229_heartbeat)
    child_heartbeat = reader.latest_rizan_child_executor_heartbeat()
    if child_heartbeat is not None:
        critical_heartbeats.append(child_heartbeat)
    atlas_operational = reader.latest_xau_atlas_operational_heartbeat()
    if atlas_operational is not None:
        critical_heartbeats.append(atlas_operational)
    v226_operational = reader.latest_xau_v226_operational_heartbeat()
    if v226_operational is not None:
        critical_heartbeats.append(v226_operational)
    return {
        "critical_heartbeats": critical_heartbeats,
        "afic_forecast_states": list(reader.latest_afic_forecast_states(limit=6)),
        "afic_prepared_plans": list(reader.latest_afic_prepared_plans(limit=1)),
        "afic_execution_geometry": list(reader.latest_rizan_execution_geometry_compact(limit=1)),
        "xau_prepared_plan_lifecycle": list(reader.latest_xau_prepared_plan_lifecycle(limit=4)),
    }


@st.cache_data(ttl=300, show_spinner=False)
def _load_backend_structural_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    """Completed-structure V182/V226 detail; refreshed every five minutes."""
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    return {
        "structural_heartbeats": list(
            reader.heartbeats_for_workers(list(RIZAN_DASHBOARD_STRUCTURAL_HEARTBEATS))
        )
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _load_backend_support_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    """Full detail for non-authoritative research/evidence workers."""
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    return {
        "support_heartbeats": list(
            reader.heartbeats_for_workers(list(RIZAN_DASHBOARD_SUPPORT_HEARTBEATS))
        )
    }


@st.cache_data(ttl=300, show_spinner=False)
def _load_backend_slow_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    """Non-critical observability/history state with a five-minute egress budget.

    This preserves the same dashboard data and fields while avoiding repeated
    retransmission of heavy historical/heartbeat payloads every 60 seconds.
    """
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    run = reader.latest_run()

    return {
        "latest_run": run,
        "rankings": list(reader.rankings_for_run(None if run is None else run.get("id"))),
        "signals": list(reader.latest_signals()),
        "heartbeats": list(reader.heartbeat_summaries()),
        "macro": list(reader.latest_macro()),
        "performance": list(reader.latest_performance()),
    }


@st.cache_data(ttl=21600, show_spinner=False)
def _load_backend_outcome_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    """Prospective/OOS evidence changes slowly; refresh every six hours."""
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    return {"xau_outcomes": list(reader.latest_xau_outcomes())}


@st.cache_data(ttl=300, show_spinner=False)
def _load_full_heartbeat_details(url: str, secret_key: str) -> list[dict[str, Any]]:
    """On-demand full worker details; excluded from the automatic refresh path."""
    client = _supabase_client(url, secret_key)
    reader = SupabaseDashboardReader(client)
    return list(reader.heartbeats())


def _merge_heartbeat_rows(
    critical_rows: list[dict[str, Any]],
    observability_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay fresh operational rows while preserving cached research detail."""
    return merge_runtime_heartbeat_rows(
        list(observability_rows or []),
        list(critical_rows or []),
    )


def _load_backend_snapshot(url: str, secret_key: str) -> dict[str, Any]:
    # Operational/decision state remains 60s. Heavy history/observability is
    # cached for five minutes to reduce Supabase data-plane egress.
    merged = dict(_load_backend_slow_snapshot(url, secret_key))
    merged.update(_load_backend_outcome_snapshot(url, secret_key))
    support = dict(_load_backend_support_snapshot(url, secret_key))
    structural = dict(_load_backend_structural_snapshot(url, secret_key))
    decision = dict(_load_backend_decision_snapshot(url, secret_key))
    support_and_summary = _merge_heartbeat_rows(
        list(support.get("support_heartbeats", []) or []),
        list(merged.get("heartbeats", []) or []),
    )
    structural_and_support = _merge_heartbeat_rows(
        list(structural.get("structural_heartbeats", []) or []),
        support_and_summary,
    )
    merged["heartbeats"] = _merge_heartbeat_rows(
        list(decision.pop("critical_heartbeats", []) or []),
        structural_and_support,
    )
    merged.update(decision)
    merged.update(_load_backend_fast_snapshot(url, secret_key))
    return merged


def _clear_backend_snapshot_cache(*, include_slow: bool) -> None:
    """Clear hot caches every minute; cold observability only on manual refresh."""
    _load_backend_fast_snapshot.clear()
    _load_backend_decision_snapshot.clear()
    if include_slow:
        _load_backend_slow_snapshot.clear()
        _load_backend_structural_snapshot.clear()
        _load_backend_support_snapshot.clear()
        _load_backend_outcome_snapshot.clear()
        _load_full_heartbeat_details.clear()


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


def _rizan_display(value: Any) -> Any:
    """User-facing alias for the legacy AFIC research lineage.

    Persisted database keys/strategy IDs remain backward-compatible internally,
    while every value rendered to the dashboard is branded RIZAN.
    """
    if isinstance(value, str):
        return (
            value.replace("AFIC", "RIZAN")
            .replace("Afic", "RIZAN")
            .replace("afic", "rizan")
        )
    if isinstance(value, list):
        return [_rizan_display(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_rizan_display(item) for item in value)
    if isinstance(value, dict):
        return {key: _rizan_display(item) for key, item in value.items()}
    return value


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


def _fmt_number(value: Any, decimals: int = 1) -> str:
    try:
        return f"{float(value):,.{int(decimals)}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_minutes(value: Any) -> str:
    try:
        return f"{float(value):.0f} mnt"
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


def _rizan_chart_frame(
    raw_bars: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    timeframe: str,
) -> pd.DataFrame:
    if not raw_bars:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    frame = pd.DataFrame(list(raw_bars))
    required = {"time", "open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    for col in ("open", "high", "low", "close"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time")
    if frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    frame = frame.set_index("time")[["open", "high", "low", "close"]]
    tf = str(timeframe or "M15").upper()
    if tf == "M15":
        return frame.tail(120)
    rule, duration, limit = {
        "H1": ("1h", pd.Timedelta(hours=1), 96),
        "H4": ("4h", pd.Timedelta(hours=4), 60),
    }.get(tf, ("1h", pd.Timedelta(hours=1), 96))
    source_end = frame.index.max() + pd.Timedelta(minutes=15)
    out = frame.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    out = out[(out.index + duration) <= source_end]
    return out.tail(limit)


def _chart_price(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not pd.notna(parsed):
        return None
    return parsed


def _rizan_chart_target_ladder(
    *,
    direction: str,
    price_now: float,
    entry_zone: dict[str, Any] | None,
    structural_targets: list[dict[str, Any]] | None,
    current_target: Any,
    terminal_zone: dict[str, Any] | None,
    next_target: Any,
    order_targets_authorized: bool = True,
) -> tuple[list[dict[str, Any]], float | None, bool]:
    """Return a clean geometric target ladder for the chart.

    If price is still approaching the active depth/reaction zone, the visual path
    first points to the entry reference and then follows structural targets.
    Otherwise only still-forward targets are shown. Structural M15/H1/H4 targets
    always take precedence over legacy path fallbacks.
    """
    side = str(direction or "").upper()
    zone = dict(entry_zone or {})
    low = _chart_price(zone.get("entry_low", zone.get("low")))
    high = _chart_price(zone.get("entry_high", zone.get("high")))
    entry_ref = _chart_price(zone.get("entry_reference"))
    if entry_ref is None and low is not None and high is not None:
        entry_ref = (low + high) / 2.0

    approaching_entry = bool(
        side == "LONG"
        and high is not None
        and float(price_now) > high
        or side == "SHORT"
        and low is not None
        and float(price_now) < low
    )
    anchor = entry_ref if approaching_entry and entry_ref is not None else float(price_now)

    raw_targets: list[dict[str, Any]] = []
    for raw in list(structural_targets or []):
        item = dict(raw or {})
        price = _chart_price(item.get("target_price"))
        timeframe = str(item.get("timeframe") or "").upper()
        if price is None or timeframe not in {"M15", "H1", "H4", "D1"}:
            continue
        if side == "LONG" and price <= anchor:
            continue
        if side == "SHORT" and price >= anchor:
            continue
        raw_targets.append(
            {
                "price": price,
                "timeframe": timeframe,
                "role": str(item.get("role") or f"{timeframe}_TARGET"),
                "zone_low": _chart_price(item.get("zone_low")),
                "zone_high": _chart_price(item.get("zone_high")),
                "rr": _chart_price(item.get("rr")),
                "source": "STRUCTURAL",
            }
        )

    if not raw_targets:
        fallbacks: list[tuple[Any, str, str]] = [
            (current_target, "", "REACTION TARGET"),
        ]
        terminal = dict(terminal_zone or {})
        terminal_price = (
            _chart_price(terminal.get("low"))
            if side == "LONG"
            else _chart_price(terminal.get("high"))
            if side == "SHORT"
            else None
        )
        fallbacks.append((terminal_price, str(terminal.get("timeframe") or ""), "OPPOSING ZONE"))
        fallbacks.append((next_target, "", "NEXT TARGET"))
        for value, timeframe, role in fallbacks:
            price = _chart_price(value)
            if price is None:
                continue
            if side == "LONG" and price <= anchor:
                continue
            if side == "SHORT" and price >= anchor:
                continue
            raw_targets.append(
                {
                    "price": price,
                    "timeframe": timeframe.upper(),
                    "role": role,
                    "zone_low": None,
                    "zone_high": None,
                    "rr": None,
                    "source": "PATH_FALLBACK",
                }
            )

    raw_targets.sort(key=lambda item: abs(float(item["price"]) - anchor))
    targets: list[dict[str, Any]] = []
    for item in raw_targets:
        if any(abs(float(existing["price"]) - float(item["price"])) < 0.05 for existing in targets):
            continue
        targets.append(item)
        if len(targets) >= 3:
            break

    for index, item in enumerate(targets, start=1):
        tf = str(item.get("timeframe") or "")
        prefix = "TP" if order_targets_authorized else "PATH"
        item["label"] = f"{prefix}{index}" + (f" {tf}" if tf else "")
    return targets, entry_ref, approaching_entry


def _rizan_chart_png(
    raw_bars: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    timeframe: str,
    zones: list[dict[str, Any]],
    price_now: float,
    probability_by_zone: dict[str, dict[str, Any]],
    path_roles: dict[str, str],
    current_direction: str,
    current_target: Any,
    terminal_zone: dict[str, Any] | None,
    next_target: Any,
    depth_overlays: list[dict[str, Any]] | None = None,
    entry_zone: dict[str, Any] | None = None,
    structural_targets: list[dict[str, Any]] | None = None,
    next_leg_direction: str | None = None,
    next_leg_source: dict[str, Any] | None = None,
    next_leg_target: dict[str, Any] | None = None,
    next_leg_terminal: dict[str, Any] | None = None,
    next_leg_micro: dict[str, Any] | None = None,
    order_targets_authorized: bool = True,
) -> tuple[bytes | None, str | None]:
    frame = _rizan_chart_frame(raw_bars, timeframe)
    if frame.empty or len(frame) < 4:
        return None, "OHLC snapshot belum cukup untuk membentuk candlestick."

    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyArrowPatch, Rectangle
        from io import BytesIO
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    fig, ax = plt.subplots(figsize=(16.8, 8.2))
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")

    visible = frame.copy()
    x_values = list(range(len(visible)))
    candle_width = 0.62
    up_color = "#22c55e"
    down_color = "#ef4444"
    wick_color = "#cbd5e1"

    for x, (_, row) in zip(x_values, visible.iterrows()):
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        close = float(row["close"])
        color = up_color if close >= o else down_color
        ax.vlines(x, l, h, color=wick_color, linewidth=0.72, alpha=0.92, zorder=3)
        body_low = min(o, close)
        body_height = max(abs(close - o), max((h - l) * 0.012, 0.04))
        ax.add_patch(
            Rectangle(
                (x - candle_width / 2.0, body_low),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.7,
                zorder=4,
            )
        )

    right_edge = len(visible) + 26
    nearest_long = next(
        (z for z in zones if str(z.get("direction") or "").upper() == "LONG"),
        None,
    )
    nearest_short = next(
        (z for z in zones if str(z.get("direction") or "").upper() == "SHORT"),
        None,
    )
    key_zone_ids = {
        str(dict(nearest_long or {}).get("zone_id") or ""),
        str(dict(nearest_short or {}).get("zone_id") or ""),
        *[str(key) for key in path_roles.keys()],
    }

    def origin_x(zone: dict[str, Any]) -> int:
        origin = pd.to_datetime(zone.get("origin_at"), utc=True, errors="coerce")
        if pd.isna(origin):
            return max(0, len(visible) - 30)
        idx = int(visible.index.searchsorted(origin))
        return max(0, min(len(visible) - 1, idx))

    for zone in zones[:8]:
        try:
            low = float(zone["low"])
            high = float(zone["high"])
        except (KeyError, TypeError, ValueError):
            continue
        side = str(zone.get("direction") or "").upper()
        zone_id = str(zone.get("zone_id") or "")
        is_demand = side == "LONG"
        face = "#16a34a" if is_demand else "#dc2626"
        edge = "#4ade80" if is_demand else "#f87171"
        important = zone_id in key_zone_ids
        alpha = 0.19 if important else 0.075
        start_x = origin_x(zone)
        width = right_edge - start_x - 1.0
        ax.add_patch(
            Rectangle(
                (start_x, low),
                width,
                max(high - low, 1e-6),
                facecolor=face,
                edgecolor=edge,
                alpha=alpha,
                linewidth=1.45 if important else 0.75,
                zorder=1,
            )
        )

        prob = dict(probability_by_zone.get(zone_id) or {})
        p_touch = dict(prob.get("destination") or {}).get("p_touch")
        p_hold = dict(prob.get("reaction") or {}).get("p_hold_050")
        lifecycle = dict(zone.get("lifecycle") or {})
        freshness = str(lifecycle.get("freshness") or "")
        role = path_roles.get(zone_id, "")
        label = (
            f"{zone.get('timeframe','')} {'DEMAND' if is_demand else 'SUPPLY'}  "
            f"{low:.2f}–{high:.2f}"
        )
        role_label = {
            "SOURCE": "SUMBER LEG",
            "TARGET 1": "ZONA LAWAN",
            "NEXT SOURCE": "AREA REAKSI",
            "NEXT TARGET": "TARGET PANTULAN",
        }.get(role, "")
        detail = role_label
        if important:
            ax.text(
                right_edge - 0.6,
                (low + high) / 2.0,
                label + ("\n" + detail if detail else ""),
                ha="right",
                va="center",
                fontsize=8.0,
                color="#f8fafc",
                bbox=dict(
                    boxstyle="round,pad=0.32",
                    facecolor="#111827",
                    edgecolor=edge,
                    alpha=0.94,
                ),
                zorder=6,
            )

    # V226 RIZAN Depth hotspot / nested locator overlays.
    # Keep only the active-leg overlays; the opposing leg gets its own explicit
    # reaction-zone/pocket layer below, which is much easier to read on mobile.
    chart_tf = str(timeframe or "M15").upper()
    depth_shown = 0
    for depth in list(depth_overlays or []):
        visible_on = {str(item).upper() for item in list(depth.get("visible_on") or [])}
        if visible_on and chart_tf not in visible_on:
            continue
        side = str(depth.get("direction") or "").upper()
        if side and side != str(current_direction or "").upper():
            continue
        if depth_shown >= 3:
            break
        try:
            depth_low = float(depth["low"])
            depth_high = float(depth["high"])
        except (KeyError, TypeError, ValueError):
            continue
        depth_shown += 1
        kind = str(depth.get("kind") or "DEPTH_LOCATOR").upper()
        if kind.startswith("H4"):
            depth_edge = "#facc15"
        elif kind.startswith("H1"):
            depth_edge = "#38bdf8"
        else:
            depth_edge = "#a78bfa"
        depth_start_x = max(0.0, len(visible) * 0.45)
        depth_width = right_edge - depth_start_x - 1.0
        ax.add_patch(
            Rectangle(
                (depth_start_x, depth_low),
                depth_width,
                max(depth_high - depth_low, 1e-6),
                facecolor=depth_edge,
                edgecolor=depth_edge,
                alpha=0.12,
                linewidth=1.7,
                linestyle="--",
                zorder=2,
            )
        )
        median_price = depth.get("median_price")
        try:
            if median_price is not None:
                median_value = float(median_price)
                ax.hlines(
                    median_value,
                    depth_start_x,
                    right_edge - 1.0,
                    color=depth_edge,
                    linewidth=1.15,
                    linestyle=":",
                    alpha=0.95,
                    zorder=5,
                )
        except (TypeError, ValueError):
            pass
        depth_label = str(depth.get("label") or "RIZAN Depth hotspot")
        # Keep chart labels short. Detailed applicability/reuse state belongs in
        # the dashboard metrics, not on top of the candles.
        ax.text(
            len(visible) + 0.8,
            depth_high,
            f"{depth_label} • {depth_low:.2f}–{depth_high:.2f}",
            ha="left",
            va="bottom",
            fontsize=7.6,
            color=depth_edge,
            bbox=dict(
                boxstyle="round,pad=0.25",
                facecolor="#111827",
                edgecolor=depth_edge,
                alpha=0.92,
            ),
            zorder=8,
        )

    targets, entry_reference, approaching_entry = _rizan_chart_target_ladder(
        direction=current_direction,
        price_now=float(price_now),
        entry_zone=entry_zone,
        structural_targets=structural_targets,
        current_target=current_target,
        terminal_zone=terminal_zone,
        next_target=next_target,
        order_targets_authorized=order_targets_authorized,
    )

    next_side = str(next_leg_direction or "").upper()
    reaction_zone = dict(next_leg_source or {})
    reaction_low = _chart_price(reaction_zone.get("low"))
    reaction_high = _chart_price(reaction_zone.get("high"))
    next_target_row = dict(next_leg_target or {})
    next_reaction_price = _chart_price(next_target_row.get("price"))
    next_terminal_row = dict(next_leg_terminal or {})
    next_terminal_low = _chart_price(next_terminal_row.get("low"))
    next_terminal_high = _chart_price(next_terminal_row.get("high"))
    next_micro_row = dict(next_leg_micro or {})
    refined_pocket = dict(next_micro_row.get("refined_entry_pocket") or {})
    refined_low = _chart_price(refined_pocket.get("low"))
    refined_high = _chart_price(refined_pocket.get("high"))
    two_leg_mode = bool(
        str(current_direction or "").upper() in {"LONG", "SHORT"}
        and next_side in {"LONG", "SHORT"}
        and next_side != str(current_direction or "").upper()
        and reaction_low is not None
        and reaction_high is not None
        and reaction_high > reaction_low
    )

    active_entry = dict(entry_zone or {})
    active_entry_low = _chart_price(active_entry.get("entry_low", active_entry.get("low")))
    active_entry_high = _chart_price(active_entry.get("entry_high", active_entry.get("high")))
    if active_entry_low is not None and active_entry_high is not None and active_entry_high > active_entry_low:
        entry_start_x = max(0.0, len(visible) * 0.56)
        ax.add_patch(
            Rectangle(
                (entry_start_x, active_entry_low),
                right_edge - entry_start_x - 1.0,
                active_entry_high - active_entry_low,
                facecolor="#f59e0b",
                edgecolor="#fbbf24",
                alpha=0.13,
                linewidth=2.0,
                linestyle="-",
                zorder=2,
            )
        )
        ax.text(
            entry_start_x + 0.35,
            active_entry_high,
            "DEPTH / ENTRY AKTIF  "
            f"{active_entry_low:.2f}–{active_entry_high:.2f}",
            ha="left",
            va="bottom",
            fontsize=8.0,
            color="#fbbf24",
            bbox=dict(
                boxstyle="round,pad=0.28",
                facecolor="#111827",
                edgecolor="#f59e0b",
                alpha=0.94,
            ),
            zorder=9,
        )

    target_colors = ("#38bdf8", "#a78bfa", "#f59e0b")
    if not two_leg_mode:
        for index, target in enumerate(targets):
            target_price = float(target["price"])
            target_color = target_colors[min(index, len(target_colors) - 1)]
            target_label = str(target.get("label") or f"TP{index + 1}")
            if index == len(targets) - 1 and len(targets) > 1:
                target_label += " • TARGET BERIKUTNYA"
            ax.hlines(
                target_price,
                max(0.0, len(visible) * 0.58),
                right_edge - 1.0,
                color=target_color,
                linewidth=1.05,
                linestyle=":",
                alpha=0.82,
                zorder=5,
            )
            ax.text(
                right_edge - 0.6,
                target_price,
                f"{target_label}  {target_price:.2f}",
                ha="right",
                va="bottom",
                fontsize=8.1,
                color=target_color,
                bbox=dict(
                    boxstyle="round,pad=0.24",
                    facecolor="#111827",
                    edgecolor=target_color,
                    alpha=0.94,
                ),
                zorder=9,
            )
    else:
        checkpoint = _chart_price(current_target)
        if checkpoint is not None:
            ax.hlines(
                checkpoint,
                max(0.0, len(visible) * 0.64),
                right_edge - 1.0,
                color="#38bdf8",
                linewidth=1.25,
                linestyle=":",
                alpha=0.95,
                zorder=6,
            )
            ax.text(
                len(visible) + 2.0,
                checkpoint,
                f"CHECKPOINT {str(current_direction).upper()}  {checkpoint:.2f}",
                ha="left",
                va="bottom",
                fontsize=8.2,
                color="#38bdf8",
                bbox=dict(
                    boxstyle="round,pad=0.24",
                    facecolor="#111827",
                    edgecolor="#38bdf8",
                    alpha=0.95,
                ),
                zorder=10,
            )

        reaction_start_x = max(0.0, len(visible) * 0.58)
        ax.add_patch(
            Rectangle(
                (reaction_start_x, float(reaction_low)),
                right_edge - reaction_start_x - 1.0,
                float(reaction_high) - float(reaction_low),
                facecolor="#ef4444" if next_side == "SHORT" else "#22c55e",
                edgecolor="#fb7185" if next_side == "SHORT" else "#4ade80",
                alpha=0.15,
                linewidth=2.2,
                zorder=3,
            )
        )
        reaction_label_color = "#fb7185" if next_side == "SHORT" else "#4ade80"
        ax.text(
            len(visible) + 9.0,
            (float(reaction_low) + float(reaction_high)) / 2.0,
            f"AREA REAKSI • PANTAU {next_side}\n"
            f"{float(reaction_low):.2f}–{float(reaction_high):.2f}",
            ha="left",
            va="center",
            fontsize=8.4,
            color="#f8fafc",
            bbox=dict(
                boxstyle="round,pad=0.30",
                facecolor="#111827",
                edgecolor=reaction_label_color,
                alpha=0.96,
            ),
            zorder=11,
        )

        if (
            refined_low is not None
            and refined_high is not None
            and refined_high > refined_low
        ):
            pocket_start_x = max(0.0, len(visible) * 0.70)
            ax.add_patch(
                Rectangle(
                    (pocket_start_x, refined_low),
                    right_edge - pocket_start_x - 1.0,
                    refined_high - refined_low,
                    facecolor="#f97316",
                    edgecolor="#fb923c",
                    alpha=0.18,
                    linewidth=1.5,
                    linestyle="--",
                    zorder=4,
                )
            )
            ax.text(
                len(visible) + 9.0,
                refined_high,
                f"M5 POCKET  {refined_low:.2f}–{refined_high:.2f}",
                ha="left",
                va="bottom",
                fontsize=7.6,
                color="#fb923c",
                bbox=dict(
                    boxstyle="round,pad=0.22",
                    facecolor="#111827",
                    edgecolor="#fb923c",
                    alpha=0.94,
                ),
                zorder=11,
            )

        if next_reaction_price is not None:
            ax.hlines(
                next_reaction_price,
                max(0.0, len(visible) * 0.68),
                right_edge - 1.0,
                color="#fb923c",
                linewidth=1.15,
                linestyle=":",
                alpha=0.95,
                zorder=6,
            )
            ax.text(
                len(visible) + 16.0,
                next_reaction_price,
                f"TARGET {next_side}  {next_reaction_price:.2f}",
                ha="left",
                va="top",
                fontsize=8.1,
                color="#fb923c",
                bbox=dict(
                    boxstyle="round,pad=0.23",
                    facecolor="#111827",
                    edgecolor="#fb923c",
                    alpha=0.95,
                ),
                zorder=10,
            )
    ax.axhline(float(price_now), color="#f8fafc", linewidth=1.0, linestyle="--", alpha=0.72)
    ax.text(
        len(visible) + 0.8,
        float(price_now),
        f"NOW  {float(price_now):.2f}",
        ha="left",
        va="bottom",
        fontsize=9,
        color="#f8fafc",
        bbox=dict(boxstyle="round,pad=0.25", facecolor="#1f2937", edgecolor="#94a3b8"),
        zorder=8,
    )

    if two_leg_mode:
        current_side = str(current_direction or "").upper()
        checkpoint = _chart_price(current_target)
        current_start_x = max(0.0, len(visible) - 5.0)
        # Dedicated future-path rail. Wider spacing prevents labels and arrows
        # from colliding with each other or with the zone labels.
        x1 = len(visible) + 3.0
        x2 = len(visible) + 10.0
        x3 = len(visible) + 17.0

        current_destination = (
            checkpoint
            if checkpoint is not None
            else float(reaction_low if current_side == "LONG" else reaction_high)
        )
        current_arrow = FancyArrowPatch(
            (current_start_x, float(price_now)),
            (x1, float(current_destination)),
            arrowstyle="-|>",
            mutation_scale=20,
            linewidth=2.6,
            color="#38bdf8",
            linestyle="-",
            connectionstyle="arc3,rad=0.03",
            zorder=12,
        )
        ax.add_patch(current_arrow)
        ax.text(
            (current_start_x + x1) / 2.0,
            (float(price_now) + float(current_destination)) / 2.0,
            f"LEG AKTIF {current_side}",
            fontsize=8.6,
            color="#38bdf8",
            ha="center",
            va="bottom",
            fontweight="bold",
            zorder=13,
        )

        reaction_entry = float(
            refined_low + (refined_high - refined_low) / 2.0
            if refined_low is not None and refined_high is not None
            else reaction_low + (reaction_high - reaction_low) / 2.0
        )
        if abs(float(current_destination) - reaction_entry) > 0.05:
            approach_arrow = FancyArrowPatch(
                (x1, float(current_destination)),
                (x2, reaction_entry),
                arrowstyle="-|>",
                mutation_scale=18,
                linewidth=1.8,
                color="#94a3b8",
                linestyle="--",
                connectionstyle="arc3,rad=0.04",
                zorder=11,
            )
            ax.add_patch(approach_arrow)
            ax.text(
                x2,
                reaction_entry,
                f"CEK REAKSI {next_side}",
                fontsize=8.1,
                color=reaction_label_color,
                ha="center",
                va="bottom",
                fontweight="bold",
                zorder=13,
            )

        if next_reaction_price is not None:
            reaction_arrow = FancyArrowPatch(
                (x2, reaction_entry),
                (x3, float(next_reaction_price)),
                arrowstyle="-|>",
                mutation_scale=20,
                linewidth=2.4,
                color="#fb923c",
                linestyle="--",
                connectionstyle="arc3,rad=-0.08",
                zorder=12,
            )
            ax.add_patch(reaction_arrow)
            ax.text(
                (x2 + x3) / 2.0,
                (reaction_entry + float(next_reaction_price)) / 2.0,
                f"JIKA REJECT → {next_side}",
                fontsize=8.5,
                color="#fb923c",
                ha="center",
                va="top" if next_reaction_price < reaction_entry else "bottom",
                fontweight="bold",
                zorder=13,
            )

            continuation_edge = (
                next_terminal_low
                if next_side == "SHORT"
                else next_terminal_high
            )
            if (
                continuation_edge is not None
                and abs(float(continuation_edge) - float(next_reaction_price)) > 0.05
            ):
                continuation_arrow = FancyArrowPatch(
                    (x3, float(next_reaction_price)),
                    (right_edge - 1.3, float(continuation_edge)),
                    arrowstyle="-|>",
                    mutation_scale=16,
                    linewidth=1.5,
                    color="#fb923c",
                    linestyle=":",
                    connectionstyle="arc3,rad=-0.04",
                    zorder=10,
                )
                ax.add_patch(continuation_arrow)
                ax.text(
                    right_edge - 1.4,
                    float(continuation_edge),
                    f"jika zona target jebol → {float(continuation_edge):.2f}",
                    fontsize=7.4,
                    color="#fb923c",
                    ha="right",
                    va="top" if next_side == "SHORT" else "bottom",
                    zorder=12,
                )
    else:
        path_points: list[tuple[float, float, str]] = [
            (max(0.0, len(visible) - 5.0), float(price_now), "NOW")
        ]
        future_x = len(visible) + 1.2
        if approaching_entry and entry_reference is not None:
            path_points.append((future_x, float(entry_reference), "DEPTH / ENTRY"))
            future_x += 3.3

        for index, target in enumerate(targets):
            label = str(target.get("label") or f"TP{index + 1}")
            if index == len(targets) - 1 and len(targets) > 1:
                label += " • NEXT TARGET"
            path_points.append((future_x, float(target["price"]), label))
            future_x += 3.3

        for idx, ((x1, y1, _), (x2, y2, label2)) in enumerate(zip(path_points, path_points[1:])):
            if label2 == "DEPTH / ENTRY":
                line_color = "#fbbf24"
            else:
                target_index = max(0, idx - (1 if approaching_entry and entry_reference is not None else 0))
                line_color = target_colors[min(target_index, len(target_colors) - 1)]
            arrow = FancyArrowPatch(
                (x1, y1),
                (x2, y2),
                arrowstyle="-|>",
                mutation_scale=18,
                linewidth=2.0,
                color=line_color,
                linestyle="-",
                connectionstyle="arc3,rad=0.06",
                zorder=10,
            )
            ax.add_patch(arrow)
            ax.text(
                x2,
                y2,
                label2,
                fontsize=8.2,
                color=line_color,
                va="top" if y2 < y1 else "bottom",
                ha="center",
                fontweight="bold",
                zorder=11,
            )

    y_values = [float(visible["low"].min()), float(visible["high"].max()), float(price_now)]
    for zone in zones[:8]:
        try:
            y_values.extend([float(zone["low"]), float(zone["high"])])
        except (KeyError, TypeError, ValueError):
            pass
    depth_y_shown = 0
    for depth in list(depth_overlays or []):
        visible_on = {str(item).upper() for item in list(depth.get("visible_on") or [])}
        if visible_on and chart_tf not in visible_on:
            continue
        if str(depth.get("direction") or "").upper() not in {
            "",
            str(current_direction or "").upper(),
        }:
            continue
        if depth_y_shown >= 3:
            break
        try:
            y_values.extend([float(depth["low"]), float(depth["high"])])
            depth_y_shown += 1
        except (KeyError, TypeError, ValueError):
            pass
    if active_entry_low is not None and active_entry_high is not None:
        y_values.extend([active_entry_low, active_entry_high])
    for target in targets:
        y_values.append(float(target["price"]))
    for scenario_value in (
        reaction_low,
        reaction_high,
        next_reaction_price,
        next_terminal_low,
        next_terminal_high,
        refined_low,
        refined_high,
    ):
        if scenario_value is not None:
            y_values.append(float(scenario_value))
    pad = max(2.0, (max(y_values) - min(y_values)) * 0.08)
    ax.set_ylim(min(y_values) - pad, max(y_values) + pad)
    ax.set_xlim(-1.0, right_edge)

    tick_count = min(7, len(visible))
    if tick_count > 1:
        step = max(1, len(visible) // (tick_count - 1))
        positions = list(range(0, len(visible), step))
        if positions[-1] != len(visible) - 1:
            positions.append(len(visible) - 1)
        labels = [
            visible.index[pos].tz_convert(WIB).strftime("%d/%m\n%H:%M")
            for pos in positions
        ]
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, color="#94a3b8", fontsize=8)
    ax.tick_params(axis="y", colors="#94a3b8", labelsize=8)
    ax.grid(axis="y", color="#334155", alpha=0.28, linewidth=0.7)
    for spine in ax.spines.values():
        spine.set_color("#334155")

    title_suffix = (
        f"leg aktif {str(current_direction or '—').upper()} • berikutnya cek {next_side}"
        if two_leg_mode
        else f"leg aktif {str(current_direction or '—').upper()} • path: ENTRY → TP berikutnya"
    )
    ax.set_title(
        f"XAUUSD • RIZAN-style Supply/Demand • {str(timeframe).upper()} • {title_suffix}",
        color="#f8fafc",
        fontsize=12,
        loc="left",
        pad=12,
    )
    if two_leg_mode:
        ax.text(
            0.01,
            0.985,
            "Biru solid = leg aktif • Abu putus = masuk area reaksi • Oranye putus = skenario pantulan",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.2,
            color="#cbd5e1",
            bbox=dict(
                boxstyle="round,pad=0.28",
                facecolor="#111827",
                edgecolor="#475569",
                alpha=0.92,
            ),
            zorder=14,
        )
    ax.set_ylabel("Harga XAUUSD", color="#cbd5e1")
    fig.tight_layout()

    output = BytesIO()
    fig.savefig(
        output,
        format="png",
        dpi=190,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    return output.getvalue(), None


def _rizan_path_text(direction: str, state: str) -> str:
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


def _rizan_next_action(
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
        return "PROTECTION ALERT", "Order side-effect exists; new RIZAN-style orders must remain blocked until SL/TP is reconciled."
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
    return "WAIT FORECAST", "No execution-ready RIZAN-style path is active yet."


def _render_standalone_dashboard(state: dict[str, Any]) -> None:
    quote = dict(state.get("quote") or {})
    canonical = dict(state.get("canonical") or {})
    pressure = dict(state.get("pressure_transition") or {})
    dynamic = dict(state.get("dynamic_depth") or {})
    regime = dict(state.get("strategic_regime") or {})
    strategic = dict(regime.get("current") or {})
    atlas = dict(state.get("atlas") or {})
    projection = dict(state.get("m5_projection") or {})
    current_leg = dict(projection.get("current_leg") or {})
    collection = dict(state.get("collection") or {})
    bridge = dict(state.get("bridge") or {})

    st.warning(
        "CTRADER QUOTE BACKUP • DIAGNOSTIC ONLY • NO DASHBOARD AUTHORITY • "
        "DEMO auto-execution OFF. Tidak ada order yang dikirim dari mode ini."
    )
    st.caption(
        f"Update {_fmt_wib_datetime(state.get('as_of'))} • "
        f"quote age {_fmt_number(quote.get('age_seconds'), 1)} dtk • "
        f"M15 {collection.get('m15_bars', 0)} bar • M5 {collection.get('m5_bars', 0)} bar • "
        f"DOM {collection.get('dom_frames', 0)} frame • Supabase I/O 0"
    )

    direction = str(canonical.get("direction") or "WAIT")
    action = str(dynamic.get("action") or pressure.get("state") or canonical.get("state") or "WAIT")
    decision_labels = {
        "ENTRY_WINDOW": "ENTRY WINDOW — kandidat entry manual",
        "WAIT_ZONE": "WAIT — BELUM ENTRY (harga belum di zona)",
        "WAIT_PRESSURE": "WAIT — tekanan belum mendukung",
        "WAIT_M5_CONFIRM": "WAIT — tunggu konfirmasi M5",
        "WAIT_STRUCTURE_REMAP": "WAIT — zona perlu remap",
        "WAIT_OR_DEEPER": "WAIT — tunggu harga lebih dalam",
        "WAIT_SECOND_SAMPLE": "WAIT — tunggu sampel pressure berikutnya",
    }
    decision_label = decision_labels.get(action, action)

    st.markdown("### Keputusan Entry RIZAN")
    if bridge and not bool(bridge.get("fresh")):
        st.error(
            f"DATA STALE • Keputusan terakhir: {decision_label}. "
            "Jangan gunakan sebagai entry live sampai snapshot baru masuk. "
            f"Snapshot age: {_fmt_number(bridge.get('age_seconds'), 0)} detik."
        )
        s1, s2, s3 = st.columns(3)
        s1.metric("Arah terakhir", direction)
        s2.metric("Keputusan terakhir", decision_label)
        s3.metric("Harga snapshot", _fmt_price(quote.get("mid")))
        st.caption(
            "Entry/SL/TP live tetap disembunyikan saat stale. "
            f"State terakhir: {canonical.get('state') or '—'} • "
            f"lokasi: {dynamic.get('location_state') or '—'}."
        )
        return

    if action == "ENTRY_WINDOW":
        st.success(f"KEPUTUSAN ENTRY: {decision_label} • Standalone tetap manual-only.")
    elif "WAIT" in action or bool(pressure.get("hard_block")):
        st.info(f"KEPUTUSAN ENTRY: {decision_label}")
    else:
        st.info(f"KEPUTUSAN ENTRY: {decision_label}")

    entry_low = canonical.get("entry_low")
    entry_high = canonical.get("entry_high")
    entry_text = (
        f"{_fmt_price(entry_low)}–{_fmt_price(entry_high)}"
        if entry_low is not None and entry_high is not None
        else "—"
    )
    q1, q2, q3, q4, q5 = st.columns(5)
    q1.metric("Arah RIZAN", direction)
    q2.metric("XAU Mid", _fmt_price(quote.get("mid")))
    q3.metric("Entry Zone", entry_text)
    q4.metric("SL Struktural", _fmt_price(canonical.get("sl")))
    q5.metric("TP1", _fmt_price(canonical.get("tp1")))

    depth_value = dynamic.get("current_depth")
    depth_text = _fmt_pct(depth_value) if depth_value is not None else "—"
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Strategic Bias", str(strategic.get("strategic_bias") or "—"))
    p2.metric("Source", str(canonical.get("source_layer") or "—"))
    p3.metric("Depth Saat Ini", depth_text)
    p4.metric("Buyer Index", _fmt_number(pressure.get("buyer_index"), 1))
    p5.metric("Seller Index", _fmt_number(pressure.get("seller_index"), 1))

    d1, d2 = st.columns(2)
    with d1:
        st.markdown("**Demand reversal utama**")
        demand = dict(canonical.get("nearest_demand") or {})
        st.write(
            f"{demand.get('timeframe') or '—'} • "
            f"{_fmt_price(demand.get('low'))}–{_fmt_price(demand.get('high'))} • "
            f"touch {demand.get('touch_count', '—')}"
        )
    with d2:
        st.markdown("**Supply reversal utama**")
        supply = dict(canonical.get("nearest_supply") or {})
        st.write(
            f"{supply.get('timeframe') or '—'} • "
            f"{_fmt_price(supply.get('low'))}–{_fmt_price(supply.get('high'))} • "
            f"touch {supply.get('touch_count', '—')}"
        )

    recommended = dict(dynamic.get("recommended_band") or {})
    if recommended:
        st.markdown("### Dynamic Depth V251")
        x1, x2, x3, x4 = st.columns(4)
        x1.metric(
            "Band reversal",
            f"{_fmt_pct(recommended.get('lower_depth'))}–{_fmt_pct(recommended.get('upper_depth'))}",
        )
        x2.metric(
            "Area harga",
            f"{_fmt_price(dynamic.get('recommended_price_low'))}–{_fmt_price(dynamic.get('recommended_price_high'))}",
        )
        x3.metric("Hazard adj.", _fmt_pct(recommended.get("adjusted_hazard")))
        x4.metric("Pressure", str(pressure.get("state") or "—"))

    st.markdown("### Jalur harga & M5")
    st.write(
        f"M5 current leg: **{current_leg.get('direction') or '—'}** • "
        f"state **{current_leg.get('pocket_state') or projection.get('state') or '—'}** • "
        f"reference entry **{_fmt_price(canonical.get('entry_reference'))}** • "
        f"TP2 **{_fmt_price(canonical.get('tp2'))}**"
    )

    chart = _rizan_chart_frame(list(atlas.get("chart_bars_m15") or []), "M15")
    if not chart.empty:
        st.markdown("### XAU M15 — live cTrader")
        st.line_chart(chart[["close"]], height=320)

    future = [dict(x) for x in list(dynamic.get("future_bands") or [])]
    if future:
        table = pd.DataFrame(future[:10])
        wanted = [
            col for col in (
                "band", "lower_depth", "upper_depth", "hazard", "adjusted_hazard",
                "at_risk", "price_low", "price_high", "eligible"
            ) if col in table.columns
        ]
        st.markdown("### Depth bands berikutnya")
        st.dataframe(table[wanted], hide_index=True, width="stretch")

    parity = dict(state.get("logic_parity") or {})
    if parity:
        with st.expander("Logic Parity — apakah sama dengan scanner utama?"):
            p1, p2 = st.columns(2)
            p1.metric(
                "Core analysis",
                "SAME LOGIC" if parity.get("analysis_core_parity") else "DIFFERENT",
            )
            p2.metric(
                "End-to-end execution",
                "SAME" if parity.get("end_to_end_execution_parity") else "DISABLED / NOT PARITY",
            )
            st.markdown("**Core yang memakai logic produksi yang sama**")
            st.write(", ".join(str(x) for x in list(parity.get("core_same_logic") or [])) or "—")
            st.markdown("**Pengganti khusus Restricted Mode**")
            st.write(", ".join(str(x) for x in list(parity.get("standalone_substitutes") or [])) or "—")
            st.markdown("**Layer stateful yang sementara tidak aktif**")
            st.write(", ".join(str(x) for x in list(parity.get("disabled_stateful_layers") or [])) or "—")

    with st.expander("Detail Standalone / audit"):
        st.json(
            _rizan_display(
                {
                    "state": state.get("state"),
                    "canonical": canonical,
                    "pressure_transition": pressure,
                    "dynamic_depth": dynamic,
                    "collection": collection,
                    "safety": state.get("safety"),
                }
            )
        )


cfg, config_error = _safe_config()
policy = None
policy_error = None
try:
    policy = load_execution_policy(ROOT)
except Exception as exc:
    policy_error = f"{type(exc).__name__}: {exc}"

supabase_url = _secret("SUPABASE_URL")
supabase_secret = _secret("SUPABASE_SERVICE_ROLE_KEY") or _secret(
    "SUPABASE_SECRET_KEY"
)
backend_configured = bool(supabase_url and supabase_secret)
supabase_project_ref = _supabase_project_ref(supabase_url)
supabase_project_matches = bool(
    not supabase_url or supabase_project_ref == FOREXRIZAN_PROJECT_REF
)

backend: dict[str, Any] | None = None
backend_source = "OFFLINE"
backend_bridge_meta: dict[str, Any] = {}
backend_error: str | None = None
direct_backend_error: str | None = None
dashboard_bridge_error: str | None = None
dashboard_bridge_degraded_error: str | None = None
dashboard_bridge_selected_url: str | None = None
dashboard_bridge_attempts: list[str] = []

supabase_restricted_until = float(
    st.session_state.get("supabase_restricted_until", 0.0) or 0.0
)
now_epoch = datetime.now(tz=UTC).timestamp()

# A publishable key is valid for the public API but must never be granted broad
# table SELECT just to make the dashboard work. In that case we go straight to
# the curated read-only GitHub bridge.
publishable_key_configured = _supabase_key_role(supabase_secret) == "anon"

if (
    backend_configured
    and supabase_project_matches
    and not publishable_key_configured
    and now_epoch >= supabase_restricted_until
):
    try:
        backend = _load_backend_snapshot(supabase_url, supabase_secret)
        backend_source = "SUPABASE_DIRECT"
    except (DashboardReadError, OperationalStoreUnavailable, Exception) as exc:
        direct_backend_error = f"{type(exc).__name__}: {exc}"
        lowered = direct_backend_error.lower()
        if "402" in lowered or "egress_quota" in lowered or "exceed_egress" in lowered:
            st.session_state["supabase_restricted_until"] = now_epoch + 1800.0
        elif (
            "42501" in lowered
            or "permission denied" in lowered
            or "role anon" in lowered
        ):
            # Do not hammer protected tables once Streamlit is known to have
            # only an anon/publishable credential. The bridge remains fresh
            # while database tables stay private.
            st.session_state["supabase_restricted_until"] = now_epoch + 21600.0
elif backend_configured and not supabase_project_matches:
    direct_backend_error = (
        "SUPABASE_PROJECT_MISMATCH: Streamlit secret points to "
        f"{supabase_project_ref or 'UNKNOWN'}; expected {FOREXRIZAN_PROJECT_REF}. "
        "Direct reads disabled; using canonical ForexRizan bridge."
    )
elif backend_configured and not publishable_key_configured:
    direct_backend_error = (
        "SUPABASE_DIRECT_COOLDOWN: direct Data API temporarily bypassed; "
        "using the curated dashboard bridge."
    )
elif publishable_key_configured:
    direct_backend_error = (
        "SUPABASE_PUBLISHABLE_KEY: direct protected-table reads intentionally disabled."
    )

configured_dashboard_bridge_url = _secret("RIZAN_DASHBOARD_SNAPSHOT_URL")
dashboard_bridge_urls = [DEFAULT_DASHBOARD_SNAPSHOT_URL]
if (
    configured_dashboard_bridge_url
    and configured_dashboard_bridge_url not in dashboard_bridge_urls
):
    dashboard_bridge_urls.append(configured_dashboard_bridge_url)

def _accept_dashboard_bridge_payload(
    payload: dict[str, Any],
    *,
    source_url: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = dict(payload.get("source") or {})
    project_ref = str(source.get("project_ref") or "")
    if project_ref != FOREXRIZAN_PROJECT_REF:
        raise ValueError(
            f"dashboard bridge project mismatch: {project_ref or 'UNKNOWN'}"
        )
    candidate_backend = dict(payload.get("backend") or {})
    if not candidate_backend:
        raise ValueError("dashboard bridge returned an empty backend snapshot")
    meta = dict(payload.get("bridge") or {})
    meta["source_url_kind"] = (
        "CANONICAL"
        if source_url == DEFAULT_DASHBOARD_SNAPSHOT_URL
        else "CONFIGURED_FALLBACK"
    )
    return candidate_backend, meta

if backend is None:
    fresh_errors: list[str] = []
    for candidate_url in dashboard_bridge_urls:
        try:
            dashboard_bridge_payload = _load_dashboard_bridge(
                candidate_url,
                require_fresh=True,
            )
            backend, backend_bridge_meta = _accept_dashboard_bridge_payload(
                dashboard_bridge_payload,
                source_url=candidate_url,
            )
            backend_source = "GITHUB_DASHBOARD_BRIDGE"
            dashboard_bridge_selected_url = candidate_url
            break
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            fresh_errors.append(error)
            dashboard_bridge_attempts.append(
                ("CANONICAL" if candidate_url == DEFAULT_DASHBOARD_SNAPSHOT_URL else "CONFIGURED")
                + ":FRESH_FAIL:" + error
            )
    if backend is None:
        dashboard_bridge_error = " | ".join(fresh_errors) or "no dashboard bridge candidate"

        degraded_errors: list[str] = []
        for candidate_url in dashboard_bridge_urls:
            try:
                degraded_payload = _load_dashboard_bridge(
                    candidate_url,
                    require_fresh=False,
                )
                degraded_backend, degraded_meta = _accept_dashboard_bridge_payload(
                    degraded_payload,
                    source_url=candidate_url,
                )
                degraded_age = degraded_meta.get("age_seconds")
                degraded_age_f = (
                    None if degraded_age is None else float(degraded_age)
                )
                if (
                    degraded_age_f is None
                    or degraded_age_f > DASHBOARD_DEGRADED_MAX_AGE_SECONDS
                ):
                    raise ValueError(
                        "dashboard bridge stale beyond degraded-read window"
                    )
                backend = degraded_backend
                backend_bridge_meta = degraded_meta
                backend_source = "GITHUB_DASHBOARD_BRIDGE_STALE"
                dashboard_bridge_selected_url = candidate_url
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                degraded_errors.append(error)
                dashboard_bridge_attempts.append(
                    ("CANONICAL" if candidate_url == DEFAULT_DASHBOARD_SNAPSHOT_URL else "CONFIGURED")
                    + ":STALE_FAIL:" + error
                )
        if backend is None:
            dashboard_bridge_degraded_error = (
                " | ".join(degraded_errors) or "no degraded dashboard bridge candidate"
            )
standalone_url = _secret("RIZAN_STANDALONE_SNAPSHOT_URL") or DEFAULT_SNAPSHOT_URL
standalone: dict[str, Any] | None = None
standalone_error: str | None = None
backend_error = direct_backend_error if backend is None else None
# Quote overlay is always loaded when available. It never replaces ForexRizan
# as the canonical backend and never grants execution authority; it exists only
# to prevent the user-facing XAU price from freezing on an older prepared-plan
# heartbeat while a fresher FP Markets/cTrader quote is already published.
try:
    standalone = _load_standalone_bridge(standalone_url)
except Exception as exc:
    standalone_error = f"{type(exc).__name__}: {exc}"

backend_snapshot_stale = bool(
    backend is not None
    and backend_source == "GITHUB_DASHBOARD_BRIDGE_STALE"
)

with st.sidebar:
    st.title("RIZAN XAU Scanner")
    st.caption(f"RIZAN-style decision dashboard • Engine v{__version__}")

    if st.button("Refresh dashboard", width="stretch"):
        _clear_backend_snapshot_cache(include_slow=True)
        _load_dashboard_bridge.clear()
        _load_standalone_bridge.clear()
        st.rerun()
    auto_refresh_enabled = st.toggle(
        "Auto refresh monitor",
        value=True,
        help="Refresh the read-only dashboard every 60 seconds. Scanner/order runtime is independent.",
    )

    st.divider()
    st.markdown("**Runtime model**")
    st.write("ForexRizan is the canonical dashboard backend.")
    st.write("cTrader standalone is quote/diagnostic backup only; it never replaces ForexRizan.")
    st.caption(f"Build: {DASHBOARD_BUILD_ID}")

    st.divider()
    st.markdown("**Backend**")
    if backend is not None and backend_source == "SUPABASE_DIRECT":
        st.success("ForexRizan • Supabase direct")
    elif backend is not None and backend_source == "GITHUB_DASHBOARD_BRIDGE":
        st.success("ForexRizan • Dashboard Bridge")
        age = backend_bridge_meta.get("age_seconds")
        st.caption(
            "Snapshot read-only GitHub"
            + (" • age " + _fmt_number(age, 0) + " dtk" if age is not None else "")
        )
    elif backend is not None and backend_source == "GITHUB_DASHBOARD_BRIDGE_STALE":
        age = backend_bridge_meta.get("age_seconds")
        st.warning("ForexRizan • Dashboard Bridge STALE")
        st.caption(
            "Full diagnostic view tetap tersedia, tetapi admission UI dipaksa NO ORDER"
            + (" • age " + _fmt_number(age, 0) + " dtk" if age is not None else "")
        )
    elif backend_configured:
        st.error("ForexRizan backend unavailable")
    else:
        st.error("ForexRizan bridge unavailable")
    if standalone is not None:
        standalone_meta = dict(standalone.get("bridge") or {})
        standalone_age = standalone_meta.get("age_seconds")
        st.caption(
            "cTrader quote backup: "
            + ("FRESH" if bool(standalone_meta.get("fresh")) else "STALE")
            + (" • age " + _fmt_number(standalone_age, 0) + " dtk" if standalone_age is not None else "")
            + " • diagnostic only"
        )

    st.markdown("**Execution safety**")
    if backend_snapshot_stale:
        st.code("STALE MONITOR / UI NO ORDER / DEMO RUNTIME INDEPENDENT", language=None)
    elif backend is None:
        st.code("FOREXRIZAN UNAVAILABLE / UI NO ORDER / LIVE OFF", language=None)
    elif policy is not None and str(policy.ctrader.get("environment", "")).upper() == "DEMO":
        st.code("DEMO AUTO CAPABLE / LIVE OFF", language=None)
    else:
        st.code("LIVE EXECUTION NOT AUTHORIZED", language=None)


if "dashboard_auto_refresh_at" not in st.session_state:
    st.session_state["dashboard_auto_refresh_at"] = datetime.now(tz=UTC)


@st.fragment(run_every="60s")
def _dashboard_auto_refresh_tick() -> None:
    if not auto_refresh_enabled:
        return
    now = datetime.now(tz=UTC)
    last = st.session_state.get("dashboard_auto_refresh_at")
    if not isinstance(last, datetime) or (now - last).total_seconds() >= 59.5:
        st.session_state["dashboard_auto_refresh_at"] = now
        _clear_backend_snapshot_cache(include_slow=False)
        _load_dashboard_bridge.clear()
        _load_standalone_bridge.clear()
        st.rerun()


_dashboard_auto_refresh_tick()


st.title("RIZAN XAU Institutional Scanner")
st.caption(
    "RIZAN XAU decision dashboard • Normal mode uses durable ForexRizan snapshots "
    "via direct Supabase or the curated ForexRizan Dashboard Bridge. "
    "cTrader standalone is never treated as the dashboard backend. "
    f"Build: {DASHBOARD_BUILD_ID}."
)

if config_error:
    st.error(f"Configuration invalid: {config_error}")
if policy_error:
    st.error(f"Execution policy invalid: {policy_error}")
if backend_error:
    st.warning(f"Backend snapshot unavailable: {backend_error}")
elif backend_snapshot_stale:
    age = backend_bridge_meta.get("age_seconds")
    st.error(
        "DASHBOARD BRIDGE STALE • full diagnostic tetap ditampilkan agar halaman tidak "
        "berhenti, tetapi data ini tidak boleh dipakai sebagai entry baru. "
        f"Snapshot age: {_fmt_number(age, 0)} detik. Admission UI = NO ORDER sampai bridge fresh."
    )
elif backend_source == "GITHUB_DASHBOARD_BRIDGE" and direct_backend_error:
    st.caption(
        "Direct Supabase table access is unavailable in Streamlit; "
        "dashboard is using the fresh curated ForexRizan bridge instead."
    )
if backend_source == "GITHUB_DASHBOARD_BRIDGE" and not backend_configured:
    st.info(
        "Dashboard can be deployed now without backend secrets; "
        "the read-only ForexRizan Dashboard Bridge is active."
    )
if dashboard_bridge_error and backend is None:
    st.warning(f"ForexRizan Dashboard Bridge belum tersedia: {dashboard_bridge_error}")
    if dashboard_bridge_degraded_error:
        st.caption("Degraded bridge juga gagal: " + dashboard_bridge_degraded_error)
    if dashboard_bridge_attempts:
        with st.expander("Diagnostik transport ForexRizan", expanded=False):
            st.code("\n".join(dashboard_bridge_attempts), language=None)
if standalone_error:
    st.warning(f"Standalone snapshot belum tersedia: {standalone_error}")
if backend is None and standalone is None:
    st.info(
        "Dashboard can be deployed now. Restricted Mode sedang menunggu snapshot "
        "RIZAN pertama dari GitHub Actions. Tidak diperlukan credential cTrader di Streamlit."
    )

mode = "—" if cfg is None else str(cfg.risk.get("mode", "—"))
pairs = 0 if cfg is None else len(cfg.pairs)
fast_setup = "—"
execution_watch = "—"
if policy is not None:
    fast_setup = f"{policy.scheduler['fast_setup_seconds']:.0f}s"
    execution_watch = f"{policy.scheduler['execution_watch_seconds'] * 1000:.0f} ms"

runtime_mode = mode
if backend is not None:
    _summary_control = dict(backend.get("control") or {})
    _summary_execution_mode = str(
        _summary_control.get("execution_mode") or ""
    ).upper()
    _summary_demo = bool(
        policy is not None
        and str(policy.ctrader.get("environment", "")).upper() == "DEMO"
        and bool(policy.ctrader.get("require_demo", False))
    )
    if _summary_demo:
        runtime_mode = (
            f"DEMO {_summary_execution_mode}"
            if _summary_execution_mode
            else "DEMO"
        )
    elif _summary_execution_mode:
        runtime_mode = _summary_execution_mode

backend_label = (
    "SUPABASE"
    if backend is not None and backend_source == "SUPABASE_DIRECT"
    else "RIZAN BRIDGE"
    if backend is not None and backend_source == "GITHUB_DASHBOARD_BRIDGE"
    else "RIZAN BRIDGE STALE"
    if backend is not None and backend_source == "GITHUB_DASHBOARD_BRIDGE_STALE"
    else "FOREXRIZAN ERROR"
    if backend is None
    else "FOREXRIZAN"
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Runtime Mode", runtime_mode)
m2.metric("Pair aktif", "XAUUSD")
m3.metric("Top-5 Scan Cadence", fast_setup)
m4.metric("Execution Watch", execution_watch)
m5.metric("Dashboard Backend", backend_label)
if backend is not None and backend_source.startswith("GITHUB_DASHBOARD_BRIDGE"):
    st.caption(
        "ForexRizan transport: "
        + str(backend_bridge_meta.get("source_url_kind") or "UNKNOWN")
        + " • snapshot age "
        + _fmt_number(backend_bridge_meta.get("age_seconds"), 0)
        + " detik"
    )

if backend is None and standalone is not None:
    standalone_quote = dict(standalone.get("quote") or {})
    standalone_meta = dict(standalone.get("bridge") or {})
    st.warning(
        "ForexRizan belum tersedia. cTrader standalone hanya dipakai sebagai quote backup "
        "untuk diagnostik; supply/demand, V240, admission, SL/TP, dan order tidak diambil "
        "dari jalur standalone."
    )
    with st.expander("cTrader quote backup (diagnostic only)", expanded=False):
        st.write(
            {
                "mid": standalone_quote.get("mid"),
                "snapshot_age_seconds": standalone_meta.get("age_seconds"),
                "fresh": standalone_meta.get("fresh"),
                "execution_authority": False,
            }
        )

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
    if backend_snapshot_stale:
        st.warning(
            "Status execution-control pada dashboard bersifat historis karena transport snapshot stale. "
            "Runtime DEMO broker tetap independen; jangan membuat keputusan entry dari panel ini sampai fresh."
        )
    elif demo_locked and mode_now == "AUTO" and orders_now and not emergency_now:
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
    st.subheader("Dashboard Keputusan XAUUSD")
    st.caption(
        "**Prakiraan XAUUSD & Zona Reaksi (XAUUSD Forecast & Reaction Zone)** • "
        "Tampilan utama disusun untuk keputusan cepat: **Ringkasan → Zona/Depth → "
        "Eksekusi → Posisi**. Panel riset, evidence, validasi, dan histori tetap "
        "tersedia di bagian detail tetapi ditutup secara default. "
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
- **Freshness / Kesegaran:** umur dan riwayat sentuhan zone. Pada H4/H1 ini adalah konteks lifecycle/ranking, bukan syarat first-touch; zona retest tetap aktif sampai struktur invalid. M15 multi-test juga tidak langsung dibuang, tetapi wajib pressure transition + fresh M5 confirmation sebelum DEMO execution.
"""
        )

    heartbeats = [] if backend is None else backend.get("heartbeats", [])
    prepared_hb = (
        _latest_heartbeat(heartbeats, "ctrader_demo_xau_rizan_prepared_plan_producer")
        or _latest_heartbeat(heartbeats, "ctrader_demo_xau_afic_prepared_plan_producer")
    )
    fast_handoff_hb = (
        _latest_heartbeat(heartbeats, "ctrader_demo_xau_rizan_fast_handoff")
        or _latest_heartbeat(heartbeats, "ctrader_demo_xau_afic_fast_handoff")
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
    v214_lifecycle_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v214_pocket_lifecycle"
    )
    v216_calibration_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v216_lifecycle_calibration"
    )
    v222_pocket_quality_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v222_m5_pocket_quality"
    )
    v223_cluster_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v223_m5_pocket_cluster_selector"
    )
    v224_primary_calibration_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v224_primary_pocket_prospective"
    )
    v226_depth_map_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v226_rizan_depth_map"
    )
    v227_depth_calibration_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v227_depth_map_prospective"
    )
    v229_depth_execution_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v229_depth_execution"
    )
    v282_lifecycle_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_prepared_plan_lifecycle"
    )
    v229_child_executor_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v229_child_executor"
    )
    v296_decision_center_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_decision_center_v296"
    )
    v297_meta_sampler_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_meta_research_sampler_v297"
    )
    v318_structural_probe_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_structural_research_probe_v318"
    )
    v320_micro_entry_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_micro_entry_refinement_v320"
    )
    v321_micro_entry_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_micro_entry_dual_cycle_v321"
    )
    v322_micro_handoff_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_micro_handoff_v322"
    )
    v217_direction_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v217_direction_probability"
    )
    v220_calibration_hb = _latest_heartbeat(
        heartbeats, "ctrader_demo_xau_v220_direction_prospective_calibration"
    )
    forecast_rows = [] if backend is None else backend.get("afic_forecast_states", [])
    prepared_rows = [] if backend is None else backend.get("afic_prepared_plans", [])
    geometry_rows = [] if backend is None else backend.get("afic_execution_geometry", [])
    broker_timeline_events = [] if backend is None else list(backend.get("xau_execution_events", []) or [])
    geometry_events = [] if backend is None else list(backend.get("xau_geometry_events", []) or [])
    execution_events = sorted(
        [*geometry_events, *broker_timeline_events],
        key=lambda row: str(dict(row).get("observed_at") or ""),
        reverse=True,
    )
    lifecycle_rows = [] if backend is None else backend.get("xau_prepared_plan_lifecycle", [])
    dedicated_xau_rows = [] if backend is None else backend.get("xau_signals", [])
    xau_technical_signal_rows = [
        dict(row) for row in dedicated_xau_rows
        if not str(row.get("setup_type") or "").upper().startswith(("AFIC_", "RIZAN_"))
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
            str(event_row.get("code") or "") in {
                "XAU_RIZAN_PATH_EXECUTION_V1",
                "XAU_AFIC_PATH_EXECUTION_V1",
            }
            or str(event_payload.get("strategy_id") or "") in {
                "XAU_RIZAN_PATH_EXECUTION_V1",
                "XAU_AFIC_PATH_EXECUTION_V1",
            }
            or (
                str(event_payload.get("symbol") or "").upper() == "XAUUSD"
                and str(event_row.get("signal_key") or "") == str(hb_details.get("signal_id") or "")
            )
        ):
            latest_exec_row = event_row
            latest_exec_event = str(event_row.get("event_type") or "")
            break
    next_action, next_reason = _rizan_next_action(
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
    if not afic_sd_context and supply_demand_hb is not None:
        # V182 is the canonical source for structural/path context. Prepared and
        # forecast hot payloads intentionally no longer duplicate the same large
        # structure JSON every minute.
        _sd_seed_details = dict(supply_demand_hb.get("details") or {})
        _sd_seed_eval = dict(_sd_seed_details.get("evaluation") or {})
        _sd_seed_path_map = dict(_sd_seed_eval.get("path_map") or {})
        afic_sd_context = {
            "first_leg_path": dict(_sd_seed_path_map.get("active_path") or {}),
            "active_reaction_path": dict(_sd_seed_path_map.get("active_path") or {}),
            "first_leg_m5_path_projection": dict(
                _sd_seed_eval.get("m5_path_projection")
                or _sd_seed_path_map.get("m5_path_projection")
                or {}
            ),
            "m5_path_projection": dict(
                _sd_seed_eval.get("m5_path_projection")
                or _sd_seed_path_map.get("m5_path_projection")
                or {}
            ),
            "first_leg_micro_refinement": dict(
                _sd_seed_eval.get("micro_refinement")
                or _sd_seed_path_map.get("micro_refinement")
                or {}
            ),
            "micro_refinement": dict(
                _sd_seed_eval.get("micro_refinement")
                or _sd_seed_path_map.get("micro_refinement")
                or {}
            ),
        }

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
    dc_parent_rescue = dict(dc_micro.get("parent_reversal_rescue") or {})
    dc_parent_rescue_active = bool(dc_parent_rescue.get("active"))
    dc_parent_source_zone = dict(dc_projection_current.get("parent_source_zone") or {})
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

    if dc_projection_current:
        # The explicit V196 pocket_state is authoritative. Do not resurrect a
        # prior reuse/refined pocket when the current projection says CANDIDATE
        # or NO_M5_POCKET_YET.
        dc_initial_candidate = (
            dict(dc_current_projected_pocket)
            if dc_current_pocket_state == "CANDIDATE_M5_POCKET"
            else {}
        )
        dc_refined_display = (
            dict(dc_current_projected_pocket)
            if dc_current_pocket_state == "REFINED_M5_POCKET"
            else {}
        )
    else:
        dc_initial_candidate = dict(
            dc_micro.get("candidate_entry_pocket")
            or dc_current_reuse.get("active_candidate_micro_pocket")
            or dc_candidate
            or {}
        )
        dc_refined_display = dict(
            dc_micro.get("refined_entry_pocket")
            or dc_current_reuse.get("active_refined_micro_pocket")
            or dc_refined
            or {}
        )

    if dc_projection_next:
        dc_next_initial_candidate = (
            dict(dc_next_projected_pocket)
            if dc_next_pocket_state == "CANDIDATE_M5_POCKET"
            else {}
        )
        dc_next_refined_display = (
            dict(dc_next_projected_pocket)
            if dc_next_pocket_state == "REFINED_M5_POCKET"
            else {}
        )
    else:
        dc_next_initial_candidate = dict(
            dc_next_micro.get("candidate_entry_pocket")
            or dc_next_reuse.get("active_candidate_micro_pocket")
            or dc_next_candidate
            or {}
        )
        dc_next_refined_display = dict(
            dc_next_micro.get("refined_entry_pocket")
            or dc_next_reuse.get("active_refined_micro_pocket")
            or dc_next_refined
            or {}
        )

    # Migration-era snapshots may contain a next-leg pocket created from an old
    # touch of the future opposing zone. Suppress it in the UI unless its evidence
    # occurred after the current leg activation. V196 now enforces the same rule
    # at source, this is a defensive display guard for older cached snapshots.
    dc_current_source_lifecycle = dict(
        dict(dc_projection_current.get("source_zone") or dc_source or {}).get("lifecycle")
        or {}
    )
    dc_current_leg_activation = _parse_timestamp(
        dc_micro.get("first_eligible_touch_at")
        or dc_current_source_lifecycle.get("first_touch_at")
    )
    dc_next_evidence_at = _parse_timestamp(
        dc_next_micro.get("first_eligible_touch_at")
        or dict(dc_next_micro.get("sweep") or {}).get("at")
        or dc_next_refined_display.get("origin_at")
        or dc_next_initial_candidate.get("origin_at")
    )
    dc_next_pocket_causally_fresh = bool(
        dc_current_leg_activation is not None
        and dc_next_evidence_at is not None
        and dc_next_evidence_at >= dc_current_leg_activation
    )
    if dc_current_leg_activation is not None and not dc_next_pocket_causally_fresh:
        dc_next_initial_candidate = {}
        dc_next_refined_display = {}
        if dc_next_pocket_state in {"CANDIDATE_M5_POCKET", "REFINED_M5_POCKET"}:
            dc_next_pocket_state = "NO_M5_POCKET_YET"

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
    # Select the freshest ForexRizan backend price first. The prepared-plan
    # heartbeat can legitimately lag when there is NO_MAP/WAIT, so it must not
    # permanently dominate newer V182/V226 observations.
    dc_price_candidates: list[tuple[datetime, float, str]] = []

    def _add_dc_price_candidate(
        value: Any,
        observed_at: Any,
        source: str,
    ) -> None:
        px = _chart_price(value)
        ts = _parse_timestamp(observed_at)
        if px is None or ts is None:
            return
        dc_price_candidates.append((ts, float(px), source))

    _add_dc_price_candidate(
        live_price,
        None if prepared_hb is None else prepared_hb.get("observed_at"),
        "PREPARED_LIVE_PRICE",
    )
    _add_dc_price_candidate(
        dc_sd_eval.get("last_closed_m15_price"),
        dc_sd_eval.get("as_of")
        or (None if supply_demand_hb is None else supply_demand_hb.get("observed_at")),
        "V182_LAST_CLOSED_M15",
    )
    _v226_price_details = (
        {}
        if v226_depth_map_hb is None
        else dict(v226_depth_map_hb.get("details") or {})
    )
    _v226_price_eval = dict(_v226_price_details.get("evaluation") or {})
    _add_dc_price_candidate(
        _v226_price_eval.get("price_reference"),
        _v226_price_eval.get("as_of")
        or (None if v226_depth_map_hb is None else v226_depth_map_hb.get("observed_at")),
        "V226_PRICE_REFERENCE",
    )

    dc_backend_reference_price = None
    dc_backend_price_source = "UNAVAILABLE"
    dc_backend_price_observed_at: datetime | None = None
    if dc_price_candidates:
        dc_price_candidates.sort(key=lambda item: item[0], reverse=True)
        (
            dc_backend_price_observed_at,
            dc_backend_reference_price,
            dc_backend_price_source,
        ) = dc_price_candidates[0]

    # Fresh standalone quote is from the same FP Markets/cTrader feed but remains
    # diagnostic-only. It may update the displayed/visual price and geometry
    # monitor, but it does not replace ForexRizan admission or broker authority.
    dc_quote_overlay = {} if standalone is None else dict(standalone.get("quote") or {})
    dc_quote_bridge = {} if standalone is None else dict(standalone.get("bridge") or {})
    dc_quote_mid = _chart_price(dc_quote_overlay.get("mid"))
    dc_quote_timestamp = _parse_timestamp(dc_quote_overlay.get("timestamp"))
    dc_quote_age = (
        None
        if dc_quote_timestamp is None
        else max(0.0, (datetime.now(tz=UTC) - dc_quote_timestamp).total_seconds())
    )
    dc_quote_fresh = bool(
        dc_quote_mid is not None
        and bool(dc_quote_bridge.get("fresh"))
        and dc_quote_age is not None
        and dc_quote_age <= 180.0
    )

    dc_reference_price = (
        float(dc_quote_mid)
        if dc_quote_fresh
        else dc_backend_reference_price
    )
    dc_reference_price_source = (
        "FP_MARKETS_CTRADER_QUOTE"
        if dc_quote_fresh
        else dc_backend_price_source
    )
    dc_reference_price_age = (
        dc_quote_age
        if dc_quote_fresh
        else (
            None
            if dc_backend_price_observed_at is None
            else max(
                0.0,
                (datetime.now(tz=UTC) - dc_backend_price_observed_at).total_seconds(),
            )
        )
    )

    # Keep legacy display panels aligned with the same current-price truth.
    if dc_reference_price is not None:
        live_price = dc_reference_price

    def _m5_pocket_limit_side_valid(
        direction: str,
        pocket: dict[str, Any],
        price: Any,
    ) -> bool:
        low = _chart_price(dict(pocket or {}).get("low"))
        high = _chart_price(dict(pocket or {}).get("high"))
        px = _chart_price(price)
        side = str(direction or "").upper()
        if low is None or high is None or px is None or high <= low:
            return False
        # The DEMO child executor uses limit-side semantics for M5 retest entries:
        # BUY entry must be below ask/current price; SELL entry must be above bid/current price.
        if side == "LONG":
            return bool(high < px)
        if side == "SHORT":
            return bool(low > px)
        return False

    dc_current_refined_limit_side_valid = bool(
        dc_current_pocket_state == "REFINED_M5_POCKET"
        and dc_current_projected_pocket
        and _m5_pocket_limit_side_valid(
            dc_current_leg_direction,
            dc_current_projected_pocket,
            dc_reference_price,
        )
    )
    dc_current_refined_historical = bool(
        dc_current_pocket_state == "REFINED_M5_POCKET"
        and dc_current_projected_pocket
        and not dc_current_refined_limit_side_valid
    )

    dc_terminal_low = _chart_price(dc_current_leg_terminal.get("low"))
    dc_terminal_high = _chart_price(dc_current_leg_terminal.get("high"))
    dc_price_float = _chart_price(dc_reference_price)
    dc_inside_current_terminal = bool(
        dc_price_float is not None
        and dc_terminal_low is not None
        and dc_terminal_high is not None
        and dc_terminal_low <= dc_price_float <= dc_terminal_high
    )
    dc_reaction_price = _chart_price(dc_current_leg_target.get("price"))
    dc_current_reaction_reached = bool(
        dc_price_float is not None
        and dc_reaction_price is not None
        and (
            (
                dc_current_leg_direction == "LONG"
                and dc_price_float >= dc_reaction_price
            )
            or (
                dc_current_leg_direction == "SHORT"
                and dc_price_float <= dc_reaction_price
            )
        )
    )
    dc_current_leg_completed = bool(
        dc_inside_current_terminal or dc_current_reaction_reached
    )
    if dc_current_leg_completed and dc_current_pocket_state == "REFINED_M5_POCKET":
        # A refined pocket belonging to a completed leg is historical evidence,
        # not a fresh re-entry invitation. Timing focus moves to the opposing leg.
        dc_current_refined_limit_side_valid = False
        dc_current_refined_historical = True

    dc_next_leg_watch_text = (
        f"{dc_next_leg_direction} • "
        + (
            "Refined "
            if dc_next_pocket_state == "REFINED_M5_POCKET"
            else "Candidate "
            if dc_next_pocket_state == "CANDIDATE_M5_POCKET"
            else "Watch "
        )
        + (
            f"{_fmt_price(dc_next_projected_pocket.get('low'))}–"
            f"{_fmt_price(dc_next_projected_pocket.get('high'))}"
            if dc_next_projected_pocket
            else (
                f"{_fmt_price(dc_next_leg_source.get('low'))}–"
                f"{_fmt_price(dc_next_leg_source.get('high'))}"
                if dc_next_leg_source
                else "Belum ada"
            )
        )
        if dc_next_leg_direction in {"LONG", "SHORT"}
        else "Belum ada"
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

    st.markdown(
        '<div class="rizan-kicker">1 • RINGKASAN KEPUTUSAN</div>'
        '<div class="rizan-title">Pusat Keputusan XAUUSD</div>'
        '<div class="rizan-note">Satu layar untuk bias, leg aktif, status setup, dan prioritas tindakan.</div>',
        unsafe_allow_html=True,
    )

    v296_meta_details = (
        {}
        if v296_decision_center_hb is None
        else dict(v296_decision_center_hb.get("details") or {})
    )
    v296_meta_decision = dict(v296_meta_details.get("decision") or {})
    v296_meta_age = (
        None
        if v296_decision_center_hb is None
        else _age_seconds(v296_decision_center_hb.get("observed_at"))
    )
    v296_meta_fresh = bool(
        v296_meta_decision
        and bool(v296_decision_center_hb.get("healthy"))
        and v296_meta_age is not None
        and v296_meta_age <= 180.0
    )
    v296_geometry = dict(v296_meta_decision.get("geometry") or {})
    v296_reference_geometry = dict(
        v296_meta_decision.get("reference_geometry") or {}
    )
    v296_display_geometry = v296_geometry or v296_reference_geometry
    v296_geometry_reference_only = bool(
        not v296_geometry and v296_reference_geometry
    )
    v296_direction = str(
        v296_meta_decision.get("consensus_direction") or "WAIT"
    ).upper()
    v296_dominant_direction = str(
        v296_meta_decision.get("dominant_direction")
        or v296_direction
        or "WAIT"
    ).upper()
    v296_direction_display = (
        f"{v296_direction} • bias {v296_dominant_direction}"
        if v296_direction == "WAIT"
        and v296_dominant_direction in {"LONG", "SHORT"}
        else v296_direction
    )
    v296_action = str(v296_meta_decision.get("action") or "WAIT")
    v296_freshness_display = (
        "LIVE"
        if v296_meta_fresh
        else "STALE • LAST-KNOWN"
        if v296_meta_decision
        else "BELUM ADA SNAPSHOT"
    )
    v296_confidence = float(v296_meta_decision.get("confidence") or 0.0)
    v296_agreement = float(v296_meta_decision.get("agreement") or 0.0)
    v296_coverage = float(v296_meta_decision.get("coverage") or 0.0)
    v296_evidence_coverage = float(
        v296_meta_decision.get("evidence_coverage") or 0.0
    )
    v296_action_display = {
        "DEMO_ORDER_ELIGIBLE": "DEMO ORDER ELIGIBLE",
        "DEMO_RESEARCH_PROBE_ELIGIBLE": "DEMO RESEARCH PROBE",
        "DEMO_CONFLICT_RESEARCH_PROBE_ELIGIBLE": "DEMO CONFLICT RESEARCH PROBE",
        "PREPARE_WAIT_CONFIRMATION": "PREPARE • WAIT CONFIRMATION",
        "WAIT_ENGINE_CONFLICT": "WAIT • ENGINE CONFLICT",
        "WAIT_NO_CANONICAL_GEOMETRY": "WAIT • NO CANONICAL GEOMETRY",
        "DATA_STALE_WAIT": "WAIT • META DATA STALE",
    }.get(v296_action, _rizan_display(v296_action))
    if not v296_meta_fresh:
        v296_action_display += " • " + v296_freshness_display

    v297_sampler_details = (
        {}
        if v297_meta_sampler_hb is None
        else dict(v297_meta_sampler_hb.get("details") or {})
    )
    v297_sampler_state = str(v297_sampler_details.get("state") or "WAIT")
    v297_sampler_age = (
        None
        if v297_meta_sampler_hb is None
        else _age_seconds(v297_meta_sampler_hb.get("observed_at"))
    )
    v297_sampler_fresh = bool(
        v297_meta_sampler_hb is not None
        and bool(v297_meta_sampler_hb.get("healthy"))
        and v297_sampler_age is not None
        and v297_sampler_age <= 180.0
    )
    if not v297_sampler_fresh:
        v297_sampler_state = (
            f"STALE • LAST-KNOWN {v297_sampler_state}"
            if v297_sampler_details
            else "BELUM ADA SNAPSHOT"
        )

    v297_meta_calibration = dict(
        v296_meta_decision.get("meta_research_calibration") or {}
    )
    v297_executed_cal = dict(
        v297_meta_calibration.get("executed_demo") or {}
    )
    v297_executed_n = int(v297_executed_cal.get("decisive") or 0)
    v297_win_rate = v297_executed_cal.get("win_rate")
    v297_wilson = v297_executed_cal.get("wilson_lower_95")

    with st.container(border=True):
        st.markdown("### Kesimpulan Final Ensemble V296")
        meta1, meta2, meta3, meta4 = st.columns(4)
        meta1.metric("Arah final", v296_direction_display)
        meta2.metric("Action", v296_action_display)
        meta3.metric(
            "Confidence ensemble",
            f"{v296_confidence:.1f}%" if v296_meta_decision else "BELUM ADA DATA",
        )
        meta4.metric(
            "Agreement engine",
            f"{v296_agreement * 100.0:.1f}%" if v296_meta_decision else "BELUM ADA DATA",
        )
        st.caption(
            "Confidence ensemble bukan winrate. Bobot engine memprioritaskan "
            "hasil DEMO executed bila sample cukup; sebelum itu memakai geometry prior "
            "dari forward/outcome ledger dan engine dengan sample kecil dibatasi. "
            f"Coverage engine={v296_coverage * 100.0:.1f}% • "
            f"evidence calibrated={v296_evidence_coverage * 100.0:.1f}% • "
            f"freshness={v296_freshness_display} • "
            + (
                f"age={v296_meta_age:.0f}s"
                if v296_meta_age is not None
                else "age=—"
            )
            + "."
        )

        # V317: Decision Center must remain informative even when the execution
        # layer correctly returns WAIT_NO_CANONICAL_GEOMETRY. Structural route
        # and liquidity-sweep context are informational only; they never invent
        # an entry or grant broker authority.
        v296_style_path = dict(
            v296_meta_decision.get("rizan_style_path_engine") or {}
        )
        v296_liquidity_map = dict(
            v296_meta_decision.get("liquidity_sweep_map_v317") or {}
        )
        v296_decision_zone = dict(
            v296_style_path.get("next_decision_zone")
            or v296_liquidity_map.get("decision_zone")
            or {}
        )
        v296_sweep_band = dict(v296_liquidity_map.get("sweep_band") or {})
        v296_acceptance = dict(v296_style_path.get("acceptance_branch") or {})
        v296_rejection = dict(v296_style_path.get("rejection_branch") or {})
        v296_next_destination = dict(
            v296_acceptance.get("next_destination_zone") or {}
        )
        v296_structural_direction = str(
            v296_style_path.get("active_direction")
            or v296_dominant_direction
            or "WAIT"
        ).upper()
        v296_price_now = v296_style_path.get("price_now")

        st.markdown("**Peta operasional saat ini — tetap terisi walau action WAIT**")
        op1, op2, op3, op4 = st.columns(4)
        op1.metric("Harga referensi", _fmt_price(v296_price_now))
        op2.metric("Bias struktural", v296_structural_direction)
        op3.metric(
            "Decision zone",
            (
                f"{_fmt_price(v296_decision_zone.get('low'))}–"
                f"{_fmt_price(v296_decision_zone.get('high'))}"
                if v296_decision_zone else "BELUM ADA"
            ),
        )
        op4.metric(
            "Liquidity sweep risk",
            str(v296_liquidity_map.get("risk_grade") or "BELUM ADA"),
        )

        op5, op6, op7, op8 = st.columns(4)
        op5.metric(
            "Sweep danger band",
            (
                f"{_fmt_price(v296_sweep_band.get('low'))}–"
                f"{_fmt_price(v296_sweep_band.get('high'))}"
                if v296_sweep_band else "BELUM ADA"
            ),
        )
        op6.metric(
            "Next destination",
            (
                f"{_fmt_price(v296_next_destination.get('low'))}–"
                f"{_fmt_price(v296_next_destination.get('high'))}"
                if v296_next_destination else "BELUM ADA"
            ),
        )
        op7.metric(
            "Branch",
            str(v296_style_path.get("branch_preference") or "WAIT_DECISION"),
        )
        op8.metric(
            "Canonical entry",
            "ADA" if v296_geometry else "BELUM ADA • WAIT",
        )

        if v296_liquidity_map.get("first_touch_warning"):
            st.warning(
                "V317 LIQUIDITY SWEEP WARNING • decision zone bukan otomatis titik reversal. "
                "Ada parent/liquidity extension di luar batas zona sempit. "
                "Tunggu sweep exhaustion + M5/M15 reclaim/MSS/displacement sebelum "
                "menganggap reversal selesai. Danger band="
                f"{_fmt_price(v296_sweep_band.get('low'))}–"
                f"{_fmt_price(v296_sweep_band.get('high'))}."
            )
        elif v296_liquidity_map:
            st.info(
                "V317 liquidity map aktif • sweep side="
                + str(v296_liquidity_map.get("sweep_side") or "—")
                + " • confluence="
                + str(v296_liquidity_map.get("liquidity_confluence_count") or 0)
                + " • context only / bukan izin order."
            )

        v296_liquidity_levels = list(
            v296_liquidity_map.get("liquidity_levels") or []
        )
        if v296_liquidity_levels:
            st.caption(
                "Liquidity sebelum reversal: "
                + " • ".join(
                    f"{str(dict(row).get('source') or 'LEVEL')} "
                    f"{_fmt_price(dict(row).get('price'))}"
                    for row in v296_liquidity_levels[:6]
                )
                + "."
            )
        if v296_decision_zone and not v296_geometry:
            st.caption(
                "Execution center sedang WAIT karena canonical geometry belum lolos. "
                "Namun structural map tetap tersedia: zone="
                f"{_fmt_price(v296_decision_zone.get('low'))}–"
                f"{_fmt_price(v296_decision_zone.get('high'))} • "
                "rejection rule="
                + str(v296_rejection.get("condition") or "—")
                + " • acceptance rule="
                + str(v296_acceptance.get("condition") or "—")
                + "."
            )

        rs1, rs2, rs3, rs4 = st.columns(4)
        rs1.metric("V297 Research Sampler", _rizan_display(v297_sampler_state))
        rs2.metric(
            "Executed sample",
            f"{v297_executed_n} • collecting"
            if v297_executed_n == 0
            else str(v297_executed_n),
        )
        rs3.metric(
            "Executed TP/Win rate",
            "BELUM ADA EXECUTED SAMPLE"
            if v297_win_rate is None
            else f"{float(v297_win_rate) * 100.0:.1f}%",
        )
        rs4.metric(
            "Wilson lower 95%",
            "MENUNGGU SAMPLE"
            if v297_wilson is None
            else f"{float(v297_wilson) * 100.0:.1f}%",
        )
        st.caption(
            "V297 = order DEMO 0.01 untuk riset ensemble, maksimal satu pending/position "
            "meta pada satu waktu dan satu sample per decision signature. "
            "Statistik ini berasal dari outcome ledger dan tidak dicampur dengan "
            "confidence internal engine."
        )
        v297_reason = str(v297_sampler_details.get("reason") or "—")
        v297_next = str(v297_sampler_details.get("next_required") or "—")
        v297_bias = str(
            v297_sampler_details.get("dominant_direction")
            or v296_dominant_direction
            or "WAIT"
        ).upper()
        st.caption(
            f"Sampler reason={v297_reason} • bias={v297_bias} • "
            f"next required={v297_next}."
        )
        if str(v297_sampler_state).upper() == "ORDER_ACCEPTED":
            st.success(
                "Meta research order accepted • entry="
                + _fmt_price(v297_sampler_details.get("entry"))
                + " • SL="
                + _fmt_price(v297_sampler_details.get("sl"))
                + " • TP="
                + _fmt_price(v297_sampler_details.get("tp"))
                + " • RR="
                + (
                    f"{float(v297_sampler_details.get('rr')):.2f}R"
                    if v297_sampler_details.get("rr") is not None
                    else "—"
                )
            )

        v296_hard_blocks = list(v296_meta_decision.get("hard_blocks") or [])
        v296_geometry_actionable = bool(
            v296_display_geometry
            and not v296_geometry_reference_only
            and v296_meta_fresh
            and not backend_snapshot_stale
            and v296_action == "DEMO_ORDER_ELIGIBLE"
            and not v296_hard_blocks
        )

        if v296_display_geometry:
            entry_low = v296_display_geometry.get("entry_low")
            entry_high = v296_display_geometry.get("entry_high")
            geometry_age = _age_seconds(v296_display_geometry.get("observed_at"))
            geometry_reference_only_ui = not v296_geometry_actionable
            entry_label = (
                "Entry referensi terakhir — JANGAN ENTRY"
                if geometry_reference_only_ui
                else "CURRENT PLAN • Entry canonical aktif"
            )

            raw_tp1 = v296_display_geometry.get("tp1")
            raw_tp2 = v296_display_geometry.get("tp2")
            duplicate_targets = False
            try:
                duplicate_targets = (
                    raw_tp1 is not None
                    and raw_tp2 is not None
                    and abs(float(raw_tp1) - float(raw_tp2)) <= 0.05
                )
            except (TypeError, ValueError):
                duplicate_targets = False

            path_checkpoint = dc_current_leg_target.get("price")
            geo1, geo2, geo3, geo4 = st.columns(4)
            geo1.metric(
                entry_label,
                f"{_fmt_price(entry_low)}–{_fmt_price(entry_high)}",
            )
            geo2.metric(
                "SL canonical" if v296_geometry_actionable else "SL referensi",
                _fmt_price(v296_display_geometry.get("sl")),
            )
            if duplicate_targets:
                geo3.metric(
                    "Checkpoint path • BUKAN TP order",
                    _fmt_price(path_checkpoint),
                )
                geo4.metric(
                    "TP terminal geometry",
                    _fmt_price(raw_tp2),
                )
            else:
                geo3.metric("TP1 geometry", _fmt_price(raw_tp1))
                geo4.metric("TP2 / terminal", _fmt_price(raw_tp2))

            if geometry_reference_only_ui:
                st.warning(
                    "Geometry ini hanya LAST-KNOWN/REFERENCE. Jangan membuka entry baru dari angka ini "
                    "sampai bridge + Decision Center fresh, action=DEMO_ORDER_ELIGIBLE, dan hard block kosong."
                )
            else:
                st.success(
                    "CURRENT PLAN canonical aktif. NEXT LEG pada panel/chart di bawah tetap skenario berikutnya, "
                    "bukan entry tambahan saat ini."
                )

            st.caption(
                "Geometry dipilih utuh dari **"
                + str(v296_display_geometry.get("engine") or "—")
                + "** • signal="
                + str(v296_display_geometry.get("signal_id") or "—")
                + " • state="
                + str(v296_display_geometry.get("state") or "—")
                + " • RR terminal="
                + (
                    f"{float(v296_display_geometry.get('rr2')):.2f}R"
                    if v296_display_geometry.get("rr2") is not None
                    else "—"
                )
                + (
                    " • **REFERENCE ONLY / BUKAN IZIN ORDER**"
                    if geometry_reference_only_ui
                    else " • **CURRENT PLAN / canonical aligned**"
                )
                + (
                    " • TP1=TP2 pada raw geometry; duplikasi disembunyikan dan checkpoint path ditampilkan terpisah."
                    if duplicate_targets
                    else ""
                )
                + (
                    f" • geometry age={geometry_age:.0f}s"
                    if geometry_age is not None
                    else " • geometry age=unknown"
                )
                + ". Entry/SL/TP antar-engine tidak pernah dirata-ratakan."
            )
        else:
            st.info(
                "Belum ada geometry utuh dari engine. Dashboard tetap menampilkan "
                "arah, action, votes, gates, dan freshness; entry/SL/TP tidak diisi "
                "dengan angka buatan."
            )

        if v296_hard_blocks:
            st.error(
                "Hard block: "
                + ", ".join(
                    f"{str(dict(row).get('name') or 'GATE')}="
                    f"{str(dict(row).get('state') or dict(row).get('reason') or 'BLOCK')}"
                    for row in v296_hard_blocks
                )
            )

        with st.expander("Lihat keputusan & kalibrasi tiap engine", expanded=False):
            vote_rows = []
            for raw_vote in list(v296_meta_decision.get("votes") or []):
                vote = dict(raw_vote or {})
                cal = dict(vote.get("calibration") or {})
                vote_rows.append(
                    {
                        "Engine": vote.get("engine"),
                        "Role": vote.get("role"),
                        "Keputusan": vote.get("direction"),
                        "Weight efektif": round(float(vote.get("effective_weight") or 0.0), 3),
                        "Sample decisive": int(cal.get("decisive") or 0),
                        "TP1/Win rate": (
                            None
                            if cal.get("win_rate") is None
                            else round(float(cal.get("win_rate")) * 100.0, 1)
                        ),
                        "Wilson lower 95%": (
                            None
                            if cal.get("wilson_lower_95") is None
                            else round(float(cal.get("wilson_lower_95")) * 100.0, 1)
                        ),
                        "Basis": cal.get("basis"),
                        "Executed n": int(cal.get("executed_decisive") or 0),
                        "Geometry n": int(cal.get("geometry_decisive") or cal.get("decisive") or 0),
                        "Kalibrasi": cal.get("state"),
                        "Reason": vote.get("reason"),
                    }
                )
            if vote_rows:
                st.dataframe(
                    pd.DataFrame(vote_rows),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.caption("Belum ada vote engine V296.")

            support_rows = [
                {
                    "Engine/Gate": dict(row).get("engine"),
                    "Role": dict(row).get("role"),
                    "Decision": dict(row).get("decision"),
                    "State": dict(row).get("state"),
                    "Detail": dict(row).get("detail"),
                }
                for row in list(v296_meta_decision.get("support_evidence") or [])
            ]
            if support_rows:
                st.markdown("**Evidence / gate non-voting**")
                st.dataframe(
                    pd.DataFrame(support_rows),
                    width="stretch",
                    hide_index=True,
                )

    dc_h4_text = (
        f"{_fmt_price(dc_h4_parent.get('low'))}–{_fmt_price(dc_h4_parent.get('high'))}"
        if dc_h4_parent else "—"
    )
    dc_d1_text = (
        f"{_fmt_price(dc_d1_parent.get('low'))}–{_fmt_price(dc_d1_parent.get('high'))}"
        if dc_d1_parent else "—"
    )

    v217_details = (
        {} if v217_direction_hb is None else dict(v217_direction_hb.get("details") or {})
    )
    v217_eval = dict(v217_details.get("evaluation") or {})
    v217_strategic = dict(v217_eval.get("strategic_htf") or {})
    v217_tactical = dict(v217_eval.get("tactical_first_leg") or {})
    v217_next = dict(v217_eval.get("opposing_next_leg") or {})
    v217_relationship = dict(v217_eval.get("relationship") or {})
    v217_htf_context = dict(v217_strategic.get("htf_context") or {})

    v220_details = (
        {} if v220_calibration_hb is None else dict(v220_calibration_hb.get("details") or {})
    )
    v220_summary = dict(v220_details.get("summary") or {})

    dc_htf_context_bias = str(
        v217_htf_context.get("strategic_bias")
        or dc_strategic_bias
        or "NEUTRAL"
    ).upper()
    dc_current_leg_label = (
        dc_current_leg_direction
        if dc_current_leg_direction in {"LONG", "SHORT"}
        else "WAIT"
    )
    dc_leg_relation = (
        "SEARAH HTF"
        if dc_current_leg_label == dc_htf_context_bias
        else "COUNTERTREND / RETRACE"
        if dc_current_leg_label in {"LONG", "SHORT"}
        and dc_htf_context_bias in {"LONG", "SHORT"}
        else "BELUM TERKLASIFIKASI"
    )
    dc_setup_summary = (
        "MANAGE POSITION"
        if dc_position_mode
        else f"TERMINAL ZONE • NEXT {dc_next_leg_direction} WATCH"
        if dc_inside_current_terminal and dc_next_leg_direction in {"LONG", "SHORT"}
        else "M15 READY"
        if dc_m15_ready
        else "M5 REFINED • RETEST WATCH"
        if dc_current_refined_limit_side_valid
        else "M5 REFINED LAMA • WAIT NEW TRIGGER"
        if dc_current_refined_historical
        else "M5 CANDIDATE • WAIT"
        if dc_current_pocket_state == "CANDIDATE_M5_POCKET"
        else "WAIT"
    )

    with st.container(border=True):
        top1, top2 = st.columns(2)
        top1.metric("Harga XAUUSD", _fmt_price(dc_reference_price))
        top2.metric("Action sekarang", dc_setup_summary)
        st.caption(
            "Price source="
            + str(dc_reference_price_source)
            + (
                " • age="
                + f"{float(dc_reference_price_age):.0f}s"
                if dc_reference_price_age is not None
                else ""
            )
            + (
                " • backend ref="
                + _fmt_price(dc_backend_reference_price)
                + " (" + str(dc_backend_price_source) + ")"
                if dc_backend_reference_price is not None
                else ""
            )
            + ". FP Markets/cTrader quote overlay is display/geometry only; execution authority tetap ForexRizan."
        )
        top3, top4 = st.columns(2)
        top3.metric("Arah aktif (V182)", dc_current_leg_label)
        top4.metric("Konteks HTF", dc_htf_context_bias)

        if dc_position_mode:
            st.success(
                f"**POSITION MODE** • {len(dc_active_demo_positions)} posisi XAUUSD DEMO aktif. "
                "Prioritas: proteksi SL → BE/partial → target reaksi → opposing zone."
            )
        else:
            if dc_inside_current_terminal and dc_next_leg_direction in {"LONG", "SHORT"}:
                st.warning(
                    f"**Path {dc_current_leg_label} sudah mencapai opposing/terminal zone** "
                    f"{_fmt_price(dc_current_leg_terminal.get('low'))}–"
                    f"{_fmt_price(dc_current_leg_terminal.get('high'))}. "
                    f"Next leg watch: **{dc_next_leg_watch_text}**. "
                    "Next leg belum menjadi entry resmi sampai handoff struktural + V240/V229 + "
                    "M15 + pressure/admission konsisten."
                )
            else:
                st.info(
                    f"**Path aktif {dc_current_leg_label}** ({dc_leg_relation})"
                    f" → target reaksi {_fmt_price(dc_current_leg_target.get('price'))}"
                    f" → opposing zone "
                    f"{_fmt_price(dc_current_leg_terminal.get('low'))}–"
                    f"{_fmt_price(dc_current_leg_terminal.get('high'))}. "
                    "**Konteks HTF bukan perintah entry.** Entry resmi hanya muncul setelah "
                    "V240/V229 + M15 + protection/admission konsisten; izin order tetap mengikuti admission dan protection contract."
                )

        dc_v182_age = (
            None
            if supply_demand_hb is None
            else _age_seconds(supply_demand_hb.get("observed_at"))
        )
        dc_v226_age = (
            None
            if v226_depth_map_hb is None
            else _age_seconds(v226_depth_map_hb.get("observed_at"))
        )
        dc_v182_age_text = "—" if dc_v182_age is None else f"{dc_v182_age:.0f}s"
        dc_v226_age_text = "—" if dc_v226_age is None else f"{dc_v226_age:.0f}s"
        st.caption(
            f"HTF context {dc_htf_context_bias} • H4 parent {dc_h4_text} • D1 parent {dc_d1_text} • "
            f"current path map {_fmt_wib_datetime(current_map, seconds=False)} • "
            f"V182 age={dc_v182_age_text} • V226 age={dc_v226_age_text} • "
            f"dashboard {_fmt_wib_datetime(datetime.now(tz=UTC), seconds=False)}."
        )


    dc_geometry_code_by_signal: dict[str, str] = {}
    for dc_event_row in geometry_rows:
        if str(dc_event_row.get("event_type") or "") != "DEMO_SIGNAL_GEOMETRY":
            continue
        dc_signal_key = str(dc_event_row.get("signal_key") or "")
        if dc_signal_key and dc_signal_key not in dc_geometry_code_by_signal:
            dc_geometry_code_by_signal[dc_signal_key] = str(dc_event_row.get("code") or "")

    dc_latest_signal = dict(dedicated_xau_rows[0]) if dedicated_xau_rows else {}
    dc_latest_signal_id = str(dc_latest_signal.get("id") or "")
    dc_latest_signal_state = str(dc_latest_signal.get("state") or "").upper()
    dc_latest_signal_guards = list(dc_latest_signal.get("active_guards") or [])
    dc_latest_geometry_code = dc_geometry_code_by_signal.get(dc_latest_signal_id, "")
    dc_latest_expiry = _parse_timestamp(dc_latest_signal.get("expires_at"))
    dc_latest_expired = bool(dc_latest_expiry and dc_latest_expiry < dc_now)

    if dc_position_mode:
        dc_admission_label = "MANAGE POSITION"
        dc_route_label = "POSISI AKTIF"
    elif dc_latest_signal_state == "INVALIDATED":
        dc_admission_label = "INVALIDATED"
        dc_route_label = "NO ORDER"
    elif dc_latest_expired:
        dc_admission_label = "EXPIRED"
        dc_route_label = "NO ORDER"
    elif dc_latest_signal_guards:
        dc_admission_label = "BLOCKED"
        dc_route_label = "GUARD ACTIVE"
    elif dc_latest_signal_state == "EXECUTION_READY" and dc_latest_geometry_code == "XAU_RIZAN_DEPTH_EXECUTION_V1":
        dc_admission_label = "V229 READY"
        dc_route_label = "V229 DEPTH"
    elif dc_latest_signal_state == "EXECUTION_READY" and dc_latest_geometry_code in {
        "XAU_RIZAN_PATH_EXECUTION_V1",
        "XAU_AFIC_PATH_EXECUTION_V1",
        "XAU_M15_EMA_SMC_RECLAIM_V1",
        "XAU_V24_CHAMPION_DEMO_V1",
    }:
        dc_admission_label = "BROKER ELIGIBLE"
        dc_route_label = "DEMO ROUTE"
    elif dc_latest_signal_state == "EXECUTION_READY":
        dc_admission_label = "SHADOW READY"
        dc_route_label = "NO AUTHORITY"
    else:
        dc_admission_label = "WAIT"
        dc_route_label = "NO ORDER"

    if backend_snapshot_stale:
        dc_admission_label = "DATA STALE"
        dc_route_label = "NO ORDER"

    v318_probe_details = (
        {}
        if v318_structural_probe_hb is None
        else dict(v318_structural_probe_hb.get("details") or {})
    )
    v318_probe_geometry = dict(v318_probe_details.get("geometry") or {})
    v318_probe_age = (
        None
        if v318_structural_probe_hb is None
        else _age_seconds(v318_structural_probe_hb.get("observed_at"))
    )
    v318_probe_fresh = bool(
        v318_structural_probe_hb is not None
        and bool(v318_structural_probe_hb.get("healthy"))
        and v318_probe_age is not None
        and v318_probe_age <= 180.0
    )
    v318_probe_state = str(v318_probe_details.get("state") or "BELUM ADA SNAPSHOT")
    v318_probe_label = (
        v318_probe_state
        if v318_probe_fresh
        else f"LAST-KNOWN • {v318_probe_state}"
        if v318_structural_probe_hb is not None
        else "BELUM ADA SNAPSHOT"
    )

    st.markdown(
        '<div class="rizan-flow-note"><b>Urutan baca utama:</b> '
        '1 Ringkasan keputusan → 2 Zona & Depth → 3 Eksekusi sekarang → '
        '4 Manajemen posisi. <b>Strict lane</b> dan <b>DEMO Research Probe</b> '
        'ditampilkan terpisah agar forecast tidak lagi disamakan dengan izin order.</div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        flow1, flow2 = st.columns(2)
        flow1.metric("1 • HTF context", dc_htf_context_bias)
        flow2.metric("2 • Path aktif V182", dc_current_leg_direction)
        flow3, flow4 = st.columns(2)
        flow3.metric("3 • M15", dc_m15_state)
        flow4.metric("4 • Admission", dc_admission_label)
        st.info(f"**Strict lane / Broker route:** {dc_route_label}")
        st.info(
            "**DEMO Research Probe V318:** "
            + v318_probe_label
            + " • 0.01 lot • H1/H4 structural source • tidak wajib M15/pressure confirmation. "
            "Fresh cTrader quote, structural SL/TP, no-chase, RR ≥1R, dan explicit event/shock block tetap wajib."
        )
        if v318_probe_geometry:
            st.caption(
                "V318 geometry • "
                f"{v318_probe_geometry.get('direction') or '—'} • "
                f"entry {_fmt_price(v318_probe_geometry.get('entry'))} • "
                f"SL {_fmt_price(v318_probe_geometry.get('sl'))} • "
                f"TP {_fmt_price(v318_probe_geometry.get('tp'))} • "
                f"RR {_fmt_number(v318_probe_geometry.get('rr'), 2)} • "
                f"source {v318_probe_geometry.get('source_timeframe') or '—'}."
            )
        if dc_inside_current_terminal and dc_next_leg_direction in {"LONG", "SHORT"}:
            st.caption(
                f"Next leg watch (BUKAN ENTRY): {dc_next_leg_watch_text}. "
                "Current path sudah mencapai terminal/opposing zone."
            )
        if dc_latest_signal_guards:
            st.warning(
                "Guard aktif: "
                + ", ".join(str(_rizan_display(x)) for x in dc_latest_signal_guards)
            )
        elif dc_admission_label == "V229 READY":
            st.success(
                "V229 memakai jalur khusus. Fresh mode = 4-CHILD 2+2 "
                "(2 pre-touch LIMIT + 2 child konfirmasi); H4/H1 retest tetap eligible. "
                "V275/V276: fresh first-touch memakai radius arm adaptif. Base ≤0,50 ATR; "
                "boleh diperluas sampai ≤1,00 ATR hanya bila M30 parent overlap ≥70% dan "
                "composite pressure mendukung arah yang sama. L1 DEMO 0,01 lot boleh di-arm "
                "lebih awal; L2/L3/L4 tetap strict. "
                "Untuk retest, L1 DEMO calibration probe 0,01 lot memakai M5 pocket aktual. Jika pocket aktual "
                "sudah disentuh terlalu dalam lalu closed M5 reject kembali ke no-chase band, V270 boleh "
                "memasang satu LIMIT retest di Dynamic Depth band yang masih eligible (maksimum umur M5 60 menit). "
                "RR probe tetap ≥1,00R dan research cap probe 85%; L3/L4 tetap jalur strict ≥1,50R. "
                "Tidak diteruskan ke generic MARKET handoff."
            )

    v226_details = (
        {} if v226_depth_map_hb is None else dict(v226_depth_map_hb.get("details") or {})
    )
    v226_eval = dict(v226_details.get("evaluation") or {})
    v227_details = (
        {} if v227_depth_calibration_hb is None
        else dict(v227_depth_calibration_hb.get("details") or {})
    )
    v227_summary = dict(v227_details.get("summary") or {})
    v226_overlays = [
        dict(item) for item in list(v226_eval.get("chart_overlays") or [])
    ]
    v226_focus_direction = str(
        v226_eval.get("focus_direction") or dc_current_leg_direction or ""
    ).upper()
    v226_focus_map = dict(
        v226_eval.get(v226_focus_direction.lower()) or {}
    )
    v226_h4 = dict(v226_focus_map.get("h4") or {})
    v226_h4_selection_mode = str(
        v226_focus_map.get("h4_selection_mode") or "—"
    )
    v226_nearest_h4_context = dict(
        v226_focus_map.get("nearest_h4_context") or {}
    )
    v226_nearest_h4_context_zone = dict(
        v226_nearest_h4_context.get("zone") or {}
    )
    v226_nearest_h4_context_app = dict(
        v226_nearest_h4_context.get("applicability") or {}
    )
    v226_h1 = dict(v226_focus_map.get("h1") or {})
    v226_m15 = dict(v226_focus_map.get("m15") or {})
    v226_h4_hotspot = dict(v226_h4.get("hotspot") or {})
    v226_h4_quantiles = dict(v226_h4.get("quantiles") or {})
    v226_h1_locator = dict(v226_h1.get("nested_locator") or {})
    v226_h1_envelope = dict(v226_h1_locator.get("envelope") or {})
    v226_m15_locator = dict(v226_m15.get("nested_locator") or {})
    v226_m15_envelope = dict(v226_m15_locator.get("envelope") or {})
    v226_entry_candidate = dict(
        v226_focus_map.get("depth_entry_candidate")
        or v226_eval.get("depth_entry_candidate")
        or {}
    )
    v226_entry_candidates = dict(v226_eval.get("entry_candidates") or {})
    v226_long_entry_candidate = dict(v226_entry_candidates.get("long") or {})
    v226_short_entry_candidate = dict(v226_entry_candidates.get("short") or {})
    v226_four_order_ladder = dict(v226_eval.get("four_order_ladder") or {})
    v226_ladder_slots = list(v226_four_order_ladder.get("slots") or [])
    v226_projected_m5_watch = dict(
        v226_eval.get("projected_m5_watch_pocket") or {}
    )
    v226_reversal_heatmap = [
        dict(item)
        for item in list(v226_eval.get("reversal_depth_heatmap") or [])
    ]
    v226_reversal_heatmap_source = dict(
        v226_eval.get("reversal_depth_heatmap_source") or {}
    )

    v240_saved_geometry: dict[str, Any] = {}
    for chart_event in geometry_rows:
        chart_payload = dict(chart_event.get("payload") or {})
        if (
            str(chart_event.get("event_type") or "") == "DEMO_SIGNAL_GEOMETRY"
            and (
                str(chart_event.get("code") or "") == "XAU_RIZAN_DEPTH_EXECUTION_V1"
                or str(chart_payload.get("strategy_id") or "") == "XAU_RIZAN_DEPTH_EXECUTION_V1"
            )
        ):
            v240_saved_geometry = chart_payload
            break

    v240_v212_details = (
        {} if v212_probability_hb is None
        else dict(v212_probability_hb.get("details") or {})
    )
    v240_zone_probabilities = [
        dict(item) for item in list(v240_v212_details.get("zone_probabilities") or [])
    ]
    v240_decision = build_canonical_xau_decision(
        v226_evaluation=v226_eval,
        atlas_evaluation=dc_sd_eval,
        price_now=dc_reference_price,
        path_direction=dc_current_leg_direction,
        saved_v229_geometry=v240_saved_geometry,
        zone_probabilities=v240_zone_probabilities,
        v226_age_seconds=(
            None if v226_depth_map_hb is None
            else _age_seconds(v226_depth_map_hb.get("observed_at"))
        ),
        atlas_age_seconds=(
            None if supply_demand_hb is None
            else _age_seconds(supply_demand_hb.get("observed_at"))
        ),
    )
    v240_direction = str(
        v240_decision.get("direction") or dc_current_leg_direction or "—"
    ).upper()
    v240_authority = str(v240_decision.get("authority") or "")
    v240_entry_authorized = bool(v240_decision.get("entry_authorized"))
    v240_confirmation_window_armed = bool(
        v240_decision.get("confirmation_window_armed")
    )
    v240_confirmation_window = dict(
        v240_decision.get("confirmation_entry_window") or {}
    )
    v240_entry_zone = {
        "entry_low": v240_decision.get("entry_low"),
        "entry_high": v240_decision.get("entry_high"),
        "entry_reference": v240_decision.get("entry_reference"),
    }
    v240_targets = [
        dict(item) for item in list(v240_decision.get("structural_targets") or [])
    ]
    v240_children = [
        dict(item) for item in list(v240_decision.get("children") or [])
    ]
    v240_destination = dict(v240_decision.get("likely_destination") or {})
    v240_nearest_demand = dict(
        v240_decision.get("primary_reversal_demand")
        or v240_decision.get("nearest_demand")
        or {}
    )
    v240_nearest_supply = dict(
        v240_decision.get("primary_reversal_supply")
        or v240_decision.get("nearest_supply")
        or {}
    )
    v240_reversal_watch = dict(v240_decision.get("primary_reversal_watch") or {})
    v240_hist = dict(v240_decision.get("historical_context") or {})
    v240_hist_entry = dict(v240_decision.get("historical_research_entry") or {})
    v240_conflicts = list(v240_decision.get("conflicts") or [])
    v240_blocking_conflicts = list(
        v240_decision.get("blocking_conflicts") or []
    )
    v240_stale = list(v240_decision.get("stale_reasons") or [])
    v240_remap = list(v240_decision.get("remap_reasons") or [])
    v240_local_structure = dict(v240_decision.get("local_structure_override") or {})
    v240_active_source = dict(v240_decision.get("active_path_source") or {})

    # Operational buyer/seller pressure is surfaced directly in V240 and uses
    # the same classifier as the cTrader DEMO child executor.
    v240_pressure_transition = evaluate_pressure_transition(
        direction=v240_direction,
        dom_heartbeat={} if dom_v191_hb is None else dict(dom_v191_hb),
        now=datetime.now(tz=UTC),
    )
    v240_dom_score = v240_pressure_transition.get("score")
    v240_buyer_index = v240_pressure_transition.get("buyer_index")
    v240_seller_index = v240_pressure_transition.get("seller_index")
    v240_opposing_pressure = v240_pressure_transition.get("opposing_pressure")
    v240_pressure_change = v240_pressure_transition.get("score_change")
    v240_dom_age = v240_pressure_transition.get("age_seconds")
    v240_current_dom_sample_fresh = bool(
        v240_pressure_transition.get(
            "current_sample_fresh",
            v240_pressure_transition.get("fresh"),
        )
    )
    v240_calibration_pressure_allowed = bool(
        v240_pressure_transition.get("calibration_entry_allowed")
    )
    v240_calibration_pressure_reason = str(
        v240_pressure_transition.get("calibration_pressure_reason") or ""
    )
    v240_dom_stale = not v240_current_dom_sample_fresh
    v240_dom_state = str(v240_pressure_transition.get("dom_state") or "UNAVAILABLE")
    v240_pressure_trend = str(v240_pressure_transition.get("state") or "UNAVAILABLE")

    # V272 price-derived pressure remains available when broker DOM is stale.
    # It is explicitly not order-flow volume and never becomes standalone
    # execution authority. Strict L3/L4 still use the normal structure/RR path.
    v240_composite_pressure = dict(dc_sd_eval.get("composite_pressure_v272") or {})
    v240_m30_shadow = dict(dc_sd_eval.get("m30_shadow_v272") or {})
    v240_m30_rejection = dict(dc_sd_eval.get("m30_deep_rejection_v277") or {})
    v240_m30_policy = dict(dc_sd_eval.get("m30_entry_policy_v278") or {})
    v240_composite_available = bool(v240_composite_pressure.get("available"))
    v240_composite_buyer = v240_composite_pressure.get("buyer_index")
    v240_composite_seller = v240_composite_pressure.get("seller_index")
    v240_pressure_source = "DOM"
    v240_effective_buyer_index = v240_buyer_index
    v240_effective_seller_index = v240_seller_index
    v240_effective_pressure_state = v240_pressure_trend
    v240_effective_opposing_pressure = v240_opposing_pressure
    if (
        (v240_dom_score is None or v240_dom_stale)
        and v240_composite_available
        and v240_composite_buyer is not None
    ):
        v240_pressure_source = "RIZAN_COMPOSITE"
        v240_effective_buyer_index = float(v240_composite_buyer)
        v240_effective_seller_index = float(v240_composite_seller)
        v240_effective_pressure_state = str(
            v240_composite_pressure.get("state") or "UNAVAILABLE"
        )
        signed_buyer = (float(v240_composite_buyer) - 50.0) * 2.0
        v240_effective_opposing_pressure = (
            -signed_buyer
            if v240_direction == "LONG"
            else signed_buyer
            if v240_direction == "SHORT"
            else None
        )

    # Calibrated dynamic hazard is valid only when current V229/V226 geometry is
    # aligned and authoritative. Otherwise show physical depth of the current
    # V182 source only; never project an old hazard band onto a new local zone.
    v240_depth_zone = dict(
        v240_active_source
        or v240_local_structure
        or (
            v240_nearest_demand
            if v240_direction == "LONG"
            else v240_nearest_supply
            if v240_direction == "SHORT"
            else {}
        )
    )
    if (
        v240_authority == "V229_CANONICAL_GEOMETRY"
        and v240_entry_authorized
        and not v240_remap
        and not v240_stale
        and not v240_blocking_conflicts
    ):
        v240_depth_hazard = build_dynamic_depth_hazard(
            v226_evaluation=v226_eval,
            direction=v240_direction,
            live_price=dc_reference_price,
            pressure_transition=v240_pressure_transition,
        )
    elif dc_reference_price is not None and v240_depth_zone:
        v240_depth_hazard = build_geometry_depth_status(
            zone=v240_depth_zone,
            live_price=float(dc_reference_price),
        )
    else:
        v240_depth_hazard = {
            "state": "UNAVAILABLE",
            "reason": "NO_CURRENT_DEPTH_GEOMETRY",
            "execution_ready": False,
        }

    # Surface the same lifecycle/execution state used by the DEMO route.
    v226_h4_app = dict(v226_h4.get("applicability") or {})
    v226_h1_app = dict(v226_h1.get("applicability") or {})
    v226_m15_app = dict(v226_m15.get("applicability") or {})
    v226_candidate_reuse = dict(v226_entry_candidate.get("zone_reuse") or {})
    v229_exec_details = (
        {} if v229_depth_execution_hb is None
        else dict(v229_depth_execution_hb.get("details") or {})
    )
    v229_exec_plan = dict(v229_exec_details.get("plan") or {})
    v229_plan_diagnostics = dict(v229_exec_details.get("plan_diagnostics") or {})
    v229_child_details = (
        {} if v229_child_executor_hb is None
        else dict(v229_child_executor_hb.get("details") or {})
    )
    v282_lifecycle_details = (
        {} if v282_lifecycle_hb is None
        else dict(v282_lifecycle_hb.get("details") or {})
    )
    v282_lifecycle_metrics = dict(v282_lifecycle_details.get("metrics") or {})
    v282_latency_metrics = dict(v282_lifecycle_metrics.get("latency") or {})
    v229_child_actions = list(v229_child_details.get("actions") or [])
    v240_reversal_stage = dict(
        v229_exec_details.get("reversal_stage")
        or v229_exec_plan.get("reversal_stage")
        or {}
    )
    v240_reversal_stage_candidate = str(
        v229_exec_details.get("candidate_key")
        or v229_exec_plan.get("candidate_key")
        or ""
    )
    if (
        v240_reversal_stage
        and v240_reversal_stage_candidate
        and str(v240_decision.get("candidate_key") or "")
        and v240_reversal_stage_candidate != str(v240_decision.get("candidate_key") or "")
    ):
        v240_reversal_stage = {}
    if (
        not v240_reversal_stage
        and v229_exec_plan
        and dc_reference_price is not None
        and str(v229_exec_plan.get("direction") or "").upper() == v240_direction
    ):
        try:
            v240_reversal_stage = evaluate_reversal_stage(
                plan=v229_exec_plan,
                atlas_evaluation=dc_sd_eval,
                depth_hazard=v240_depth_hazard,
                pressure_transition=v240_pressure_transition,
                live_price=float(dc_reference_price),
                now=datetime.now(tz=UTC),
            )
            v240_reversal_stage["dashboard_recomputed_without_live_spread"] = True
        except Exception:
            v240_reversal_stage = {}

    v284_first_touch_calibrated = bool(
        v240_reversal_stage.get("first_touch_calibrated")
        or str(v226_candidate_reuse.get("historical_prior_scope") or "").upper()
        == "FIRST_TOUCH_CALIBRATED"
    )
    v284_competing_risk = evaluate_v281_competing_risk_prior(
        timeframe=str(
            v240_reversal_stage.get("source_timeframe")
            or v226_reversal_heatmap_source.get("timeframe")
            or v240_active_source.get("timeframe")
            or ""
        ),
        direction=v240_direction,
        depth=(
            v240_reversal_stage.get("depth")
            if v240_reversal_stage.get("depth") is not None
            else v240_depth_hazard.get("current_depth")
        ),
        first_touch_calibrated=v284_first_touch_calibrated,
    )

    if v240_effective_opposing_pressure is None:
        v240_penetration_risk = "UNAVAILABLE"
    elif float(v240_effective_opposing_pressure) >= 45.0:
        v240_penetration_risk = "TINGGI — opposing pressure masih kuat"
    elif float(v240_effective_opposing_pressure) >= 15.0:
        v240_penetration_risk = "SEDANG — pressure sedang mereda"
    elif float(v240_effective_opposing_pressure) > -15.0:
        v240_penetration_risk = "BALANCED / ABSORPTION"
    else:
        v240_penetration_risk = "RENDAH — control mulai berbalik"

    v240_session = "OFF_SESSION"
    if cfg is not None:
        try:
            v240_session = session_label(datetime.now(tz=UTC), cfg.sessions)
        except Exception:
            v240_session = "SESSION_UNAVAILABLE"
    v240_wib_clock = datetime.now(tz=UTC).astimezone(WIB).strftime("%H:%M WIB")
    v286_contextual_risk = evaluate_v281_contextual_competing_risk(
        timeframe=str(
            v240_reversal_stage.get("source_timeframe")
            or v226_reversal_heatmap_source.get("timeframe")
            or v240_active_source.get("timeframe")
            or ""
        ),
        depth=(
            v240_reversal_stage.get("depth")
            if v240_reversal_stage.get("depth") is not None
            else v240_depth_hazard.get("current_depth")
        ),
        session=v240_session,
        atr_points=v240_active_source.get("atr_points"),
        live_pressure_state=v240_pressure_trend,
        first_touch_calibrated=v284_first_touch_calibrated,
        year=datetime.now(tz=UTC).year,
    )
    v240_gate_reason = str(
        v229_exec_details.get("reason")
        or v240_depth_hazard.get("action")
        or v240_decision.get("state")
        or "WAIT"
    )
    v240_admission_label = dc_admission_label
    v240_route_label = dc_route_label
    if not dc_position_mode and not v240_entry_authorized:
        v240_admission_label = "DATA STALE" if backend_snapshot_stale else "WAIT"
        v240_route_label = "NO ORDER"

    # V303 RIZAN STYLE PATH ENGINE: branching structural forecast built from
    # the same current V182 map and the freshest dashboard price. This is
    # deliberately non-voting and cannot authorize an order.
    rizan_style_path = build_rizan_style_path_engine(
        atlas_evaluation=dc_sd_eval,
        price_now=dc_reference_price,
        path_direction=v240_direction,
    )
    rizan_style_zone = dict(rizan_style_path.get("next_decision_zone") or {})
    rizan_style_keys = dict(rizan_style_path.get("key_levels") or {})
    rizan_style_primary = dict(rizan_style_path.get("primary_path") or {})
    rizan_style_rejection = dict(rizan_style_path.get("rejection_branch") or {})
    rizan_style_acceptance = dict(rizan_style_path.get("acceptance_branch") or {})

    def _rizan_style_zone_text(zone_row: dict[str, Any]) -> str:
        if not zone_row:
            return "Belum tersedia"
        side = str(zone_row.get("direction") or "").upper()
        kind = "Demand" if side == "LONG" else "Supply" if side == "SHORT" else "Zone"
        tf = str(zone_row.get("timeframe") or "").upper()
        return (
            f"{kind} {tf} {_fmt_price(zone_row.get('low'))}–"
            f"{_fmt_price(zone_row.get('high'))}"
        )

    def _rizan_style_route_text(route_rows: Any) -> str:
        prices = []
        for raw in list(route_rows or []):
            row = dict(raw or {})
            if row.get("price") is None:
                continue
            prices.append(_fmt_price(row.get("price")))
        return " → ".join(prices) if prices else "Belum ada waypoint valid"

    # V322 adds no-chase handoff + V182 micro confluence. V321/V320 remain
    # compatibility fallbacks while older bridge snapshots age out.
    micro_hb = v322_micro_handoff_hb or v321_micro_entry_hb or v320_micro_entry_hb
    v320_micro_details = (
        {}
        if micro_hb is None
        else dict(micro_hb.get("details") or {})
    )
    v320_micro_eval = dict(v320_micro_details.get("evaluation") or {})
    v320_micro_age = (
        None
        if micro_hb is None
        else _age_seconds(micro_hb.get("observed_at"))
    )
    v320_micro_fresh = bool(
        micro_hb is not None
        and bool(micro_hb.get("healthy"))
        and v320_micro_age is not None
        and v320_micro_age <= 300.0
    )
    v320_micro_primary = dict(
        v320_micro_eval.get("primary") or v320_micro_eval
    )
    v320_micro_levels = dict(v320_micro_primary.get("levels") or {})
    v320_micro_anchor = dict(v320_micro_primary.get("anchor") or {})
    v320_micro_delta = dict(v320_micro_primary.get("delta") or {})
    v320_micro_parent = dict(v320_micro_primary.get("decision_zone") or {})
    v320_micro_targets = list(v320_micro_primary.get("targets") or [])
    v320_micro_opposing = dict(v320_micro_primary.get("nearest_opposing_zone") or {})
    v321_active_source = dict(v320_micro_eval.get("active_source") or {})
    v321_next_opposing = dict(v320_micro_eval.get("next_opposing") or {})
    v321_primary_role = str(
        v320_micro_eval.get("primary_setup_role")
        or v320_micro_primary.get("setup_role")
        or "V320_COMPATIBILITY"
    )

    tab_supply, tab_micro = st.tabs(
        [
            "1 • RIZAN Supply/Demand + Liquidity",
            "2 • RIZAN Micro Entry Refinement",
        ]
    )
    with tab_supply:
        with st.container(border=True):
            st.markdown("### RIZAN STYLE PATH ENGINE")
            st.caption(
                "Peta alur bercabang: source → decision zone → rejection atau acceptance → "
                "destination berikutnya. Ini forecast struktural, bukan jaminan harga dan "
                "tidak memberi execution authority."
            )
            rp1, rp2 = st.columns(2)
            rp1.metric(
                "Arah leg aktif",
                str(rizan_style_path.get("active_direction") or "WAIT"),
            )
            rp2.metric(
                "State path",
                _rizan_display(rizan_style_path.get("state") or "NO_STRUCTURAL_PATH"),
            )
            st.markdown(
                "**Decision zone berikut:** "
                + _rizan_style_zone_text(rizan_style_zone)
            )
            k1, k2 = st.columns(2)
            k1.metric(
                "KEY rejection / reclaim",
                _fmt_price(rizan_style_keys.get("rejection_reclaim_key")),
            )
            k2.metric(
                "KEY break / acceptance",
                _fmt_price(rizan_style_keys.get("break_acceptance_key")),
            )
            st.markdown(
                "**Primary path:** "
                + str(rizan_style_primary.get("direction") or "WAIT")
                + " • "
                + _rizan_style_route_text(rizan_style_primary.get("route"))
            )
            st.markdown(
                "**Jika REJECTION terkonfirmasi:** "
                + str(rizan_style_rejection.get("direction") or "WAIT")
                + " • "
                + _rizan_style_route_text(rizan_style_rejection.get("route"))
            )
            st.caption(
                "Trigger rejection: "
                + str(rizan_style_rejection.get("condition") or "WAIT_REJECTION")
                + " • M5="
                + str(rizan_style_rejection.get("m5_state") or "WAIT")
            )
            next_break_zone = dict(
                rizan_style_acceptance.get("next_destination_zone") or {}
            )
            st.markdown(
                "**Jika ACCEPTANCE / break:** "
                + str(rizan_style_acceptance.get("direction") or "WAIT")
                + " → "
                + _rizan_style_zone_text(next_break_zone)
            )
            st.caption(
                "Trigger acceptance: "
                + str(rizan_style_acceptance.get("condition") or "WAIT_ACCEPTANCE")
                + " • branch="
                + str(rizan_style_path.get("branch_preference") or "WAIT_DECISION")
                + "."
            )
            if str(rizan_style_path.get("state") or "").upper() == "DECISION_ZONE_REJECTION_CONFIRMED":
                st.success("RIZAN path: rejection branch terkonfirmasi secara struktural/M5.")
            elif str(rizan_style_path.get("state") or "").upper() == "DECISION_ZONE_ACCEPTED_BREAK":
                st.warning("RIZAN path: decision zone diterima/break — ikuti continuation map, jangan fade zona lama.")
            elif str(rizan_style_path.get("state") or "").upper() == "DECISION_ZONE_ACTIVE":
                st.info("RIZAN path: harga sedang berada di decision zone — tunggu rejection vs acceptance.")
            else:
                st.info("RIZAN path: harga masih menuju decision zone berikut.")
    
    
        with st.container(border=True):
            st.markdown("### Zona Liquidity & Reversal Validation")
            st.caption(
                "Tab 1 mempertahankan peta besar H4/H1. Saat harga masuk decision zone, "
                "V317 memetakan liquidity sweep band dan scanner menunggu validasi reversal "
                "M5/M15; zona sempit tidak dianggap otomatis sebagai titik balik."
            )
            liq1, liq2, liq3 = st.columns(3)
            liq1.metric(
                "Decision zone",
                (
                    f"{_fmt_price(v296_decision_zone.get('low'))}–"
                    f"{_fmt_price(v296_decision_zone.get('high'))}"
                    if v296_decision_zone else "BELUM ADA"
                ),
            )
            liq2.metric(
                "Liquidity sweep band",
                (
                    f"{_fmt_price(v296_sweep_band.get('low'))}–"
                    f"{_fmt_price(v296_sweep_band.get('high'))}"
                    if v296_sweep_band else "BELUM ADA"
                ),
            )
            liq3.metric(
                "Sweep risk",
                str(v296_liquidity_map.get("risk_grade") or "BELUM ADA"),
            )
            if v296_liquidity_levels:
                st.caption(
                    "Level liquidity: "
                    + " • ".join(
                        f"{str(dict(row).get('source') or 'LEVEL')} "
                        f"{_fmt_price(dict(row).get('price'))}"
                        for row in v296_liquidity_levels[:8]
                    )
                )
            rejection_rule = str(
                dict(rizan_style_path.get("rejection_branch") or {}).get("condition")
                or "WAIT_M5_M15_RECLAIM"
            )
            acceptance_rule = str(
                dict(rizan_style_path.get("acceptance_branch") or {}).get("condition")
                or "WAIT_M15_ACCEPTANCE"
            )
            st.info(
                "Validasi reversal: " + rejection_rule
                + " • Jika gagal dan terjadi acceptance: " + acceptance_rule + "."
            )

    with tab_micro:
        def _render_micro_setup(
            title: str,
            setup: dict[str, Any],
            *,
            primary: bool = False,
        ) -> None:
            row = dict(setup or {})
            if not row or str(row.get("state") or "") == "NO_ZONE":
                st.caption(title + ": belum ada structural zone yang valid.")
                return
            levels = dict(row.get("levels") or {})
            anchor = dict(row.get("anchor") or {})
            delta = dict(row.get("delta") or {})
            zone_row = dict(row.get("decision_zone") or {})
            badge = " • PRIMARY" if primary else ""
            st.markdown("**" + title + badge + "**")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Arah", str(row.get("direction") or "WAIT"))
            c2.metric("TF", str(row.get("selected_timeframe") or "—"))
            c3.metric("Phase", _rizan_display(row.get("phase") or "WAIT"))
            c4.metric(
                "Confidence",
                (
                    f"{float(row.get('confidence')):.0f}%"
                    if row.get("confidence") is not None else "—"
                ),
            )
            st.caption(
                "Parent "
                + str(zone_row.get("timeframe") or "—")
                + " "
                + _fmt_price(zone_row.get("low"))
                + "–"
                + _fmt_price(zone_row.get("high"))
                + " • "
                + ("A CONFIRMED" if bool(anchor.get("confirmed")) else "A PROJECTED")
            )
            e1, e2, e3 = st.columns(3)
            e1.metric("A", _fmt_price(levels.get("a")))
            e2.metric("X", _fmt_price(levels.get("x")))
            e3.metric("Y", _fmt_price(levels.get("y")))
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("SL", _fmt_price(levels.get("sl")))
            t2.metric("TP1 • 5Δ", _fmt_price(levels.get("tp1")))
            t3.metric("TP2 • 8Δ", _fmt_price(levels.get("tp2")))
            t4.metric("TP3 • 13Δ", _fmt_price(levels.get("tp3")))
            st.caption(
                "Δ="
                + _fmt_price(delta.get("value"))
                + " • ATR14="
                + _fmt_price(delta.get("atr14"))
                + " • exact formula referensi belum terverifikasi."
            )

        with st.container(border=True):
            st.markdown("### RIZAN STYLE MICRO ENTRY REFINEMENT • V322")
            st.caption(
                "Dua siklus dipisahkan: (1) micro-entry pada source H4/H1 yang sedang "
                "aktif/disentuh, dan (2) pre-map entry pada opposing zone berikutnya. "
                "M5 dipakai untuk timing cepat; H1 memberi ladder swing yang lebih lebar. "
                "Model A → X → Y → 5Δ / 8Δ / 13Δ tetap research-only."
            )
            if not v320_micro_eval:
                st.warning(
                    "V322 belum memiliki snapshot. Tunggu worker micro-handoff membaca "
                    "atlas H4/H1 dan data M5/M15/H1."
                )
            else:
                top1, top2, top3 = st.columns(3)
                top1.metric(
                    "State dual-cycle",
                    _rizan_display(v320_micro_eval.get("state") or "WAIT"),
                )
                top2.metric("Primary sekarang", _rizan_display(v321_primary_role))
                top3.metric(
                    "Harga",
                    _fmt_price(
                        v320_micro_eval.get("price_now")
                        or v320_micro_primary.get("price_now")
                    ),
                )

                active_m5 = dict(v321_active_source.get("m5") or {})
                active_h1 = dict(v321_active_source.get("h1") or {})
                next_m5 = dict(v321_next_opposing.get("m5") or {})
                next_h1 = dict(v321_next_opposing.get("h1") or {})

                _render_micro_setup(
                    "ACTIVE SOURCE • M5 fast entry",
                    active_m5,
                    primary=v321_primary_role == "ACTIVE_SOURCE_M5",
                )

                v322_micro_context = dict(v321_active_source.get("micro_context") or {})
                v322_sweep = dict(v322_micro_context.get("sweep") or {})
                v322_candidate_pocket = dict(
                    v322_micro_context.get("candidate_micro_pocket") or {}
                )
                v322_refined_pocket = dict(
                    v322_micro_context.get("refined_micro_pocket") or {}
                )
                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric(
                    "V182 M5 state",
                    _rizan_display(v322_micro_context.get("state") or "WAIT"),
                )
                mc2.metric("Sweep", _fmt_price(v322_sweep.get("price")))
                mc3.metric("MSS level", _fmt_price(v322_micro_context.get("mss_level")))
                mc4.metric(
                    "Source distance",
                    (
                        f"{float(v321_active_source.get('distance_atr')):.2f} ATR"
                        if v321_active_source.get("distance_atr") is not None
                        else "—"
                    ),
                )
                if bool(v321_active_source.get("no_chase")):
                    st.warning(
                        "ACTIVE SOURCE = NO CHASE. Harga sudah >0,75 ATR meninggalkan "
                        "source setelah reaction; source tetap konteks, tetapi fokus persiapan "
                        "dipindahkan ke NEXT OPPOSING."
                    )
                if v322_candidate_pocket:
                    st.caption(
                        "M5 candidate pocket "
                        + _fmt_price(v322_candidate_pocket.get("low"))
                        + "–"
                        + _fmt_price(v322_candidate_pocket.get("high"))
                        + " • source="
                        + str(v322_candidate_pocket.get("source") or "—")
                        + "."
                    )
                if v322_refined_pocket:
                    st.success(
                        "M5 refined pocket "
                        + _fmt_price(v322_refined_pocket.get("low"))
                        + "–"
                        + _fmt_price(v322_refined_pocket.get("high"))
                        + " • confluence V182 aktif."
                    )

                with st.expander("ACTIVE SOURCE • H1 swing ladder", expanded=False):
                    _render_micro_setup(
                        "H1 swing",
                        active_h1,
                        primary=False,
                    )

                st.divider()
                _render_micro_setup(
                    "NEXT OPPOSING ZONE • M5 pre-map",
                    next_m5,
                    primary=v321_primary_role == "NEXT_OPPOSING_M5",
                )
                with st.expander("NEXT OPPOSING • H1 swing ladder", expanded=False):
                    _render_micro_setup(
                        "H1 swing",
                        next_h1,
                        primary=False,
                    )

                st.info(
                    "Cara baca V322: ACTIVE SOURCE menjadi primary saat harga masih di source "
                    "atau masih dalam retest window ≤0,75 ATR. Jika harga sudah bergerak terlalu "
                    "jauh, NO CHASE aktif dan NEXT OPPOSING menjadi fokus persiapan. Saat harga "
                    "masuk NEXT OPPOSING, handoff dilakukan ke cycle reversal berikutnya."
                )
                st.caption(
                    "Snapshot "
                    + ("FRESH" if v320_micro_fresh else "LAST-KNOWN/STALE")
                    + (
                        f" • age {v320_micro_age:.0f}s"
                        if v320_micro_age is not None else ""
                    )
                    + " • execution authority = FALSE • LIVE OFF."
                )


    st.markdown("### 2 • Zona Aktif & Dynamic Depth")
    with st.container(border=True):
        st.markdown("##### V240 — Canonical XAU Decision Map")
        st.caption(
            "Satu sumber kebenaran untuk arah, Depth Candidate, entry, SL, TP dan tujuan berikutnya. "
            "Entry/SL/TP dihitung dengan builder V229 yang sama dengan jalur DEMO; snapshot lama tidak boleh mengalahkan candidate aktif."
        )
        # Smartphone-first operational sequence. Only current V182/V240
        # structure is shown here. V226 historical locator data lives in a
        # collapsed research panel further below.
        def _quick_zone_text(zone_row: dict[str, Any]) -> str:
            if not zone_row:
                return "Belum tersedia"
            direction = str(zone_row.get("direction") or "").upper()
            zone_kind = (
                "Demand"
                if direction == "LONG"
                else "Supply"
                if direction == "SHORT"
                else "Zone"
            )
            return (
                f"{zone_kind} {_fmt_price(zone_row.get('low'))}–"
                f"{_fmt_price(zone_row.get('high'))}"
            )

        def _human_wait_reason(value: Any) -> str:
            raw = str(_rizan_display(value) or "WAIT").upper()
            mapping = {
                "WAIT_STRUCTURALLY_ACTIVE_DEPTH_CANDIDATE": "Plan V229 belum terbentuk — cek struktur/RR",
                "WAIT_TERMINAL_RR_BELOW_MINIMUM": "RR terminal struktural < 1,50R — NO ORDER",
                "WAIT_NO_RR_ELIGIBLE_CONFIRMATION_WINDOW": "Tidak ada area M5 dalam source zone yang bisa mencapai 1,50R — NO ORDER",
                "WAIT_NO_FORWARD_STRUCTURAL_TARGET": "Belum ada target struktural forward — NO ORDER",
                "CONFIRMATION_WINDOW_ARMED": "M5 confirmation window aktif — tunggu entry aktual + RR ≥1,50R",
                "FRESH_FIRST_TOUCH_CALIBRATION_ARMED": "L1 DEMO calibration armed — L2/L3/L4 tetap strict",
                "WAIT_DYNAMIC_DEPTH_HAZARD:WAIT_ZONE": "Menunggu harga masuk zona aktif",
                "WAIT_DYNAMIC_DEPTH_HAZARD:WAIT_PRESSURE": "Menunggu tekanan DOM membaik",
                "WAIT_DYNAMIC_DEPTH_HAZARD:WAIT_M5_CONFIRM": "Menunggu konfirmasi M5",
                "WAIT_DYNAMIC_DEPTH_HAZARD:WAIT_STRUCTURE_REMAP": "Menunggu remap struktur",
                "WAIT_ZONE": "Menunggu harga masuk zona",
                "WAIT_NEW_TRIGGER": "Zona sudah bereaksi; tunggu trigger baru",
                "WAIT_CONFIRMATION": "Harga di zona; tunggu konfirmasi",
                "WAIT_STRUCTURE_REMAP": "Menunggu remap struktur",
                "LOCAL_PATH_WATCH": "Watch path lokal — belum entry",
                "LOCAL_REMAP_WAIT": "Remap lokal — belum entry",
                "TARGET_REACHED_WAIT_HANDOFF": "Target current leg tercapai — tunggu handoff",
                "STALE_WAIT": "Data stale — no order",
                "CONFLICT_WAIT": "Konflik data — no order",
                "BLOCK_MISSED_ENTRY_WAIT_NEXT_SETUP:SELECTED_ENTRY_BAND_PASSED_WITHOUT_M5_CONFIRMATION": "MISSED ENTRY — band lama terlewati; tunggu setup baru",
                "BLOCK_BREAK_RISK:BREAKDOWN_EVIDENCE_STRONGER_THAN_REVERSAL": "BREAK RISK — jangan tambah entry",
                "BLOCK_SETUP_INVALID:DISTAL_CLOSE_ACCEPTANCE_OR_ZONE_BROKEN": "SETUP INVALID — close acceptance melewati distal / zone broken",
            }
            return mapping.get(raw, raw.replace("_", " ").title())

        v240_state = str(v240_decision.get("state") or "WAIT").upper()
        v240_current_path_relation = (
            "SEARAH HTF"
            if v240_direction == dc_htf_context_bias
            else "COUNTERTREND / RETRACE"
            if v240_direction in {"LONG", "SHORT"}
            and dc_htf_context_bias in {"LONG", "SHORT"}
            else "—"
        )
        v240_m5_quick = dict(
            dc_next_projected_pocket
            if dc_current_leg_completed and dc_next_projected_pocket
            else dc_current_projected_pocket
            or v226_projected_m5_watch
            or {}
        )
        v240_m5_state_quick = (
            "NEXT_REFINED_M5_WATCH"
            if dc_current_leg_completed
            and dc_next_pocket_state == "REFINED_M5_POCKET"
            and dc_next_projected_pocket
            else "NEXT_CANDIDATE_M5_WATCH"
            if dc_current_leg_completed
            and dc_next_pocket_state == "CANDIDATE_M5_POCKET"
            and dc_next_projected_pocket
            else "NEXT_LEG_WAIT"
            if dc_current_leg_completed
            else "REFINED_M5_POCKET"
            if dc_current_refined_limit_side_valid
            else "REFINED_M5_HISTORICAL"
            if dc_current_refined_historical
            else dc_current_pocket_state
            if dc_current_projected_pocket
            else "PROJECTED_M5_WATCH"
            if v226_projected_m5_watch
            else "WAIT_M5"
        )
        v240_m5_price_quick = (
            f"{_fmt_price(v240_m5_quick.get('low'))}–"
            f"{_fmt_price(v240_m5_quick.get('high'))}"
            if v240_m5_quick
            else "Belum ada"
        )
        v240_watch_text = (
            f"{_fmt_price(v240_decision.get('entry_low'))}–"
            f"{_fmt_price(v240_decision.get('entry_high'))}"
            if v240_decision.get("entry_low") is not None
            and v240_decision.get("entry_high") is not None
            else "Belum ada"
        )
        v240_depth_location = str(
            v240_depth_hazard.get("location_state") or ""
        ).upper()
        if v240_depth_location == "AHEAD_OF_ZONE":
            v240_depth_text = "Belum masuk zona"
        elif v240_depth_location == "AFTER_REACTION":
            v240_depth_text = "Sudah bereaksi / keluar zona"
        elif v240_depth_location == "AT_OR_BEYOND_DISTAL":
            v240_depth_text = "Lewati distal — remap"
        elif v240_depth_location == "INSIDE_ZONE":
            v240_depth_text = (
                "Di dalam zona • "
                + (
                    f"{100.0 * float(v240_depth_hazard.get('current_depth')):.1f}% depth"
                    if v240_depth_hazard.get("current_depth") is not None
                    else "depth N/A"
                )
            )
        else:
            v240_depth_text = "Belum tersedia"

        v240_depth_state = str(v240_depth_hazard.get("state") or "").upper()
        v240_depth_calibrated = v240_depth_state == "DYNAMIC_DEPTH_HAZARD_AVAILABLE"
        v240_probe_depth_action = str(
            v240_depth_hazard.get("calibration_probe_depth_action") or ""
        ).upper()
        v240_probe_depth_eligible = bool(
            v240_depth_hazard.get("calibration_probe_depth_eligible")
        )
        v240_probe_depth_ceiling = v240_depth_hazard.get(
            "calibration_probe_depth_ceiling"
        )
        v240_probe_depth_text = (
            "PROBE NO-CHASE"
            if v240_probe_depth_action == "NO_CHASE_DEEP_ZONE"
            else "Probe depth OK"
            if v240_probe_depth_eligible
            else "Probe menunggu"
        )
        if (
            v240_depth_location == "INSIDE_ZONE"
            and v240_probe_depth_action == "NO_CHASE_DEEP_ZONE"
        ):
            v240_depth_text += " • PROBE NO-CHASE"
        if v240_depth_hazard.get("recommended_depth_low") is not None:
            v240_depth_band_text = (
                f"Band hazard riset "
                f"{100.0 * float(v240_depth_hazard.get('recommended_depth_low')):.0f}–"
                f"{100.0 * float(v240_depth_hazard.get('recommended_depth_high')):.0f}%"
            )
        else:
            v240_depth_band_text = (
                "Geometry only — hanya posisi harga relatif terhadap source zone; "
                "bukan forecast reversal dan bukan entry band"
            )

        v280_stage = str(v240_reversal_stage.get("stage") or "PREPARE").upper()
        v280_hard_block = bool(v240_reversal_stage.get("hard_execution_block"))
        v280_demo_allowed = bool(
            v240_reversal_stage.get("demo_entry_allowed")
            and not v280_hard_block
        )
        v240_effective_entry_authorized = bool(
            v240_entry_authorized and v280_demo_allowed
        )
        if (
            not dc_position_mode
            and v240_entry_authorized
            and not v240_effective_entry_authorized
        ):
            v240_admission_label = (
                "INVALIDATED" if v280_stage == "SETUP_INVALID" else "BLOCKED"
            )
            v240_route_label = "NO ORDER"

        v240_action_now = (
            "MANAGE POSITION"
            if dc_position_mode
            else (
                f"TARGET TERCAPAI • NEXT {dc_next_leg_direction} WATCH"
                if dc_current_leg_completed
                and dc_next_leg_direction in {"LONG", "SHORT"}
                else "TARGET TERCAPAI • WAIT HANDOFF"
            )
            if v240_state == "TARGET_REACHED_WAIT_HANDOFF"
            else "MISSED ENTRY — WAIT NEXT SETUP"
            if v280_stage == "MISSED_ENTRY_WAIT_NEXT_SETUP"
            else "SETUP INVALID — NO ORDER"
            if v280_stage == "SETUP_INVALID"
            else "BREAK RISK — NO NEW ENTRY"
            if v280_stage == "BREAK_RISK"
            else "EXECUTION READY"
            if v240_effective_entry_authorized
            and v240_admission_label in {"V229 READY", "BROKER ELIGIBLE"}
            and not backend_snapshot_stale
            else "WAIT • NO ORDER"
        )
        v240_entry_label = (
            "7 • Entry resmi"
            if v240_effective_entry_authorized
            else "7 • Source zone (SUDAH DIREAKSI)"
            if v240_depth_location == "AFTER_REACTION"
            else "7 • Zone watch (BUKAN ENTRY)"
        )
        v240_sl_text = (
            _fmt_price(v240_decision.get("sl"))
            if v240_effective_entry_authorized and v240_decision.get("sl") is not None
            else "Belum ada — belum admitted"
        )
        v240_tp_text = (
            f"{_fmt_price(v240_decision.get('tp1'))} → "
            f"{_fmt_price(v240_decision.get('tp2'))}"
            if v240_effective_entry_authorized
            and v240_decision.get("tp1") is not None
            else "Belum ada — belum admitted"
        )

        st.markdown("###### Tahap Reversal V280 — RISET/FORECAST → DEMO")
        stage_reason_text = " • ".join(
            str(x).replace("_", " ")
            for x in list(v240_reversal_stage.get("reasons") or [])
        ) or "Menunggu bukti tahap berikutnya"
        stage_label_map = {
            "PREPARE": "PERSIAPAN",
            "REVERSAL_WATCH": "REVERSAL WATCH",
            "REACTION_VISIBLE": "REAKSI TERLIHAT",
            "M5_CONFIRMATION": "KONFIRMASI M5",
            "DEMO_ENTRY_ALLOWED": "ENTRY DEMO DIIZINKAN",
            "BREAK_RISK": "BREAK RISK",
            "SETUP_INVALID": "SETUP INVALID",
            "MISSED_ENTRY_WAIT_NEXT_SETUP": "MISSED ENTRY — WAIT NEXT SETUP",
        }
        stage_label = stage_label_map.get(
            v280_stage,
            v280_stage.replace("_", " "),
        )
        if v280_stage == "DEMO_ENTRY_ALLOWED":
            st.success(f"**{stage_label}** • {stage_reason_text}")
        elif v280_stage in {"SETUP_INVALID", "MISSED_ENTRY_WAIT_NEXT_SETUP"}:
            st.error(f"**{stage_label}** • {stage_reason_text}")
        elif v280_stage in {"BREAK_RISK", "REACTION_VISIBLE", "M5_CONFIRMATION"}:
            st.warning(f"**{stage_label}** • {stage_reason_text}")
        else:
            st.info(f"**{stage_label}** • {stage_reason_text}")

        stage_cols = st.columns(2)
        stage_cols[0].metric(
            "Band entry terpilih",
            (
                f"{_fmt_price(v240_reversal_stage.get('selected_entry_low'))}–"
                f"{_fmt_price(v240_reversal_stage.get('selected_entry_high'))}"
                if v240_reversal_stage.get("selected_entry_low") is not None
                else "Belum tersedia"
            ),
        )
        stage_cols[1].metric(
            "Depth sekarang",
            (
                f"{100.0 * float(v240_reversal_stage.get('depth')):.1f}%"
                if v240_reversal_stage.get("depth") is not None
                else "N/A"
            ),
        )
        stage_cols2 = st.columns(2)
        stage_cols2[0].metric(
            "Batas invalidasi",
            (
                f"distal {_fmt_price(dict(v240_reversal_stage.get('distal') or {}).get('distal'))}"
                if dict(v240_reversal_stage.get("distal") or {}).get("distal") is not None
                else "Belum tersedia"
            ),
        )
        stage_cols2[1].metric(
            "M5 status",
            (
                "CONFIRMED"
                if v240_reversal_stage.get("m5_confirmed")
                else "Reaksi terlihat"
                if v240_reversal_stage.get("reaction_visible")
                else str(dc_micro.get("state") or "WAIT")
            ),
        )
        st.caption(
            "Urutan: REVERSAL WATCH → REAKSI TERLIHAT → KONFIRMASI M5 → ENTRY DEMO DIIZINKAN. "
            "BREAK RISK / SETUP INVALID / MISSED ENTRY menghentikan promosi. "
            "V225 tetap prior historis first-touch; stage ini bukan probabilitas reversal terkalibrasi."
        )

        st.markdown("###### Apa yang harus dilakukan sekarang")
        act1, act2 = st.columns(2)
        act1.metric("Action", v240_action_now)
        act2.metric("Arah aktif V182", v240_direction)
        st.caption(
            f"HTF context={dc_htf_context_bias} • hubungan={v240_current_path_relation} • "
            f"V240 state={v240_state} • direction source="
            f"{v240_decision.get('direction_source') or '—'}."
        )

        st.markdown("###### Struktur aktif — bukan locator historis • role-aware")
        v240_zone_role_state = dict(v240_decision.get("zone_role_state") or {})
        if v240_direction == "LONG":
            demand_role = "ACTIVE SOURCE"
            supply_role = "FORWARD OPPOSING / DESTINATION"
        elif v240_direction == "SHORT":
            demand_role = "FORWARD OPPOSING / DESTINATION"
            supply_role = "ACTIVE SOURCE"
        else:
            demand_role = "STRUCTURAL"
            supply_role = "STRUCTURAL"
        qs1, qs2 = st.columns(2)
        qs1.metric("Demand reversal utama", _quick_zone_text(v240_nearest_demand))
        qs2.metric("Supply reversal utama", _quick_zone_text(v240_nearest_supply))
        st.caption(
            f"Role path aktif: Demand={demand_role} • Supply={supply_role}. "
            "Dashboard operasional V309 hanya menampilkan PRIMARY REVERSAL ZONE yang forward-reachable; "
            "zona dekat/roadblock tetap diagnostic dan tidak menjadi authority path."
        )
        if bool(v240_zone_role_state.get("raw_overlap_detected")):
            st.info(
                "Atlas mendeteksi supply dan demand mentah yang saling overlap. "
                "Itu boleh terjadi karena zona dibentuk independen pada timeframe/umur berbeda, "
                "tetapi dashboard operasional TIDAK lagi memakai keduanya sebagai dua arah entry. "
                "Panel ini menampilkan source dari path aktif dan opposing zone forward sebagai tujuan."
            )
        qs3, qs4 = st.columns(2)
        qs3.metric("Harga XAU sekarang", _fmt_price(dc_reference_price))
        qs4.metric(
            "Source path aktif",
            _quick_zone_text(v240_active_source or v240_local_structure),
        )
        qs5, qs6 = st.columns(2)
        qs5.metric(
            "M15 confirmation",
            "Belum ada"
            if dc_m15_row is None
            else f"{dc_m15_direction} • {dc_m15_state}",
        )
        qs6.metric(
            "M5 timing",
            (
                f"Next {dc_next_leg_direction} refined • " + v240_m5_price_quick
                if v240_m5_state_quick == "NEXT_REFINED_M5_WATCH"
                else f"Next {dc_next_leg_direction} candidate • " + v240_m5_price_quick
                if v240_m5_state_quick == "NEXT_CANDIDATE_M5_WATCH"
                else f"Next {dc_next_leg_direction} • belum confirmed"
                if v240_m5_state_quick == "NEXT_LEG_WAIT"
                and dc_next_leg_direction in {"LONG", "SHORT"}
                else "Refined retest • " + v240_m5_price_quick
                if v240_m5_state_quick == "REFINED_M5_POCKET"
                else "Refined lama • tunggu baru"
                if v240_m5_state_quick == "REFINED_M5_HISTORICAL"
                else "Candidate • " + v240_m5_price_quick
                if v240_m5_state_quick == "CANDIDATE_M5_POCKET"
                else "Projected watch • " + v240_m5_price_quick
                if v240_m5_state_quick == "PROJECTED_M5_WATCH"
                else "Belum aktif"
            ),
        )
        if v240_m5_state_quick == "NEXT_CANDIDATE_M5_WATCH":
            st.warning(
                f"Current leg {v240_direction} sudah mencapai target/opposing zone. "
                f"Pocket M5 berikutnya adalah **{dc_next_leg_direction} candidate** "
                f"{v240_m5_price_quick}, tetapi masih WATCH ONLY — belum refined dan belum entry resmi."
            )
        elif v240_m5_state_quick == "NEXT_REFINED_M5_WATCH":
            st.warning(
                f"Current leg {v240_direction} sudah selesai. Next {dc_next_leg_direction} refined "
                f"{v240_m5_price_quick} adalah handoff watch, bukan entry resmi sampai V182 handoff "
                "dan V240/V229/M15/pressure admission konsisten."
            )
        elif v240_m5_state_quick == "NEXT_LEG_WAIT":
            st.caption(
                f"Current leg {v240_direction} sudah mencapai tujuan. Menunggu M5 baru untuk "
                f"next {dc_next_leg_direction} dari opposing zone."
            )
        elif v240_m5_state_quick == "CANDIDATE_M5_POCKET":
            st.caption(
                "M5 candidate sudah terpetakan tetapi **belum refined**. "
                f"Micro state={dc_micro.get('state') or 'WAIT'}; tunggu reclaim + MSS/displacement "
                "sesuai confirmation contract sebelum dianggap timing entry."
            )
        elif v240_m5_state_quick == "REFINED_M5_POCKET":
            st.caption(
                "M5 refined pocket berada pada sisi limit/retest yang masih valid. "
                "Tetap bukan entry resmi sebelum V240/V229 admission lolos."
            )
        elif v240_m5_state_quick == "REFINED_M5_HISTORICAL":
            st.warning(
                "Refined pocket yang terlihat berasal dari reaksi sebelumnya dan sudah berada "
                "di sisi harga yang tidak valid untuk limit/retest DEMO saat ini. Dashboard "
                "tidak mempromosikannya sebagai entry; tunggu pocket baru dari touch-cycle aktif."
            )
        elif v240_m5_state_quick == "PROJECTED_M5_WATCH":
            st.info(
                "M5 aktual belum membentuk candidate/refined pocket. Agar peta tidak pernah kosong, "
                "dashboard menampilkan **Projected M5 Watch Pocket** dari narrowing H4→H1→M15 "
                "dan historical M15 highest-hazard depth. Ini penanda observasi, **bukan entry broker**; "
                "begitu M5 aktual muncul, pocket aktual otomatis menggantikannya."
            )
        else:
            st.caption(
                "M5 aktual belum aktif dan projected watch pocket belum tersedia."
            )

        if dc_parent_rescue_active:
            st.warning(
                "HTF PARENT REVERSAL RESCUE AKTIF • H1 child sudah ditembus, tetapi sweep masih "
                f"berada di dalam {dc_parent_rescue.get('parent_timeframe') or 'HTF'} parent yang valid. "
                f"Mode={dc_parent_rescue.get('mode') or 'HTF_PARENT_RESCUE'} • "
                f"parent zone={_fmt_price(dc_parent_source_zone.get('low'))}–"
                f"{_fmt_price(dc_parent_source_zone.get('high'))} • "
                f"penetrasi child={_fmt_distance(dc_parent_rescue.get('child_penetration_atr'), ' ATR')}. "
                "M5 candidate/refined tetap dipertahankan sebagai SHADOW/PREPARE; kondisi ini sendiri "
                "tidak memberi execution authority."
            )

        st.markdown("###### Entry riset historis — BUKAN ORDER")
        if v240_hist_entry:
            hr1, hr2 = st.columns(2)
            hr1.metric(
                "Historical entry band",
                (
                    f"{_fmt_price(v240_hist_entry.get('low'))}–"
                    f"{_fmt_price(v240_hist_entry.get('high'))}"
                ),
            )
            hr2.metric(
                "Historical reference",
                _fmt_price(v240_hist_entry.get("reference")),
            )
            hist_ctx = dict(v240_hist_entry.get("historical_context") or {})
            st.caption(
                f"arah={v240_hist_entry.get('direction') or '—'} • "
                f"TF={v240_hist_entry.get('source_timeframe') or '—'} • "
                f"source={v240_hist_entry.get('source_layer') or '—'} • "
                f"prior={v240_hist_entry.get('prior_scope') or '—'} • "
                f"status={v240_hist_entry.get('display_status') or '—'}. "
                f"Reaction evidence H4={_fmt_pct(hist_ctx.get('h4_parent_rate'))}, "
                f"H1={_fmt_pct(hist_ctx.get('h1_standalone_rate'))}, "
                f"M15={_fmt_pct(hist_ctx.get('m15_standalone_rate'))}. "
                "Ini hasil pemetaan riset V225/V226 pada source V182 aktif; "
                "bukan order broker dan bukan win rate trading."
            )
            if str(v240_hist_entry.get("prior_scope") or "").upper() != "FIRST_TOUCH_CALIBRATED":
                st.info(
                    "Zona sudah pernah disentuh/retest: historical entry dipakai sebagai "
                    "geometry/prior context saja. DEMO tetap menunggu pressure + fresh M5 "
                    "confirmation sebelum child order boleh dikirim."
                )
        else:
            st.info(
                "Historical research entry belum tersedia untuk source aktif. "
                "Dashboard tidak menggunakan locator historis lama sebagai pengganti."
            )

        if str(v240_gate_reason).upper() == "WAIT_TERMINAL_RR_BELOW_MINIMUM":
            rr_best = v229_plan_diagnostics.get("best_terminal_rr")
            rr_min = v229_plan_diagnostics.get("minimum_terminal_rr")
            rr_stop = v229_plan_diagnostics.get("structural_stop")
            st.warning(
                "**DEMO belum boleh entry karena RR struktural.** "
                f"RR terminal terbaik saat plan dibangun = "
                f"{_fmt_number(rr_best, 2) if rr_best is not None else 'N/A'}R "
                f"(minimum {_fmt_number(rr_min, 2) if rr_min is not None else '1.50'}R). "
                f"SL struktur={_fmt_price(rr_stop)}. "
                "Scanner sengaja fail-closed; historical entry tetap ditampilkan sebagai riset, "
                "bukan dipaksa menjadi order."
            )
        elif str(v240_gate_reason).upper() == "WAIT_NO_RR_ELIGIBLE_CONFIRMATION_WINDOW":
            st.warning(
                "**DEMO belum boleh entry:** source zone aktif tidak memiliki area entry M5 "
                "yang dapat mencapai terminal RR minimum 1,50R dengan SL struktural saat ini."
            )
        elif str(v240_gate_reason).upper() == "WAIT_NO_FORWARD_STRUCTURAL_TARGET":
            st.warning(
                "**DEMO belum boleh entry:** belum ada opposing Supply/Demand forward "
                "yang dapat menjadi target struktural broker."
            )

        if v240_confirmation_window_armed and v240_confirmation_window:
            cw1, cw2 = st.columns(2)
            cw1.metric(
                "RR-eligible M5 confirmation window",
                (
                    f"{_fmt_price(v240_confirmation_window.get('low'))}–"
                    f"{_fmt_price(v240_confirmation_window.get('high'))}"
                ),
            )
            cw2.metric(
                "RR threshold entry",
                _fmt_price(v240_confirmation_window.get("threshold")),
            )
            st.info(
                "**Belum ada order.** Window ini hanya menunjukkan area di dalam source H1/H4 "
                "di mana entry M5 aktual masih berpotensi memenuhi terminal RR ≥1,50R. "
                "Pada parent retest, L2 tetap OFF. L1 boleh dipakai sekali sebagai **DEMO calibration probe "
                "0,01 lot** memakai M5 pocket aktual bila pressure valid. Jika raw pocket terlalu dalam "
                "tetapi closed M5 sudah reject keluar dari pocket dan kembali ke Dynamic Depth band yang masih "
                "eligible, V270 boleh memakai **post-rejection LIMIT retest** berumur maksimum 60 menit. "
                "Research ceiling L1 adalah 85%; jika depth/hazard/pressure tidak eligible dashboard tetap menulis **PROBE NO-CHASE**. "
                "V271: bila DOM current sample masih fresh tetapi sample pembanding terlambat, hanya DEMO "
                "calibration yang boleh lanjut bila pressure absolut netral/supportive; strict L3/L4 tetap "
                "wajib transition dua-sample. Limit-side harus valid "
                "dan opposing-zone RR ≥1,00R. L3/L4 tetap jalur strict: reclaim/MSS atau displacement "
                "valid dan terminal RR ≥1,50R. TP/SL selalu dihitung dari struktur aktual."
            )

        st.markdown("###### Peta Entry — riset → M5 → DEMO → broker")
        em1, em2 = st.columns(2)
        em1.metric(
            "1 • Historical research entry",
            (
                f"{_fmt_price(v240_hist_entry.get('low'))}–"
                f"{_fmt_price(v240_hist_entry.get('high'))}"
                if v240_hist_entry
                else "Belum tersedia"
            ),
        )
        em2.metric(
            "2 • M5 pocket saat ini",
            v240_m5_price_quick,
        )
        em3, em4 = st.columns(2)
        em3.metric(
            "3 • RR-eligible DEMO window",
            (
                f"{_fmt_price(v240_confirmation_window.get('low'))}–"
                f"{_fmt_price(v240_confirmation_window.get('high'))}"
                if v240_confirmation_window_armed and v240_confirmation_window
                else "Tidak aktif"
            ),
        )
        em4.metric(
            "4 • Official broker entry",
            (
                v240_watch_text
                if v240_effective_entry_authorized
                else "Belum ada • ARMED"
                if v240_confirmation_window_armed
                else "Belum ada • WAIT"
            ),
        )

        m5_window_relation = "UNAVAILABLE"
        try:
            m5_low = float(v240_m5_quick.get("low"))
            m5_high = float(v240_m5_quick.get("high"))
            window_low = float(v240_confirmation_window.get("low"))
            window_high = float(v240_confirmation_window.get("high"))
            overlap_low = max(m5_low, window_low)
            overlap_high = min(m5_high, window_high)
            if overlap_low <= overlap_high:
                m5_window_relation = (
                    "OVERLAP • M5 sudah menyentuh RR-eligible window "
                    f"{_fmt_price(overlap_low)}–{_fmt_price(overlap_high)}"
                )
            elif m5_high < window_low:
                m5_window_relation = (
                    "BELOW WINDOW • M5 masih terlalu dangkal untuk RR ≥1,50R"
                )
            else:
                m5_window_relation = (
                    "ABOVE WINDOW • M5 berada melewati execution window"
                )
        except (TypeError, ValueError):
            pass
        st.caption(
            "Urutan baca: historical entry = prior riset, M5 pocket = timing aktual, "
            "DEMO window = area yang secara struktural masih bisa memenuhi RR, official "
            "broker entry = baru ada setelah semua gate lolos. "
            f"Relasi M5↔window: **{m5_window_relation}**."
        )

        st.markdown("###### V281 Competing Risk — reversal vs break (RISET FIRST-TOUCH)")
        if bool(v284_competing_risk.get("available")):
            v284_rows = list(v284_competing_risk.get("all_bands") or [])
            v284_selected_band = str(v284_competing_risk.get("band") or "")
            v284_cells = []
            for row in v284_rows:
                rev = float(row.get("p_reversal") or 0.0)
                brk = float(row.get("p_break") or 0.0)
                margin = rev - brk
                if margin >= 0.15:
                    bg = "#166534"
                elif margin > 0.0:
                    bg = "#65a30d"
                elif margin > -0.10:
                    bg = "#ca8a04"
                else:
                    bg = "#b91c1c"
                matching_price = next(
                    (
                        h
                        for h in v226_reversal_heatmap
                        if str(h.get("band") or "") == str(row.get("band") or "")
                    ),
                    {},
                )
                border = (
                    "2px solid #ffffff"
                    if str(row.get("band") or "") == v284_selected_band
                    else "1px solid rgba(255,255,255,.18)"
                )
                price_line = (
                    f"{_fmt_price(matching_price.get('price_low'))}–"
                    f"{_fmt_price(matching_price.get('price_high'))}<br>"
                    if matching_price
                    else ""
                )
                v284_cells.append(
                    "<div style='flex:1;min-width:104px;padding:8px;margin:2px;"
                    f"border-radius:8px;background:{bg};color:white;border:{border}'>"
                    f"<b>{row.get('band') or '—'}</b><br>"
                    + price_line
                    + f"REV {_fmt_pct(row.get('p_reversal'))}<br>"
                    + f"BREAK {_fmt_pct(row.get('p_break'))}<br>"
                    + f"n={int(row.get('at_risk') or 0):,}"
                    + "</div>"
                )
            st.markdown(
                "<div style='display:flex;flex-wrap:wrap;gap:2px'>"
                + "".join(v284_cells)
                + "</div>",
                unsafe_allow_html=True,
            )
            selected_risk = dict(v284_competing_risk.get("selected") or {})
            rev_ci = list(selected_risk.get("reversal_wilson_95") or [])
            brk_ci = list(selected_risk.get("break_wilson_95") or [])
            cr1, cr2 = st.columns(2)
            cr1.metric(
                "Historical reversal ≥0,50 ATR",
                _fmt_pct(selected_risk.get("p_reversal")),
            )
            cr2.metric(
                "Historical break / invalid",
                _fmt_pct(selected_risk.get("p_break")),
            )
            st.caption(
                f"Source {v284_competing_risk.get('timeframe') or '—'} "
                f"{v284_competing_risk.get('direction') or '—'} • "
                f"band sekarang={v284_selected_band or '—'} • "
                f"n-at-risk={int(selected_risk.get('at_risk') or 0):,} • "
                f"95% CI reversal="
                f"{_fmt_pct(rev_ci[0]) if len(rev_ci) == 2 else '—'}–"
                f"{_fmt_pct(rev_ci[1]) if len(rev_ci) == 2 else '—'} • "
                f"95% CI break="
                f"{_fmt_pct(brk_ci[0]) if len(brk_ci) == 2 else '—'}–"
                f"{_fmt_pct(brk_ci[1]) if len(brk_ci) == 2 else '—'}. "
                f"Band pertama break historis mengungguli reversal: "
                f"**{v284_competing_risk.get('first_break_dominant_band') or '—'}**."
            )
            oos = dict(v284_competing_risk.get("oos") or {})
            st.info(
                "V281 memakai denominator semua episode **first-touch** yang benar-benar "
                "mencapai band tersebut. Ini conditional historical frequency, bukan "
                "probabilitas live terkalibrasi dan bukan win rate trading. "
                f"OOS {oos.get('test_years') or '2025–2026'}: "
                f"{int(oos.get('test_episode_count') or 0):,} episode / "
                f"{int(oos.get('resolved_exposures') or 0):,} resolved band exposures; "
                f"classification accuracy={_fmt_pct(oos.get('classification_accuracy_resolved_exposures'))}. "
                "Historical pressure stratification memakai causal M1 OHLC proxy; DOM live tetap sumber terpisah."
            )
        else:
            st.info(
                "**V281 tidak dipakai sebagai peluang pada zona retest.** "
                f"reason={v284_competing_risk.get('reason') or 'UNAVAILABLE'} • "
                "V281 mengukur first-touch saja. Untuk retest, dashboard hanya memakai "
                "geometry context + pressure/M5 prospective; tidak mengimpor probabilitas first-touch."
            )

        st.markdown("###### V286 Contextual Competing Risk — RISET FIRST-TOUCH")
        if bool(v286_contextual_risk.get("available")):
            context_cells = dict(v286_contextual_risk.get("cells") or {})
            context_specs = [
                (
                    "Session",
                    context_cells.get("session") or {},
                    str(v286_contextual_risk.get("session") or "—"),
                ),
                (
                    "Volatilitas",
                    context_cells.get("volatility") or {},
                    str(v286_contextual_risk.get("volatility_bucket") or "—"),
                ),
                (
                    "Pressure proxy historis",
                    context_cells.get("historical_pressure_proxy") or {},
                    str(
                        dict(v286_contextual_risk.get("pressure_bridge") or {}).get(
                            "historical_proxy_bucket"
                        )
                        or "—"
                    ),
                ),
                (
                    "Era",
                    context_cells.get("era") or {},
                    str(v286_contextual_risk.get("era") or "—"),
                ),
            ]
            for start in (0, 2):
                cols = st.columns(2)
                for col, (label, cell, key) in zip(cols, context_specs[start : start + 2]):
                    selected = dict(cell.get("selected") or {})
                    col.metric(
                        f"{label} • {key}",
                        (
                            f"REV {_fmt_pct(selected.get('p_reversal'))} / "
                            f"BREAK {_fmt_pct(selected.get('p_break'))}"
                            if selected
                            else "N/A"
                        ),
                        (
                            f"n={int(selected.get('at_risk') or 0):,}"
                            if selected
                            else "cell unavailable"
                        ),
                    )
            bridge = dict(v286_contextual_risk.get("pressure_bridge") or {})
            st.caption(
                f"Band={v286_contextual_risk.get('band') or '—'} • "
                f"session={v286_contextual_risk.get('session') or '—'} • "
                f"volatility={v286_contextual_risk.get('volatility_bucket') or '—'} • "
                f"DOM live={bridge.get('live_dom_state') or 'UNAVAILABLE'} → "
                f"proxy historis={bridge.get('historical_proxy_bucket') or 'UNAVAILABLE'} "
                "(semantic bridge only). "
                "Keempat kartu adalah **marginal contextual splits**, bukan joint probability. "
                "Historical pressure memakai causal M1 OHLC proxy; DOM live tetap cTrader Level-II "
                "dan tidak pernah dianggap sebagai DOM historis."
            )
            st.info(
                "V286 tetap **RISET/FORECAST**: tidak memberi execution authority/influence. "
                "Volatility threshold dibekukan dari 2012–2024; OOS 2025–2026 dipakai untuk "
                "evaluasi event forecast, bukan win rate/PF trading."
            )
        else:
            st.info(
                "**V286 contextual prior tidak berlaku pada retest/reused zone.** "
                f"reason={v286_contextual_risk.get('reason') or 'UNAVAILABLE'} • "
                "Session/volatility/pressure historical first-touch tidak dipromosikan menjadi "
                "probabilitas live pada zona yang sudah disentuh."
            )

        st.markdown("###### Historical Reversal Depth Heatmap — V225.2 (2012–2026)")
        if v226_reversal_heatmap:
            heat_max = max(
                float(item.get("hazard") or 0.0)
                for item in v226_reversal_heatmap
            )
            heat_cells = []
            for heat_row in v226_reversal_heatmap:
                heat_hazard = float(heat_row.get("hazard") or 0.0)
                heat_ratio = 0.0 if heat_max <= 0 else heat_hazard / heat_max
                # Reversal-opportunity semantics: greener = higher
                # conditional reversal hazard; redder = lower/no-chase.
                heat_bg = (
                    "#166534"
                    if bool(heat_row.get("is_highest_hazard"))
                    else "#65a30d"
                    if heat_ratio >= 0.80
                    else "#ca8a04"
                    if heat_ratio >= 0.60
                    else "#b91c1c"
                )
                heat_cells.append(
                    "<div style='flex:1;min-width:92px;padding:8px;margin:2px;"
                    f"border-radius:8px;background:{heat_bg};color:white'>"
                    f"<b>{heat_row.get('band') or '—'}</b><br>"
                    f"{_fmt_price(heat_row.get('price_low'))}–"
                    f"{_fmt_price(heat_row.get('price_high'))}<br>"
                    f"hazard {_fmt_pct(heat_row.get('hazard'))}<br>"
                    f"n={int(heat_row.get('at_risk') or 0):,}"
                    "</div>"
                )
            st.markdown(
                "<div style='display:flex;flex-wrap:wrap;gap:2px'>"
                + "".join(heat_cells)
                + "</div>",
                unsafe_allow_html=True,
            )
            top_heat = next(
                (
                    item
                    for item in v226_reversal_heatmap
                    if bool(item.get("is_highest_hazard"))
                ),
                {},
            )
            st.caption(
                f"Source {v226_reversal_heatmap_source.get('timeframe') or '—'} "
                f"{v226_reversal_heatmap_source.get('direction') or '—'} • "
                "0% = sisi pertama harga memasuki zona, 100% = sisi terdalam. "
                f"Band reversal hazard tertinggi saat ini: **{top_heat.get('band') or '—'}** "
                f"({_fmt_price(top_heat.get('price_low'))}–{_fmt_price(top_heat.get('price_high'))}, "
                f"hazard {_fmt_pct(top_heat.get('hazard'))}). "
                "Hazard adalah conditional reversal rate per depth band, bukan win rate order. "
                "Warna hijau = reversal hazard relatif lebih tinggi; kuning = menengah; "
                "merah = reversal hazard rendah / NO-CHASE."
            )
        else:
            st.caption("Heatmap depth historis belum tersedia untuk source aktif.")

        st.markdown("###### Entry → Dynamic Depth → Admission")
        qe1, qe2 = st.columns(2)
        qe1.metric(v240_entry_label, v240_watch_text)
        qe2.metric(
            "8 • Dynamic Depth Hazard"
            if v240_depth_calibrated
            else "8 • Lokasi vs source zone",
            v240_depth_text,
        )
        st.caption(
            f"{v240_depth_band_text} • source={v240_decision.get('source_layer') or 'V182 current path'} • "
            f"reference={_fmt_price(v240_decision.get('entry_reference'))}. "
            + (
                "Hazard hanya menjadi timing context dan tidak pernah memberi izin order sendirian. "
                + (
                    f"DEMO probe 0,01 lot: **{v240_probe_depth_text}** "
                    f"(hard ceiling {_fmt_pct(v240_probe_depth_ceiling)}). "
                    "Status probe terpisah dari strict L3/L4; strict masih wajib M5 reclaim/MSS "
                    "atau displacement + terminal RR ≥1,50R."
                    if v240_probe_depth_ceiling is not None
                    else ""
                )
                if v240_depth_calibrated
                else "Tanpa V229 geometry yang aligned, dashboard sengaja tidak menghitung reversal band."
            )
        )
        qe3, qe4 = st.columns(2)
        qe3.metric(
            "9 • Pressure / DOM",
            (
                "STALE"
                if v240_dom_stale
                else (
                    f"{v240_pressure_trend}"
                    + (
                        " • DEMO CAL OK"
                        if (
                            v240_pressure_trend == "WAIT_SECOND_SAMPLE"
                            and v240_calibration_pressure_allowed
                        )
                        else ""
                    )
                    + f" • B {_fmt_number(v240_buyer_index, 0)} / S {_fmt_number(v240_seller_index, 0)}"
                )
            ),
        )
        qe4.metric(
            "10 • Execution Admission",
            f"{v240_admission_label} • {v240_route_label}",
        )
        if (
            v240_pressure_trend == "WAIT_SECOND_SAMPLE"
            and v240_current_dom_sample_fresh
        ):
            st.caption(
                "DOM current sample masih fresh, tetapi strict transition belum punya second sample yang "
                "cukup dekat. "
                + (
                    "**DEMO calibration pressure eligible** — hanya jalur calibration 0,01 lot; "
                    "strict L3/L4 tetap BLOCK sampai dua-sample transition valid."
                    if v240_calibration_pressure_allowed
                    else "**DEMO calibration pressure BLOCK** — absolute opposing pressure masih terlalu kuat."
                )
                + (
                    f" • {v240_calibration_pressure_reason}"
                    if v240_calibration_pressure_reason
                    else ""
                )
            )

        st.markdown("###### Risk & target")
        qr1, qr2 = st.columns(2)
        qr1.metric("11 • SL resmi", v240_sl_text)
        qr2.metric("12 • TP order resmi", v240_tp_text)
        qr3, qr4 = st.columns(2)
        qr3.metric(
            "13 • Path target (BUKAN TP order)",
            (
                "SUDAH TERCAPAI • " + _fmt_price(v240_destination.get("target_price"))
                if v240_destination.get("role") == "PATH_TARGET_REACHED"
                and v240_destination.get("target_price") is not None
                else _fmt_price(v240_destination.get("target_price"))
                if v240_destination.get("target_price") is not None
                else "Belum tersedia"
            ),
        )
        qr4.metric(
            "14 • WAIT / BLOCK reason",
            _human_wait_reason(v240_gate_reason),
        )
        if v240_destination:
            st.caption(
                "Opposing zone tujuan: "
                f"{_fmt_price(v240_destination.get('zone_low'))}–"
                f"{_fmt_price(v240_destination.get('zone_high'))} • "
                f"state={v240_destination.get('destination_state') or v240_decision.get('path_destination_state') or '—'} • "
                f"role={v240_destination.get('role') or 'PATH WATCH'}. "
                + (
                    "Current leg sudah mencapai area tujuan; fokus berikutnya adalah watch next-leg, bukan mengejar target lama."
                    if v240_destination.get("role") == "PATH_TARGET_REACHED"
                    else "Jika belum ada admission, angka ini adalah tujuan struktur, bukan TP order."
                )
            )
        qr5, qr6 = st.columns(2)
        qr5.metric("15 • Lifecycle", _human_wait_reason(v240_state))
        qr6.metric("16 • Session WIB", f"{v240_session} • {v240_wib_clock}")
        st.info(
            "**Alasan keputusan saat ini:** "
            + _human_wait_reason(v240_gate_reason)
        )

        if not v240_effective_entry_authorized:
            st.warning(
                "**Belum ada entry resmi.** Zona yang ditampilkan adalah watch/current path. "
                "SL dan TP order sengaja disembunyikan sampai V229 geometry, M15, pressure, "
                "freshness, dan broker admission konsisten."
            )
        if v240_conflicts:
            st.caption(
                "Diagnostik (tidak otomatis menjadi arah): "
                + ", ".join(str(x) for x in v240_conflicts)
            )
        if v240_stale or backend_snapshot_stale:
            st.error(
                "Data decision stale. Semua angka di panel ini hanya konteks diagnostik; "
                "Admission dipaksa NO ORDER sampai snapshot fresh."
            )

        st.markdown("###### Buyer / Seller Pressure — timing masuk zona")
        st.caption(
            f"Pressure source aktif: **{v240_pressure_source}**. "
            "DOM tetap ditampilkan terpisah; RIZAN Composite adalah pressure berbasis harga, "
            "bukan volume/order-flow global."
        )
        pr1, pr2 = st.columns(2)
        pr1.metric(
            "Buyer index",
            "—"
            if v240_effective_buyer_index is None
            else f"{float(v240_effective_buyer_index):.1f}/100",
        )
        pr2.metric(
            "Seller index",
            "—"
            if v240_effective_seller_index is None
            else f"{float(v240_effective_seller_index):.1f}/100",
        )
        pr3, pr4 = st.columns(2)
        pr3.metric(
            "Incoming pressure vs zona",
            "—"
            if v240_effective_opposing_pressure is None
            else f"{float(v240_effective_opposing_pressure):+.1f}",
        )
        pr4.metric(
            "Penetration risk",
            str(v240_penetration_risk).split(" —", 1)[0],
        )
        pt1, pt2 = st.columns(2)
        pt1.metric("Pressure transition", v240_effective_pressure_state)
        pt2.metric(
            "Pre-touch DEMO (strict)",
            "ALLOW" if v240_pressure_transition.get("pre_touch_entry_allowed") else "WAIT",
        )
        pc1, pc2 = st.columns(2)
        pc1.metric(
            "M5-confirm DEMO (strict)",
            "ALLOW" if v240_pressure_transition.get("confirmation_entry_allowed") else "WAIT",
        )
        composite_calibration_allowed = bool(
            v240_composite_pressure.get(
                "long_calibration_allowed"
                if v240_direction == "LONG"
                else "short_calibration_allowed"
                if v240_direction == "SHORT"
                else "",
                False,
            )
        )
        pc2.metric(
            "DEMO calibration",
            "ALLOW"
            if (
                v240_calibration_pressure_allowed
                or (
                    v240_pressure_source == "RIZAN_COMPOSITE"
                    and composite_calibration_allowed
                )
            )
            else "WAIT",
        )
        st.caption(f"Penetration detail: {v240_penetration_risk}")
        if v240_dom_score is None:
            st.warning(
                "DOM Level-II belum tersedia. Dashboard tidak mengarang buyer/seller pressure. "
                + (
                    "Dynamic Depth hazard tetap hanya context dari geometry V229 yang sudah aligned."
                    if v240_depth_calibrated
                    else "Karena V229 belum aligned, yang ditampilkan hanya posisi geometris dalam zona."
                )
            )
        elif v240_dom_stale:
            st.warning(
                f"Pressure terakhir **STALE** (age={'—' if v240_dom_age is None else f'{v240_dom_age:.0f}s'}). "
                f"State terakhir={v240_dom_state} • transition={v240_pressure_trend}. "
                "Jangan perlakukan sebagai microstructure live sampai V191 refresh."
            )
        else:
            st.info(
                f"DOM **{v240_dom_state}** • transition **{v240_pressure_trend}** • "
                f"top-5 imbalance="
                + (
                    "—"
                    if v240_pressure_transition.get("last_imbalance") is None
                    else f"{float(v240_pressure_transition.get('last_imbalance')):+.2f}"
                )
                + ". Gate DEMO aktif: pre-touch child hanya boleh masuk setelah transition "
                "cukup matang; child M5 boleh masuk lebih awal ketika opposing pressure mulai "
                "fading tetapi reclaim/MSS/displacement sudah terkonfirmasi."
            )
        st.caption(
            "DOM Buyer/Seller index berasal dari cTrader Level-II broker/venue. Jika DOM stale/tidak "
            "tersedia, V272 menampilkan RIZAN Composite Pressure dari M5/M15: DI + EMA structure/slope "
            "+ candle pressure + directional efficiency, dengan ADX/ADXR hanya sebagai pengukur "
            "kekuatan/stabilitas tren. Composite bukan volume global COMEX dan bukan probabilitas."
        )

        if v240_composite_available:
            comp_m5 = dict(v240_composite_pressure.get("m5") or {})
            comp_m15 = dict(v240_composite_pressure.get("m15") or {})
            composite_gap = (
                None
                if v240_dom_score is None or v240_composite_buyer is None
                else abs(float(v240_dom_score) - float(v240_composite_buyer))
            )
            cp1, cp2 = st.columns(2)
            cp1.metric(
                "Composite M5",
                f"{float(comp_m5.get('buyer_index') or 50.0):.1f} buyer",
            )
            cp2.metric(
                "Composite M15",
                f"{float(comp_m15.get('buyer_index') or 50.0):.1f} buyer",
            )
            cp3, cp4 = st.columns(2)
            cp3.metric(
                "M5 ADX / ADXR",
                (
                    f"{float(comp_m5.get('adx14') or 0.0):.1f} / "
                    f"{float(comp_m5.get('adxr14') or 0.0):.1f}"
                ),
            )
            cp4.metric(
                "M15 ADX / ADXR",
                (
                    f"{float(comp_m15.get('adx14') or 0.0):.1f} / "
                    f"{float(comp_m15.get('adxr14') or 0.0):.1f}"
                ),
            )
            st.caption(
                "DOM ↔ Composite gap: "
                + ("—" if composite_gap is None else f"{composite_gap:.1f} poin")
                + ". Gap besar adalah konflik evidence, bukan alasan otomatis untuk entry."
            )

        m30_supply = dict(v240_m30_shadow.get("nearest_supply") or {})
        m30_demand = dict(v240_m30_shadow.get("nearest_demand") or {})
        if m30_supply or m30_demand:
            st.markdown("###### M30 Parent Zone Shadow — kalibrasi gaya Afiq")
            m30_focus = (
                m30_demand
                if v240_direction == "LONG"
                else m30_supply
                if v240_direction == "SHORT"
                else {}
            )
            m30_overlap = m30_focus.get("canonical_overlap_ratio") if m30_focus else None
            m30_match_tf = m30_focus.get("canonical_match_timeframe") if m30_focus else None
            mz1, mz2 = st.columns(2)
            mz1.metric(
                "M30 demand",
                (
                    "—"
                    if not m30_demand
                    else f"{_fmt_price(m30_demand.get('low'))}–{_fmt_price(m30_demand.get('high'))}"
                ),
            )
            mz2.metric(
                "M30 supply",
                (
                    "—"
                    if not m30_supply
                    else f"{_fmt_price(m30_supply.get('low'))}–{_fmt_price(m30_supply.get('high'))}"
                ),
            )
            mz3, mz4 = st.columns(2)
            mz3.metric(
                "Overlap canonical",
                (
                    "—"
                    if m30_overlap is None
                    else f"{100.0 * float(m30_overlap):.0f}%"
                ),
            )
            mz4.metric("Parent match", str(m30_match_tf or "NONE"))
            rejection_state = str(v240_m30_rejection.get("state") or "UNAVAILABLE")
            rejection_max_depth = v240_m30_rejection.get("max_depth")
            rejection_close_depth = v240_m30_rejection.get("latest_close_depth")
            rejection_retreat = v240_m30_rejection.get("confirmation_retreat")
            rz1, rz2 = st.columns(2)
            rz1.metric(
                "M30 deep-rejection",
                rejection_state,
            )
            rz2.metric(
                "Max depth",
                (
                    "—"
                    if rejection_max_depth is None
                    else f"{100.0 * float(rejection_max_depth):.0f}%"
                ),
            )
            rz3, rz4 = st.columns(2)
            rz3.metric(
                "Close depth sekarang",
                (
                    "—"
                    if rejection_close_depth is None
                    else f"{100.0 * float(rejection_close_depth):.0f}%"
                ),
            )
            rz4.metric(
                "Retreat dari max",
                (
                    "—"
                    if rejection_retreat is None
                    else f"{100.0 * float(rejection_retreat):.0f}% lebar zona"
                ),
            )
            policy_lane = str(v240_m30_policy.get("lane") or "NONE")
            policy_state = str(v240_m30_policy.get("lane_state") or "WAIT")
            policy_ev = dict(v240_m30_policy.get("research_evidence") or {})
            near_rate = policy_ev.get("near_edge_hold_050_same_confirmed_population")
            deep_rate = policy_ev.get("deep_rejection_hold_050_rate")
            policy1, policy2 = st.columns(2)
            policy1.metric("V278 lane", policy_lane)
            policy2.metric("Lane state", policy_state)
            if near_rate is not None and deep_rate is not None:
                st.info(
                    "V278 frozen 100K-bar evidence • near-edge first-touch **"
                    f"{100.0 * float(near_rate):.1f}%** vs deep-rejection **"
                    f"{100.0 * float(deep_rate):.1f}%** reaction ≥0,50 ATR "
                    "pada populasi holdout yang sama. Ini **research rate**, bukan "
                    "probabilitas live. Near-edge tetap primary DEMO calibration; "
                    "deep-rejection hanya recovery/re-entry bila primary terlewat."
                )
            if rejection_state == "DEEP_REJECTION_CONFIRMED":
                st.success(
                    "V277: parent M30 sudah penetrasi ≥60% lalu closed kembali ≤55% depth "
                    "dengan retreat ≥20% lebar zona. Ini **deep-rejection confirmed**. "
                    "V278 memperlakukannya sebagai recovery watch, bukan primary entry; "
                    "order strict tetap menunggu M5 retest/structure."
                )
            elif rejection_state == "DEEP_TOUCH_WAIT_REJECTION":
                st.warning(
                    "V277: harga sudah deep touch parent M30, tetapi rejection belum cukup. "
                    "Jangan menganggap depth dalam sebagai reversal otomatis."
                )
            elif rejection_state == "PARENT_INVALIDATED":
                st.error(
                    "V277: completed M5 sudah menerima harga melewati distal parent M30. "
                    "Parent zone ini dianggap invalid."
                )
            st.caption(
                "M30 adalah shadow parent-zone saja. H4/H1 tetap canonical, M15/M5 tetap refinement. "
                "V273 menguji apakah overlap tinggi M30↔H1/H4 benar-benar menaikkan reaction ≥0,50 ATR; "
                "V277 membandingkan near-edge dengan deep-rejection "
                "(≥60% penetration → retreat ≥20% → close ≤55% depth). "
                "V278 membekukan hasil holdout: near-edge sebagai primary, deep-rejection sebagai recovery. "
                "Semua angka tetap research evidence dan tidak otomatis menjadi authority order."
            )

        st.markdown(
            "###### Dynamic Depth Hazard — next depth / reversal window"
            if v240_depth_calibrated
            else "###### Lokasi vs source zone — geometry only (BUKAN reversal forecast)"
        )
        hz1, hz2 = st.columns(2)
        hz1.metric(
            "Current depth",
            v240_depth_text,
        )
        hz2.metric(
            "Hazard action",
            _human_wait_reason(v240_depth_hazard.get("action") or "WAIT"),
        )
        hz3, hz4 = st.columns(2)
        hz3.metric(
            "Next reversal band",
            (
                "N/A — geometry only"
                if str(v240_depth_hazard.get("state") or "") == "GEOMETRY_ONLY"
                else "Belum tersedia"
                if v240_depth_hazard.get("recommended_depth_low") is None
                else (
                    f"{100.0 * float(v240_depth_hazard.get('recommended_depth_low')):.0f}–"
                    f"{100.0 * float(v240_depth_hazard.get('recommended_depth_high')):.0f}%"
                )
            ),
        )
        hz4.metric(
            "Harga band",
            (
                "N/A — geometry only"
                if str(v240_depth_hazard.get("state") or "") == "GEOMETRY_ONLY"
                else "Belum tersedia"
                if v240_depth_hazard.get("recommended_price_low") is None
                else (
                    f"{_fmt_price(v240_depth_hazard.get('recommended_price_low'))}–"
                    f"{_fmt_price(v240_depth_hazard.get('recommended_price_high'))}"
                )
            ),
        )
        child_status_by_slot: dict[str, str] = {}
        for raw_child in list(v229_exec_plan.get("children") or []):
            child = dict(raw_child)
            slot = str(child.get("slot") or "").upper()
            if not slot:
                continue
            if bool(child.get("submit_eligible")):
                status = "ELIGIBLE"
            elif bool(child.get("execution_enabled")):
                status = "ARMED / WAIT"
            else:
                status = "OFF / CONFIRM"
            child_status_by_slot[slot] = status
        st.markdown("###### Child L1–L4 — status eksekusi DEMO")
        l1, l2 = st.columns(2)
        l1.metric("L1", child_status_by_slot.get("L1", "WAIT"))
        l2.metric("L2", child_status_by_slot.get("L2", "WAIT"))
        l3, l4 = st.columns(2)
        l3.metric("L3", child_status_by_slot.get("L3", "WAIT"))
        l4.metric("L4", child_status_by_slot.get("L4", "WAIT"))
        st.caption(
            "L1/L2 = pre-touch depth child bila lifecycle mengizinkan; "
            "L3/L4 = confirmation child. Pada retest M15, L1/L2 tetap OFF dan L3/L4 "
            "baru boleh aktif setelah pressure + M5 confirmation."
        )

        if str(v240_depth_hazard.get("state") or "") == "DYNAMIC_DEPTH_HAZARD_AVAILABLE":
            best_hazard = dict(v240_depth_hazard.get("recommended_band") or {})
            st.info(
                "Sequential hazard aktif • "
                f"source={v240_depth_hazard.get('timeframe','—')} • "
                f"base hazard={float(best_hazard.get('hazard') or 0.0):.1%} • "
                f"adjusted={float(best_hazard.get('adjusted_hazard') or 0.0):.1%} • "
                f"action={v240_depth_hazard.get('action','WAIT')}. "
                "Band ini hanya berlaku pada V229/V226 geometry yang aligned; admission tetap wajib."
            )
        elif str(v240_depth_hazard.get("state") or "") == "GEOMETRY_ONLY":
            st.info(
                "Dynamic Depth **geometry-only** • "
                f"lokasi={v240_depth_hazard.get('location_state','—')} • "
                f"depth={v240_depth_text}. Tidak ada reversal/hazard band yang diproyeksikan "
                "karena V226/V229 belum aligned dengan current V182 path. **NO ORDER authority.**"
            )
        else:
            st.warning(
                "Dynamic Depth belum tersedia: "
                + str(v240_depth_hazard.get("reason") or "missing current structural geometry")
            )

        hazard_future_rows = [
            {
                "band": row.get("band"),
                "depth_low": row.get("lower_depth"),
                "depth_high": row.get("upper_depth"),
                "price_low": row.get("price_low"),
                "price_high": row.get("price_high"),
                "base_hazard": row.get("hazard"),
                "adjusted_hazard": row.get("adjusted_hazard"),
                "at_risk": row.get("at_risk"),
                "distance_bands": row.get("distance_bands"),
            }
            for row in list(v240_depth_hazard.get("future_bands") or [])
        ]
        if hazard_future_rows:
            st.dataframe(
                pd.DataFrame(hazard_future_rows),
                hide_index=True,
                width="stretch",
            )
        st.caption(
            "Prior scope: "
            f"{v240_depth_hazard.get('historical_prior_scope','—')} • "
            f"retest confirmation required="
            f"{'YES' if v240_depth_hazard.get('retest_confirmation_required') else 'NO'}. "
            + (
                "Geometry-only berarti hanya posisi fisik harga terhadap zona; tidak ada klaim probabilitas reversal."
                if str(v240_depth_hazard.get("state") or "") == "GEOMETRY_ONLY"
                else "Hazard prior tetap tidak boleh dipakai sebagai probabilitas reuse atau izin order."
            )
        )

        st.markdown("###### V282 Forward Latency — observability DEMO")
        v282_plan_count = int(v282_lifecycle_metrics.get("plans") or 0)
        v282_cancel_rate = v282_lifecycle_metrics.get("cancellation_rate")
        v282_execution_rate = v282_lifecycle_metrics.get("execution_conversion_rate")
        v282_prevented = int(v282_lifecycle_metrics.get("v280_prevented_entry_count") or 0)
        lat1, lat2 = st.columns(2)
        lat1.metric(
            "Forward plans",
            f"{v282_plan_count:,}",
            (
                "sample kecil"
                if v282_plan_count < 25
                else "sample observability"
            ),
        )
        lat2.metric(
            "Execution conversion",
            _fmt_pct(v282_execution_rate),
            f"cancel {_fmt_pct(v282_cancel_rate)}",
        )

        def _latency_median(label: str) -> str:
            row = dict(v282_latency_metrics.get(label) or {})
            value = row.get("median_minutes")
            n = int(row.get("n") or 0)
            return (
                f"{float(value):.1f} menit • n={n}"
                if value is not None
                else f"N/A • n={n}"
            )

        lat3, lat4 = st.columns(2)
        lat3.metric(
            "Touch → konfirmasi",
            _latency_median("first_touch_to_confirmation"),
        )
        lat4.metric(
            "Konfirmasi → ready",
            _latency_median("confirmation_to_execution_ready"),
        )
        lat5, lat6 = st.columns(2)
        lat5.metric(
            "Ready → order accepted",
            _latency_median("execution_ready_to_order_accepted"),
        )
        lat6.metric(
            "V280 entry dicegah",
            str(v282_prevented),
            (
                f"no-chase={int(v282_lifecycle_metrics.get('v280_no_chase_prevented_count') or 0)} • "
                f"break={int(v282_lifecycle_metrics.get('v280_break_risk_block_count') or 0)} • "
                f"invalid={int(v282_lifecycle_metrics.get('v280_setup_invalid_block_count') or 0)}"
            ),
        )
        if v282_plan_count < 25:
            st.warning(
                "**Forward sample belum cukup untuk inferensi performa.** "
                f"Baru {v282_plan_count} plan lifecycle dalam window observability. "
                "Gunakan panel ini untuk mengukur bottleneck waktu dan entry yang dicegah, "
                "bukan untuk menyimpulkan win rate/PF/expectancy."
            )
        else:
            st.info(
                "V282 adalah telemetry forward DEMO. Latency dihitung dari timestamp lifecycle "
                "aktual; tetap bukan bukti profitabilitas sampai jumlah trade OOS/forward memenuhi gate."
            )
        st.caption(
            "Egress: heartbeat V282 dibaca pada support cadence 1 jam; lifecycle reconstruction "
            "sendiri dibatasi 7 hari dengan narrow fields. Tidak ada polling baru per 60 detik."
        )

        st.markdown("###### Current Supply/Demand Lifecycle")
        lifecycle_rows_dashboard = []
        for role, zone in (
            ("CURRENT SOURCE", v240_active_source or v240_local_structure),
            ("PRIMARY REVERSAL DEMAND", v240_nearest_demand),
            ("PRIMARY REVERSAL SUPPLY", v240_nearest_supply),
        ):
            zone = dict(zone or {})
            if not zone:
                continue
            lifecycle_rows_dashboard.append(
                {
                    "role": role,
                    "TF": zone.get("timeframe"),
                    "direction": zone.get("direction"),
                    "zone": (
                        f"{_fmt_price(zone.get('low'))}–"
                        f"{_fmt_price(zone.get('high'))}"
                    ),
                    "touch": zone.get("touch_count"),
                    "freshness": zone.get("freshness"),
                    "score": zone.get("research_score"),
                }
            )
        if lifecycle_rows_dashboard:
            st.dataframe(
                pd.DataFrame(lifecycle_rows_dashboard),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("Lifecycle current path belum tersedia.")

        st.caption(
            "Tabel ini hanya menampilkan struktur current V182/V240. "
            "Lifecycle H4/H1/M15 V226 historis dipindahkan ke panel riset V226 agar "
            "tidak terlihat seperti zona entry operasional."
        )
        with st.expander("Riset lifecycle V226 historis", expanded=False):
            v226_lifecycle_rows = [
                {
                    "TF": "H4",
                    "zone": (
                        f"{_fmt_price(dict(v226_h4.get('zone') or {}).get('low'))}–"
                        f"{_fmt_price(dict(v226_h4.get('zone') or {}).get('high'))}"
                    ),
                    "touch": v226_h4_app.get("touch_count"),
                    "freshness": v226_h4_app.get("freshness"),
                    "state": v226_h4_app.get("state"),
                    "prior_scope": v226_h4_app.get("prior_scope"),
                },
                {
                    "TF": "H1",
                    "zone": (
                        f"{_fmt_price(dict(v226_h1.get('zone') or {}).get('low'))}–"
                        f"{_fmt_price(dict(v226_h1.get('zone') or {}).get('high'))}"
                    ),
                    "touch": v226_h1_app.get("touch_count"),
                    "freshness": v226_h1_app.get("freshness"),
                    "state": v226_h1_app.get("state"),
                    "prior_scope": v226_h1_app.get("prior_scope"),
                },
                {
                    "TF": "M15",
                    "zone": (
                        f"{_fmt_price(dict(v226_m15.get('zone') or {}).get('low'))}–"
                        f"{_fmt_price(dict(v226_m15.get('zone') or {}).get('high'))}"
                    ),
                    "touch": v226_m15_app.get("touch_count"),
                    "freshness": v226_m15_app.get("freshness"),
                    "state": v226_m15_app.get("state"),
                    "prior_scope": v226_m15_app.get("prior_scope"),
                },
            ]
            st.dataframe(
                pd.DataFrame(v226_lifecycle_rows),
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "V226 lifecycle = research/depth context. Candidate lama tidak mengalahkan "
                "current V182 path dan tidak menjadi entry tanpa aligned V229 plan."
            )

        st.markdown("###### V229 DEMO Execution — producer + child executor")
        ex1, ex2, ex3, ex4 = st.columns(4)
        ex1.metric(
            "Execution producer",
            str(v229_exec_details.get("reason") or "NO HEARTBEAT"),
        )
        ex2.metric(
            "Execution phase",
            str(v229_exec_plan.get("execution_phase") or "—"),
        )
        ex3.metric(
            "Signal",
            str(v229_exec_details.get("signal_id") or "—")[:18],
        )
        ex4.metric(
            "Child executor",
            "HEALTHY"
            if v229_child_executor_hb is not None and bool(v229_child_executor_hb.get("healthy"))
            else "WAIT / NO HEARTBEAT",
        )
        if v229_exec_plan:
            execution_child_rows = []
            for child in list(v229_exec_plan.get("children") or []):
                row = dict(child)
                execution_child_rows.append(
                    {
                        "slot": row.get("slot"),
                        "enabled": row.get("execution_enabled"),
                        "mode": row.get("execution_mode"),
                        "entry/ref": row.get("planned_entry") or row.get("reference_price"),
                        "SL": row.get("planned_sl"),
                        "TP": row.get("planned_tp"),
                        "target_tf": row.get("target_timeframe"),
                        "submit_eligible": row.get("submit_eligible"),
                    }
                )
            if execution_child_rows:
                st.dataframe(
                    pd.DataFrame(execution_child_rows),
                    hide_index=True,
                    width="stretch",
                )
        if v229_child_actions:
            st.caption("Aksi child executor terbaru:")
            st.dataframe(
                pd.DataFrame({"action": v229_child_actions}),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption(
                "Belum ada aksi child executor pada heartbeat terakhir. Ketika order dipasang, "
                "ditahan, dibatalkan, atau menunggu depth/pressure/M5, alasan akan muncul di sini."
            )

        st.markdown("###### Primary Reversal Watch — area tujuan sebelum potensi reversal")
        rw1, rw2, rw3, rw4 = st.columns(4)
        rw1.metric(
            "Area reversal utama",
            (
                f"{_fmt_price(v240_reversal_watch.get('low'))}–"
                f"{_fmt_price(v240_reversal_watch.get('high'))}"
                if v240_reversal_watch else "—"
            ),
        )
        rw2.metric("P touch (research)", _fmt_pct(v240_reversal_watch.get("p_touch")))
        rw3.metric(
            "P reaksi ≥0.50 ATR",
            _fmt_pct(v240_reversal_watch.get("p_hold_050")),
        )
        rw4.metric(
            "Touch×Reaction score",
            _fmt_pct(v240_reversal_watch.get("research_joint_score")),
        )
        if v240_reversal_watch:
            st.caption(
                f"{v240_reversal_watch.get('timeframe','—')} "
                f"{v240_reversal_watch.get('direction','—')} • "
                f"confidence={v240_reversal_watch.get('confidence','—')} • "
                f"P break={_fmt_pct(v240_reversal_watch.get('p_break'))} • "
                f"jarak={_fmt_price(v240_reversal_watch.get('distance_points'))} poin. "
                "Touch×Reaction adalah skor riset untuk meranking zona tujuan + potensi reaksi; "
                "bukan probabilitas terkalibrasi dan bukan izin entry."
            )
        else:
            st.caption(
                "Belum ada opposing zone di depan harga yang memiliki evidence V212 lengkap "
                "untuk touch dan reaction. Dashboard tidak mengarang probabilitas reversal."
            )

        st.caption(
            "Historical reaction context: "
            f"H4 {_fmt_pct(v240_hist.get('h4_parent_rate'))} • "
            f"H1 {_fmt_pct(v240_hist.get('h1_standalone_rate'))} • "
            f"M15 {_fmt_pct(v240_hist.get('m15_standalone_rate'))}. "
            "Angka ini adalah reaction evidence, bukan win rate trading atau profit factor."
        )
        if v240_conflicts:
            st.error(
                "**CONFLICT WAIT:** " + ", ".join(str(x) for x in v240_conflicts)
                + ". Tidak ada angka entry/SL/TP lama yang boleh dipromosikan menjadi order baru."
            )
        elif v240_stale:
            st.warning(
                "**STALE WAIT:** " + ", ".join(str(x) for x in v240_stale)
                + ". Level tetap ditampilkan sebagai snapshot terakhir, tetapi bukan harga/otoritas live."
            )
        elif str(v240_decision.get("state") or "") == "CANONICAL_PLAN_READY":
            st.success(
                "**Canonical plan konsisten.** Harga → Depth Entry → SL/invalidation → "
                "TP struktural terdekat → opposing Supply/Demand. Execution tetap mengikuti admission DEMO."
            )
        else:
            st.info(
                "Depth/Atlas tersedia sebagai preparation, tetapi V229 belum dapat membentuk plan resmi. "
                "Jangan mengisi SL/TP dari panel lama secara manual."
            )
    v241_truth = build_xau_profitability_truth(
        outcomes=[] if backend is None else list(backend.get("xau_outcomes") or []),
        performance=[] if backend is None else list(backend.get("performance") or []),
    )
    v241_perf = dict(v241_truth.get("performance") or {})
    v241_sd = dict(v241_truth.get("supply_demand_reaction") or {})
    v241_exec = dict(v241_truth.get("authorized_execution") or {})

    with st.container(border=True):
        st.markdown("##### V241 — XAU Profitability Truth")
        st.caption(
            "Pisahkan kualitas reaction Supply/Demand dari profitabilitas trading. "
            "Reaction ≥0,50 ATR bukan win rate; Profit Factor/expectancy hanya boleh berasal "
            "dari sample execution/OOS yang benar-benar tersimpan."
        )
        pt1, pt2, pt3, pt4 = st.columns(4)
        pt1.metric(
            "S/D prospective hold",
            _fmt_pct(v241_sd.get("precision_hold")),
            delta=f"{v241_sd.get('holds',0)}/{v241_sd.get('resolved',0)} resolved",
        )
        pt2.metric(
            "Primary S/D candidate",
            _fmt_pct(v241_sd.get("primary_precision")),
            delta=f"n={v241_sd.get('primary_n',0)} / min {v241_sd.get('minimum_n',50)}",
        )
        pt3.metric(
            "Broker-authorized terminal sample",
            str(v241_exec.get("terminal_rows", 0)),
            delta=f"{v241_exec.get('authorized_rows',0)} rows total",
        )
        pt4.metric(
            "Profitability validation",
            (
                "AVAILABLE"
                if v241_perf.get("available")
                else "NOT VALIDATED"
            ),
        )

        if v241_perf.get("available"):
            pp1, pp2, pp3, pp4 = st.columns(4)
            pp1.metric("OOS Win rate", _fmt_pct(v241_perf.get("win_rate")))
            pp2.metric(
                "Profit Factor",
                _fmt_number(v241_perf.get("profit_factor"), 2),
            )
            pp3.metric(
                "Expectancy",
                (
                    "—"
                    if v241_perf.get("expectancy_r") is None
                    else f"{float(v241_perf.get('expectancy_r')):.3f}R"
                ),
            )
            pp4.metric(
                "Max DD",
                (
                    "—"
                    if v241_perf.get("max_drawdown_r") is None
                    else f"{float(v241_perf.get('max_drawdown_r')):.2f}R"
                ),
            )
            st.caption(
                f"setup={_rizan_display(v241_perf.get('setup_type','—'))} • "
                f"scope={v241_perf.get('sample_scope','—')} • "
                f"trades={v241_perf.get('trades',0)} • "
                f"as_of={_fmt_wib_datetime(v241_perf.get('as_of'))}."
            )
        else:
            st.warning(
                "**Belum ada row OOS XAU di model_performance.** "
                "Karena itu dashboard tidak boleh mengklaim win rate atau Profit Factor trading. "
                "Prospective Supply/Demand saat ini hanya evidence reaction."
            )

        if v241_sd.get("replication_gate_met"):
            st.success(
                "Primary Supply/Demand prospective replication gate terpenuhi, "
                "tetapi tetap bukan execution authority."
            )
        else:
            st.info(
                "Primary Supply/Demand masih mengumpulkan sample prospective: "
                f"{v241_sd.get('primary_holds',0)}/{v241_sd.get('primary_n',0)} HOLD, "
                f"Wilson LB95={_fmt_pct(v241_sd.get('primary_wilson_lower_95'))}; "
                f"gate membutuhkan n≥{v241_sd.get('minimum_n',50)}, "
                f"precision≥{_fmt_pct(v241_sd.get('minimum_precision'))}, "
                f"Wilson LB≥{_fmt_pct(v241_sd.get('minimum_wilson_lower_95'))}."
            )

    st.caption(
        "**Peta Harga & Supply/Demand — RIZAN-style.** "
        "Candlestick berasal dari snapshot completed M15 cTrader yang disimpan V182. "
        "Kotak hijau = demand, kotak merah = supply; zona utama diberi border lebih tegas. "
        "Panah menunjukkan jalur preparation, bukan jaminan pergerakan harga."
    )

    chart_price = dc_sd_eval.get("last_closed_m15_price")
    chart_raw_bars = list(dc_sd_eval.get("chart_bars_m15") or [])
    chart_zones = [
        dict(item)
        for item in list(dc_sd_eval.get("zones") or [])
        if bool(dict(item.get("lifecycle") or {}).get("active"))
    ]

    chart_seen: set[str] = set()
    chart_pool: list[dict[str, Any]] = []
    for raw_zone in [
        v240_nearest_demand,
        v240_nearest_supply,
        dc_source,
        dc_current_leg_terminal,
        dc_next_leg_source,
        dc_next_leg_terminal,
    ]:
        zone = dict(raw_zone or {})
        if not zone or zone.get("low") is None or zone.get("high") is None:
            continue
        zone_lifecycle = dict(zone.get("lifecycle") or {})
        zone_status = str(zone.get("status") or "").upper()
        if zone_lifecycle and zone_lifecycle.get("active") is False:
            continue
        if "BROKEN" in zone_status or "INVALID" in zone_status:
            continue
        zone_key = str(zone.get("zone_id") or "") or (
            f"{zone.get('timeframe')}:{zone.get('direction')}:{zone.get('low')}:{zone.get('high')}"
        )
        if zone_key in chart_seen:
            continue
        chart_seen.add(zone_key)
        chart_pool.append(zone)

    v212_chart_details = (
        {} if v212_probability_hb is None else dict(v212_probability_hb.get("details") or {})
    )
    v212_chart_by_zone = {
        str(dict(row).get("zone_id") or ""): dict(row)
        for row in list(v212_chart_details.get("zone_probabilities") or [])
        if dict(row).get("zone_id")
    }
    path_zone_ids = {
        str(dc_source.get("zone_id") or ""): "SOURCE",
        str(dc_current_leg_terminal.get("zone_id") or ""): "TARGET 1",
        str(dc_next_leg_source.get("zone_id") or ""): "NEXT SOURCE",
        str(dc_next_leg_terminal.get("zone_id") or ""): "NEXT TARGET",
    }
    path_zone_ids.pop("", None)

    def _chart_zone_priority(zone: dict[str, Any]) -> tuple[float, float, float]:
        zone_id = str(zone.get("zone_id") or "")
        role_rank = {
            "SOURCE": 0.0,
            "TARGET 1": 0.5,
            "NEXT SOURCE": 1.0,
            "NEXT TARGET": 1.5,
        }.get(path_zone_ids.get(zone_id), 2.5)
        probability = dict(v212_chart_by_zone.get(zone_id) or {})
        p_touch = dict(probability.get("destination") or {}).get("p_touch")
        p_hold = dict(probability.get("reaction") or {}).get("p_hold_050")
        try:
            touch_score = float(p_touch)
        except (TypeError, ValueError):
            touch_score = 0.50
        try:
            hold_score = float(p_hold)
        except (TypeError, ValueError):
            hold_score = 0.50
        try:
            distance = abs(float(zone.get("distance_points") or 999999.0))
        except (TypeError, ValueError):
            distance = 999999.0
        return role_rank, distance / max(0.20, touch_score), -hold_score

    chart_pool.sort(key=_chart_zone_priority)
    chart_pool = chart_pool[:8]

    with st.expander(
        "Riset V226 — locator historis/depth evidence (BUKAN entry utama)",
        expanded=False,
    ):
        st.markdown("##### V226 — RIZAN Depth Map")
        if v226_eval and str(v226_eval.get("state") or "") == "RIZAN_DEPTH_MAP_AVAILABLE":
            st.markdown("###### RISET / PREPARATION — Depth Entry Candidate")
            st.caption(
                "Untuk keputusan rutin gunakan V240 Canonical XAU Decision Map. "
                "V226 hanya locator/depth evidence dan tidak mengalahkan angka canonical."
            )
            ec1, ec2, ec3, ec4 = st.columns(4)
            ec1.metric(
                "Arah",
                str(v226_entry_candidate.get("direction") or "—"),
            )
            ec2.metric(
                "Candidate entry",
                (
                    f"{_fmt_price(v226_entry_candidate.get('entry_low'))}–"
                    f"{_fmt_price(v226_entry_candidate.get('entry_high'))}"
                    if v226_entry_candidate else "—"
                ),
            )
            ec3.metric(
                "Reference entry",
                _fmt_price(v226_entry_candidate.get("entry_reference")),
            )
            ec4.metric(
                "Sumber",
                str(v226_entry_candidate.get("source_layer") or "—"),
            )
            ec_hist = dict(v226_entry_candidate.get("historical_context") or {})
            st.caption(
                f"status={v226_entry_candidate.get('display_status','—')} • "
                f"approach={v226_entry_candidate.get('approach_state','—')} • "
                f"jarak={_fmt_price(v226_entry_candidate.get('distance_points'))} poin • "
                f"H4 reaction≥0.50 ATR={_fmt_pct(ec_hist.get('h4_parent_rate'))} • "
                f"H1 standalone={_fmt_pct(ec_hist.get('h1_standalone_rate'))} • "
                f"M15 standalone={_fmt_pct(ec_hist.get('m15_standalone_rate'))}. "
                "Ini kandidat preparation/shadow, bukan perintah entry dan belum memiliki execution authority."
            )
            st.caption(
                "Kandidat dua arah • LONG "
                f"{_fmt_price(v226_long_entry_candidate.get('entry_low'))}–"
                f"{_fmt_price(v226_long_entry_candidate.get('entry_high'))} • SHORT "
                f"{_fmt_price(v226_short_entry_candidate.get('entry_low'))}–"
                f"{_fmt_price(v226_short_entry_candidate.get('entry_high'))}. "
                "Focus direction menentukan kandidat utama yang ditonjolkan."
            )
            if len(v226_ladder_slots) == 4:
                st.markdown("###### 4-Order Hybrid Depth Plan — 0,01 lot per order")
                lc1, lc2, lc3, lc4 = st.columns(4)
                for col, slot in zip((lc1, lc2, lc3, lc4), v226_ladder_slots):
                    display_price = (
                        _fmt_price(slot.get("price"))
                        if slot.get("submit_eligible")
                        else f"WAIT M5 • ref {_fmt_price(slot.get('reference_price'))}"
                    )
                    col.metric(
                        f"Order {slot.get('slot','—')} • 0,01 lot",
                        display_price,
                        f"depth {_fmt_pct(slot.get('depth'))}",
                    )
                    col.caption(str(slot.get("stage") or "—"))
                st.caption(
                    f"arah={v226_four_order_ladder.get('direction','—')} • "
                    f"source={v226_four_order_ladder.get('source_profile_timeframe','—')} • "
                    f"pre-touch maksimum={v226_four_order_ladder.get('max_pretouch_lots',0):.2f} lot • "
                    f"total maksimum setelah konfirmasi="
                    f"{v226_four_order_ladder.get('total_lots_if_all_four_eventually_filled',0):.2f} lot. "
                    "Order 1–2 = pre-touch q10/q35 hanya bila candidate benar-benar fresh; "
                    "Order 3–4 = reclaim/MSS dan displacement/retest M5. V226 sendiri adalah "
                    "locator, tetapi V229 dapat memberi execution authority DEMO sesuai lifecycle, "
                    "pressure transition, Dynamic Depth Hazard, dan M5 confirmation."
                )

            d1, d2, d3, d4 = st.columns(4)
            d1.metric(
                "Fokus",
                v226_focus_direction or "—",
            )
            d2.metric(
                "H4 RIZAN Depth hotspot",
                (
                    f"{_fmt_price(v226_h4_hotspot.get('low'))}–"
                    f"{_fmt_price(v226_h4_hotspot.get('high'))}"
                    if v226_h4_hotspot else "—"
                ),
            )
            d3.metric(
                "H1 nested locator",
                (
                    f"{_fmt_price(v226_h1_envelope.get('low'))}–"
                    f"{_fmt_price(v226_h1_envelope.get('high'))}"
                    if v226_h1_envelope else "—"
                ),
            )
            d4.metric(
                "M15 nested locator",
                (
                    f"{_fmt_price(v226_m15_envelope.get('low'))}–"
                    f"{_fmt_price(v226_m15_envelope.get('high'))}"
                    if v226_m15_envelope else "—"
                ),
            )

            h4_profile = dict(v226_h4.get("historical_profile") or {})
            h4_top = dict(h4_profile.get("highest_hazard_band") or {})
            h4_app = dict(v226_h4.get("applicability") or {})
            h4_median = dict(v226_h4_quantiles.get("median") or {})
            st.caption(
                "V225.2 prior 2012–2026 • "
                f"H4 top-band={h4_top.get('band','—')} "
                f"(conditional hazard {_fmt_pct(h4_top.get('hazard'))}, "
                f"n-at-risk={h4_top.get('at_risk','—')}) • "
                f"median reversal depth={_fmt_pct(h4_median.get('depth'))} "
                f"@ {_fmt_price(h4_median.get('price'))} • "
                f"applicability={h4_app.get('state','—')} • "
                f"selection={v226_h4_selection_mode}. "
                "H1/M15 adalah locator nested bila child zone sudah tersedia sebelum reversal."
            )
            calibrated_h4_zone = dict(v226_h4.get("zone") or {})
            calibrated_h4_id = str(calibrated_h4_zone.get("zone_id") or "")
            nearest_context_id = str(v226_nearest_h4_context_zone.get("zone_id") or "")
            if (
                calibrated_h4_id
                and nearest_context_id
                and calibrated_h4_id != nearest_context_id
            ):
                st.info(
                    "**Selected H4 parent:** "
                    f"{_fmt_price(calibrated_h4_zone.get('low'))}–"
                    f"{_fmt_price(calibrated_h4_zone.get('high'))} "
                    f"({dict(calibrated_h4_zone.get('lifecycle') or {}).get('freshness','—')}, "
                    f"touch={dict(calibrated_h4_zone.get('lifecycle') or {}).get('touch_count','—')}). "
                    "**Nearest H4 context:** "
                    f"{_fmt_price(v226_nearest_h4_context_zone.get('low'))}–"
                    f"{_fmt_price(v226_nearest_h4_context_zone.get('high'))} "
                    f"({v226_nearest_h4_context_app.get('state','—')}). "
                    "Selector sekarang mengutamakan structural validity + proximity; first-touch hanya menentukan scope prior/jenis execution, bukan apakah H4 boleh dipakai."
                )
            if str(h4_app.get("state") or "") == "ACTIVE_HTF_RETEST":
                st.info(
                    "H4 ini sudah retest/multi-touch tetapi masih structurally active. "
                    "Zona tetap dipakai. V225.2 first-touch depth hanya menjadi geometry context; "
                    "jalur DEMO untuk retest wajib confirmation-only melalui pressure + M5."
                )
            st.info(
                "V226 menggambar zona lebih awal tanpa menunggu liquidity sweep, MSS, atau reclaim. "
                "V226 adalah locator/depth engine; execution authority diberikan terpisah oleh V229. "
                "Freshness H4/H1 bukan lagi hard gate selama zona structurally active."
            )
        else:
            st.caption(
                "V226 belum memiliki depth map aktif. Menunggu heartbeat atlas + prior V225.2."
            )

    with st.container(border=True):
        st.markdown("##### V227 — Prospective RIZAN Depth Calibration (RISET SAJA)")
        st.caption(
            "V227 hanya mengukur apakah locator V226 benar secara prospective. "
            "Angka V227 bukan entry/SL/TP dan tidak memiliki execution authority."
        )
        if v227_summary:
            v227_reaction_025 = dict(v227_summary.get("reaction_025") or {})
            v227_reaction_050 = dict(v227_summary.get("reaction_050") or {})
            v227_reaction_075 = dict(v227_summary.get("reaction_075") or {})
            v227_reaction_100 = dict(v227_summary.get("reaction_100") or {})
            v227_hotspot = dict(v227_summary.get("h4_hotspot_capture_given_reaction_050") or v227_summary.get("h4_hotspot_capture_given_reaction") or {})
            v227_iqr = dict(v227_summary.get("h4_iqr_capture_given_reaction_050") or v227_summary.get("h4_iqr_capture_given_reaction") or {})
            v227_m15 = dict(v227_summary.get("m15_locator_capture_given_reaction_050") or v227_summary.get("m15_locator_capture_given_reaction") or {})
            v227_entry_capture = dict(v227_summary.get("depth_entry_candidate_capture_given_reaction_050") or {})
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Reaction ≥0.25 ATR", _fmt_pct(v227_reaction_025.get("rate")))
            r2.metric("Reaction ≥0.50 ATR", _fmt_pct(v227_reaction_050.get("rate")))
            r3.metric("Reaction ≥0.75 ATR", _fmt_pct(v227_reaction_075.get("rate")))
            r4.metric("Reaction ≥1.00 ATR", _fmt_pct(v227_reaction_100.get("rate")))
            st.caption(
                f"fresh forecast={v227_summary.get('forecasts',0)} • "
                f"sample={v227_summary.get('sample_state','—')} • "
                f"resolved-touch={v227_summary.get('resolved_after_touch',0)} • "
                f"pending={v227_summary.get('pending',0)} • "
                f"H4 top-band capture@0.50={_fmt_pct(v227_hotspot.get('rate'))} • "
                f"H4 IQR capture@0.50={_fmt_pct(v227_iqr.get('rate'))} • "
                f"M15 locator capture@0.50={_fmt_pct(v227_m15.get('rate'))} • "
                f"Depth Entry Candidate capture@0.50={_fmt_pct(v227_entry_capture.get('rate'))} • "
                f"median actual depth@0.50={_fmt_pct(v227_summary.get('median_turning_depth'))} • "
                f"median error ke prediksi H4={_fmt_pct(v227_summary.get('median_h4_depth_error'))}. "
                "Hanya H4 fresh/untouched yang direkam sebelum first touch. "
                "V227 tetap shadow-only."
            )
        else:
            st.caption(
                "V227 menunggu episode H4 fresh yang belum disentuh. Reuse/multi-tested tidak masuk sampel."
            )

    chart_control_1, chart_control_2 = st.columns([1, 3])
    with chart_control_1:
        rizan_chart_tf = st.selectbox(
            "Timeframe chart",
            ("M15", "H1", "H4"),
            index=1,
            key="rizan_chart_timeframe",
        )
    with chart_control_2:
        nearest_demand = dict(v240_nearest_demand or {})
        nearest_supply = dict(v240_nearest_supply or {})
        st.caption(
            "Demand reversal utama "
            f"**{_fmt_price(nearest_demand.get('low'))}–{_fmt_price(nearest_demand.get('high'))}**"
            " • Supply reversal utama "
            f"**{_fmt_price(nearest_supply.get('low'))}–{_fmt_price(nearest_supply.get('high'))}**"
            f" • leg aktif **{dc_current_leg_direction}**."
        )
        chart_map_age = (
            None if supply_demand_hb is None else _age_seconds(supply_demand_hb.get("observed_at"))
        )
        if chart_map_age is not None and chart_map_age > 3600.0:
            st.warning(
                "Snapshot scanner ini tidak live. Peta terakhir: "
                f"{_fmt_wib_datetime(supply_demand_hb.get('observed_at'), seconds=False)}. "
                "Gunakan sebagai state terakhir yang tersimpan sampai feed pasar aktif kembali."
            )

    chart_v229_geometry = (
        v240_saved_geometry
        if bool(v240_decision.get("saved_geometry_match"))
        else {}
    )
    # V234 compatibility/audit: saved child targets remain observable, but they
    # never override the freshly rebuilt V240 canonical target ladder.
    chart_saved_structural_targets = [
        dict(raw_target)
        for chart_child in list(chart_v229_geometry.get("children") or [])
        for raw_target in list(dict(chart_child).get("structural_targets") or [])
    ]
    chart_structural_targets = list(v240_targets)
    chart_entry_zone = (
        dict(v240_entry_zone) if v240_effective_entry_authorized else {}
    )
    chart_depth_overlays = (
        list(v226_overlays) if v240_effective_entry_authorized else []
    )
    chart_next_micro = dict(dc_next_micro)
    if not dc_next_pocket_causally_fresh:
        chart_next_micro.pop("candidate_entry_pocket", None)
        chart_next_micro.pop("refined_entry_pocket", None)

    chart_preview_targets, chart_entry_reference, chart_approaching_entry = _rizan_chart_target_ladder(
        direction=v240_direction,
        price_now=float(chart_price) if chart_price is not None else 0.0,
        entry_zone=chart_entry_zone,
        structural_targets=chart_structural_targets,
        current_target=dc_current_leg_target.get("price"),
        terminal_zone=dc_current_leg_terminal,
        next_target=dc_next_leg_target.get("price"),
        order_targets_authorized=v240_effective_entry_authorized,
    )
    chart_next_target = chart_preview_targets[0] if chart_preview_targets else {}
    chart_terminal_target = chart_preview_targets[-1] if chart_preview_targets else {}
    chart_next_source_low = _chart_price(dc_next_leg_source.get("low"))
    chart_next_source_high = _chart_price(dc_next_leg_source.get("high"))
    chart_next_reaction = _chart_price(dc_next_leg_target.get("price"))
    chart_next_refined_low = _chart_price(dc_next_refined_display.get("low"))
    chart_next_refined_high = _chart_price(dc_next_refined_display.get("high"))
    chart_two_leg = bool(
        dc_current_leg_direction in {"LONG", "SHORT"}
        and dc_next_leg_direction in {"LONG", "SHORT"}
        and dc_current_leg_direction != dc_next_leg_direction
        and chart_next_source_low is not None
        and chart_next_source_high is not None
    )
    with st.container(border=True):
        cv1, cv2, cv3, cv4 = st.columns(4)
        cv1.metric("Harga sekarang", _fmt_price(chart_price))
        cv2.metric(
            f"CURRENT LEG • checkpoint {v240_direction}",
            _fmt_price(dc_current_leg_target.get("price")),
        )
        cv3.metric(
            f"NEXT LEG WATCH • {dc_next_leg_direction} source",
            (
                f"{_fmt_price(chart_next_source_low)}–{_fmt_price(chart_next_source_high)}"
                if chart_two_leg else "—"
            ),
        )
        cv4.metric(
            f"NEXT LEG target • jika confirmed",
            _fmt_price(chart_next_reaction),
        )
        if chart_two_leg:
            pocket_text = (
                f" • refined M5 pocket {_fmt_price(chart_next_refined_low)}–"
                f"{_fmt_price(chart_next_refined_high)}"
                if chart_next_refined_low is not None and chart_next_refined_high is not None
                else ""
            )
            st.info(
                f"**CURRENT LEG:** **{dc_current_leg_direction}** dari harga sekarang menuju "
                f"checkpoint **{_fmt_price(dc_current_leg_target.get('price'))}**. "
                f"**NEXT LEG WATCH — BUKAN ENTRY SAAT INI:** area **{_fmt_price(chart_next_source_low)}–"
                f"{_fmt_price(chart_next_source_high)}** hanya dipakai untuk mengecek kemungkinan "
                f"reversal **{dc_next_leg_direction}**{pocket_text}. "
                f"Baru jika next-leg terkonfirmasi, target awalnya **{_fmt_price(chart_next_reaction)}**. "
                "Jangan mencampur level NEXT LEG dengan entry/TP CURRENT PLAN. Ini skenario bercabang, bukan jalur harga pasti."
            )
            current_terminal_high = _chart_price(dc_current_leg_terminal.get("high"))
            if (
                dc_current_leg_direction == "LONG"
                and current_terminal_high is not None
                and chart_next_source_high is not None
                and current_terminal_high > chart_next_source_high
            ):
                st.caption(
                    f"Catatan: **{_fmt_price(current_terminal_high)} adalah batas atas zona supply HTF**, "
                    "bukan TP yang diasumsikan akan disentuh langsung. Harga harus melewati/menahan "
                    "area reaksi lebih dulu sebelum skenario continuation LONG dianggap relevan."
                )
        else:
            st.caption(
                (
                    "Baca chart: harga sekarang → entry resmi → TP struktural terdekat → target berikutnya. "
                    if v240_effective_entry_authorized
                    else "Baca chart: harga sekarang → current path target / opposing zone. Tidak ada entry/TP order resmi. "
                )
                + "Panah menunjukkan skenario, bukan jaminan."
            )

    if chart_price is not None and chart_pool:
        chart_png, chart_error = _rizan_chart_png(
            chart_raw_bars,
            timeframe=rizan_chart_tf,
            zones=chart_pool,
            price_now=float(chart_price),
            probability_by_zone=v212_chart_by_zone,
            path_roles=path_zone_ids,
            current_direction=v240_direction,
            current_target=dc_current_leg_target.get("price"),
            terminal_zone=dc_current_leg_terminal,
            next_target=dc_next_leg_target.get("price"),
            depth_overlays=chart_depth_overlays,
            entry_zone=chart_entry_zone,
            structural_targets=chart_structural_targets,
            next_leg_direction=dc_next_leg_direction,
            next_leg_source=dc_next_leg_source,
            next_leg_target=dc_next_leg_target,
            next_leg_terminal=dc_next_leg_terminal,
            next_leg_micro=chart_next_micro,
            order_targets_authorized=v240_effective_entry_authorized,
        )
        if chart_png is not None:
            st.image(chart_png, width="stretch")
            st.download_button(
                "Download chart RIZAN-style (PNG)",
                data=chart_png,
                file_name=f"xauusd_rizan_supply_demand_{rizan_chart_tf.lower()}.png",
                mime="image/png",
                width="stretch",
            )
        else:
            st.info(
                "Menunggu snapshot OHLC baru dari V182 untuk candlestick RIZAN-style. "
                f"Detail: {chart_error or 'belum tersedia'}"
            )
    else:
        st.info("Belum ada zona Supply/Demand aktif yang cukup untuk membuat chart.")

    with st.container(border=True):
        st.markdown("##### Jalur harga yang sedang dipantau")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric(
            "Source zone",
            (
                f"{_fmt_price(dc_source.get('low'))}–{_fmt_price(dc_source.get('high'))}"
                if dc_source else "—"
            ),
        )
        p2.metric("Reaction target", _fmt_price(dc_current_leg_target.get("price")))
        p3.metric(
            "Opposing zone",
            (
                f"{_fmt_price(dc_current_leg_terminal.get('low'))}–"
                f"{_fmt_price(dc_current_leg_terminal.get('high'))}"
                if dc_current_leg_terminal else "—"
            ),
        )
        p4.metric(
            "Next leg",
            str(v217_next.get("direction") or dc_next_leg_direction or "—"),
        )
        st.caption(
            f"Source H1/HTF → {dc_current_leg_direction} reaction → target internal → "
            "opposing zone → evaluasi leg berikutnya. "
            "Kotak zona yang sudah broken/invalid tidak diperlakukan sebagai setup aktif."
        )

    with st.expander("Probabilitas & validasi arah", expanded=False):
        if v217_eval:
            st.markdown("##### V217 — Probabilitas Arah Multi-Horizon")
            dp1, dp2, dp3, dp4 = st.columns(4)
            dp1.metric("Tactical first leg", str(v217_tactical.get("direction") or "—"))
            dp2.metric("P LONG", _fmt_pct(v217_tactical.get("p_long")))
            dp3.metric("P SHORT", _fmt_pct(v217_tactical.get("p_short")))
            dp4.metric("P NEUTRAL", _fmt_pct(v217_tactical.get("p_neutral")))
            st.caption(
                "Strategic HTF support • "
                f"HTF source={v217_htf_context.get('source') or '—'} • "
                f"strategic bias={v217_htf_context.get('strategic_bias') or dc_strategic_bias} • "
                f"fresh={v217_htf_context.get('fresh')} • "
                f"parity={v217_htf_context.get('parity_state') or '—'} • "
                f"relationship={v217_relationship.get('state') or '—'}. "
                "V217 tetap shadow-only."
            )

        if v220_summary:
            st.markdown("##### V220 — Prospective Direction Calibration")
            pc1, pc2, pc3, pc4 = st.columns(4)
            pc1.metric("Forecast pre-touch", int(v220_summary.get("forecasts") or 0))
            pc2.metric("Resolved", int(v220_summary.get("resolved_directional") or 0))
            pc3.metric("Accuracy", _fmt_pct(v220_summary.get("dominant_accuracy")))
            pc4.metric(
                "Mean Brier",
                "—"
                if v220_summary.get("mean_brier_multiclass") is None
                else f"{float(v220_summary.get('mean_brier_multiclass')):.3f}",
            )
            st.caption(
                f"sample={v220_summary.get('sample_state','—')} • "
                f"pending={v220_summary.get('pending',0)} • "
                f"no-touch={v220_summary.get('no_touch',0)}. "
                "Hanya forecast PRE_TOUCH yang dinilai; V220 tetap shadow-only dan tidak memiliki execution authority."
            )

        with st.expander("Raw detail V217/V220", expanded=False):
            st.json(
                {
                    "v217": v217_eval,
                    "v220": v220_summary,
                }
            )

    with st.expander("Kondisi volatilitas V203", expanded=False):
        if v203_shock_hb is None:
            st.info("Belum ada heartbeat V203.")
        elif not v203_fresh:
            st.warning("Heartbeat V203 stale; shock-state belum terverifikasi.")
        else:
            v203_message = (
                f"state={v203_state} • action={v203_action} • "
                f"range={v203_range_text} • spread={v203_spread_text} • "
                f"tick={v203_tick_text} • reason={v203_reasons}"
            )
            if v203_state == "SHOCK":
                st.error(v203_message)
            elif v203_state in {"STABILIZING", "ELEVATED", "INSUFFICIENT_DATA"}:
                st.warning(v203_message)
            else:
                st.success(v203_message)
            st.json(
                {
                    "observed_at": v203_shock_hb.get("observed_at"),
                    "state": v203_state,
                    "shadow_action": v203_action,
                    "latest_completed_m5": v203_latest,
                    "execution_influence": v203_details.get("execution_influence"),
                    "execution_authority": v203_details.get("execution_authority"),
                }
            )


    # Execution Now must use exactly the same V240/V229 geometry shown above.
    # Never fall back to a legacy V226 locator or an older prepared-plan number.
    ui_entry_low = v240_decision.get("entry_low")
    ui_entry_high = v240_decision.get("entry_high")
    ui_reference_entry = v240_decision.get("entry_reference")
    ui_stop = (
        v240_decision.get("sl") if v240_effective_entry_authorized else None
    )
    ui_tp1 = (
        v240_decision.get("tp1") if v240_effective_entry_authorized else None
    )
    ui_tp2 = (
        v240_decision.get("tp2") if v240_effective_entry_authorized else None
    )

    st.markdown("### 3 • Eksekusi Sekarang")
    with st.container(border=True):
        ex1, ex2 = st.columns(2)
        ex1.metric(
            "Entry resmi"
            if v240_effective_entry_authorized
            else "Zone watch (bukan entry)",
            (
                f"{_fmt_price(ui_entry_low)}–{_fmt_price(ui_entry_high)}"
                if ui_entry_low is not None and ui_entry_high is not None
                else "Belum ada"
            ),
        )
        ex2.metric(
            "Reference entry"
            if v240_effective_entry_authorized
            else "Reference watch",
            _fmt_price(ui_reference_entry) if ui_reference_entry is not None else "Belum ada",
        )
        if v240_entry_authorized and not v240_effective_entry_authorized:
            st.warning(
                "V280 effective authorization veto: geometri V240 lama mungkin masih "
                "memiliki entry, tetapi stage reversal/no-chase saat ini **tidak "
                "mengizinkan order**. Entry/SL/TP resmi disembunyikan sampai setup baru "
                "lolos kembali."
            )
        ex3, ex4, ex5 = st.columns(3)
        ex3.metric(
            "Stop Loss resmi",
            _fmt_price(ui_stop) if ui_stop is not None else "Belum ada — no admission",
        )
        ex4.metric(
            "TP1 order",
            _fmt_price(ui_tp1) if ui_tp1 is not None else "Belum ada — no admission",
        )
        ex5.metric(
            "TP terminal order",
            _fmt_price(ui_tp2) if ui_tp2 is not None else "Belum ada — no admission",
        )

        if (
            v240_admission_label in {"V229 READY", "BROKER ELIGIBLE"}
            and v240_effective_entry_authorized
        ):
            st.success(
                f"Admission: **{v240_admission_label}** • route: **{v240_route_label}**"
            )
        elif v240_admission_label in {"DATA STALE", "BLOCKED", "INVALIDATED", "EXPIRED"}:
            st.warning(
                f"Admission: **{v240_admission_label}** • **NO ORDER**. "
                "Angka watch/path tidak boleh diperlakukan sebagai entry."
            )
        else:
            st.info(
                "Belum ada setup canonical yang lolos admission. "
                "Section ini tidak mengambil angka fallback dari V226/standalone/plan lama."
            )

        if v240_effective_entry_authorized and v240_children:
            ladder_rows = []
            for ui_slot in v240_children:
                ui_slot_no = int(ui_slot.get("slot") or 0)
                ladder_rows.append(
                    {
                        "child": f"L{ui_slot_no}",
                        "lot": ui_slot.get("lot", 0.01),
                        "entry acuan": _fmt_price(ui_slot.get("reference_price")),
                        "cara aktif": (
                            "PRE-TOUCH LIMIT"
                            if ui_slot_no in {1, 2}
                            else "M5 CONFIRM + RETEST"
                        ),
                        "status": (
                            "boleh pending sebelum touch"
                            if ui_slot_no in {1, 2}
                            else "reserve; tunggu evidence M5"
                        ),
                    }
                )
            st.dataframe(pd.DataFrame(ladder_rows), hide_index=True, width="stretch")
            st.caption(
                "V229 child ladder: maksimum 4 × 0,01 lot. L1–L2 pre-touch LIMIT; "
                "L3–L4 hanya setelah evidence M5 masing-masing. Semua child wajib SL/TP server-side."
            )
        elif v226_ladder_slots:
            st.caption(
                "Ladder V226/V229 research ada di backend tetapi **disembunyikan dari eksekusi** "
                "karena current V240 belum mempunyai entry authority."
            )

    with st.expander("Detail setup multi-timeframe — H1 / M5 / M15 / DOM / Event", expanded=False):
        st.markdown("#### 2. H1 / HTF — Zona Reaksi Utama")
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
                "Belum ada H1 source zone aktif pada path RIZAN-style/Supply-Demand saat ini."
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

        v214_details = (
            {} if v214_lifecycle_hb is None else dict(v214_lifecycle_hb.get("details") or {})
        )
        v214_eval = dict(v214_details.get("evaluation") or {})
        v214_current = dict(v214_eval.get("current_leg") or {})
        v214_next = dict(v214_eval.get("next_leg") or {})
        v214_current_timeline = dict(v214_current.get("timeline") or {})
        v214_current_latency = dict(v214_current.get("latency_minutes") or {})
        v214_next_timeline = dict(v214_next.get("timeline") or {})
        v214_next_latency = dict(v214_next.get("latency_minutes") or {})

        v222_details = (
            {} if v222_pocket_quality_hb is None else dict(v222_pocket_quality_hb.get("details") or {})
        )
        v222_eval = dict(v222_details.get("evaluation") or {})
        v222_latest = dict(v222_eval.get("latest_pocket") or {})
        v222_family = [dict(row) for row in list(v222_eval.get("family") or [])]

        v223_details = (
            {} if v223_cluster_hb is None else dict(v223_cluster_hb.get("details") or {})
        )
        v223_eval = dict(v223_details.get("evaluation") or {})
        v223_primary = dict(v223_eval.get("primary_cluster") or {})
        v223_alternative = dict(v223_eval.get("alternative_cluster") or {})
        if v223_primary:
            v223_union = dict(v223_primary.get("union_zone") or {})
            v223_core = dict(v223_primary.get("consensus_core") or {})
            st.success(
                "V223 — Primary M5 Pocket Cluster • "
                f"**{_fmt_price(v223_union.get('low'))}–{_fmt_price(v223_union.get('high'))}** • "
                f"role={v223_primary.get('role','—')} • "
                f"score={_fmt_number(v223_primary.get('selector_score_research'), 1)}/100 • "
                f"distance={_fmt_number(v223_primary.get('distance_atr'), 2)} ATR."
            )
            if v223_core:
                v223_policy = dict(v223_eval.get("selection_policy") or {})
                st.caption(
                    "Consensus core "
                    f"**{_fmt_price(v223_core.get('low'))}–{_fmt_price(v223_core.get('high'))}** • "
                    f"{v223_primary.get('count',0)} pocket dalam micro-wave ini • "
                    f"total micro-wave={v223_policy.get('micro_wave_cluster_count','—')} • "
                    f"latest mapped={_fmt_wib_datetime(v223_primary.get('latest_mapped_at'), seconds=False)}. "
                    "V223 memutus cluster saat time-gap/span/midpoint shift terlalu besar, sehingga pocket lama "
                    "tidak menyatu ke area aktif baru. Consensus core adalah geometry riset; V223 tetap shadow-only."
                )
        elif v223_eval:
            retest_clusters = list(v223_eval.get("retest_only_clusters") or [])
            if retest_clusters:
                st.warning(
                    "V223 belum memiliki PRIMARY first-entry cluster. "
                    f"{len(retest_clusters)} cluster saat ini hanya berstatus RETEST_ONLY."
                )
            else:
                st.caption("V223 belum menemukan cluster M5 aktif yang layak menjadi PRIMARY watch.")

        v224_details = (
            {} if v224_primary_calibration_hb is None
            else dict(v224_primary_calibration_hb.get("details") or {})
        )
        v224_summary = dict(v224_details.get("summary") or {})
        if v224_summary:
            st.markdown("##### V224 — Prospective Primary Pocket Accuracy")
            q1, q2, q3, q4 = st.columns(4)
            q1.metric("Primary forecast", int(v224_summary.get("forecasts") or 0))
            q2.metric("Resolved touch", int(v224_summary.get("resolved_after_touch") or 0))
            q3.metric(
                "Hit ≥0.50 ATR",
                _fmt_pct(dict(v224_summary.get("hit_050") or {}).get("rate")),
            )
            q4.metric(
                "Wilson LB 95%",
                _fmt_pct(dict(v224_summary.get("hit_050") or {}).get("wilson_lower_95")),
            )
            st.caption(
                f"sample={v224_summary.get('sample_state','—')} • "
                f"pending={v224_summary.get('pending',0)} • "
                f"no-touch={v224_summary.get('no_touch',0)} • "
                f"median touch={_fmt_minutes(v224_summary.get('median_forecast_to_touch_minutes'))} • "
                f"median touch→0.50ATR={_fmt_minutes(v224_summary.get('median_touch_to_050_minutes'))}. "
                "Hanya PRIMARY cluster yang dipilih saat harga masih di luar pocket pada sisi approach yang benar "
                "yang boleh masuk sampel. V224 tetap shadow-only."
            )

        if v222_latest:
            v222_geometry = (
                f"{_fmt_price(v222_latest.get('low'))}–{_fmt_price(v222_latest.get('high'))}"
            )
            v222_timing = str(v222_latest.get("timing_state") or "—")
            v222_quality = v222_latest.get("quality_score_research")
            if v222_timing == "LATE_FOR_FIRST_ENTRY_WAIT_RETEST":
                st.warning(
                    f"V222 • pocket terbaru **{v222_geometry}** sudah diklasifikasikan "
                    "**LATE FOR FIRST ENTRY / WAIT RETEST**. "
                    f"Quality research={_fmt_number(v222_quality, 1)} • "
                    f"reference price={_fmt_price(v222_latest.get('current_price_reference'))}. "
                    "Ini berarti pocket tetap berguna sebagai origin/retest reference, tetapi bukan "
                    "fresh first-entry pocket hanya karena statusnya refined."
                )
            else:
                st.info(
                    f"V222 • pocket terbaru **{v222_geometry}** • "
                    f"timing={v222_timing} • quality research={_fmt_number(v222_quality, 1)}. "
                    "V222 membedakan formation/origin dari post-map retest."
                )
            if v222_latest.get("refined_first_observed_at"):
                st.caption(
                    "Refined first-observed • "
                    f"{_fmt_wib_datetime(v222_latest.get('refined_first_observed_at'), seconds=True)} • "
                    f"candidate→refined observed={_fmt_minutes(v222_latest.get('candidate_to_refined_observed_minutes'))} • "
                    f"state={v222_latest.get('refinement_timing_state','—')}. "
                    "Waktu ini lebih penting untuk no-lookahead daripada timestamp origin/refined geometry."
                )

            if str(v222_eval.get("family_state") or "") in {
                "SEQUENTIAL_REMAP_UP",
                "SEQUENTIAL_REMAP_DOWN",
            }:
                st.caption(
                    f"Pocket family: {v222_eval.get('family_count', 0)} kandidat • "
                    f"state={v222_eval.get('family_state')} • "
                    "pocket terbaru tidak otomatis menggusur kandidat lama dalam evaluasi kualitas."
                )

        if dc_parent_rescue_active:
            st.info(
                "Parent-reversal rescue • microstructure M5 tidak dibuang hanya karena H1 child invalid. "
                f"Parent={dc_parent_rescue.get('parent_timeframe') or 'HTF'} "
                f"{_fmt_price(dc_parent_source_zone.get('low'))}–"
                f"{_fmt_price(dc_parent_source_zone.get('high'))} • "
                f"mode={dc_parent_rescue.get('mode') or '—'} • "
                "status tetap SHADOW/PREPARE sampai confirmation/admission canonical lolos."
            )

        dc_current_pocket_shown = False
        if dc_initial_candidate:
            dc_current_pocket_shown = True
            st.warning(
                f"INITIAL M5 **{dc_current_leg_direction}** POCKET: "
                f"**{_fmt_price(dc_initial_candidate.get('low'))}–{_fmt_price(dc_initial_candidate.get('high'))}** • "
                f"state={dc_micro.get('state','—')} • status=CANDIDATE/ORIGIN. "
                f"Pocket awal tetap dipertahankan walaupun refined pocket sudah terbentuk. "
                f"Reaction target={dc_current_target_text} • opposing zone={dc_current_terminal_text}."
            )
            st.caption(
                "Lifecycle awal • "
                f"mapped={_fmt_wib_datetime(v214_current_timeline.get('candidate_mapped_at') or dc_initial_candidate.get('origin_at'), seconds=False)} • "
                f"first touch={_fmt_wib_datetime(v214_current_timeline.get('first_touch_at'), seconds=False)} • "
                f"sweep={_fmt_wib_datetime(v214_current_timeline.get('sweep_at') or dict(dc_micro.get('sweep') or {}).get('at'), seconds=False)} • "
                f"lead={_fmt_minutes(v214_current_latency.get('candidate_map_to_touch'))}."
            )

        if dc_refined_display:
            dc_current_pocket_shown = True
            st.success(
                f"REFINED M5 **{dc_current_leg_direction}** POCKET: "
                f"**{_fmt_price(dc_refined_display.get('low'))}–{_fmt_price(dc_refined_display.get('high'))}** • "
                f"state={dc_micro.get('state','—')} • "
                f"sweep={_fmt_price(dict(dc_micro.get('sweep') or {}).get('price'))} • "
                f"reclaim={_fmt_price(dc_micro.get('source_proximal_reclaim_level'))} • "
                f"MSS={_fmt_price(dc_micro.get('mss_level'))}. "
                f"Reaction target={dc_current_target_text} • opposing zone={dc_current_terminal_text}. "
                "**SHADOW/PREPARE — belum otomatis menjadi entry resmi.**"
            )

            st.caption(
                "Lifecycle refined • "
                f"reclaim={_fmt_wib_datetime(v214_current_timeline.get('reclaim_at') or dc_micro.get('reclaim_at'), seconds=False)} • "
                f"MSS={_fmt_wib_datetime(v214_current_timeline.get('mss_at') or dc_micro.get('mss_at'), seconds=False)} • "
                f"displacement={_fmt_wib_datetime(v214_current_timeline.get('displacement_at') or dc_micro.get('displacement_at'), seconds=False)} • "
                f"refined mapped={_fmt_wib_datetime(v214_current_timeline.get('refined_mapped_at') or dc_refined_display.get('origin_at'), seconds=False)} • "
                f"touch→refined={_fmt_minutes(v214_current_latency.get('touch_to_refined'))}."
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

            if dc_next_initial_candidate:
                dc_next_pocket_shown = True
                st.info(
                    f"INITIAL M5 **{dc_next_leg_direction}** POCKET berikutnya: "
                    f"**{_fmt_price(dc_next_initial_candidate.get('low'))}–{_fmt_price(dc_next_initial_candidate.get('high'))}** • "
                    f"state={dc_next_micro.get('state','—')} • status=CANDIDATE. "
                    f"Reaction target={dc_next_target_text} • "
                    f"terminal opposing zone={dc_next_terminal_text}."
                )

            if dc_next_refined_display:
                dc_next_pocket_shown = True
                st.success(
                    f"REFINED M5 **{dc_next_leg_direction}** POCKET berikutnya: "
                    f"**{_fmt_price(dc_next_refined_display.get('low'))}–{_fmt_price(dc_next_refined_display.get('high'))}** • "
                    f"state={dc_next_micro.get('state','—')}. "
                    f"Reaction target={dc_next_target_text} • "
                    f"terminal opposing zone={dc_next_terminal_text}. "
                    "Refined pocket tetap tidak menjadi izin broker tanpa admission yang valid."
                )

            if dc_next_initial_candidate:
                st.caption(
                    "Next-leg lifecycle • "
                    f"mapped={_fmt_wib_datetime(v214_next_timeline.get('candidate_mapped_at') or dc_next_initial_candidate.get('origin_at'), seconds=False)} • "
                    f"touch={_fmt_wib_datetime(v214_next_timeline.get('first_touch_at'), seconds=False)} • "
                    f"reclaim={_fmt_wib_datetime(v214_next_timeline.get('reclaim_at') or dc_next_micro.get('reclaim_at'), seconds=False)} • "
                    f"MSS={_fmt_wib_datetime(v214_next_timeline.get('mss_at') or dc_next_micro.get('mss_at'), seconds=False)} • "
                    f"touch→refined={_fmt_minutes(v214_next_latency.get('touch_to_refined'))}."
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

        with st.expander("Riset pocket, reaction & zone reuse (V200/V212–V216/V222/V223)", expanded=False):
            if v223_eval:
                st.markdown("##### V223 — Primary M5 Pocket Cluster")
                cl1, cl2, cl3, cl4 = st.columns(4)
                cl1.metric("Cluster", len(list(v223_eval.get("clusters") or [])))
                cl2.metric(
                    "Primary role",
                    str(v223_primary.get("role") or "—"),
                )
                cl3.metric(
                    "Primary score",
                    "—"
                    if v223_primary.get("selector_score_research") is None
                    else f"{float(v223_primary.get('selector_score_research')):.1f}/100",
                )
                cl4.metric(
                    "Distance",
                    "—"
                    if v223_primary.get("distance_atr") is None
                    else f"{float(v223_primary.get('distance_atr')):.2f} ATR",
                )
                st.caption(
                    "V223 menggabungkan pocket yang overlap/berdekatan agar pocket terbaru tidak "
                    "otomatis menggusur micro-area yang stabil. Consensus core tetap shadow-only "
                    "dan belum boleh dipakai sebagai entry order."
                )
                cluster_rows = []
                for row in list(v223_eval.get("clusters") or [])[-6:]:
                    item = dict(row)
                    union = dict(item.get("union_zone") or {})
                    core = dict(item.get("consensus_core") or {})
                    cluster_rows.append(
                        {
                            "Cluster": item.get("cluster_id"),
                            "Role": item.get("role"),
                            "Union": f"{_fmt_price(union.get('low'))}–{_fmt_price(union.get('high'))}",
                            "Consensus core": (
                                f"{_fmt_price(core.get('low'))}–{_fmt_price(core.get('high'))}"
                                if core else "—"
                            ),
                            "Count": item.get("count"),
                            "Score": item.get("selector_score_research"),
                            "Distance ATR": item.get("distance_atr"),
                        }
                    )
                if cluster_rows:
                    st.dataframe(pd.DataFrame(cluster_rows), width="stretch", hide_index=True)

            if v222_eval:
                st.markdown("##### V222 — M5 Pocket Quality & Stability")
                pq1, pq2, pq3, pq4 = st.columns(4)
                pq1.metric("Pocket family", int(v222_eval.get("family_count") or 0))
                pq2.metric("Family state", str(v222_eval.get("family_state") or "—"))
                pq3.metric(
                    "Latest quality",
                    "—"
                    if v222_latest.get("quality_score_research") is None
                    else f"{float(v222_latest.get('quality_score_research')):.1f}/100",
                )
                pq4.metric("Latest timing", str(v222_latest.get("timing_state") or "—"))
                st.caption(
                    "Formation candle memang sudah memperdagangkan harga pocket sebelum pocket dapat "
                    "dipetakan dari completed M5. first_touch hanya berarti retest setelah mapping. "
                    "Karena itu ORIGIN/FORMATION tidak boleh disamakan dengan fresh entry. "
                    "V222 tetap shadow-only."
                )
                if v222_family:
                    family_rows = []
                    for row in v222_family[-6:]:
                        family_rows.append(
                            {
                                "Seq": row.get("sequence"),
                                "Pocket": f"{_fmt_price(row.get('low'))}–{_fmt_price(row.get('high'))}",
                                "Mapped WIB": _fmt_wib_datetime(row.get("mapped_at"), seconds=False),
                                "Post-map touch": _fmt_wib_datetime(row.get("first_touch_at"), seconds=False),
                                "Timing": row.get("timing_state"),
                                "Quality": row.get("quality_score_research"),
                                "Shift ATR": row.get("midpoint_shift_atr"),
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(family_rows),
                        width="stretch",
                        hide_index=True,
                    )

            v216_details = (
                {} if v216_calibration_hb is None else dict(v216_calibration_hb.get("details") or {})
            )
            v216_summary = dict(v216_details.get("summary") or {})
            if v216_summary:
                st.markdown("##### V215/V216 — Candidate vs Refined Calibration")
                cv1, cv2, cv3, cv4 = st.columns(4)
                cv1.metric("Episode", int(v216_summary.get("episodes") or 0))
                cv2.metric(
                    "Refined | touched",
                    _fmt_pct(v216_summary.get("refinement_rate_given_touch")),
                )
                before_025 = dict(v216_summary.get("reaction_025_before_refined") or {})
                before_050 = dict(v216_summary.get("reaction_050_before_refined") or {})
                cv3.metric("0.25 ATR sebelum refined", _fmt_pct(before_025.get("rate")))
                cv4.metric("0.50 ATR sebelum refined", _fmt_pct(before_050.get("rate")))
                st.caption(
                    f"sample={v216_summary.get('sample_state','—')} • "
                    f"median candidate lead={_fmt_minutes(v216_summary.get('median_premap_lead_minutes'))}. "
                    "Jika reaksi sering terjadi sebelum refined, refined dibaca sebagai retest/re-entry confirmation, "
                    "bukan origin reversal pertama. V215/V216 tetap shadow-only."
                )

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

    st.markdown("### 4 • Manajemen Posisi XAUUSD")
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
    tm2.metric("Posisi XAU aktif", tm_summary.get("count", 0) if tm_snapshot_fresh else "—")
    tm3.metric("Total volume", f"{float(tm_summary.get('total_volume') or 0.0):.2f}" if tm_snapshot_fresh else "—")
    tm4.metric(
        "Floating P/L",
        "—"
        if not tm_snapshot_fresh or tm_summary.get("total_profit") is None
        else f"{float(tm_summary.get('total_profit') or 0.0):+.2f}",
    )

    if backend and backend.get("account_telemetry_redacted"):
        st.info("Informasi akun disembunyikan dari dashboard publik. Periksa posisi di cTrader; tanda — bukan berarti tidak ada posisi.")
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

    with st.expander("Riset & evidence prospective — V197 sampai V201", expanded=False):
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
        "Detail Diagnostik RIZAN-style ↔ Supply/Demand / V189 / DOM / Event",
        expanded=False,
    ):
        st.caption(
            "Detail ini tetap tersedia untuk audit. Untuk keputusan cepat gunakan "
            "Pusat Keputusan XAUUSD di atas."
        )
        st.markdown("### Integrasi RIZAN-style ↔ Supply/Demand")
        st.caption(
            "Supply/Demand V182 sekarang menjadi context map untuk RIZAN-style. Context ini dapat "
            "mendukung zona canonical, memberi peringatan zona reversal lawan, atau menyediakan "
            "fallback PREPARE ketika canonical RIZAN-style belum ada. Context ini TIDAK mengubah Grade "
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
                    "Supply/Demand searah RIZAN-style: "
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
                    "Ini adalah Plan-B / reaction watch, bukan alasan entry melawan RIZAN-style."
                )
            dom_context = dict(afic_sd_context.get("dom_context") or {})
            if not dom_context and dom_v191_hb is not None:
                dom_details = dict(dom_v191_hb.get("details") or {})
                dom_context = dict(dom_details.get("analysis") or {})
                dom_context["stale"] = False
                dom_context["alignment_with_first_leg"] = "BELUM_DIHUBUNGKAN_KE_SNAPSHOT_RIZAN"
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
                    "V191 ditampilkan sebagai operational microstructure context; execution authority tetap mengikuti canonical admission."
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
                        "Path RIZAN-style saat ini: "
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
                    "Canonical RIZAN-style belum memiliki zona valid, tetapi atlas Supply/Demand "
                    "memiliki context aktif. Scanner boleh menampilkan PERSIAPAN/WATCH lebih awal, "
                    "namun order tetap dilarang sampai canonical RIZAN-style + completed M15 confirmation "
                    "terbentuk."
                )
            if afic_sd_context.get("atlas_stale"):
                st.error(
                    "Snapshot Supply/Demand terlalu lama untuk dipakai sebagai context aktif. "
                    "RIZAN-style tetap berjalan tanpa policy effect dari atlas sampai heartbeat baru tersedia."
                )
        else:
            st.caption(
                "Context integrasi RIZAN-style ↔ Supply/Demand belum tersedia pada snapshot runtime ini."
            )


    with st.expander("Riset HTF, atlas Supply/Demand & validasi zona", expanded=False):
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
                    f"Arah candle H4 RIZAN-style saat ini = {direction}. "
                    "Keduanya dapat berbeda karena V180 adalah konteks strategis, sedangkan "
                    "RIZAN-style V161 tetap merupakan peta taktis canonical untuk eksekusi."
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
                "RIZAN-style V161 tetap menjadi otoritas eksekusi."
            )

        st.markdown("### Atlas Supply & Demand HTF (V182)")
        st.caption(
            "Atlas riset D1/H4/H1 untuk mendeteksi demand/supply lebih awal dari canonical RIZAN-style. "
            "Zona dibentuk dari structural origin atau base→departure imbalance, lalu dinilai "
            "berdasarkan freshness, touch/mitigation, HTF nesting, liquidity confluence, jarak, "
            "dan kualitas pendekatan harga. V182 SELALU PREPARE ONLY / NO EXECUTION."
        )
        sd_details = {} if supply_demand_hb is None else dict(supply_demand_hb.get("details") or {})
        sd_eval = dict(sd_details.get("evaluation") or {})
        sd_raw_zones = [dict(item) for item in list(sd_eval.get("zones") or [])]
        nearest_demand = dict(sd_eval.get("nearest_demand") or {})
        nearest_supply = dict(sd_eval.get("nearest_supply") or {})
        sd_path_map = dict(sd_eval.get("path_map") or {})
        sd_active_path = dict(sd_path_map.get("active_path") or {})

        # Keep path-critical zones visible even when an older score-ranked V182
        # snapshot omitted them from its flat top-12 export. New V182 snapshots
        # already guarantee this; the UI union protects migration-era snapshots.
        sd_critical_zones = [
            nearest_demand,
            nearest_supply,
            dict(sd_active_path.get("source_zone") or {}),
            dict(sd_active_path.get("primary_opposing_zone") or {}),
            dict(sd_active_path.get("terminal_target_zone") or {}),
        ]
        sd_zones: list[dict[str, Any]] = []
        sd_seen: set[tuple[Any, ...]] = set()
        for item in [*sd_critical_zones, *sd_raw_zones]:
            if not item:
                continue
            zone_id = str(item.get("zone_id") or "")
            key = (
                "ID",
                zone_id,
            ) if zone_id else (
                "GEO",
                str(item.get("timeframe") or ""),
                str(item.get("direction") or ""),
                item.get("low"),
                item.get("high"),
            )
            if key in sd_seen:
                continue
            sd_seen.add(key)
            sd_zones.append(item)

        if sd_zones:
            sd1, sd2, sd3, sd4 = st.columns(4)
            sd1.metric("Zona aktif", sd_eval.get("active_count", 0))
            sd2.metric("Zona current + riset", len(sd_zones))
            sd3.metric("Konteks sesi", str(sd_eval.get("session_context") or "—"))
            sd4.metric("Izin eksekusi", "TIDAK ADA")
            nd_col, ns_col = st.columns(2)
            with nd_col:
                if nearest_demand:
                    nd_lifecycle = dict(nearest_demand.get("lifecycle") or {})
                    nd_approach = dict(nearest_demand.get("approach") or {})
                    st.info(
                        "Demand reversal utama: "
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
                        "Supply reversal utama: "
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
                "Canonical RIZAN-style ≤24 jam, M15 confirmation, fresh quote, risk/margin, dan "
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
                "V183 tidak mengubah V182, V181, canonical RIZAN-style, atau broker lane. "
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
            "sampai H4 map berikutnya selesai dan canonical RIZAN-style memvalidasinya."
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
                "pemilihan RIZAN-style A/B sebelum dapat memiliki jalur broker."
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

    with st.expander("Detail execution, admission & diagnostik", expanded=False):
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
                        "Gunakan hanya untuk bersiap; BELUM menjadi entry zone RIZAN-style."
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
                  "selesai tetap wajib memberikan konfirmasi untuk jalur otomatis RIZAN-style."
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
                "rencana RIZAN-style terbaru tanpa mengubah aturan eksekusi."
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
            "XAU_RIZAN_DEPTH_EXECUTION_V1",
        }
        geometry_code_by_signal = {}
        for event_row in geometry_rows:
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
                reason = ", ".join(str(_rizan_display(x)) for x in guards)
            elif state_u != "EXECUTION_READY":
                admission = "NOT READY"
                reason = f"Status={state_u or '—'}"
            elif geometry_code == "XAU_RIZAN_DEPTH_EXECUTION_V1":
                admission = "DEDICATED CHILD ELIGIBLE"
                reason = (
                    "V229 dedicated 2+2 child lane; L1-L2 pre-touch LIMIT, "
                    "L3-L4 menunggu konfirmasi M5"
                )
            elif geometry_code in authorized_geometry_codes:
                admission = "BROKER ELIGIBLE"
                reason = (
                    f"{_rizan_display(geometry_code)}; "
                    "menunggu validasi ulang quote/risiko"
                )
            else:
                admission = "SHADOW READY"
                reason = (
                    f"{_rizan_display(geometry_code or 'NO_AUTHORIZED_GEOMETRY')} tidak memiliki izin broker"
                )
            admission_rows.append({
                "waktu (WIB)": _fmt_wib_datetime(row.get("observed_at")),
                "setup": _rizan_display(row.get("setup_type")),
                "arah": row.get("direction"),
                "grade/skor": row.get("final_score"),
                "status tersimpan": row.get("state"),
                "kelayakan": admission,
                "izin geometry": _rizan_display(geometry_code or "—"),
                "alasan": reason,
                "kedaluwarsa (WIB)": _fmt_wib_datetime(row.get("expires_at")),
            })
        if admission_rows:
            st.dataframe(pd.DataFrame(admission_rows), hide_index=True, width="stretch")
            latest_admission = admission_rows[0]
            if latest_admission["kelayakan"] in {"BROKER ELIGIBLE", "DEDICATED CHILD ELIGIBLE"}:
                st.success(
                    "Signal XAU terbaru memiliki geometry DEMO yang diizinkan. "
                    "Untuk V229, eksekusi dimiliki dedicated 4-child lane; strategy ini tidak masuk "
                    "generic MARKET handoff. Semua order tetap tunduk pada quote, margin, dan SL/TP."
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
            "Bagian ini terpisah dari RIZAN-style H4 map. Baris berasal dari mesin teknikal XAU lain. "
            "CURRENT/EXPIRED ditentukan dari expires_at; setup yang kedaluwarsa hanya konteks "
            "historis dan tidak boleh dianggap sebagai rancangan order RIZAN-style yang masih aktif."
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
                        "setup": _rizan_display(row.get("setup_type")),
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
                        "guard/pengaman": ", ".join(
                            str(_rizan_display(x))
                            for x in (row.get("active_guards") or [])
                        ) or "—",
                        "kedaluwarsa (WIB)": _fmt_wib_datetime(expires_raw),
                    }
                )
            latest_technical = technical_rows[0]
            if latest_technical["runtime"] == "CURRENT":
                st.info(
                    "Setup teknikal XAU non-RIZAN-style terbaru masih CURRENT. Geometry ditampilkan "
                    "di bawah, tetapi izin RIZAN-style tetap merupakan gerbang terpisah."
                )
            elif latest_technical["runtime"] == "WATCH":
                st.info(
                    "Baris XAU non-RIZAN-style terbaru hanya WATCH. Ia tidak memiliki izin trading "
                    "mandiri dan tidak boleh dibaca sebagai entry aktif."
                )
            elif latest_technical["runtime"] == "INVALIDATED":
                st.warning(
                    "Setup XAU non-RIZAN-style terbaru INVALIDATED. Geometry disimpan hanya sebagai "
                    "evidence historis."
                )
            else:
                st.warning(
                    "Setup teknikal XAU non-RIZAN-style terbaru EXPIRED. Entry/SL/TP hanya geometry "
                    "historis, bukan instruksi yang masih aktif."
                )
            st.dataframe(
                pd.DataFrame(technical_rows),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("Belum ada baris signal teknikal XAU non-RIZAN-style.")

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
                "Diagnostik hanya bersifat deskriptif; tidak melonggarkan selector RIZAN-style dan "
                "tidak menciptakan izin broker."
            )
        else:
            st.caption(
                "Diagnostik zona belum tersedia pada heartbeat ini; siklus RIZAN-style berikutnya "
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
                "RIZAN-style reaction zones. first durable touch is preserved across H4 remaps; "
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
                f"• {watch_status}. This is not the current primary RIZAN-style zone. {path_hint}"
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
        f4.metric("Live XAU", _fmt_price(dc_reference_price))
        f5.metric("Distance to zone", _fmt_distance(distance_points, " pts"))
        f6.metric("RIZAN scan", f"{int(scan_seconds)}s" if scan_seconds else "—")
        st.caption(
            "H4 continuation is structural context only. It is not a current BUY/SELL call; "
            "trade authority still requires a valid current RIZAN-style zone/selector/confirmation."
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
        h5.metric("Last RIZAN broker event", latest_exec_event or "NONE")
        st.caption(next_reason)
        if fast_handoff_hb is not None:
            fast_details = dict(fast_handoff_hb.get("details") or {})
            st.caption(
                "RIZAN-style fast handoff • "
                f"age={'—' if fast_age is None else f'{fast_age:.0f}s'} • "
                f"duration={_fmt_distance(fast_details.get('duration_seconds'), 's')} • "
                f"exit={fast_details.get('exit_code', '—')} • "
                f"code={str(fast_details.get('code_version') or '—')[:12]}"
            )

    with st.expander("Forecast ensemble & probabilitas tambahan", expanded=False):
        st.markdown("#### Gabungan Prakiraan V171 (Forecast Ensemble V171)")
        ensemble_details = {} if ensemble_hb is None else dict(ensemble_hb.get("details") or {})
        ensemble = dict(ensemble_details.get("ensemble") or {})
        primary = dict(ensemble.get("primary_scenario") or {})
        alternative = dict(ensemble.get("alternative_scenario") or {})
        ensemble_age = None if ensemble_hb is None else _age_seconds(ensemble_hb.get("observed_at"))
        ensemble_components = dict(ensemble.get("components") or {})
        if "rizan" not in ensemble_components:
            legacy_structural = dict(ensemble_components.get("afic") or {})
            if legacy_structural:
                ensemble_components["rizan"] = legacy_structural

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
                "does not alter RIZAN-style Grade-A/B execution authority."
            )
            directional_prior = dict(ensemble.get("directional_prior") or {})
            if directional_prior:
                st.caption(
                    "Directional prior: "
                    f"{directional_prior.get('direction', '—')} • "
                    f"score={_fmt_distance(directional_prior.get('score'), '')} • "
                    f"prior confidence={_fmt_pct(directional_prior.get('confidence'))}. "
                    "A valid RIZAN-style H4 map/reaction zone is still required before this can "
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
                ("rizan", "RIZAN structural"),
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
                "RIZAN-style and V170 remain independently visible below."
            )

    if zone_low is not None and zone_high is not None:
        st.markdown(
            f"**Reaction zone:** {_fmt_price(zone_low)} – {_fmt_price(zone_high)}  "
            f"• **Proximity:** {proximity}  "
            f"• **Distance:** {_fmt_distance(distance_atr, ' ATR')}"
        )
    st.info(_rizan_path_text(direction, state))

    if grade in {"A", "B"}:
        st.success(
            f"Canonical V161 selector Grade {grade}: eligible for DEMO auto execution "
            "only after completed M15 confirmation and fresh broker revalidation."
        )
    elif grade == "C":
        st.warning(
            "Grade C: shadow/watch only. Scanner will not auto-order this RIZAN-style map "
            "even if the zone is touched."
        )
    else:
        st.caption("No canonical RIZAN-style selector grade available yet.")

    with st.expander("Detail order blueprint & broker timeline", expanded=False):
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
            target_model = str(prepared_plan.get("target_model") or "LEGACY")
            structural_targets = list(prepared_plan.get("structural_target_ladder") or [])
            if target_ladder:
                st.caption(
                    "Target ladder: "
                    + " → ".join(
                        f"TP{i} {_fmt_price(level)}"
                        for i, level in enumerate(target_ladder, start=1)
                    )
                    + f" • Terminal target = TP{len(target_ladder)}"
                    + f" • model={target_model}"
                )
            if structural_targets:
                st.markdown("###### Peta TP Struktural — opposing Supply/Demand")
                structural_rows = []
                for item in structural_targets:
                    structural_rows.append(
                        {
                            "timeframe": item.get("timeframe"),
                            "role": item.get("role"),
                            "zona lawan": (
                                f"{_fmt_price(item.get('zone_low'))}–"
                                f"{_fmt_price(item.get('zone_high'))}"
                            ),
                            "TP front-run": _fmt_price(item.get("target_price")),
                            "RR": _fmt_distance(item.get("rr"), "R"),
                            "lolos RR minimum": bool(item.get("rr_eligible")),
                        }
                    )
                st.dataframe(pd.DataFrame(structural_rows), hide_index=True, width="stretch")
                macro_target = dict(prepared_plan.get("macro_terminal_target") or {})
                st.caption(
                    "Urutan struktural: M15 → H1 → H4; D1 hanya macro terminal opsional. "
                    "TP ditempatkan sedikit sebelum proximal edge zona lawan. RR adalah validasi, "
                    "bukan sumber level target."
                    + (
                        f" Macro D1: {_fmt_price(macro_target.get('target_price'))}."
                        if macro_target else ""
                    )
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
                "Latest RIZAN-style broker-authorized geometry: "
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

    with st.expander("Expected move & riwayat forecast", expanded=False):
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
            st.caption("No durable RIZAN-style forecast transitions have been recorded yet.")

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
    elif backend and backend.get("account_telemetry_redacted"):
        st.info("Saldo, equity, dan posisi tidak dipublikasikan. Periksa akun langsung di cTrader.")
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
        display_signals = signals[display_cols].copy()
        for display_col in display_signals.columns:
            display_signals[display_col] = display_signals[display_col].apply(
                _rizan_display
            )
        st.dataframe(
            display_signals,
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("No signal snapshots have been written yet.")

with data_tab:
    st.subheader("Makro Mata Uang (Currency Macro)")
    if backend is not None and backend["macro"]:
        macro = _frame(backend["macro"])
        if "observed_at" in macro.columns:
            checked = pd.to_datetime(macro["observed_at"], utc=True, errors="coerce")
            stale = checked.isna() | ((pd.Timestamp.now(tz="UTC") - checked).dt.total_seconds() > 172800)
            macro["status_data"] = stale.map({True: "KEDALUWARSA — konteks historis saja", False: "PEMERIKSAAN TERBARU — lihat coverage"})
        if "macro_score" in macro.columns and macro["macro_score"].isna().any():
            st.warning("Sebagian data makro belum lengkap; skor kosong bukan sinyal netral.")
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
    heartbeat_rows = [] if backend is None else list(backend.get("heartbeats") or [])
    load_full_heartbeat_details = st.toggle(
        "Muat detail JSON semua worker",
        value=False,
        help=(
            "Default hanya memuat detail penuh untuk worker yang dipakai V240/pressure/depth. "
            "Aktifkan ini hanya saat audit karena payload observability jauh lebih besar."
        ),
    )
    if load_full_heartbeat_details and backend_configured:
        try:
            heartbeat_rows = _load_full_heartbeat_details(
                supabase_url,
                supabase_secret,
            )
        except Exception as exc:
            st.warning(
                "Detail heartbeat lengkap gagal dimuat; menggunakan ringkasan: "
                f"{type(exc).__name__}: {exc}"
            )
    if heartbeat_rows:
        heartbeats = _convert_frame_times_to_wib(
            _frame(heartbeat_rows),
            ("observed_at",),
        ).rename(columns={"observed_at": "observed_at (WIB)"})
        if "worker_name" in heartbeats.columns:
            heartbeats["worker_name"] = (
                heartbeats["worker_name"]
                .astype(str)
                .str.replace("AFIC", "RIZAN", regex=False)
                .str.replace("afic", "rizan", regex=False)
            )
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
            heartbeats["details"] = (
                heartbeats["details"]
                .astype(str)
                .str.replace("AFIC", "RIZAN", regex=False)
                .str.replace("afic", "rizan", regex=False)
            )
        st.dataframe(heartbeats, hide_index=True, width="stretch")
        if not load_full_heartbeat_details:
            st.caption(
                "Mode hemat egress: detail JSON worker V240/pressure/depth tetap fresh 60 detik; "
                "worker observability lain ditampilkan sebagai status ringkas."
            )
    else:
        st.info("No runtime heartbeat snapshots are available.")

    if backend is not None and backend.get("latest_run"):
        st.subheader("Proses Scanner Terbaru (Latest Scanner Run)")
        run = backend["latest_run"]
        run_display = json.loads(
            json.dumps(run, ensure_ascii=False, default=str)
            .replace("AFIC", "RIZAN")
            .replace("afic", "rizan")
        )
        st.json(run_display, expanded=False)

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
