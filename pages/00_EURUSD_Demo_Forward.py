from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_scanner.dashboard_snapshot_transport import fetch_eurusd_snapshot  # noqa: E402

UTC = timezone.utc
WIB = ZoneInfo("Asia/Jakarta")
EURUSD_WORKER = "ctrader_demo_eurusd_frozen_dd37"
ORDER_AUDIT_WORKER = "ctrader_demo_order_protection_audit"
STRATEGY_ID = "EURUSD_SWEEP_COMPOUND_DD37_FROZEN_V1"

st.set_page_config(
    page_title="RIZAN EURUSD DEMO",
    page_icon="💶",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container {padding-top:.75rem; padding-bottom:2rem; max-width:1100px;}
      .eu-title {font-size:1.75rem; font-weight:800; margin-bottom:.15rem;}
      .eu-sub {opacity:.72; margin-bottom:.8rem;}
      .eu-card {border:1px solid rgba(128,128,128,.22); border-radius:14px; padding:.75rem .85rem; margin:.35rem 0;}
      .eu-kicker {font-size:.78rem; opacity:.68; text-transform:uppercase; letter-spacing:.05em;}
      .eu-value {font-size:1.42rem; font-weight:700; overflow-wrap:anywhere;}
      .eu-reason {font-size:.92rem; line-height:1.45;}
      div[data-testid="stMetric"] {border:1px solid rgba(128,128,128,.18); border-radius:12px; padding:.45rem .6rem;}
      @media (max-width:768px) {
        .block-container {padding-left:.75rem; padding-right:.75rem;}
        .eu-title {font-size:1.42rem;}
        .eu-value {font-size:1.18rem;}
        div[data-testid="stMetricValue"] {font-size:1.15rem; overflow-wrap:anywhere;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _fmt_wib(value: Any) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "—"
    return parsed.astimezone(WIB).strftime("%d %b %Y • %H:%M:%S WIB")


def _age_seconds(value: Any) -> float | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def _fmt_price(value: Any) -> str:
    try:
        return f"{float(value):.5f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _latest_heartbeat(rows: list[dict[str, Any]], worker: str) -> dict[str, Any] | None:
    matches = [dict(row or {}) for row in rows if str((row or {}).get("worker_name") or "") == worker]
    if not matches:
        return None
    return max(matches, key=lambda row: str(row.get("observed_at") or ""))


REASON_TEXT = {
    "NO_FRESH_SWEEP": "Belum ada liquidity sweep M15 baru yang memenuhi kontrak strategi.",
    "WAIT_NEXT_M15_OPEN_WINDOW": "Menunggu jendela pembukaan M15 berikutnya. Setup hanya boleh diproses pada window sinyal yang masih fresh.",
    "SIGNAL_ALREADY_CONSUMED": "Sinyal M15 ini sudah pernah diproses; engine tidak mengejar atau mengirim ulang sinyal lama.",
    "EURUSD_BASKET_OR_EXTERNAL_ORDER_ACTIVE": "Masih ada basket/order EURUSD aktif, sehingga basket baru ditahan.",
    "EURUSD_SPREAD_ABOVE_STRESS_2_2_PIPS": "Spread EURUSD lebih lebar dari batas stres 2,2 pip; entry diblokir.",
    "BUDGET_BELOW_ONE_CHILD": "Equity/free margin saat ini tidak cukup untuk minimal satu child 0,01 lot sesuai kontrak sizing.",
    "CHILD_BATCH_QUOTE_DRIFT_OR_SPREAD": "Harga bergerak terlalu jauh atau spread melebar ketika batch child akan dikirim.",
    "CHILD_BATCH_BUDGET_LIMIT": "Batch dihentikan karena batas risiko/margin basket telah tercapai.",
    "BROKER_FREE_MARGIN_LIMIT": "Free margin broker tidak cukup untuk child berikutnya.",
    "UNCERTAIN_ATTEMPT_QUARANTINE": "Ada submission yang statusnya tidak pasti. Runtime dikarantina agar tidak terjadi duplicate order.",
}


@st.cache_data(ttl=30, show_spinner=False)
def _load_snapshot() -> tuple[dict[str, Any] | None, str | None, bool]:
    try:
        payload = fetch_eurusd_snapshot()
        degraded = not bool(payload["bridge"]["fresh"])
        return payload, ("Snapshot publikasi kedaluwarsa" if degraded else None), degraded
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}", True


def _contains_eurusd(row: Any) -> bool:
    try:
        raw = json.dumps(row, ensure_ascii=False, default=str).upper()
    except Exception:
        raw = str(row).upper()
    return "EURUSD" in raw or "RZEU37" in raw or "EU37" in raw


st.markdown('<div class="eu-title">💶 EURUSD • DEMO Forward</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="eu-sub">Strategy aktif: <b>EURUSD_SWEEP_COMPOUND_DD37_FROZEN_V1</b> • halaman khusus EURUSD, tidak bercampur dengan keputusan XAUUSD.</div>',
    unsafe_allow_html=True,
)

refresh_col, note_col = st.columns([1, 3])
with refresh_col:
    if st.button("↻ Refresh EURUSD", width="stretch"):
        _load_snapshot.clear()
        st.rerun()
with note_col:
    st.caption("Snapshot dashboard diperbarui sekitar 60 detik. Runtime broker tetap berjalan independen dari halaman ini.")

@st.fragment(run_every="60s")
def _eurusd_refresh_tick():
    now = datetime.now(UTC)
    last = st.session_state.get("eurusd_refresh_at")
    if not isinstance(last, datetime):
        st.session_state["eurusd_refresh_at"] = now
    elif (now - last).total_seconds() >= 59.5:
        st.session_state["eurusd_refresh_at"] = now
        _load_snapshot.clear()
        st.rerun()

_eurusd_refresh_tick()

payload, load_error, degraded = _load_snapshot()
if payload is None:
    st.error("Data EURUSD belum dapat dibaca dari ForexRizan bridge.")
    st.code(load_error or "UNKNOWN_BRIDGE_ERROR", language=None)
    st.stop()

backend = dict(payload.get("backend") or {})
bridge = dict(payload.get("bridge") or {})
heartbeats = list(backend.get("heartbeats") or [])
eu_hb = _latest_heartbeat(heartbeats, EURUSD_WORKER)
audit_hb = _latest_heartbeat(heartbeats, ORDER_AUDIT_WORKER)
bridge_age = bridge.get("age_seconds")

if load_error:
    st.caption("Freshness note: " + load_error)

if eu_hb is None:
    st.error("Heartbeat EURUSD belum ditemukan. Strategy boleh sudah ada di kode, tetapi runtime EURUSD belum dapat diverifikasi dari dashboard.")
    st.stop()

observed_at = eu_hb.get("observed_at")
eu_age = _age_seconds(observed_at)
eu = dict(eu_hb.get("details") or {})
state = str(eu.get("state") or "UNKNOWN").upper()
reason = str(eu.get("reason") or "UNKNOWN")
stale = bool(degraded or eu_age is None or eu_age > 180)

candidate = dict(eu.get("candidate") or {})
side_raw = candidate.get("side")
if side_raw == 1 or str(side_raw).upper() in {"1", "BUY", "LONG"}:
    direction = "BUY"
elif side_raw == -1 or str(side_raw).upper() in {"-1", "SELL", "SHORT"}:
    direction = "SELL"
elif eu.get("entry") is not None:
    direction = "BUY/SELL ACTIVE"
else:
    direction = "WAIT"

if stale:
    effective_state = "STALE"
elif not eu_hb.get("healthy", False):
    effective_state = "ERROR_FAIL_CLOSED"
else:
    effective_state = state

if effective_state == "ORDER_ACCEPTED":
    st.success("EURUSD ORDER ACCEPTED • broker DEMO menerima minimal satu child order.")
elif effective_state in {"BLOCKED", "ERROR", "ERROR_FAIL_CLOSED"}:
    st.error(f"EURUSD {effective_state} • entry baru tidak boleh diteruskan.")
elif effective_state == "STALE":
    st.error("EURUSD STALE • snapshot atau heartbeat belum fresh. Angka entry adalah catatan terakhir.")
else:
    st.info(f"EURUSD {effective_state} • {REASON_TEXT.get(reason, reason)}")

setup_tab, positions_tab, strategy_tab, diagnostics_tab = st.tabs(
    ["Setup", "Posisi & order", "Strategi", "Diagnostik"])
with setup_tab:
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Arah", direction)
    with c2:
        st.metric("Status", effective_state)

    st.markdown(
        f"""
        <div class="eu-card">
          <div class="eu-kicker">Alasan runtime</div>
          <div class="eu-reason"><b>{reason}</b><br>{REASON_TEXT.get(reason, 'Lihat kode alasan runtime di atas; engine tetap fail-closed bila syarat broker atau data tidak lengkap.')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    from fx_scanner.frozen_layering_dashboard import render_layering
    render_layering("EURUSD",eu)
    st.subheader("Entry plan")
    entry = eu.get("entry")
    sl = eu.get("sl")
    tp = eu.get("tp")
    if entry is None:
        st.info("Belum ada harga entry aktif. Engine sedang menunggu setup baru; dashboard tidak membuat angka entry buatan.")
    else:
        p1, p2, p3 = st.columns(3)
        p1.metric("ENTRY", _fmt_price(entry))
        p2.metric("SL", _fmt_price(sl))
        p3.metric("TP", _fmt_price(tp))
        st.caption("Target frozen contract = 4R. SL berbasis 3× ATR14 dan dibatasi 5–60 pip.")

    l1, l2 = st.columns(2)
    l1.metric("Layer rencana", int(eu.get("planned_children") or 0))
    l2.metric("Layer diterima", int(eu.get("accepted_children") or 0))
    lot_plan = float(eu.get("planned_total_lot") or 0.0)
    lot_live = int(eu.get("accepted_children") or 0) * 0.01
    st.caption(f"Rencana total {lot_plan:.2f} lot • diterima broker pada cycle ini {lot_live:.2f} lot • setiap child 0,01 lot.")

    m1, m2 = st.columns(2)
    m1.metric("Sizing multiplier", _fmt_num(eu.get("sizing_multiplier"), 3))
    m2.metric("Update runtime", _fmt_wib(observed_at))


with diagnostics_tab:
    with st.expander("Kesehatan strategy & signal", expanded=True):
        h1, h2 = st.columns(2)
        h1.metric("Fast EMA outcome (R)", _fmt_num(eu.get("fast_ema_r"), 3))
        h2.metric("Slow EMA outcome (R)", _fmt_num(eu.get("slow_ema_r"), 3))
        st.write("M1 selesai terakhir:", eu.get("last_completed_m1") or "—")
        st.write("Policy hash:", eu.get("policy_hash") or "—")
        st.write("Git SHA runtime:", eu.get("git_sha") or "—")
        st.write("Execution scope:", eu.get("execution_scope") or "—")
        st.write("LIVE execution:", "AKTIF" if eu.get("live_execution_enabled") else "TIDAK AKTIF")
        if candidate:
            st.write("Candidate M15:", candidate)


with positions_tab:
    st.subheader("Posisi & order broker EURUSD")
    if audit_hb is None:
        st.warning("Heartbeat broker protection audit belum tersedia pada snapshot ini.")
    else:
        audit = dict(audit_hb.get("details") or {})
        positions = [row for row in list(audit.get("open_positions") or []) if _contains_eurusd(row)]
        accepted = [row for row in list(audit.get("latest_accepted_orders") or []) if _contains_eurusd(row)]
        a1, a2 = st.columns(2)
        a1.metric("Posisi EURUSD terbuka", len(positions))
        a2.metric("Audit broker", _fmt_wib(audit_hb.get("observed_at")))
        if positions:
            st.dataframe(positions, hide_index=True, width="stretch")
            st.caption("SL/TP pada tabel berasal dari posisi broker DEMO yang diaudit, bukan hanya rencana scanner.")
        else:
            st.info("Tidak ada posisi EURUSD terbuka yang teridentifikasi pada audit broker terakhir.")
        if accepted:
            with st.expander("Order EURUSD terbaru yang diterima broker", expanded=False):
                st.dataframe(accepted, hide_index=True, width="stretch")


with strategy_tab:
    with st.expander("Kontrak strategy EURUSD yang dibekukan", expanded=False):
        st.markdown(
            """
    - **Signal:** liquidity sweep M15 terhadap 8 candle sebelumnya + body ratio; H1 harus netral menurut kontrak frozen.
    - **Window signal:** hanya sinyal fresh pada pembukaan M15; sinyal yang terlambat tidak dikejar.
    - **Stop:** 3× ATR14 sederhana, dibatasi 5–60 pip.
    - **Target:** 4R.
    - **Basket risk reference:** 27,25% equity, tetapi jumlah child aktual tetap dibatasi free margin dan expected broker margin.
    - **Initial margin budget:** 60% reference equity sebelum multiplier.
    - **Child order:** 0,01 lot per child; semua child wajib memiliki server-side SL + TP.
    - **Timeout:** maksimum 240 menit dan tidak ditahan melewati 20:00 UTC.
    - **Scope:** DEMO only. XAUUSD tidak mewarisi override risiko EURUSD.

    Hasil replay terpilih 2016–2025 ($100 → $11.820,23; PF 2,211; floating DD 37,08%) adalah hasil historis terpilih, **bukan** proyeksi return atau batas drawdown forward.
            """
        )


st.divider()
st.caption(
    f"ForexRizan bridge age: {('—' if bridge_age is None else str(round(float(bridge_age), 1)) + 's')} • "
    f"Strategy: {STRATEGY_ID} • data source read-only dashboard bridge."
)
