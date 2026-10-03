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


def yield_pct(value: Any) -> str:
    number = f(value)
    return "BELUM TERSEDIA" if number is None else f"{number:.3f}%"


def bps(value: Any) -> str:
    number = f(value)
    if number is None:
        return "—"
    return f"{number:+.1f} bp"


def age_label(value: Any) -> str:
    seconds = f(value)
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f} dtk"
    return f"{seconds / 60.0:.1f} mnt"


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
    "Satu halaman untuk membaca keputusan scanner. V378 menambahkan Decision Confidence berbasis evidence "
    "serta menampilkan US10Y FRED daily dan pressure intraday secara langsung. "
    "Score adalah kualitas evidence, bukan probabilitas menang. LIVE tetap keputusan manual."
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
decision_confidence = d(summary.get("decision_confidence"))
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
behavior = d(sd.get("afiq_behavioral"))
behavior_regime = d(behavior.get("regime"))
behavior_role = d(behavior.get("active_zone_role"))
behavior_acceptance = d(behavior.get("acceptance_rejection"))
behavior_m30 = d(behavior.get("m30_internal"))
behavior_response = d(behavior.get("response_timer"))

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

st.markdown("### V378 Decision Confidence")
if decision_confidence:
    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric("Evidence score", f"{float(decision_confidence.get('evidence_score') or 0):.1f}/100")
    dc2.metric("Confidence band", str(decision_confidence.get("confidence_band") or "LOW"))
    dc3.metric("Evidence coverage", f"{float(decision_confidence.get('coverage_pct') or 0):.0f}%")
    dc4.metric("Arah yang dinilai", str(decision_confidence.get("direction") or "WAIT"))
    st.caption("Decision Confidence mengukur kualitas dan keselarasan evidence; bukan calibrated win probability dan bukan trigger entry mandiri.")
    components = list(decision_confidence.get("components") or [])
    if components:
        st.dataframe(
            [
                {
                    "Komponen": row.get("name"),
                    "Bobot": row.get("weight"),
                    "Score": row.get("score"),
                    "Kontribusi": row.get("contribution"),
                    "Available": row.get("available"),
                    "State": row.get("state"),
                }
                for row in components
            ],
            use_container_width=True,
            hide_index=True,
        )
    conflicts = list(decision_confidence.get("conflicting_factors") or [])
    missing = list(decision_confidence.get("missing_evidence") or [])
    if conflicts:
        st.warning("Conflict evidence • " + " | ".join(str(x) for x in conflicts))
    if missing:
        st.caption("Evidence belum tersedia • " + " | ".join(str(x) for x in missing))
else:
    st.info("V378 Decision Confidence belum tersedia pada snapshot ini. Tunggu heartbeat baru setelah deployment.")

st.caption(
    "MAIN HTF tetap menjadi anchor struktural. Reaction candidate dapat dipromosikan lebih awal, "
    "tetapi V376 dapat memblokir DEMO jika completed-bar evidence menunjukkan thesis aktif gagal."
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
        "Jika reaction sudah bergerak terlalu jauh tanpa entry, scanner tetap NO CHASE."
    )

st.markdown("## 2 • V376 Afiq Behavioral Context")
if not behavior:
    st.info("V376 belum tersedia pada heartbeat ini. Tunggu runtime baru melakukan refresh.")
else:
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Market regime", str(behavior_regime.get("state") or "UNKNOWN"))
    q2.metric("Fungsi MAIN zone", str(behavior_role.get("role") or "UNKNOWN"))
    q3.metric("Acceptance / rejection", str(behavior_acceptance.get("state") or "UNKNOWN"))
    q4.metric("M30 internal", str(behavior_m30.get("state") or "UNKNOWN"))

    r1, r2, r3 = st.columns(3)
    r1.metric("Response timer", str(behavior_response.get("state") or "NOT_STARTED"))
    r2.metric("Manual decision", str(behavior.get("manual_decision_state") or "WAIT"))
    r3.metric("DEMO behavior gate", str(behavior.get("demo_entry_gate") or "UNKNOWN"))

    if str(behavior.get("demo_entry_gate") or "").startswith("BLOCK_"):
        st.error(
            "**Behavioral hard block:** "
            + str(behavior.get("hard_block_reason") or "THESIS_FAILED")
            + ". V375/V342 DEMO candidate tidak boleh diteruskan sampai engine rebuild."
        )
    elif bool(behavior.get("m30_conflict")):
        st.warning(
            "M30 saat ini berlawanan dengan arah HTF candidate. Ini WATCH/WAIT untuk manual decision; "
            "belum menjadi hard block kecuali acceptance/reaction failure terkonfirmasi."
        )

    if behavior_acceptance:
        st.caption(
            "Zone test • penetration="
            + (
                "—"
                if behavior_acceptance.get("penetration_atr") is None
                else f"{float(behavior_acceptance.get('penetration_atr')):.2f} ATR"
            )
            + " • outside closes last4="
            + str(behavior_acceptance.get("outside_close_count_last4") or 0)
            + " • reclaim="
            + str(bool(behavior_acceptance.get("reclaim_seen")))
        )

    if behavior_response and behavior_response.get("state") != "NOT_STARTED":
        st.caption(
            "Response timer • M5 bars="
            + str(behavior_response.get("bars_elapsed") or 0)
            + " • MFE="
            + (
                "—"
                if behavior_response.get("favorable_excursion_local_atr") is None
                else f"{float(behavior_response.get('favorable_excursion_local_atr')):.2f} local ATR"
            )
            + " • MAE="
            + (
                "—"
                if behavior_response.get("adverse_excursion_local_atr") is None
                else f"{float(behavior_response.get('adverse_excursion_local_atr')):.2f} local ATR"
            )
        )

    path = list(behavior.get("expected_path") or [])
    if path:
        st.markdown("**Expected path:**")
        for step in path[:6]:
            row = d(step)
            if row.get("low") is not None and row.get("high") is not None:
                level = f"{px(row.get('low'))}–{px(row.get('high'))}"
            else:
                level = px(row.get("price"))
            st.write(f"• {row.get('role','CONTEXT')} → {level}")

    roles = list(behavior.get("zone_roles") or [])
    if roles:
        with st.expander("Zone role map"):
            st.dataframe(
                [
                    {
                        "TF": row.get("timeframe"),
                        "Direction": row.get("direction"),
                        "Low": row.get("low"),
                        "High": row.get("high"),
                        "Role": row.get("role"),
                        "Condition": row.get("condition"),
                        "Quality": row.get("quality_score"),
                    }
                    for row in roles[:12]
                ],
                use_container_width=True,
                hide_index=True,
            )

st.markdown("## 3 • Macro, US10Y & event")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Broader macro", bias_label(macro_summary.get("broader_bias")))
m2.metric("US10Y FRED Daily", yield_pct(daily_yield.get("current")), delta=bps(daily_yield.get("delta_bps")))
m3.metric("US10Y Intraday ^TNX", yield_pct(intraday_yield.get("current")), delta=bps(intraday_yield.get("net_bps")))
m4.metric("Yield alignment", str(yield_summary.get("alignment") or "UNAVAILABLE"))

fy1, fy2 = st.columns(2)
with fy1:
    st.markdown("**FRED US10Y daily (DGS10)**")
    st.write(
        {
            "state": daily_yield.get("state") or "UNAVAILABLE",
            "current": yield_pct(daily_yield.get("current")),
            "previous": yield_pct(daily_yield.get("previous")),
            "daily_change": bps(daily_yield.get("delta_bps")),
            "gold_bias": bias_label(daily_yield.get("gold_bias")),
            "freshness": daily_yield.get("freshness") or "UNAVAILABLE",
            "observed_at": daily_yield.get("observed_at") or "BELUM TERSEDIA",
            "source": daily_yield.get("source") or "FEDERAL_RESERVE_FRED",
            "series": daily_yield.get("series") or "DGS10",
        }
    )
with fy2:
    st.markdown("**US10Y intraday timing (^TNX secondary proxy)**")
    st.write(
        {
            "state": intraday_yield.get("state") or "UNAVAILABLE",
            "current": yield_pct(intraday_yield.get("current")),
            "reference": yield_pct(intraday_yield.get("reference")),
            "window_change": bps(intraday_yield.get("net_bps")),
            "window_minutes": intraday_yield.get("window_minutes") or "—",
            "gold_bias": bias_label(intraday_yield.get("gold_bias")),
            "age": age_label(intraday_yield.get("age_seconds")),
            "source": intraday_yield.get("source") or "INTRADAY_SECONDARY_PROXY",
            "available": bool(intraday_yield.get("available")),
        }
    )
    if not intraday_yield.get("available"):
        st.warning("US10Y intraday belum fresh/tersedia. Jangan gunakan intraday yield sebagai timing trigger sampai feed kembali valid.")
    post_event = d(intraday_yield.get("post_event_diagnostic"))
    if post_event:
        st.caption(
            "Post-event diagnostic • "
            + str(post_event.get("state") or "UNAVAILABLE")
            + " • net release="
            + bps(post_event.get("net_from_release_bps"))
            + " • rebound="
            + bps(post_event.get("rebound_from_low_bps"))
        )

st.caption(str(yield_summary.get("decision_note") or "Yield adalah context/timing evidence, bukan trigger entry mandiri."))

if latest_event:
    st.write(
        "**Rilis terakhir:** "
        + str(latest_event.get("title") or "—")
        + " • Actual="
        + str(latest_event.get("actual") if latest_event.get("actual") is not None else "BELUM TERSEDIA")
        + " • Forecast="
        + str(latest_event.get("forecast") if latest_event.get("forecast") is not None else "BELUM ADA KONSENSUS")
        + " • bias="
        + bias_label(latest_event.get("gold_bias"))
        + " • data="
        + str(latest_event.get("data_confidence") or "UNAVAILABLE")
        + " • arah="
        + str(latest_event.get("direction_confidence") or "UNAVAILABLE")
    )
if next_event:
    st.caption(
        "Event berikutnya • "
        + str(next_event.get("title") or "—")
        + " • "
        + str(next_event.get("scheduled_at_wib") or next_event.get("scheduled_at") or "—")
    )

st.markdown("## 4 • S/R & liquidity")
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

st.markdown("## 5 • Entry, SL & target")
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
    "V378 Decision Confidence tidak membuat entry baru. V376 tetap menangani regime/zone-role/acceptance/M30/response timer. "
    "SL tetap structural dan TP mengikuti S/R/liquidity → opposing H1/H4."
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

st.markdown("## 6 • Kenapa scanner mengambil keputusan ini")
for reason in list(summary.get("reasons") or []):
    st.write("• " + str(reason))
if behavior:
    st.write("• V376 regime: " + str(behavior_regime.get("state") or "UNKNOWN"))
    st.write("• V376 zone role: " + str(behavior_role.get("role") or "UNKNOWN"))
    st.write("• V376 acceptance/rejection: " + str(behavior_acceptance.get("state") or "UNKNOWN"))
    st.write("• V376 M30: " + str(behavior_m30.get("state") or "UNKNOWN"))
    st.write("• V376 response: " + str(behavior_response.get("state") or "NOT_STARTED"))
if decision_confidence:
    for factor in list(decision_confidence.get("supporting_factors") or []):
        st.write("• V378 support: " + str(factor))
    for factor in list(decision_confidence.get("conflicting_factors") or []):
        st.write("• V378 conflict: " + str(factor))

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
    "Urutan baca: **Keputusan → Decision Confidence → Regime → Zone role → Expected path → Acceptance/Rejection → "
    "US10Y FRED/intraday → M30 → M15/M5 confirmation → Response timer → Entry gate → Structural SL/TP**. "
    "Untuk akun LIVE, halaman ini adalah decision support: order tetap manual. "
    "Untuk DEMO, behavioral hard-failure dapat memveto candidate, tetapi V378 score sendiri belum menjadi execution gate."
)