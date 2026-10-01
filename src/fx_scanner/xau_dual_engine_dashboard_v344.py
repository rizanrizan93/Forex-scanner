from __future__ import annotations

from math import isfinite
from typing import Any


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


def _zone_label(zone: dict[str, Any]) -> str:
    if not zone:
        return "—"
    kind = "DEMAND" if str(zone.get("direction") or "").upper() == "LONG" else "SUPPLY"
    return (
        f"{zone.get('timeframe','—')} {kind} "
        f"{_px(zone.get('low'))}–{_px(zone.get('high'))}"
    )


def render_xau_dual_engine_dashboard(
    *,
    sd_heartbeat: dict[str, Any] | None,
    friend_heartbeat: dict[str, Any] | None,
) -> None:
    import streamlit as st

    sd_hb = dict(sd_heartbeat or {})
    friend_hb = dict(friend_heartbeat or {})
    sd_details = dict(sd_hb.get("details") or {})
    friend_details = dict(friend_hb.get("details") or {})
    sd = dict(sd_details.get("evaluation") or {})
    friend = dict(friend_details.get("evaluation") or {})

    st.markdown(
        '<div class="rizan-kicker">RIZAN NEW ENGINE • LEGACY PAUSED</div>'
        '<div class="rizan-title">XAUUSD — Supply/Demand, News-Zone & Micro Entry</div>'
        '<div class="rizan-note">Dua engine independen. Tidak ada ensemble/voting engine lama. '
        'Semua output saat ini research/forecast only; execution authority = OFF.</div>',
        unsafe_allow_html=True,
    )
    tab_sd, tab_friend = st.tabs(
        ["1 • Supply / Demand + Liquidity", "2 • Micro Entry Reconstruction"]
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
            roadblocks = list(sd.get("roadblocks") or [])
            nearest_roadblock = dict(sd.get("nearest_roadblock") or {})
            micro = dict(sd.get("micro_confirmation") or {})
            guide = dict(sd.get("entry_guide") or {})
            sweep = dict(sd.get("liquidity_map") or {})
            news = dict(sd.get("news_zone") or {})
            structure = dict(sd.get("market_structure") or {})
            h4 = dict(structure.get("H4") or {})
            h1 = dict(structure.get("H1") or {})

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Harga XAU", _px(price))
            c2.metric("H4 structure", str(h4.get("state") or "—"))
            c3.metric("H1 structure", str(h1.get("state") or "—"))
            c4.metric(
                "Reversal watch",
                str(sd.get("expected_reversal_direction") or "WAIT"),
            )

            st.markdown("### Peta utama")
            z1, z2 = st.columns(2)
            z1.info("Demand terdekat • " + _zone_label(dict(sd.get("nearest_demand") or {})))
            z2.warning("Supply terdekat • " + _zone_label(dict(sd.get("nearest_supply") or {})))

            if main_zone:
                st.markdown(
                    f"**MAIN H4 reversal zone:** {_zone_label(main_zone)} • "
                    f"pattern={main_zone.get('pattern','—')} • "
                    f"score={main_zone.get('score','—')} • "
                    f"freshness={dict(main_zone.get('lifecycle') or {}).get('freshness','—')}"
                )
                if refinement:
                    st.success(
                        "**H1 refinement:** "
                        + _zone_label(refinement)
                        + f" • overlap parent={_pct(refinement.get('parent_overlap_ratio'))}"
                    )
                else:
                    st.caption("Belum ada H1 refinement searah yang valid di dalam parent H4.")

                r1, r2 = st.columns(2)
                if nearest_roadblock:
                    r1.warning(
                        "**Roadblock terdekat:** "
                        + f"{nearest_roadblock.get('timeframe','—')} "
                        + f"{nearest_roadblock.get('type','—')} "
                        + f"{_px(nearest_roadblock.get('low'))}–{_px(nearest_roadblock.get('high'))} "
                        + f"• {nearest_roadblock.get('severity','—')}"
                    )
                else:
                    r1.info("Roadblock terdekat • tidak ada opposing zone sebelum destination H4.")
                if destination:
                    r2.info(
                        "**Destination H4:** "
                        + f"{_px(destination.get('low'))}–{_px(destination.get('high'))} "
                        + f"• edge {_px(destination.get('price'))}"
                    )
                else:
                    r2.info("Destination H4 • belum ada opposing H4 aktif di arah perjalanan.")

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

                if roadblocks:
                    with st.expander("Roadblock di jalur harga"):
                        st.dataframe(
                            [
                                {
                                    "TF": rb.get("timeframe"),
                                    "Type": rb.get("type"),
                                    "Low": rb.get("low"),
                                    "High": rb.get("high"),
                                    "Near edge": rb.get("near_edge"),
                                    "Severity": rb.get("severity"),
                                    "Score": rb.get("score"),
                                    "Freshness": rb.get("freshness"),
                                }
                                for rb in roadblocks
                            ],
                            use_container_width=True,
                            hide_index=True,
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

            st.markdown("### News-zone")
            focal = dict(news.get("focal_event") or {})
            interaction = dict(news.get("zone_interaction") or {})
            next_zone = dict(news.get("next_same_type_htf_zone") or {})
            n1, n2, n3, n4 = st.columns(4)
            n1.metric("News risk", str(news.get("risk_state") or "UNKNOWN"))
            n2.metric("Event", str(focal.get("title") or "—"))
            n3.metric("Overshoot risk", str(news.get("overshoot_risk") or "BASELINE"))
            n4.metric("Entry gate", str(news.get("effective_entry_state") or "WAIT"))

            if focal:
                st.caption(
                    "Next/focal event • "
                    + str(focal.get("scheduled_at_wib") or focal.get("scheduled_at") or "—")
                    + " • "
                    + str(focal.get("category") or "—")
                    + " • source="
                    + str(focal.get("source_tier") or focal.get("source") or "—")
                )
            if str(news.get("risk_state") or "") in {"PRE_EVENT", "EVENT_WINDOW"}:
                st.warning(
                    "WAIT — EVENT VOLATILITY. News tidak dipakai untuk menebak arah. "
                    "Tunggu rilis, lalu validasi sweep → reclaim → MSS/displacement."
                )
            elif str(news.get("risk_state") or "") == "NEWS_SOURCE_UNAVAILABLE":
                st.error(
                    "News calendar unavailable. Status tidak boleh dianggap CLEAR; "
                    "entry guide dipaksa WAIT_NEWS_DATA."
                )
            elif str(news.get("risk_state") or "") == "POST_EVENT_DISCOVERY":
                st.info(
                    "POST-NEWS PRICE DISCOVERY • fokus pada interaksi harga dengan decision zone, "
                    "bukan pada arah headline."
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
                        "Ini adalah validasi reversal berbasis harga; news sendiri tetap tidak memberi arah."
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
                        use_container_width=True,
                        hide_index=True,
                    )
            else:
                st.caption("Belum ada sweep envelope yang layak dipetakan.")

            st.markdown("### Validasi reversal & entry guide")
            e1, e2, e3, e4 = st.columns(4)
            e1.metric("Stage", str(micro.get("stage") or "WAIT"))
            e2.metric("Entry", _px(guide.get("entry_reference")))
            e3.metric("Invalidation", _px(guide.get("invalidation")))
            targets = list(guide.get("targets") or [])
            e4.metric("TP terdekat", _px(targets[0].get("price") if targets else None))
            st.caption(
                "Entry hanya ditampilkan sesudah touch/sweep + reclaim + local MSS + displacement. "
                "Sebelum itu status wajib WAIT_CONFIRMATION."
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
                        "Touch": life.get("touch_count"),
                        "Freshness": life.get("freshness"),
                        "Distance ATR": zone.get("distance_atr"),
                    }
                )
            if rows:
                with st.expander("Semua zona H4/H1 aktif"):
                    st.dataframe(rows, use_container_width=True, hide_index=True)

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

            st.caption("Parent zone • " + _zone_label(parent))
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
                "Hit-rate tinggi tidak boleh dibaca sebagai readiness karena planned reward relatif kecil "
                "terhadap structural risk dan friction belum termasuk. Engine ini shadow/forecast only."
            )

    st.caption(
        "Legacy decision engines dipause dari jalur terjadwal. Safety/protection, broker telemetry, "
        "token maintenance, dan dashboard bridge bukan decision engine dan tetap boleh berjalan."
    )
