"""BUY050 cBots dashboard. Read-only observations, never projected trade orders."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CONTRACT = "RIZAN_BUY050_READONLY_V1"
RELEASE = "BUY050_RUNTIMEGUARD_20261108"
SYMBOLS = ("XAUUSD", "EURUSD", "BTCUSD")
SNAPSHOT_URL = (
    "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
    "buy050-monitor-snapshots/runtime/buy050_live_snapshot.json"
)
WIB = ZoneInfo("Asia/Jakarta")


def _time(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _wib(value):
    t = _time(value)
    return t.astimezone(WIB).strftime("%d/%m %H:%M:%S WIB") if t else "—"


def _lag_label(age_seconds):
    """Age of a source observation; never substitute page refresh time."""
    if age_seconds == float("inf"):
        return "timestamp tidak tersedia"
    if age_seconds < -30:
        return "timestamp di masa depan"
    if age_seconds < 60:
        return f"{max(0, int(age_seconds))} detik"
    return f"{age_seconds / 60:.1f} menit"


def evaluate_snapshot(raw, *, now=None):
    """Reject spoofed/old contracts and distinguish publication from LIVE readiness."""
    now = now or datetime.now(timezone.utc)
    if (
        not isinstance(raw, dict) or raw.get("contract") != CONTRACT
        or raw.get("source_release") != RELEASE
        or raw.get("strategy") != "P3_BUY050"
        or raw.get("account_suffix") != "7903"
        or raw.get("read_only") is not True
        or raw.get("execution_authority") is not False
    ):
        raise ValueError("INVALID_BUY050_MONITOR_CONTRACT")
    observed = _time(raw.get("observed_at"))
    rows = raw.get("symbols")
    if not isinstance(rows, list) or len(rows) != len(SYMBOLS):
        raise ValueError("INVALID_BUY050_SYMBOLS")
    if {r.get("symbol") for r in rows if isinstance(r, dict)} != set(SYMBOLS):
        raise ValueError("INVALID_BUY050_SYMBOL_SET")
    age = (now - observed).total_seconds() if observed else float("inf")
    snapshot_fresh = -30 <= age <= 900
    health = raw.get("bridge") if isinstance(raw.get("bridge"), dict) else {}
    health_at = _time(health.get("observed_at"))
    health_age = (now - health_at).total_seconds() if health_at else float("inf")
    bridge_ready = (
        snapshot_fresh and raw.get("service_active") is True
        and health.get("profile_ok") is True and -30 <= health_age <= 120
    )
    status = {}
    lease_fresh = {}
    for r in rows:
        symbol = r["symbol"]
        touched = _time(r.get("lease_touched_at"))
        lease_age = (now - touched).total_seconds() if touched else None
        # A published lease_active flag is only useful with its own source
        # timestamp. Older source contracts omit that field: do not invent
        # freshness for them, but reject any explicitly stale lease.
        lease_fresh[symbol] = (
            -30 <= lease_age <= 120 if lease_age is not None else None
        )
        if not snapshot_fresh:
            state = "DATA_TERLAMBAT"
        elif r.get("unrecognized_checkpoint") is True:
            state = "ALGO_PERLU_VERIFIKASI"
        elif r.get("checkpoint_present") is not True or r.get("identity_ok") is not True:
            state = "IDENTITAS_BERMASALAH"
        elif not bridge_ready or r.get("lease_active") is not True:
            state = "BELUM_TERHUBUNG"
        elif lease_fresh[symbol] is False:
            state = "LEASE_TERLAMBAT"
        elif r.get("fault") is True or r.get("quarantined") is True or r.get("exit_pending") is True:
            state = "BLOKIR_NATIVE"
        elif r.get("checkpoint_basket") is True or r.get("pending_intent") is True:
            state = "CHECKPOINT_AKTIF"
        else:
            state = "TERPANTAU"
        status[symbol] = state
    return {
        "payload": raw, "observed_at": observed,
        "fresh": snapshot_fresh, "bridge_ready": bridge_ready,
        "health_age_seconds": health_age, "age_seconds": age,
        "statuses": status, "lease_freshness": lease_fresh,
    }


def _fetch(bucket):
    # Cache-buster is publication-scale; refresh UI does not imply broker poll.
    req = Request(SNAPSHOT_URL + "?slot=" + str(bucket), headers={"User-Agent": "RIZAN-cBots-readonly/1"})
    with urlopen(req, timeout=9) as response:
        data = response.read(80_001)
    if len(data) > 80_000:
        raise ValueError("BUY050_MONITOR_TOO_LARGE")
    return json.loads(data)


def _profile_details(symbol):
    return {
        "XAUUSD": (
            "Frozen utama: SL 2,4 × ATR; TP 4,5R; pengali risiko 1,65. "
            "BUY050 juga memuat entry tambahan H1 dan guard portofolio."
        ),
        "EURUSD": (
            "Frozen EUR: target 10R; konfigurasi EurStop 0,845 dan "
            "EurRisk 0,80; layering sesuai state native."
        ),
        "BTCUSD": (
            "Frozen BTC: BUY SL 2 × ATR / TP 12R, SELL SL 1,5 × ATR / TP 2R. "
            "Setup original + Break40; batas risiko basket tambahan 2,5%; "
            "guard akhir pekan mengikuti jam broker."
        ),
    }[symbol]


def render_snapshot(raw, *, now=None):
    import streamlit as st

    model = evaluate_snapshot(raw, now=now)
    p = model["payload"]
    st.subheader("cBots · Monitor BUY050")
    st.caption("Profil checkpoint P3_BUY050 · XAUUSD + EURUSD + BTCUSD · LIVE akun ****7903 · read-only")
    st.caption(
        "Identitas profil BUY050 yang terdaftar belum membuktikan versi .algo terbaru "
        "yang sedang dijalankan cTrader. Data berasal dari audit VPS read-only, "
        "bukan streaming terminal maupun konfirmasi order."
    )
    if not model["fresh"]:
        st.error("DATA TERLAMBAT · publikasi BUY050 sudah di luar batas 15 menit. "
                 "Status LIVE saat ini tidak dapat diverifikasi; ini tidak membuktikan cBot mati.")
    elif not model["bridge_ready"]:
        st.warning("Bridge belum dapat dikonfirmasi baru dan sehat. Jangan tafsirkan ini sebagai sinyal entry.")
    else:
        st.info("Bridge BUY050 teramati; kesehatan koneksi tidak membuktikan cBot dapat mengirim order.")
    rows = p["symbols"]
    count = sum(model["statuses"][s] in ("TERPANTAU", "CHECKPOINT_AKTIF", "BLOKIR_NATIVE") for s in SYMBOLS)
    st.metric("Checkpoint identitas terpantau", (str(count) if model["fresh"] else "—") + "/3")
    st.caption("Usia publikasi: " + _lag_label(model["age_seconds"]) +
               " · usia heartbeat bridge: " + _lag_label(model["health_age_seconds"]) +
               ". Refresh halaman bukan pembaruan data broker.")
    historical_connected = (p.get("bridge") or {}).get("connected")
    if not model["fresh"] and type(historical_connected) is int:
        st.caption(f"Snapshot terakhir melaporkan {historical_connected}/3 koneksi bridge; "
                   "angka historis, bukan status LIVE sekarang.")
    st.caption("Terakhir dipublikasikan " + _wib(p.get("observed_at")) + " · heartbeat bridge " + _wib((p.get("bridge") or {}).get("observed_at")))
    st.caption("Batas risiko terdaftar 20,75% · margin 50%. "
               "Parameter ini milik profil monitor BUY050, belum tentu sama dengan .algo baru. "
               "Periksa parameter aktual pada cTrader.")
    labels = {
        "TERPANTAU": "TERPANTAU · checkpoint valid, sinyal diperiksa terpisah",
        "CHECKPOINT_AKTIF": "CHECKPOINT AKTIF · periksa posisi/intent di cTrader",
        "BLOKIR_NATIVE": "BLOKIR · fault, quarantine, atau exit pending",
        "BELUM_TERHUBUNG": "WAIT · lease/bridge belum terverifikasi",
        "LEASE_TERLAMBAT": "WAIT · heartbeat lease sudah kedaluwarsa",
        "IDENTITAS_BERMASALAH": "BLOCK · checkpoint/profil tidak cocok",
        "DATA_TERLAMBAT": "WAIT · data terlambat",
        "ALGO_PERLU_VERIFIKASI": "BLOCK · format checkpoint baru perlu verifikasi",
    }
    by_symbol = {r["symbol"]: r for r in rows}
    for symbol in SYMBOLS:
        item = by_symbol[symbol]
        st.markdown("### " + symbol + " · " + labels[model["statuses"][symbol]])
        st.caption("Profil BUY050 tersimpan (bukan konfigurasi .algo yang baru diverifikasi): "
                   + _profile_details(symbol))
        if model["fresh"] and item.get("unrecognized_checkpoint") is True:
            st.warning("Ditemukan checkpoint lain untuk instrumen dan akun ini yang tidak cocok "
                       "dengan identitas BUY050 tersimpan. Sinkronisasi kontrak algo/bridge "
                       "perlu diperiksa; status otomatis tidak dinyatakan aktif.")
        if model["fresh"] and model["statuses"][symbol] == "LEASE_TERLAMBAT":
            st.warning("Lease aktif pada snapshot, tetapi waktu heartbeat lease tidak "
                       "memenuhi batas 120 detik. Jangan simpulkan cBot siap entry.")
        if model["fresh"] and item.get("checkpoint_present") is True:
            st.write("Checkpoint versi:", item.get("checkpoint_version") if type(item.get("checkpoint_version")) is int else "—")
            st.write("Candle terakhir native:", _wib(item.get("last_bar_at")))
            if symbol == "BTCUSD" and not item.get("last_bar_at"):
                st.caption("Checkpoint BTC profil ini tidak menyediakan timestamp LastBarUtc. "
                           "Lease aktif bukan bukti candle atau feed BTC terbaru; "
                           "gunakan validasi feed shadow dan terminal cTrader.")
            st.write("Sinyal terakhir tercatat:", _wib(item.get("last_signal_at")))
            if item.get("last_signal_at"):
                st.caption("Timestamp sinyal bukan bukti order broker berhasil ataupun sinyal baru yang masih berlaku.")
            if item.get("weekend_lock_until"):
                st.caption("Guard weekend BTC tercatat hingga " + _wib(item.get("weekend_lock_until")) + "; tidak otomatis berarti sedang terkunci.")
            if item.get("fault") or item.get("quarantined"):
                st.error("Native fault/quarantine terdeteksi: entry otomatis harus dianggap terblokir.")
        else:
            st.caption("Belum ada checkpoint BUY050 baru yang dapat diverifikasi untuk instrumen ini.")
        st.caption(
            "**Entry / SL / TP berikutnya: belum terverifikasi.** "
            "Checkpoint bridge tidak berisi paket kandidat, quote eksekusi, dan ukuran order lengkap. "
            "Dashboard tidak mengarang level atau menampilkan ulang sinyal V1.3.0."
        )
        st.divider()
    st.caption(
        "Snapshot VPS dibaca tanpa mengubah cBot, systemd, lease, atau broker. "
        "Eksekusi, floating P/L, volume, margin, posisi manual, dan konfirmasi SL/TP hanya dapat dipastikan di cTrader."
    )


def _render():
    import streamlit as st

    st.session_state.setdefault("rizan_buy050_view", True)
    @st.cache_data(ttl=45, show_spinner=False)
    def cached(slot):
        return _fetch(slot)

    primary_snapshot = None
    try:
        now = datetime.now(timezone.utc)
        primary_snapshot = cached(int(now.timestamp() // 45))
        render_snapshot(primary_snapshot, now=now)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError) as exc:
        # Keep independent audit feeds visible even when primary monitor fails.
        # Passing None to the shadow panel prevents LIVE verification of
        # candidate geometry without a healthy primary checkpoint.
        primary_snapshot = None
        st.subheader("cBots · BUY050 RuntimeGuard")
        st.warning(
            "WAIT · snapshot BUY050 belum tersedia atau tidak valid. "
            "Strategi lama V1.3.0 tidak digunakan sebagai pengganti. "
            "Tidak ada entry, SL atau TP LIVE yang dapat dipastikan dari monitor ini."
        )
        st.caption("Kategori kegagalan monitor: " + type(exc).__name__ +
                   ". Panel shadow dan audit di bawah tetap independen, "
                   "tetapi tidak boleh mengonfirmasi order LIVE.")
    
    # Optional secondary audit panels must never erase an otherwise valid
    # primary read-only checkpoint status if their separate feeds fail.
    try:
        from .cbot_buy050_shadow_dashboard import render_shadow_panel
        render_shadow_panel(primary_snapshot=primary_snapshot)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        st.warning("Panel sinyal shadow sementara tidak tersedia (monitor utama tetap ditampilkan).")
    try:
        from .cbot_buy050_event_dashboard import render_audit_panel
        render_audit_panel()
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        st.warning("Panel audit event sementara tidak tersedia (monitor utama tetap ditampilkan).")


def render_buy050_dashboard():
    import streamlit as st

    st.fragment(run_every="60s")(_render)()
