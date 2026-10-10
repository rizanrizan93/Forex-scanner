"""Mobile cross-asset research cards; local artifact, zero additional DB reads."""

from __future__ import annotations

import json
from pathlib import Path

SUMMARY_PATH = (
    Path(__file__).resolve().parents[2]
    / "calibration/cross_asset_research_summary.json"
)


def load_summary(path=SUMMARY_PATH):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {
            "production_status": "RESEARCH_ONLY",
            "ranking": [],
            "reason": "CALIBRATION_UNAVAILABLE",
        }


def render_cross_asset(target, *, context=None):
    import streamlit as st

    summary = load_summary()
    context = context or {}
    st.subheader("CROSS-ASSET LEAD / LAG")
    st.caption(
        "RIZAN Cross-Asset Lead–Lag Engine · lapisan pressure · tanpa otoritas order"
    )
    st.info(
        "RESEARCH ONLY · NO_SIGNAL · belum ada kalibrasi yang disetujui untuk eksekusi."
    )
    st.caption(
        "Alasan WAIT: probabilitas OOS, manfaat terhadap baseline, dan ketahanan biaya harus lolos sebelum signal aktif."
    )
    cols = st.columns(2)
    cols[0].metric("Cross-asset bias", "BELUM TERVALIDASI")
    cols[1].metric("Confidence / response", "Belum tersedia")
    candidates = [r for r in summary.get("ranking", []) if r.get("target") == target]
    with st.expander("Hasil riset historis · bukan sinyal saat ini", expanded=False):
        st.caption(
            summary.get("period", "Periode belum tersedia")
            + " · "
            + summary.get("validation", "OOS belum tersedia")
        )
        rows = []
        for candidate in candidates:
            oos = candidate.get("oos") or {}
            ci = [oos.get("ci_low"), oos.get("ci_high")]
            rows.append(
                {
                    "Leader": candidate["leader"],
                    "TF": "M" + str(candidate["timeframe_minutes"]),
                    "OOS": candidate.get("oos_year", 2025),
                    "Lag (min)": candidate.get("lag_minutes"),
                    "P arah OOS (%)": round(100 * oos["probability"], 1)
                    if oos.get("probability") is not None
                    else None,
                    "CI 95% (%)": "–".join(f"{100 * x:.1f}" for x in ci)
                    if all(x is not None for x in ci)
                    else "—",
                    "N event OOS": oos.get("events"),
                    "Verdict": candidate.get("verdict"),
                    "Alasan": ", ".join(candidate.get("reasons", [])),
                }
            )
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
        else:
            st.caption(
                "Tidak ada hasil kalibrasi tersedia. Angka contoh tidak digunakan sebagai hasil."
            )
        missing = (summary.get("missing_datasets") or {}).get(target, [])
        if missing:
            st.caption("Data belum tersedia: " + ", ".join(missing))
    # Reference remains visible even with no approved model. No fabricated
    # entry/SL/TP; all geometry comes from the existing scanner's own context.
    reference = context.get("reference_geometry") or {}
    execution = context.get("execution_geometry") or {}
    if reference or execution:
        with st.expander("Reference geometry / execution geometry", expanded=False):
            st.write(
                "REFERENCE GEOMETRY",
                reference or {"reason": "MENUNGGU_GEOMETRY_SCANNER"},
            )
            st.write("EXECUTION GEOMETRY", execution or {"reason": "BELUM_READY"})
    st.caption(
        "H1 bias → M15 struktur / supply-demand / liquidity → M5 pocket & refined pocket → entry → SL/TP struktural tetap mengikuti scanner utama."
    )
