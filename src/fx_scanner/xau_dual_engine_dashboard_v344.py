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
        '<div class="rizan-title">XAUUSD — Supply/Demand & Micro Entry</div>'
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
            micro = dict(sd.get("micro_confirmation") or {})
            guide = dict(sd.get("entry_guide") or {})
            sweep = dict(sd.get("liquidity_map") or {})
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

            if decision:
                st.markdown(
                    f"**Decision zone:** {_zone_label(decision)} • "
                    f"pattern={decision.get('pattern','—')} • "
                    f"score={decision.get('score','—')} • "
                    f"freshness={dict(decision.get('lifecycle') or {}).get('freshness','—')}"
                )
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
            full = dict(evidence.get("full_2012_2026") or {})
            oos = dict(evidence.get("oos_2025_2026") or {})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Arah", str(friend.get("direction") or "WAIT"))
            m2.metric("Phase", str(friend.get("state") or "WAIT"))
            m3.metric("Primary entry", _px(entries.get("historical_primary_price")))
            m4.metric("SL struktural", _px(friend.get("stop_loss")))

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
