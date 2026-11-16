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
              "90172c2fba345e4221ca822c8e7d1d760a98c6b1/"
              "repairs/bootstrap125_v1_20261114/STRATEGY_V1_FROZEN.md")
DIRECT_URL = "https://rizan-bridge.duckdns.org:25345/bootstrap125/status.json"
BROKER_URL = "https://rizan-bridge.duckdns.org:25345/bootstrap125/broker.json"
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
            "roles": by_role, "statuses": states, "payload": raw, "now": now}


def checklist(model, symbol):
    """Three-state evidence: a measured false gate differs from missing data."""
    rows = []
    def add(name, value, detail):
        status = "✅ Terpenuhi" if value is True else "❌ Belum terpenuhi" if value is False else "❓ Belum terverifikasi"
        rows.append({"Syarat": name, "Status": status, "Bukti / yang ditunggu": detail})
    current = model is not None and model["fresh"]
    row = model["roles"][symbol] if model else {}
    phase = model["phase"] if model else "UNKNOWN"
    add("Identitas checkpoint V1 cocok", row.get("identity_ok") if current else None,
        "Identitas akun dan kontrak pada checkpoint" if current else "Menunggu observasi V1 baru")
    add("Fase mengizinkan instrumen ini", None if phase == "UNKNOWN" else phase == "GROWTH" or symbol == "EURUSD",
        "Fase " + phase + ("; XAU/BTC menunggu GROWTH" if phase == "SEED" and symbol != "EURUSD" else ""))
    connection = None
    if current:
        if model["statuses"][symbol].startswith(("TERHUBUNG", "STATE AKTIF", "TERBLOKIR")):
            connection = True
        elif model["payload"].get("service_active") is False:
            connection = False
    add("Bridge dan lease baru", connection,
        "Heartbeat lease: " + wib(row.get("lease_touched_at")) if model else "Menunggu observasi bridge")
    for role, label, names in (
        ("BOOTSTRAP", "Pengelola fase bebas fault/halt", ("fault", "halted")),
        (symbol, "Engine instrumen bebas fault/quarantine/exit pending", ("fault", "quarantined", "exit_pending")),
    ):
        item = model["roles"][role] if model else {}
        # Only fields that this role actually persists are required.
        required = names if role == "BOOTSTRAP" else ("fault", "exit_pending") if symbol == "BTCUSD" else ("quarantined",)
        values = [item.get(k) for k in required]
        known = current and item.get("identity_ok") is True
        result = False if known and any(v is True for v in values) else True if known and all(v is False for v in values) else None
        detail = "; ".join(k + "=" + str(item.get(k)) for k in required) if known else "Menunggu state engine baru yang valid"
        add(label, result, detail)
    if symbol == "BTCUSD":
        bridge = model["payload"].get("bridge", {}) if model else {}
        feed = bridge.get("btc_feed_status") if model and model["bridge_ready"] else None
        add("Feed BTC tersedia di bridge", True if feed == "READY" else False if feed == "UNAVAILABLE" else None,
            "Status bridge: " + str(feed or "UNKNOWN") + "; penerimaan terminal diperiksa terpisah")
        until = parse_time(row.get("weekend_lock_until"))
        locked = current and row.get("identity_ok") is True and until and until > model["now"]
        add("Guard akhir pekan mengizinkan entry", False if locked else None,
            "Lock tercatat hingga " + wib(row.get("weekend_lock_until")) + "; waktu terlewati belum membuktikan guard terminal lolos")
    if phase == "SEED" and symbol == "EURUSD":
        setup = ["Warmup 512 M5 dan 1.024 H4 tertutup lengkap", "Candle M5 sinyal bullish",
                 "Close M5 > high 64 bar sebelumnya + 0,05 ATR14", "EMA20 H4 > EMA80 H4 pada candle tertutup"]
    else:
        setup = ["Candle tertutup dan warmup indikator lengkap", "Setup frozen " + {"XAUUSD": "compression/displacement", "EURUSD": "EUR", "BTCUSD": "original / Break40"}[symbol] + " terpenuhi"]
    if phase == "GROWTH" and symbol in ("XAUUSD", "EURUSD"):
        now = model["now"]
        # Source gates: EntryFamilies.XauEvaluate starts 05:00 UTC; compression
        # starts 12:00 UTC. EUR incumbent/AsiaBuy cannot trigger before 07:00 UTC.
        start = 5 if symbol == "XAUUSD" else 7
        allowed = start <= now.hour < 17
        if symbol == "XAUUSD":
            allowed = allowed and now.weekday() < 5
        add("Jam keluarga sinyal GROWTH terbuka", allowed,
            ("XAU: displacement 12:00–00:00 WIB; compression 19:00–00:00 WIB" if symbol == "XAUUSD"
             else "EUR: keluarga sinyal mulai 14:00 WIB; incumbent sampai 19:00, AsiaBuy sampai 00:00 WIB") +
            "; jam terbuka belum membuktikan pola candle atau guard lolos")
    for name in setup:
        add(name, None, "Menunggu candle broker dan evaluasi independen V1")
    for name, detail in (
        ("Trigger entry, sesi dan filter bawaan lolos", "Menunggu evaluasi trigger serta waktu/filter V1"),
        ("Risk, minlot, volume dan margin lolos", "Menunggu equity, exposure dan spesifikasi broker"),
        ("Cooldown, exposure dan guard risiko sesuai fase lolos", "Menunggu state portofolio; Guard47 berlaku pada GROWTH"),
        ("Kirim order dan AccountBinding siap", "Menunggu parameter aktual terminal"),
        ("PortfolioReady dan penerimaan feed terminal siap", "Menunggu telemetry terminal"),
        ("Request order dan hasil broker tercocokkan", "Menunggu Journal dan riwayat broker"),
    ):
        add(name, None, detail)
    return rows


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
    st.caption("✅ Terpenuhi · ❌ Belum terpenuhi berdasarkan bukti · ❓ Belum terverifikasi karena data belum tersedia. Checklist bukan tombol untuk mengirim order.")
    for symbol in ("XAUUSD", "EURUSD", "BTCUSD"):
        checks = checklist(model, symbol)
        counts = [sum(r["Status"].startswith(mark) for r in checks) for mark in ("✅", "❌", "❓")]
        with st.expander(symbol + f" · ✅ {counts[0]} · ❌ {counts[1]} · ❓ {counts[2]}", expanded=True):
            if phase == "SEED" and symbol != "EURUSD":
                st.caption("Menunggu fase GROWTH; instrumen ini tidak membuka entry pada fase SEED.")
            st.write("Entry / SL / TP berikutnya: belum terverifikasi.")
            st.dataframe(checks, hide_index=True, width="stretch")
            if model:
                row = model["roles"][symbol]
                st.caption("Sinyal terakhir tercatat: " + wib(row.get("last_signal_at")) + ". Timestamp bukan konfirmasi order.")
                if symbol == "BTCUSD":
                    st.caption("BTC weekend lock tercatat hingga " + wib(row.get("weekend_lock_until")) +
                               "; status guard sekarang perlu bukti terminal. LastBarUtc tidak disimpan oleh checkpoint BTC.")
    with st.expander("Aturan frozen V1"):
        st.markdown("**SEED — EURUSD BUY:** M5 tertutup bullish, close > high 64 bar sebelumnya + 0,05 ATR14; "
                    "EMA20 H4 > EMA80 H4 tertutup. Warmup 512 M5 / 1.024 H4. SL minimal 1,25 ATR sesuai rumus; TP 4R; "
                    "risiko rencana 8%, margin maksimal 50%; maksimum dua upaya/hari UTC; sinyal berlaku 60 detik.")
        st.markdown("**GROWTH:** XAU compression/displacement (SL 2,4 ATR, TP 4,5R), EUR (target 10R, BE3), "
                    "BTC original + Break40 (BUY stop 2 ATR / TP 12R; SELL stop 1,5 ATR / TP 2R), Guard47 dan weekend policy asli. "
                    "Aturan lengkap, sizing dan filter mengikuti source frozen.")
        st.caption("Fase GROWTH tidak kembali ke SEED saat saldo turun. Guard47 bukan jaminan batas drawdown.")
        st.markdown("[Baca aturan V1 frozen](" + SOURCE_URL + ")")
    st.caption("Status VPS dibaca langsung; target publikasi status 10 detik dan broker 60 detik, layar 15 detik. Fallback GitHub tetap mengikuti timestamp sumber. "
               "BUY050 sebelumnya sudah dihentikan dan tidak dipakai sebagai sumber status V1.")


def fetch_json(url, slot):
    request = Request(url + "?slot=" + str(slot), headers={"User-Agent": "RIZAN-V1-readonly/2", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=9) as response:
        data = response.read(80_001)
    if len(data) > 80_000:
        raise ValueError("V1_MONITOR_TOO_LARGE")
    return json.loads(data)


def fetch_snapshot(slot):
    for url in (DIRECT_URL, SNAPSHOT_URL):
        try:
            data = fetch_json(url, slot)
            evaluate_snapshot(data)
            return data
        except (OSError, ValueError, TypeError, KeyError, TimeoutError):
            if url == SNAPSHOT_URL:
                raise


def render_broker(raw, *, now=None):
    import streamlit as st
    now = now or datetime.now(timezone.utc)
    if (not isinstance(raw, dict) or raw.get("contract") != "RIZAN_BOOTSTRAP125_BROKER_READONLY_V1"
            or raw.get("account_suffix") != "7903" or raw.get("read_only") is not True
            or raw.get("execution_authority") is not False):
        raise ValueError("INVALID_V1_BROKER_CONTRACT")
    st.markdown("### Riwayat order broker V1")
    st.caption("Observasi broker: " + wib(raw.get("observed_at")) + " · cakupan history: " +
               wib(raw.get("history_from")) + " — " + wib(raw.get("history_to")))
    if not fresh(raw.get("observed_at"), now, 180) or raw.get("status") != "OBSERVED":
        st.warning("UNKNOWN · observasi broker terlambat atau gagal. Jangan menafsirkan angka lama sebagai hasil saat ini.")
        return
    st.caption("History order lengkap: " + str(raw.get("orders_history_checked") is True) +
               " · history deal lengkap: " + str(raw.get("deals_history_checked") is True))
    roles = raw.get("roles")
    if not isinstance(roles, dict):
        raise ValueError("INVALID_V1_BROKER_ROLES")
    st.dataframe([dict(Pair=s, Posisi=r.get("open_positions"), Pending=r.get("pending_orders"),
                       Order_V1_48_jam=r.get("orders"), Deal_V1_48_jam=r.get("deals"),
                       Entry_fill=r.get("entry_fills"), Ditolak=r.get("rejected_orders"))
                  for s,r in roles.items() if s in ROLES and isinstance(r,dict)],
                 hide_index=True,width="stretch")
    st.caption("Deal belum terpetakan ke label/order: " + str(raw.get("unmapped_deals", "UNKNOWN")) + ". Angka tabel hanya record V1 teridentifikasi. Nol order bukan bukti nol sinyal; "
               "pencocokan sinyal dan seluruh guard masih diperlukan untuk memastikan missed entry.")


def _render():
    import streamlit as st

    @st.cache_data(ttl=10, show_spinner=False)
    def cached(slot):
        return fetch_snapshot(slot)

    try:
        now = datetime.now(timezone.utc)
        raw = cached(int(now.timestamp() // 10))
        evaluate_snapshot(raw, now=now)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        render_snapshot(unavailable=True)
    else:
        render_snapshot(raw, now=now)
    @st.cache_data(ttl=10, show_spinner=False)
    def broker_cached(slot):
        return fetch_json(BROKER_URL, slot)
    try:
        render_broker(broker_cached(int(datetime.now(timezone.utc).timestamp() // 10)))
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        st.warning("Riwayat broker V1 belum dapat dibaca; status order/fill tetap UNKNOWN.")


def render_v1_dashboard():
    import streamlit as st
    st.fragment(run_every="15s")(_render)()
