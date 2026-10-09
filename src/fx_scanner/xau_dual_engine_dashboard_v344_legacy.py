from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _px(value: Any) -> str:
    number = _f(value)
    return "—" if number is None else f"{number:,.2f}"


def _pct(value: Any) -> str:
    number = _f(value)
    return "—" if number is None else f"{number * 100.0:.1f}%"


_DAY_ID = {
    0: "Senin",
    1: "Selasa",
    2: "Rabu",
    3: "Kamis",
    4: "Jumat",
    5: "Sabtu",
    6: "Minggu",
}



def _event_value(value: Any) -> str:
    """Keep mixed numeric/text calendar columns Arrow-compatible for display."""
    if value is None or (isinstance(value, float) and not isfinite(value)):
        return "—"
    return str(value)

def _event_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(WIB)


def _event_wib(value: Any) -> str:
    local = _event_datetime(value)
    if local is None:
        return "—" if not value else str(value)
    return f"{local:%Y-%m-%d %H.%M} WIB"


def _sort_events_latest_first(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> float:
        parsed = _event_datetime(
            item.get("scheduled_at_wib") or item.get("scheduled_at")
        )
        return float("-inf") if parsed is None else parsed.timestamp()

    return sorted((dict(item or {}) for item in events), key=sort_key, reverse=True)


def _macro_bias_label(value: Any) -> str:
    labels = {
        "GOLD_BULLISH": "BULLISH XAU",
        "GOLD_BEARISH": "BEARISH XAU",
        "NEUTRAL": "NETRAL",
        "NEUTRAL_UNKNOWN": "BELUM JELAS",
        "TWO_SIDED": "TWO-SIDED",
        "PENDING": "MENUNGGU RILIS",
        "BULLISH_XAU": "BULLISH XAU",
        "BEARISH_XAU": "BEARISH XAU",
        "NEUTRAL_MIXED": "NETRAL / MIXED",
        "UNAVAILABLE": "BELUM TERSEDIA",
    }
    raw = str(value or "NEUTRAL_UNKNOWN").upper()
    return labels.get(raw, raw)


def _zone_label(zone: dict[str, Any]) -> str:
    if not zone:
        return "—"
    kind = "DEMAND" if str(zone.get("direction") or "").upper() == "LONG" else "SUPPLY"
    return (
        f"{zone.get('timeframe','—')} {kind} "
        f"{_px(zone.get('low'))}–{_px(zone.get('high'))}"
    )


def _checkpoint_label(checkpoint: dict[str, Any]) -> str:
    if not checkpoint:
        return "—"
    if checkpoint.get("type") == "ZONE":
        tfs = "/".join(checkpoint.get("timeframes") or [])
        return (
            f"{tfs} {checkpoint.get('zone_type','ZONE')} "
            f"{_px(checkpoint.get('low'))}–{_px(checkpoint.get('high'))}"
        )
    if checkpoint.get("low") is not None and checkpoint.get("high") is not None:
        return (
            f"{checkpoint.get('zone_type','S/R')} "
            f"{_px(checkpoint.get('low'))}–{_px(checkpoint.get('high'))}"
        )
    return f"{checkpoint.get('zone_type','S/R')} ~{_px(checkpoint.get('price'))}"


def _sr_state_label(value: Any) -> str:
    labels = {
        "ACTIVE_SUPPORT": "ACTIVE SUPPORT",
        "ACTIVE_RESISTANCE": "ACTIVE RESISTANCE",
        "ACTIVE_FLIP_CONTEXT": "FLIP CONTEXT",
        "BULL_BREAKOUT_AWAIT_RETEST": "BULL BREAKOUT • WAIT RETEST",
        "BULL_RETEST_IN_PROGRESS": "BULL RETEST • WAIT HOLD",
        "CONFIRMED_SUPPORT_FLIP": "CONFIRMED SUPPORT FLIP",
        "FAILED_BULL_BREAKOUT_RECLAIM_REQUIRED": "FAILED BULL BREAKOUT • RECLAIM REQUIRED",
        "BEAR_BREAKDOWN_AWAIT_RETEST": "BEAR BREAK • WAIT RETEST",
        "BEAR_RETEST_IN_PROGRESS": "BEAR RETEST • WAIT HOLD",
        "CONFIRMED_RESISTANCE_FLIP": "CONFIRMED RESISTANCE FLIP",
        "FAILED_BEAR_BREAKDOWN_RECLAIM_REQUIRED": "FAILED BEAR BREAK • RECLAIM REQUIRED",
        "UPSIDE_SWEEP_LIKE_REJECTION": "UPSIDE SWEEP-LIKE REJECTION",
        "DOWNSIDE_SWEEP_LIKE_REJECTION": "DOWNSIDE SWEEP-LIKE REJECTION",
        "PRICE_ABOVE_RESISTANCE_UNRESOLVED": "ABOVE RESISTANCE • UNRESOLVED",
        "PRICE_BELOW_SUPPORT_UNRESOLVED": "BELOW SUPPORT • UNRESOLVED",
    }
    raw = str(value or "UNAVAILABLE").upper()
    return labels.get(raw, raw.replace("_", " "))


def _sr_path_text(path: dict[str, Any]) -> str:
    row = dict(path or {})
    checkpoints = [
        _px(dict(item or {}).get("price"))
        for item in list(row.get("checkpoints") or [])
        if dict(item or {}).get("price") is not None
    ]
    route = " → ".join(checkpoints) if checkpoints else "belum ada level berikut"
    return f"{row.get('prerequisite') or 'WAIT_CONFIRMATION'} → {route}"


def render_xau_dual_engine_dashboard(
    *,
    sd_heartbeat: dict[str, Any] | None,
    friend_heartbeat: dict[str, Any] | None,
    event_heartbeat: dict[str, Any] | None = None,
    macro_heartbeat: dict[str, Any] | None = None,
) -> None:
    import streamlit as st

    sd_hb = dict(sd_heartbeat or {})
    friend_hb = dict(friend_heartbeat or {})
    event_hb = dict(event_heartbeat or {})
    macro_hb = dict(macro_heartbeat or {})
    sd_details = dict(sd_hb.get("details") or {})
    friend_details = dict(friend_hb.get("details") or {})
    event_details = dict(event_hb.get("details") or {})
    macro_details = dict(macro_hb.get("details") or {})
    sd = dict(sd_details.get("evaluation") or {})
    friend = dict(friend_details.get("evaluation") or {})
    event_context = dict(event_details.get("risk") or {})
    macro_eval = dict(macro_details.get("evaluation") or {})

    demo_execution_on = bool(sd.get("execution_authority")) and (
        str(sd.get("execution_scope") or "").upper() == "DEMO_ONLY"
    )
    execution_label = "DEMO execution = ON • LIVE = OFF" if demo_execution_on else "Execution = OFF"
    st.markdown(
        '<div class="rizan-kicker">RIZAN NEW ENGINE • LEGACY PAUSED</div>'
        '<div class="rizan-title">XAUUSD — Structural Path & Micro Entry</div>'
        '<div class="rizan-note">Satu jalur struktural utama: H4 parent → H1 refinement → '
        'reaction/roadblock → destination. H2 support/resistance hanya konteks, bukan sinyal arah. '
        + execution_label
        + '.</div>',
        unsafe_allow_html=True,
    )
    tab_sd, tab_friend = st.tabs(
        ["1 • Structural Path", "2 • Micro Entry Reconstruction"]
    )

    with tab_sd:
        if not sd:
            st.warning(
                "Snapshot V342 belum tersedia. Engine lama tetap disembunyikan agar dashboard "
                "tidak kembali mencampur keputusan."
            )
        else:
            price = sd.get("price_now")
            decision = dict(sd.get("decision_zone") or {})
            main_zone = dict(sd.get("main_reversal_zone") or decision)
            refinement = dict(sd.get("refinement_zone") or {})
            destination = dict(sd.get("structural_destination") or {})
            structural_room = dict(sd.get("structural_room") or {})
            roadblock_room = dict(sd.get("roadblock_room") or {})
            structural_path = dict(sd.get("structural_path") or {})
            failure_path = dict(sd.get("failure_path") or {})
            destination_ladder = dict(sd.get("destination_ladder") or {})
            failure_destination_ladder = dict(sd.get("failure_destination_ladder") or {})
            zone_chain = dict(sd.get("zone_chain") or {})
            support_resistance = list(sd.get("support_resistance") or [])
            sr_map = dict(sd.get("support_resistance_map") or {})
            sr_levels = list(sr_map.get("levels") or support_resistance)
            sr_support = dict(sr_map.get("nearest_support") or {})
            sr_resistance = dict(sr_map.get("nearest_resistance") or {})
            sr_flip = dict(sr_map.get("flip_watch") or {})
            sr_bull_path = dict(sr_map.get("bull_path") or {})
            sr_bear_path = dict(sr_map.get("bear_path") or {})
            roadblocks = list(sd.get("roadblocks") or [])
            nearest_roadblock = dict(sd.get("nearest_roadblock") or {})
            micro = dict(sd.get("micro_confirmation") or {})
            guide = dict(sd.get("entry_guide") or {})
            sweep = dict(sd.get("liquidity_map") or {})
            quarantined = list(sd.get("intraday_quarantined_zones") or [])
            news = dict(sd.get("news_zone") or {})
            structure = dict(sd.get("market_structure") or {})
            h4 = dict(structure.get("H4") or {})
            h1 = dict(structure.get("H1") or {})

            entry_gate = str(news.get("effective_entry_state") or guide.get("state") or "WAIT")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Harga XAU", _px(price))
            c2.metric("H4 structure", str(h4.get("state") or "—"))
            c3.metric("Arah struktural", str(sd.get("expected_reversal_direction") or "WAIT"))
            c4.metric("Entry gate", entry_gate)
            st.caption("H1 structure • " + str(h1.get("state") or "—"))

            if quarantined:
                q = dict(quarantined[0] or {})
                q_intraday = dict(q.get("intraday_breach") or {})
                q_direction = str(q.get("direction") or "")
                q_type = "DEMAND" if q_direction == "LONG" else "SUPPLY"
                next_label = _zone_label(main_zone) if main_zone else "belum ada parent pengganti"
                st.error(
                    "**INTRADAY REROUTE aktif.** "
                    + f"{q.get('timeframe','HTF')} {q_type} {_px(q.get('low'))}–{_px(q.get('high'))} "
                    + f"dikarantina setelah completed M15 menembus distal "
                    + f"{float(q_intraday.get('breach_depth_atr') or 0.0):.2f} ATR. "
                    + "PREPARE lama dinonaktifkan. Parent aktif sekarang: "
                    + next_label
                )

            st.markdown("### RIZAN STRUCTURAL S/R MAP")
            st.caption(
                "Support/resistance dinilai sebagai level dengan lifecycle. Resistance baru berubah "
                "menjadi support setelah breakout diterima oleh completed bar lalu retest/hold; "
                "breakout yang kembali gagal diberi status RECLAIM REQUIRED. S/R tidak memberi arah "
                "atau izin order sendiri."
            )
            sr1, sr2, sr3 = st.columns(3)
            sr1.metric(
                "Nearest support",
                (
                    f"{_px(sr_support.get('price'))} • {_sr_state_label(sr_support.get('lifecycle_state'))}"
                    if sr_support else "—"
                ),
            )
            sr2.metric(
                "Nearest resistance",
                (
                    f"{_px(sr_resistance.get('price'))} • {_sr_state_label(sr_resistance.get('lifecycle_state'))}"
                    if sr_resistance else "—"
                ),
            )
            sr3.metric(
                "S/R flip watch",
                (
                    f"{_px(sr_flip.get('price'))} • {_sr_state_label(sr_flip.get('lifecycle_state'))}"
                    if sr_flip else "—"
                ),
            )
            if sr_flip:
                flip_state = str(sr_flip.get("lifecycle_state") or "")
                flip_band = (
                    f"{_px(sr_flip.get('band_low'))}–{_px(sr_flip.get('band_high'))}"
                )
                if bool(sr_flip.get("reclaim_required")):
                    st.warning(
                        "**Failed breakout / breakdown.** "
                        + f"Level {_px(sr_flip.get('price'))} ({flip_band}) belum boleh diperlakukan "
                        "sebagai role-flip baru; reclaim + hold completed-bar diperlukan."
                    )
                elif bool(sr_flip.get("confirmed_flip")):
                    st.success(
                        "**Role flip terkonfirmasi:** "
                        + _sr_state_label(flip_state)
                        + f" di {_px(sr_flip.get('price'))} • band {flip_band}."
                    )
                else:
                    st.info(
                        "**Flip belum final:** "
                        + _sr_state_label(flip_state)
                        + f" di {_px(sr_flip.get('price'))} • tunggu retest/hold."
                    )

            srp1, srp2 = st.columns(2)
            srp1.caption("Bull path (conditional) • " + _sr_path_text(sr_bull_path))
            srp2.caption("Bear path (conditional) • " + _sr_path_text(sr_bear_path))
            if sr_levels:
                with st.expander("Detail S/R lifecycle"):
                    st.dataframe(
                        [
                            {
                                "Level": row.get("price"),
                                "Role awal": row.get("base_kind") or row.get("kind"),
                                "Role sekarang": row.get("current_role") or row.get("kind"),
                                "Lifecycle": _sr_state_label(row.get("lifecycle_state")),
                                "Strength": row.get("strength"),
                                "Band low": row.get("band_low"),
                                "Band high": row.get("band_high"),
                                "Sources": ", ".join(row.get("sources") or []),
                            }
                            for row in sr_levels[:10]
                        ],
                        width="stretch",
                        hide_index=True,
                    )
            st.caption(
                "Aturan eksekusi tetap terpisah: support ≠ auto BUY dan resistance ≠ auto SELL. "
                "V367 hanya mengizinkan S/R tervalidasi menjadi roadblock/target cap pada arah H4 "
                "yang sudah dipilih; S/R tidak pernah menciptakan arah. Entry DEMO tetap membutuhkan "
                "geometry valid + reclaim/MSS/displacement sesuai engine utama."
            )

            st.markdown("### Jalur struktural utama")
            if main_zone:
                st.markdown(
                    f"**MAIN H4:** {_zone_label(main_zone)} • "
                    f"condition={main_zone.get('condition') or dict(main_zone.get('lifecycle') or {}).get('freshness','—')} • "
                    f"pattern={main_zone.get('pattern','—')} • "
                    f"reversal quality={_f(main_zone.get('main_reversal_score')) or 0.0:.1f}"
                )
                if refinement:
                    st.success(
                        "**H1 refinement:** "
                        + _zone_label(refinement)
                        + f" • overlap parent={_pct(refinement.get('parent_overlap_ratio'))}"
                    )
                else:
                    st.caption("Belum ada H1 refinement searah yang valid di dalam parent H4.")

                if destination:
                    st.info(
                        "**Primary HTF destination:** "
                        + _zone_label(destination)
                    )
                else:
                    st.caption("Primary HTF destination belum tersedia pada arah parent saat ini.")

                delivery_stages = list(destination_ladder.get("stages") or [])
                if delivery_stages:
                    route = " → ".join(
                        (
                            f"{int(stage.get('order') or 0)}. "
                            f"{stage.get('timeframe','—')} "
                            f"{'DEMAND' if str(stage.get('direction')) == 'LONG' else 'SUPPLY'} "
                            f"{_px(stage.get('low'))}–{_px(stage.get('high'))}"
                        )
                        for stage in delivery_stages
                    )
                    st.markdown("**Delivery map:** " + route)
                    terminal_stage = dict(destination_ladder.get("terminal_scenario") or {})
                    if terminal_stage:
                        st.caption(
                            "Terminal scenario • "
                            + _zone_label(terminal_stage)
                            + " • CONDITIONAL: bukan TP aktif; baru dipromosikan bila seluruh "
                            "HTF destination sebelumnya gagal secara kausal."
                        )

                next_zone = dict(zone_chain.get("next_after_failure") or {})
                if next_zone:
                    comparator = "<" if str(failure_path.get("failure_direction")) == "SHORT" else ">"
                    st.warning(
                        "**Jika MAIN gagal → NEXT HTF:** "
                        + f"close {comparator} {_px(zone_chain.get('promotion_trigger'))} → "
                        + _zone_label(next_zone)
                        + ". Engine rebuild dan mempromosikan zona berikutnya; tidak averaging "
                        "pada zona yang sudah invalid."
                    )
                    fail_terminal = dict(
                        failure_destination_ladder.get("terminal_scenario") or {}
                    )
                    if fail_terminal:
                        st.caption(
                            "Failure-path terminal scenario • "
                            + _zone_label(fail_terminal)
                            + " • tetap conditional sampai checkpoint sebelumnya ditembus."
                        )

                checkpoints = list(structural_path.get("checkpoints") or [])
                if checkpoints:
                    for cp in checkpoints:
                        order = int(cp.get("order") or 0)
                        condition = str(cp.get("condition") or cp.get("role") or "CONTEXT")
                        label = _checkpoint_label(cp)
                        if cp.get("type") == "ZONE":
                            break_level = cp.get("break_level")
                            if order == 1:
                                st.warning(
                                    f"**{order}. Reaction:** {label} • {condition} • "
                                    f"lanjut hanya jika close menembus {_px(break_level)}"
                                )
                            else:
                                st.info(
                                    f"**{order}. Jika tembus:** {label} • {condition} • "
                                    f"break {_px(break_level)}"
                                )
                        else:
                            st.caption(
                                f"**{order}. S/R + liquidity watch:** {label} • "
                                + ", ".join(cp.get("sources") or [])
                                + ". Ini konteks, bukan sinyal entry."
                            )
                elif destination:
                    st.info("Destination H4 • " + _zone_label(destination))

                failure_steps = list(failure_path.get("checkpoints") or [])
                if failure_steps:
                    failure_labels = " → ".join(
                        _checkpoint_label(cp) for cp in failure_steps[:3]
                    )
                    trigger = failure_path.get("trigger")
                    comparator = "<" if str(failure_path.get("failure_direction")) == "SHORT" else ">"
                    st.info(
                        "**Jika MAIN H4 gagal (conditional, bukan sinyal kedua):** "
                        + f"close {comparator} {_px(trigger)} → {failure_labels}"
                    )

                if nearest_roadblock:
                    rb_atr = nearest_roadblock.get("distance_parent_atr")
                    rb_rr = nearest_roadblock.get("planned_rr_to_roadblock")
                    rb_status = str(nearest_roadblock.get("status") or "PATH_OBSTACLE")
                    rb_source = str(nearest_roadblock.get("source") or "HTF_ZONE")
                    rb_lifecycle = str(nearest_roadblock.get("lifecycle_state") or "")
                    rb_text = (
                        f"{nearest_roadblock.get('timeframe','—')} "
                        f"{nearest_roadblock.get('type','—')} "
                        f"{_px(nearest_roadblock.get('low'))}–{_px(nearest_roadblock.get('high'))} "
                        f"• status={rb_status} • source={rb_source}"
                        + (f" • lifecycle={_sr_state_label(rb_lifecycle)}" if rb_lifecycle else "")
                        + (f" • room={float(rb_atr):.2f} parent ATR" if rb_atr is not None else "")
                        + (f" • RR ke roadblock={float(rb_rr):.2f}R" if rb_rr is not None else "")
                    )
                    if bool(roadblock_room.get("blocked")):
                        st.error("**Roadblock gate: WAIT** • " + rb_text)
                    else:
                        st.warning("**Roadblock di jalur:** " + rb_text)
                else:
                    st.caption(
                        "**Roadblock sebelum terminal H4:** tidak ada. "
                        "Artinya obstacle berikutnya adalah destination H4 itu sendiri, bukan H1 lawan di tengah jalur."
                    )

                room_state = str(structural_room.get("state") or "UNKNOWN")
                room_atr = structural_room.get("distance_parent_atr")
                room_rr = structural_room.get("planned_rr")
                if bool(structural_room.get("blocked")):
                    st.error(
                        "**Structural room gate: WAIT** • "
                        + room_state
                        + (f" • room={float(room_atr):.2f} ATR" if room_atr is not None else "")
                        + (f" • terminal RR={float(room_rr):.2f}R" if room_rr is not None else "")
                        + ". Opposing HTF destination terlalu dekat untuk mengejar entry."
                    )
                elif structural_room:
                    st.caption(
                        "Structural room • "
                        + room_state
                        + (f" • {float(room_atr):.2f} ATR" if room_atr is not None else "")
                        + (f" • terminal RR={float(room_rr):.2f}R" if room_rr is not None else "")
                    )

            if decision:
                prior = dict(sd.get("historical_depth_prior") or {}).get(
                    str(decision.get("timeframe") or ""),
                    {},
                )
                if prior:
                    st.caption(
                        "Prior historis V225 2012–2026 • "
                        f"touches={int(prior.get('touches') or 0):,} • "
                        f"reaction ≥0.50 ATR={_pct(prior.get('hold_rate_050_atr'))} • "
                        f"median turning depth={_pct(prior.get('turning_depth_median'))} • "
                        f"P75={_pct(prior.get('turning_depth_p75'))}. "
                        "Ini statistik deskriptif, bukan probabilitas setup saat ini."
                    )

            st.markdown("### Broader Macro Attribution")
            if macro_eval:
                broader_bias = str(macro_eval.get("broader_macro_bias") or "UNAVAILABLE")
                macro_score = macro_eval.get("macro_score")
                macro_coverage = macro_eval.get("coverage")
                relationship = str(
                    macro_eval.get("consensus_relationship")
                    or "NO_CLEAR_DIRECTIONAL_COMPARISON"
                )
                b1, b2, b3, b4 = st.columns(4)
                b1.metric("Broader Macro Bias", _macro_bias_label(broader_bias))
                b2.metric(
                    "Macro score",
                    "—" if macro_score is None else f"{float(macro_score):+.1f}",
                )
                b3.metric(
                    "Confidence",
                    str(macro_eval.get("confidence") or "LOW"),
                )
                b4.metric(
                    "Coverage",
                    "—" if macro_coverage is None else f"{float(macro_coverage) * 100.0:.0f}%",
                )

                event_bias = _macro_bias_label(macro_eval.get("event_consensus_bias"))
                st.caption(
                    "Consensus event tilt: **"
                    + event_bias
                    + "** • Broader macro: **"
                    + _macro_bias_label(broader_bias)
                    + "** • Fed repricing proxy: **"
                    + str(dict(macro_eval.get("fed_repricing_proxy") or {}).get("state") or "UNAVAILABLE")
                    + "**."
                )
                if relationship == "CONSENSUS_DIVERGENT_FROM_BROADER_MACRO":
                    st.warning(
                        "DIVERGENSI MAKRO • Consensus event dan cross-asset memberi arah berbeda. "
                        "Jangan pakai consensus event sebagai arah entry tunggal; tunggu reaksi harga "
                        "dan konfirmasi struktur."
                    )
                elif relationship == "CONSENSUS_ALIGNED_WITH_BROADER_MACRO":
                    st.info(
                        "Consensus event dan broader cross-asset sedang searah. Ini meningkatkan "
                        "konteks, tetapi tetap bukan execution authority."
                    )

                intraday_yield = dict(macro_eval.get("intraday_yield_context") or {})
                post_event_state = str(
                    macro_eval.get("post_event_macro_state") or "INTRADAY_YIELD_UNAVAILABLE"
                )
                if intraday_yield:
                    y1, y2, y3, y4 = st.columns(4)
                    y1.metric(
                        "US10Y intraday",
                        str(intraday_yield.get("state") or "UNAVAILABLE"),
                    )
                    y2.metric(
                        "Yield saat event",
                        (
                            "—"
                            if intraday_yield.get("yield_at_release") is None
                            else f"{float(intraday_yield.get('yield_at_release')):.3f}%"
                        ),
                    )
                    y3.metric(
                        "Low pasca-event",
                        (
                            "—"
                            if intraday_yield.get("post_event_low") is None
                            else f"{float(intraday_yield.get('post_event_low')):.3f}%"
                        ),
                    )
                    y4.metric(
                        "Yield sekarang / rebound",
                        (
                            "—"
                            if intraday_yield.get("current") is None
                            else (
                                f"{float(intraday_yield.get('current')):.3f}% / "
                                f"{float(intraday_yield.get('rebound_from_low_bps') or 0.0):+.1f} bps"
                            )
                        ),
                    )
                    if post_event_state == "POST_NEWS_MACRO_REVERSAL":
                        st.warning(
                            "POST-NEWS MACRO REVERSAL • arah event dan reaksi US10Y intraday "
                            "sudah berlawanan. Prioritaskan yield reversal + price structure; "
                            "jangan mempertahankan bias news awal secara statis."
                        )
                    elif post_event_state == "POST_NEWS_MACRO_CONFIRMATION":
                        st.info(
                            "POST-NEWS MACRO CONFIRMATION • arah event dan reaksi US10Y intraday "
                            "masih searah."
                        )
                    st.caption(
                        "US10Y intraday memakai ^TNX sebagai secondary market-data proxy. "
                        "FRED DGS10/DFII10 tetap menjadi referensi resmi harian; proxy intraday "
                        "tidak memiliki execution authority."
                    )

                macro_rows = []
                for name, row in dict(macro_eval.get("components") or {}).items():
                    row = dict(row or {})
                    macro_rows.append(
                        {
                            "Komponen": name,
                            "Freshness": row.get("freshness") or ("EVENT" if name == "EVENT_CONSENSUS" else "—"),
                            "Current": row.get("current"),
                            "Previous": row.get("previous"),
                            "Delta": row.get("delta"),
                            "Unit": row.get("delta_unit"),
                            "Gold score": row.get("score"),
                            "Source": row.get("provider") or row.get("source"),
                        }
                    )
                if macro_rows:
                    st.dataframe(
                        macro_rows,
                        width="stretch",
                        hide_index=True,
                    )
                st.caption(
                    "USD_BROAD_PROXY memakai FRED DTWEXBGS sebagai proxy resmi USD broad index, "
                    "bukan proprietary ICE DXY. US2Y digunakan sebagai proxy Fed repricing dan "
                    "tidak dihitung dua kali. Cross-asset FRED bersifat harian, sehingga confidence "
                    "V357 dibatasi maksimum MEDIUM."
                )
            else:
                st.caption(
                    "Broader Macro V357 belum tersedia. Event calendar tetap tampil, tetapi "
                    "consensus event belum dibandingkan dengan USD/yield/real-yield."
                )

            st.markdown("### Event Macro & Prediksi XAU")
            macro = dict(event_context or news)
            focal = dict(macro.get("focal_event") or news.get("focal_event") or {})
            latest_release = dict(
                macro.get("latest_released_event")
                or news.get("latest_released_event")
                or {}
            )
            interaction = dict(news.get("zone_interaction") or {})
            next_zone = dict(news.get("next_same_type_htf_zone") or {})
            risk_state = str(
                macro.get("state")
                or news.get("risk_state")
                or "UNKNOWN"
            )
            n1, n2, n3, n4 = st.columns(4)
            n1.metric("Event risk", risk_state)
            n2.metric("Rilis makro terakhir", str(latest_release.get("title") or "—"))
            n3.metric("Dampak XAU rilis", _macro_bias_label(latest_release.get("gold_bias")))
            n4.metric(
                "Entry gate",
                str(news.get("effective_entry_state") or macro.get("action") or "WAIT"),
            )

            if latest_release:
                st.caption(
                    "Rilis terakhir • "
                    + _event_wib(
                        latest_release.get("scheduled_at_wib")
                        or latest_release.get("scheduled_at")
                    )
                    + " • "
                    + str(latest_release.get("category") or "—")
                    + " • impact="
                    + str(latest_release.get("impact") or "—")
                    + " • confidence="
                    + str(latest_release.get("gold_bias_confidence") or "LOW")
                    + " • basis="
                    + str(latest_release.get("gold_bias_basis") or "—")
                )
                st.caption(
                    "Actual="
                    + str(latest_release.get("actual") if latest_release.get("actual") is not None else "—")
                    + " • Forecast="
                    + str(latest_release.get("forecast") if latest_release.get("forecast") is not None else "—")
                    + " • Previous="
                    + str(latest_release.get("previous") if latest_release.get("previous") is not None else "—")
                    + ". Setelah rilis, actual-vs-forecast menjadi konteks utama event."
                )

            if focal:
                st.info(
                    "**Event berikutnya:** "
                    + str(focal.get("title") or "—")
                    + " • "
                    + _event_wib(focal.get("scheduled_at_wib") or focal.get("scheduled_at"))
                    + " • prediksi pra-event="
                    + _macro_bias_label(focal.get("gold_bias"))
                    + " • confidence="
                    + str(focal.get("gold_bias_confidence") or "LOW")
                )

            upcoming = _sort_events_latest_first(
                list(macro.get("upcoming_events") or [])
            )
            if upcoming:
                event_rows = []
                for item in upcoming:
                    event_rows.append(
                        {
                            "Waktu WIB": _event_wib(
                                item.get("scheduled_at_wib") or item.get("scheduled_at")
                            ),
                            "Event": item.get("title"),
                            "Impact": item.get("impact"),
                            "Forecast": _event_value(item.get("forecast")),
                            "Previous": _event_value(item.get("previous")),
                            "Actual": _event_value(item.get("actual")),
                            "Prediksi XAU": _macro_bias_label(item.get("gold_bias")),
                            "Confidence": item.get("gold_bias_confidence"),
                            "Basis": item.get("gold_bias_basis"),
                        }
                    )
                st.dataframe(
                    event_rows,
                    width="stretch",
                    hide_index=True,
                )
                st.caption(
                    "Kalender V355 menampilkan hingga 30 hari event USD yang tersedia: jadwal resmi BLS/BEA "
                    "ditambah discovery mingguan untuk event lain. Consensus-vs-previous adalah tilt "
                    "pra-event, bukan kepastian arah; actual-vs-forecast hanya dipakai jika actual tersedia."
                )

            if risk_state in {"PRE_EVENT", "EVENT_WINDOW"}:
                st.warning(
                    "WAIT — EVENT VOLATILITY. Bias makro hanya context. "
                    "Eksekusi tetap menunggu reaksi harga: liquidity sweep → reclaim → MSS/displacement."
                )
            elif risk_state == "NEWS_SOURCE_UNAVAILABLE":
                st.error(
                    "News calendar unavailable. Status tidak boleh dianggap CLEAR; "
                    "entry guide dipaksa WAIT_NEWS_DATA."
                )
            elif risk_state == "POST_EVENT_DISCOVERY":
                st.info(
                    "POST-NEWS PRICE DISCOVERY • utamakan actual-vs-forecast, DXY/yield, "
                    "dan interaksi harga dengan decision zone."
                )

            if news:
                st.write(
                    {
                        "zone_interaction": interaction.get("state"),
                        "zone_coupled": news.get("zone_coupled"),
                        "zone_distance_atr": news.get("zone_distance_atr"),
                        "preferred_path": news.get("preferred_path"),
                        "alternative_path": news.get("alternative_path"),
                    }
                )
                if interaction.get("state") == "ZONE_FAILED_AFTER_NEWS":
                    st.error(
                        "Zona utama gagal setelah news: strong close / dua close M5 melewati distal. "
                        "Jangan pakai zona tersebut sebagai entry reversal baru."
                    )
                    if next_zone:
                        st.info("Zona HTF berikutnya • " + _zone_label(next_zone))
                elif interaction.get("state") == "NEWS_SWEEP_REVERSAL_CONFIRMED":
                    st.success(
                        "Sweep distal sudah direclaim dan konfirmasi micro setelah event tersedia. "
                        "Ini adalah validasi reversal berbasis harga; news sendiri tetap bukan otoritas entry."
                    )

            if support_resistance and not sr_levels:
                with st.expander("Detail H2 support/resistance — fallback konteks"):
                    st.dataframe(
                        [
                            {
                                "Type": row.get("kind"),
                                "Price": row.get("price"),
                                "Strength": row.get("strength"),
                                "Sources": ", ".join(row.get("sources") or []),
                            }
                            for row in support_resistance[:8]
                        ],
                        width="stretch",
                        hide_index=True,
                    )

            st.markdown("### Liquidity sweep sebelum reversal")
            if sweep:
                st.warning(
                    f"{sweep.get('side','—')} • band {_px(sweep.get('low'))}–"
                    f"{_px(sweep.get('high'))} • extension="
                    f"{_f(sweep.get('extension_atr')) or 0.0:.2f} ATR • "
                    f"{sweep.get('warning','—')}"
                )
                levels = list(sweep.get("liquidity_candidates") or [])
                if levels:
                    st.dataframe(
                        [
                            {
                                "side": row.get("side"),
                                "price": row.get("price"),
                                "strength": row.get("strength"),
                                "sources": ", ".join(row.get("sources") or []),
                            }
                            for row in levels[:8]
                        ],
                        width="stretch",
                        hide_index=True,
                    )
            else:
                st.caption("Belum ada sweep envelope yang layak dipetakan.")

            st.markdown("### Validasi reversal & entry guide")
            targets = list(guide.get("targets") or [])
            e1, e2, e3, e4 = st.columns(4)
            e1.metric("Stage", str(micro.get("stage") or "WAIT"))
            e2.metric(
                "PREPARE forecast aktif",
                f"{_px(guide.get('prepared_entry_low'))}–{_px(guide.get('prepared_entry_high'))}",
            )
            e3.metric("Fresh confirm ref", _px(guide.get("confirmation_entry_reference")))
            e4.metric(
                "Retest entry",
                f"{_px(guide.get('entry_low'))}–{_px(guide.get('entry_high'))}",
            )
            st.caption(
                "PREPARE = area reaksi dari parent yang masih aktif; V369 otomatis memindahkan PREPARE "
                "bila completed M15 mengonfirmasi breach intraday yang cukup dalam. EARLY = touch/sweep + proximal reclaim "
                "+ rejection/displacement; hanya boleh probe DEMO 0.01 dengan SL struktural dan RR valid. "
                "FULL = local MSS pada reclaim extreme + displacement. Jika harga sudah drift terlalu jauh, "
                "executor tetap no-chase dan menunggu retest."
            )
            st.caption(
                f"Invalidation {_px(guide.get('invalidation'))} • "
                f"TP terdekat {_px(targets[0].get('price') if targets else None)}"
            )

            rows = []
            for zone in list(sd.get("active_zones") or [])[:12]:
                life = dict(zone.get("lifecycle") or {})
                rows.append(
                    {
                        "TF": zone.get("timeframe"),
                        "Type": "DEMAND" if zone.get("direction") == "LONG" else "SUPPLY",
                        "Pattern": zone.get("pattern"),
                        "Role": zone.get("hierarchy_role"),
                        "Low": zone.get("low"),
                        "High": zone.get("high"),
                        "Score": zone.get("score"),
                        "Reversal class": (
                            "MAIN_REVERSAL"
                            if zone.get("main_reversal_eligible")
                            else "REACTION/ROADBLOCK"
                        ),
                        "Main score": zone.get("main_reversal_score"),
                        "Touch": life.get("touch_count"),
                        "Condition": zone.get("condition") or life.get("freshness"),
                        "Distance ATR": zone.get("distance_atr"),
                    }
                )
            if rows:
                with st.expander("Semua zona H4/H1 aktif"):
                    st.dataframe(rows, width="stretch", hide_index=True)

    with tab_friend:
        if not friend:
            st.warning(
                "Snapshot V343 belum tersedia. Tab ini tidak mengambil fallback dari engine lama."
            )
        else:
            parent = dict(friend.get("parent_zone") or {})
            levels = dict(friend.get("levels") or {})
            entries = dict(friend.get("entries") or {})
            targets = dict(friend.get("targets") or {})
            evidence = dict(friend.get("historical_evidence") or {})
            friend_news = dict(friend.get("news_zone_context") or {})
            full = dict(evidence.get("full_2012_2026") or {})
            oos = dict(evidence.get("oos_2025_2026") or {})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Arah", str(friend.get("direction") or "WAIT"))
            m2.metric("Phase", str(friend.get("state") or "WAIT"))
            m3.metric("Primary entry", _px(entries.get("historical_primary_price")))
            m4.metric("SL struktural", _px(friend.get("stop_loss")))

            if friend_news:
                st.caption(
                    "News-zone context • "
                    f"{friend_news.get('risk_state','UNKNOWN')} • "
                    f"gate={friend_news.get('effective_entry_state','WAIT')} • "
                    "geometry A/X/Y tidak diubah oleh news."
                )
                if str(friend_news.get("risk_state") or "") in {"PRE_EVENT", "EVENT_WINDOW"}:
                    st.warning("A/X/Y tetap ditampilkan sebagai geometry reference, tetapi entry = WAIT FOR NEWS.")

            st.caption(
                "Parent zone • "
                + _zone_label(parent)
                + " • touch="
                + str(friend.get("parent_touch_source") or "HTF_LIFECYCLE")
            )
            st.markdown("### Geometry A / X / Y")
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("A", _px(levels.get("A")))
            a2.metric("X = A ± Δ", _px(levels.get("X")))
            a3.metric("Y = A ± 2Δ", _px(levels.get("Y")))
            a4.metric("Δ", _px(friend.get("delta")))

            st.markdown("### Target")
            t1, t2, t3 = st.columns(3)
            t1.metric("5Δ", _px(targets.get("TP5")))
            t2.metric("8Δ", _px(targets.get("TP8")))
            t3.metric("13Δ", _px(targets.get("TP13")))

            st.info(
                "Rekonstruksi: parent H1/H4 disentuh → impulse ≥0.75 ATR M5 → "
                "dua close reclaim → pullback pivot causal membentuk A → X/Y memakai Δ=0.10 ATR M5. "
                "Setelah target/tujuan struktural, engine tidak flip otomatis; ia menunggu parent zone "
                "lawan dan membangun anchor baru."
            )
            st.markdown("### Evidence V323 2012–2026")
            h1c, h2c, h3c, h4c = st.columns(4)
            h1c.metric("Fills", f"{int(full.get('fills') or 0):,}")
            h2c.metric("Gross PF", f"{_f(full.get('profit_factor_gross_r')) or 0.0:.2f}")
            h3c.metric("Gross expectancy", f"{_f(full.get('expectancy_r_all_fills')) or 0.0:.3f}R")
            h4c.metric("OOS expectancy", f"{_f(oos.get('expectancy_r_all_fills')) or 0.0:.3f}R")
            st.warning(
                "OOS gate V323 = NOT READY karena expectancy 2025–2026 < 0.10R/fill. "
                "Hit-rate tinggi tidak boleh dibaca sebagai standalone readiness karena planned reward relatif kecil "
                "terhadap structural risk dan friction belum termasuk. V343 tidak punya direct broker authority; "
                "ia hanya menjadi forecast/confidence evidence untuk jalur DEMO."
            )

    st.caption(
        "Legacy decision engines dipause dari jalur terjadwal. Safety/protection, broker telemetry, "
        "token maintenance, dan dashboard bridge bukan decision engine dan tetap boleh berjalan."
    )
