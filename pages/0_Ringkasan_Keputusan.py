from __future__ import annotations

from typing import Any

import streamlit as st

from fx_scanner.xau_public_hot_v362 import fetch_public_hot_snapshot
from fx_scanner.xau_scanner_summary_v373 import build_scanner_summary


def d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def px(value: Any) -> str:
    number = f(value)
    return "—" if number is None else f"{number:,.2f}"


def zone_label(zone: dict[str, Any]) -> str:
    if not zone:
        return "—"
    kind = "DEMAND" if str(zone.get("direction") or "").upper() == "LONG" else "SUPPLY"
    return f"{zone.get('timeframe','HTF')} {kind} {px(zone.get('low'))}–{px(zone.get('high'))}"


def candidate_label(candidate: dict[str, Any], direction: str) -> str:
    if not candidate:
        return "—"
    low = candidate.get("low")
    high = candidate.get("high")
    if low is None or high is None:
        return zone_label(candidate)
    kind = "REACTION DEMAND" if direction == "LONG" else "REACTION SUPPLY"
    return f"{kind} {px(low)}–{px(high)}"


def bias_label(value: Any) -> str:
    labels = {
        "BULLISH_XAU": "BULLISH XAU",
        "BEARISH_XAU": "BEARISH XAU",
        "GOLD_BULLISH": "BULLISH XAU",
        "GOLD_BEARISH": "BEARISH XAU",
        "NEUTRAL_MIXED": "NETRAL / MIXED",
        "NEUTRAL_UNKNOWN": "BELUM JELAS",
        "UNAVAILABLE": "BELUM TERSEDIA",
    }
    raw = str(value or "UNAVAILABLE").upper()
    return labels.get(raw, raw.replace("_", " "))


def heartbeat(snapshot: dict[str, Any], worker: str) -> dict[str, Any]:
    for raw in list(snapshot.get("heartbeats") or []):
        row = d(raw)
        if row.get("worker_name") == worker:
            return row
    return {}


def evaluation(hb: dict[str, Any]) -> dict[str, Any]:
    return d(d(hb.get("details")).get("evaluation"))


def event_risk(hb: dict[str, Any]) -> dict[str, Any]:
    return d(d(hb.get("details")).get("risk"))


st.set_page_config(page_title="RIZAN Decision Summary", page_icon="🎯", layout="wide")
st.title("RIZAN — Ringkasan Keputusan Scanner")
st.caption(
    "Satu halaman untuk membaca keputusan scanner. V374 dapat mempromosikan reaction/liquidity area "
    "menjadi reversal candidate sebelum MAIN HTF disentuh, sehingga full MSS tidak selalu menjadi trigger pertama."
)

try:
    snapshot = fetch_public_hot_snapshot()
except Exception as exc:
    st.error(f"Public HOT snapshot belum tersedia: {type(exc).__name__}: {exc}")
    st.stop()

sd_hb = heartbeat(snapshot, "ctrader_demo_xau_sd_liquidity_v342")
friend_hb = heartbeat(snapshot, "ctrader_demo_xau_friend_entry_v343")
event_hb = heartbeat(snapshot, "ctrader_demo_xau_event_risk_v192")
macro_hb = heartbeat(snapshot, "ctrader_demo_xau_macro_attribution_v357")

sd = evaluation(sd_hb)
friend = evaluation(friend_hb)
event = event_risk(event_hb)
macro = evaluation(macro_hb)

if not sd:
    st.warning("Snapshot structural V342 belum tersedia. Ringkasan keputusan belum dapat dibangun.")
    st.stop()

summary = build_scanner_summary(
    sd_eval=sd,
    friend_eval=friend,
    event_risk=event,
    macro_eval=macro,
)

decision = d(summary.get("decision"))
main_zone = d(summary.get("main_zone"))
reaction = d(summary.get("reaction_interceptor"))
active_candidate = d(summary.get("active_reversal_candidate"))
entry = d(summary.get("entry"))
macro_summary = d(summary.get("macro"))
yield_summary = d(macro_summary.get("yield"))
daily_yield = d(yield_summary.get("daily"))
intraday_yield = d(yield_summary.get("intraday"))
event_summary = d(summary.get("event"))
latest_event = d(event_summary.get("latest_released"))
next_event = d(event_summary.get("next_event"))
destination = d(summary.get("destination"))
primary_destination = d(destination.get("primary"))
terminal_destination = d(destination.get("terminal"))
sr = d(summary.get("support_resistance"))
direction = str(decision.get("direction") or "WAIT")

st.markdown("## Keputusan scanner sekarang")
a, b, c, e = st.columns(4)
a.metric("Keputusan", str(decision.get("label") or "WAIT"))
b.metric("Arah", direction)
c.metric("Harga", px(summary.get("price")))
e.metric("Context", str(decision.get("context_alignment") or "UNAVAILABLE"))

state = str(decision.get("state") or "WAIT")
action = str(decision.get("action") or "")
if state.startswith("READY_"):
    st.success("**ACTION:** " + action)
elif state.startswith("EARLY_"):
    st.warning("**ACTION:** " + action)
elif state in {"WAIT_NEWS", "NO_CHASE", "REBUILD"}:
    st.warning("**ACTION:** " + action)
else:
    st.info("**ACTION:** " + action)

st.caption(
    "V374 merangkum dan mengintersep reversal lebih awal, tetapi tidak menambah live execution authority. "
    "MAIN HTF adalah fallback struktural; reaction zone dapat mengambil alih bila evidence causal cukup."
)

st.markdown("## 1 • Struktur & active reversal candidate")
s1, s2, s3, s4 = st.columns(4)
s1.metric("H4", str(d(summary.get("structure")).get("H4") or "—"))
s2.metric("H1", str(d(summary.get("structure")).get("H1") or "—"))
s3.metric(
    "Active candidate",
    candidate_label(active_candidate, direction) if reaction.get("promoted") else zone_label(active_candidate),
)
s4.metric("MAIN HTF fallback", zone_label(main_zone))
st.caption(
    "Distance MAIN zone: "
    + ("—" if summary.get("distance_atr") is None else f"{float(summary.get('distance_atr')):.2f} ATR")
    + " • MAIN role="
    + str(summary.get("main_zone_role") or "PRIMARY_HTF_FALLBACK")
)

if reaction.get("promoted"):
    candidate = d(reaction.get("candidate"))
    liq_near = list(reaction.get("nearby_liquidity") or [])
    st.warning(
        "**Reaction zone promoted:** "
        + candidate_label(candidate, direction)
        + " • state="
        + str(reaction.get("state") or "—")
        + " • lifecycle="
        + str(candidate.get("lifecycle_state") or "—")
        + " • score="
        + str(candidate.get("score") or "—")
    )
    if liq_near:
        st.caption(
            "Liquidity pendukung • "
            + " | ".join(f"{row.get('side','—')} {px(row.get('price'))}" for row in liq_near)
        )
    st.caption(
        "MAIN HTF tidak dibatalkan; ia menjadi deep fallback jika reaction candidate gagal. "
        "Jika reaction sudah bergerak > batas no-chase tanpa entry, scanner tidak mengejar harga."
    )

st.markdown("## 2 • Macro, US10Y & event")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Broader macro", bias_label(macro_summary.get("broader_bias")))
m2.metric("US10Y Daily", bias_label(daily_yield.get("gold_bias")))
m3.metric("US10Y Intraday", bias_label(intraday_yield.get("gold_bias")))
m4.metric("Yield alignment", str(yield_summary.get("alignment") or "UNAVAILABLE"))

if latest_event:
    st.write(
        "**Rilis terakhir:** "
        + str(latest_event.get("title") or "—")
        + " • Actual="
        + str(latest_event.get("actual") if latest_event.get("actual") is not None else "—")
        + " • Forecast="
        + str(latest_event.get("forecast") if latest_event.get("forecast") is not None else "—")
        + " • bias="
        + bias_label(latest_event.get("gold_bias"))
    )
if next_event:
    st.caption(
        "Event berikutnya • "
        + str(next_event.get("title") or "—")
        + " • "
        + str(next_event.get("scheduled_at_wib") or next_event.get("scheduled_at") or "—")
    )

st.markdown("## 3 • S/R & liquidity")
r1, r2, r3 = st.columns(3)
r1.metric("Nearest support", px(d(sr.get("support")).get("price")))
r2.metric("Nearest resistance", px(d(sr.get("resistance")).get("price")))
r3.metric("Flip watch", px(d(sr.get("flip_watch")).get("price")))
liq = list(summary.get("liquidity") or [])
if liq:
    st.caption(
        "Liquidity terdekat • "
        + " | ".join(
            f"{row.get('side','—')} {px(row.get('price'))}"
            for row in liq[:5]
        )
    )

st.markdown("## 4 • Entry, SL & target")
reaction_low = entry.get("reaction_early_low")
reaction_high = entry.get("reaction_early_high")
reaction_sl = entry.get("reaction_invalidation")
e1, e2, e3, e4 = st.columns(4)
e1.metric(
    "Early reaction band",
    f"{px(reaction_low)}–{px(reaction_high)}" if reaction_low is not None and reaction_high is not None else "—",
)
e2.metric(
    "MAIN PREPARE",
    f"{px(entry.get('prepared_low'))}–{px(entry.get('prepared_high'))}",
)
e3.metric(
    "Invalidation / SL ref",
    px(reaction_sl if reaction_sl is not None else entry.get("invalidation")),
)
e4.metric("Entry gate", str(decision.get("entry_gate") or "WAIT"))

st.caption(
    "Early layer: sweep/rejection/role-flip + liquidity dapat memicu EARLY WATCH/REACTION sebelum full MSS. "
    "Full MSS/displacement tetap digunakan untuk confirmation/add-on. Jika harga sudah lari, status berubah NO CHASE dan menunggu retest/refined pocket."
)

published_targets = list(entry.get("targets") or [])
if published_targets:
    st.write(
        "**TP scanner:** "
        + " → ".join(px(d(row).get("price")) for row in published_targets[:4])
    )
st.write("**Primary HTF destination:** " + zone_label(primary_destination))
if terminal_destination:
    st.caption(
        "Terminal scenario • " + zone_label(terminal_destination)
        + " • conditional; bukan TP aktif sebelum checkpoint sebelumnya gagal/tertembus secara kausal."
    )

st.markdown("## 5 • Kenapa scanner mengambil keputusan ini")
for reason in list(summary.get("reasons") or []):
    st.write("• " + str(reason))

friend_evidence = d(summary.get("friend_evidence"))
with st.expander("Secondary evidence — Micro Entry Reconstruction"):
    st.write(
        {
            "direction": friend_evidence.get("direction"),
            "state": friend_evidence.get("state"),
            "primary_entry": friend_evidence.get("primary_entry"),
            "stop_loss": friend_evidence.get("stop_loss"),
            "targets": friend_evidence.get("targets"),
            "oos_expectancy_r": friend_evidence.get("oos_expectancy_r"),
            "authority": friend_evidence.get("authority"),
        }
    )

st.markdown("## Cara pakai halaman ini")
st.write(
    "Urutan baca: **Keputusan → Active candidate → MAIN fallback → Macro/US10Y → S/R/liquidity → Entry gate → SL/TP**. "
    "REACTION WATCH berarti area dekat sedang diuji. EARLY REACTION berarti area tersebut sudah dipromosikan tanpa menunggu MAIN atau full MSS. "
    "READY adalah confirmation penuh. NO CHASE berarti jangan mengejar jika entry awal terlewat; tunggu retest atau setup berikutnya."
)
