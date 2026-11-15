"""Bootstrap125 V1 read-only dashboard; bridge observations are not trade signals."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PROFILE = "RIZAN_BOOTSTRAP125_V1_FROZEN_20261114"
PROFILE_HASH = "b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128"
CONTRACT = "RIZAN_BOOTSTRAP125_READONLY_V1"
ROLES = ("BOOTSTRAP", "XAUUSD", "EURUSD", "BTCUSD")
SNAPSHOT_URL = ("https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
                "bootstrap125-monitor-snapshots/runtime/bootstrap125_live_snapshot.json")
SOURCE_URL = ("https://github.com/rizanrizan93/Forex-scanner/blob/"
              "2a33f76ff281e5b4a6018fed3e080041f27413a3/"
              "repairs/bootstrap125_v1_20261114/STRATEGY_V1_FROZEN.md")
WIB = ZoneInfo("Asia/Jakarta")


def parse_time(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def wib(value):
    t = parse_time(value)
    return t.astimezone(WIB).strftime("%d/%m/%Y %H:%M:%S WIB") if t else "—"


def fresh(value, now, seconds):
    t = parse_time(value)
    return t is not None and -5 <= (now - t).total_seconds() <= seconds


def evaluate_snapshot(raw, *, now=None):
    now = now or datetime.now(timezone.utc)
    if (not isinstance(raw, dict) or raw.get("contract") != CONTRACT
            or raw.get("profile") != PROFILE or raw.get("profile_hash") != PROFILE_HASH
            or raw.get("account_suffix") != "7903" or raw.get("read_only") is not True
            or raw.get("execution_authority") is not False):
        raise ValueError("INVALID_V1_MONITOR_CONTRACT")
    rows = raw.get("roles")
    if (not isinstance(rows, list) or len(rows) != 4
            or any(not isinstance(r, dict) for r in rows)
            or {r.get("role") for r in rows} != set(ROLES)):
        raise ValueError("INVALID_V1_ROLES")
    current = fresh(raw.get("observed_at"), now, 900)
    bridge = raw.get("bridge")
    if not isinstance(bridge, dict):
        raise ValueError("INVALID_V1_BRIDGE")
    bridge_ready = (current and raw.get("service_active") is True
                    and bridge.get("profile_ok") is True
                    and fresh(bridge.get("observed_at"), now, 120))
    by_role = {r["role"]: r for r in rows}
    states = {}
    for role, row in by_role.items():
        lease_current = (row.get("lease_active") is True
                         and fresh(row.get("lease_touched_at"), now, 90)
                         and parse_time(row.get("lease_expires_at")) is not None
                         and parse_time(row["lease_expires_at"]) > now)
        if not current:
            status = "STALE"
        elif row.get("checkpoint_present") is not True:
            status = "CHECKPOINT BELUM TERSEDIA"
        elif row.get("identity_ok") is not True:
            status = "IDENTITAS BELUM VALID"
        elif not bridge_ready or not lease_current:
            status = "KONEKSI BELUM TERVERIFIKASI"
        elif any(row.get(k) is True for k in ("fault", "quarantined", "halted", "exit_pending")):
            status = "TERBLOKIR"
        elif row.get("pending_intent") is True or row.get("checkpoint_basket") is True:
            status = "STATE AKTIF · CEK EKSEKUSI"
        else:
            status = "TERHUBUNG · SINYAL BELUM TERVERIFIKASI"
        states[role] = status
    bootstrap = by_role["BOOTSTRAP"]
    phase = bootstrap.get("phase")
    if not current or bootstrap.get("identity_ok") is not True or phase not in ("SEED", "GROWTH"):
        phase = "UNKNOWN"
    return {"fresh": current, "bridge_ready": bridge_ready, "phase": phase,
            "roles": by_role, "statuses": states, "payload": raw}


def checklist(model, symbol):
    """Only observations that the bridge can actually prove receive a checkmark."""
    row = model["roles"][symbol]
    identity = model["fresh"] and row.get("identity_ok") is True
    connected = model["statuses"][symbol].startswith(("TERHUBUNG", "STATE AKTIF", "TERBLOKIR"))
    return [
        {"Syarat": "Identitas checkpoint V1 cocok", "Status": "✅ Terpenuhi" if identity else "❓ Belum terverifikasi"},
        {"Syarat": "Fase tersimpan SEED/GROWTH", "Status": "✅ " + model["phase"] if model["phase"] != "UNKNOWN" else "❓ Belum terverifikasi"},
        {"Syarat": "Bridge dan lease baru", "Status": "✅ Terpenuhi" if connected else "❓ Belum terverifikasi"},
        {"Syarat": "Candle tertutup, warmup dan aturan setup V1", "Status": "❓ Menunggu bukti candle/indikator"},
        {"Syarat": "Trigger entry, sesi dan filter bawaan", "Status": "❓ Menunggu evaluasi strategi"},
        {"Syarat": "Risk, margin, cooldown, exposure dan Guard47", "Status": "❓ Menunggu data akun dan guard"},
        {"Syarat": "Kirim order, AccountBinding, PortfolioReady dan feed terminal", "Status": "❓ Menunggu telemetry terminal"},
        {"Syarat": "Request order dan hasil broker tercocokkan", "Status": "❓ Menunggu Journal/riwayat broker"},
    ]


def render_snapshot(raw=None, *, now=None, unavailable=False):
    import streamlit as st

    st.subheader("cBots · Bootstrap125 V1")
    st.caption("RizanBootstrap125V1 · rilis 1.0.1 · LIVE ••••7903 · satu cBot untuk XAUUSD / EURUSD / BTCUSD")
    st.caption("Profil frozen 14 November 2026 · pembacaan status tanpa mengubah order atau cBot.")
    model = evaluate_snapshot(raw, now=now) if raw is not None else None
    if unavailable or model is None:
        st.warning("UNKNOWN · data bridge V1 belum tersedia atau belum valid. Koneksi dan eksekusi cBot belum dapat dipastikan.")
    elif not model["fresh"]:
        st.error("STALE · observasi V1 lebih dari 15 menit atau timestamp tidak valid. Status cBot sekarang belum dapat dipastikan.")
    elif model["bridge_ready"]:
        st.info("Observasi bridge V1 tersedia. Koneksi bridge belum membuktikan kesiapan trading atau keberhasilan order.")
    else:
        st.warning("Observasi diterima; heartbeat atau layanan bridge belum terverifikasi baru dan sehat.")
    phase = model["phase"] if model else "UNKNOWN"
    st.metric("Fase V1 tersimpan", phase)
    st.caption("SEED: EURUSD BUY · GROWTH: XAUUSD + EURUSD + BTCUSD. "
               "Perpindahan satu arah setelah balance dan equity ≥ $125, akun flat, history selesai, dan ACK fase tersimpan.")
    if model:
        p = model["payload"]
        st.caption("Observasi VPS: " + wib(p.get("observed_at")) + " · heartbeat: " + wib(p.get("bridge", {}).get("observed_at")))
        if not model["fresh"]:
            st.caption("Angka dan checkpoint di bawah adalah observasi terakhir, bukan status LIVE.")
        st.dataframe([
            {"Role": r, "Status": model["statuses"][r],
             "Checkpoint": model["roles"][r].get("checkpoint_version"),
             "Client revision": model["roles"][r].get("client_revision"),
             "Heartbeat lease": wib(model["roles"][r].get("lease_touched_at"))}
            for r in ROLES
        ], hide_index=True, width="stretch")
        st.caption("Empat role koneksi berasal dari satu instance cBot. BOOTSTRAP mengelola fase; tiga role lain mengelola instrumen.")
    st.markdown("### Sinyal V1 dan eksekusi")
    st.info("Aba-aba: UNKNOWN. Snapshot checkpoint belum memuat evaluasi candle independen, "
            "seluruh guard, dan riwayat broker. Tidak ada dasar menyatakan tidak ada sinyal atau ada order terlewat.")
    for symbol in ("XAUUSD", "EURUSD", "BTCUSD"):
        with st.expander(symbol + " · checklist V1", expanded=symbol == "EURUSD"):
            if phase == "SEED" and symbol != "EURUSD":
                st.caption("Menunggu fase GROWTH; instrumen ini tidak membuka entry pada fase SEED.")
            st.write("Entry / SL / TP berikutnya: belum terverifikasi.")
            if model:
                st.dataframe(checklist(model, symbol), hide_index=True, width="stretch")
                row = model["roles"][symbol]
                st.caption("Sinyal terakhir tercatat: " + wib(row.get("last_signal_at")) + ". Timestamp bukan konfirmasi order.")
                if symbol == "BTCUSD":
                    st.caption("BTC weekend lock tercatat hingga " + wib(row.get("weekend_lock_until")) +
                               "; status guard sekarang perlu bukti terminal. LastBarUtc tidak disimpan oleh checkpoint BTC.")
            else:
                st.write("❓ Identitas/fase, candle dan setup, trigger, guard, kesiapan terminal, request dan hasil broker belum terverifikasi.")
    with st.expander("Aturan frozen V1"):
        st.markdown("**SEED — EURUSD BUY:** M5 tertutup bullish, close > high 64 bar sebelumnya + 0,05 ATR14; "
                    "EMA20 H4 > EMA80 H4 tertutup. Warmup 512 M5 / 1.024 H4. SL minimal 1,25 ATR sesuai rumus; TP 4R; "
                    "risiko rencana 8%, margin maksimal 50%; maksimum dua upaya/hari UTC; sinyal berlaku 60 detik.")
        st.markdown("**GROWTH:** XAU compression/displacement (SL 2,4 ATR, TP 4,5R), EUR (target 10R, BE3), "
                    "BTC original + Break40 (BUY stop 2 ATR / TP 12R; SELL stop 1,5 ATR / TP 2R), Guard47 dan weekend policy asli. "
                    "Aturan lengkap, sizing dan filter mengikuti source frozen.")
        st.caption("Fase GROWTH tidak kembali ke SEED saat saldo turun. Guard47 bukan jaminan batas drawdown.")
        st.markdown("[Baca aturan V1 frozen](" + SOURCE_URL + ")")
    st.caption("Panel diperbarui setiap 60 detik; publikasi status berkala bisa terlambat. Refresh tampilan bukan pembaruan candle broker. "
               "BUY050 sebelumnya sudah dihentikan dan tidak dipakai sebagai sumber status V1.")


def fetch_snapshot(slot):
    request = Request(SNAPSHOT_URL + "?slot=" + str(slot), headers={"User-Agent": "RIZAN-V1-readonly/1"})
    with urlopen(request, timeout=9) as response:
        data = response.read(80_001)
    if len(data) > 80_000:
        raise ValueError("V1_MONITOR_TOO_LARGE")
    return json.loads(data)


def _render():
    import streamlit as st

    @st.cache_data(ttl=45, show_spinner=False)
    def cached(slot):
        return fetch_snapshot(slot)

    try:
        now = datetime.now(timezone.utc)
        raw = cached(int(now.timestamp() // 45))
        evaluate_snapshot(raw, now=now)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        render_snapshot(unavailable=True)
    else:
        render_snapshot(raw, now=now)


def render_v1_dashboard():
    import streamlit as st
    st.fragment(run_every="60s")(_render)()
