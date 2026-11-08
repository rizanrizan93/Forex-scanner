"""Read-only BUY050 native-source shadow candidate panel.

Displays only ephemeral, expiring technical geometry. Neither source-matching
nor a valid price geometry means that the LIVE cBot accepted or executed an order.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CONTRACT = "RIZAN_BUY050_SHADOW_V1"
PROFILE = "13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6"
URL = (
    "https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
    "buy050-shadow-snapshots/runtime/buy050_shadow_snapshot.json"
)
SYMBOLS = ("XAUUSD", "EURUSD", "BTCUSD")
WIB = ZoneInfo("Asia/Jakarta")


def stamp(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _wib(t):
    dt = stamp(t)
    return dt.astimezone(WIB).strftime("%d/%m %H:%M:%S WIB") if dt else "—"


def evaluate_shadow(payload, *, now=None):
    now = now or datetime.now(timezone.utc)
    if (
        not isinstance(payload, dict)
        or payload.get("contract") != CONTRACT
        or payload.get("strategy") != "P3_BUY050"
        or payload.get("profile_sha256") != PROFILE
        or payload.get("source_core") != "BUY050_NATIVE_CSHARP"
        or payload.get("read_only") is not True
        or payload.get("execution_authority") is not False
        or payload.get("execution_influence") is not False
    ):
        raise ValueError("SHADOW_CONTRACT_INVALID")
    rows = payload.get("symbols")
    if not isinstance(rows, list) or len(rows) != 3 or {
        row.get("symbol") for row in rows if isinstance(row, dict)
    } != set(SYMBOLS):
        raise ValueError("SHADOW_INSTRUMENTS_INVALID")
    time_at = stamp(payload.get("as_of"))
    age = (now - time_at).total_seconds() if time_at else float("inf")
    fresh = -30 <= age <= 900
    results = {}
    for row in rows:
        symbol = row["symbol"]
        if row.get("execution_authority") is not False or row.get("execution_influence") is not False:
            raise ValueError("SHADOW_ROW_EXECUTION_AUTHORITY_INVALID")
        candidate = row.get("candidate")
        accepted = None
        if fresh and isinstance(candidate, dict):
            at, expiry = stamp(candidate.get("at")), stamp(candidate.get("valid_until"))
            side = 1 if candidate.get("side") == "BUY" else -1 if candidate.get("side") == "SELL" else 0
            entry, sl, tp, rr = (candidate.get(x) for x in ("entry", "sl", "tp", "target_r"))
            geometry = (
                side and all(type(v) in (int, float) and math.isfinite(v) and v > 0
                             for v in (entry, sl, tp, rr))
                and 0 < side * (entry - sl)
                and 0 < side * (tp - entry)
                and abs(side * (tp - entry) - rr * side * (entry - sl))
                <= max(1e-6, abs(entry - sl) * 1e-6)
            )
            window = 5 if symbol == "BTCUSD" else 60
            if (
                geometry and at and expiry and at <= now < expiry
                and expiry <= at + __import__("datetime").timedelta(seconds=window)
                and isinstance(candidate.get("blockers"), list)
                and "CANDIDATE_NOT_BROKER_EXECUTED" in candidate["blockers"]
                and candidate.get("confidence") == "TECHNICAL_GEOMETRY_ONLY"
            ):
                accepted = candidate
        results[symbol] = {"status": row.get("status", "WAIT") if fresh else "DATA_TERLAMBAT",
                           "reason": str(row.get("reason") or "")[:210] if fresh else "Data shadow sudah kedaluwarsa.",
                           "candidate": accepted, "bar_at": row.get("bar_at") if fresh else None}
    return {"fresh": fresh, "age_seconds": age, "as_of": payload.get("as_of"), "symbols": results}


def fetch_shadow(bucket):
    req = Request(URL + "?slot=" + str(bucket), headers={"User-Agent": "RIZAN-BUY050-shadow-readonly"})
    with urlopen(req, timeout=10) as response:
        raw = response.read(80_001)
    if len(raw) > 80_000:
        raise ValueError("SHADOW_JSON_TOO_LARGE")
    return json.loads(raw)


def render_shadow(payload, *, now=None):
    import streamlit as st

    model = evaluate_shadow(payload, now=now)
    st.markdown("#### Sinyal teknis native BUY050 · XAU / EUR / BTC")
    st.caption("Perhitungan memakai modul C# frozen; status merupakan evaluasi bayangan, bukan order broker. Periode publikasi sekitar 5 menit, sehingga window sinyal 60 detik dan BTC 5 detik bisa terlewat.")
    st.caption("Data shadow " + _wib(model["as_of"]))
    if not model["fresh"]:
        st.warning("Snapshot shadow tidak baru; level entry/SL/TP disembunyikan.")
    for symbol in SYMBOLS:
        row = model["symbols"][symbol]
        st.markdown("**" + symbol + " · " + row["status"] + "**")
        cand = row["candidate"]
        if cand:
            side = cand["side"]
            st.caption("Pola " + cand.get("origin", "—") + " · " + side + " · berlaku maksimal sampai " + _wib(cand["valid_until"]))
            digits = 5 if symbol == "EURUSD" else 2
            a, b, c = st.columns(3)
            a.metric("Entry skenario", f"{cand['entry']:,.{digits}f}")
            b.metric("SL skenario", f"{cand['sl']:,.{digits}f}")
            c.metric("TP skenario", f"{cand['tp']:,.{digits}f}")
            st.warning("Belum terkonfirmasi oleh terminal LIVE. Filter makro, data broker, margin, basket, dan weekend tetap wajib lulus.")
        else:
            st.caption(row["reason"] or "Belum ada kandidat teknis baru yang memenuhi jendela strategi.")
    st.caption("Tidak ada fungsi order, stop/start, atau pengubahan parameter cBot pada modul ini.")


def render_shadow_panel():
    import streamlit as st

    @st.cache_data(ttl=50, show_spinner=False)
    def cached(slot):
        return fetch_shadow(slot)

    try:
        now = datetime.now(timezone.utc)
        render_shadow(cached(int(now.timestamp() // 50)), now=now)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        st.markdown("#### Sinyal teknis native BUY050")
        st.info("Snapshot shadow belum tersedia/valid. Entry, SL, dan TP tidak akan dibuat dari sinyal lama atau data yang tidak lengkap.")
