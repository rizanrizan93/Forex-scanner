"""Prominent read-only frozen R29.2 H4 BUY specialist block."""
from __future__ import annotations


def render_h4_buy(st,row,wib):
    st.markdown("### H4 BUY · R29.2 Precision (FROZEN SHADOW)")
    with st.container(border=True):
        status=row["state"]
        st.metric("Kandidat H4 BUY R29.2",row["direction"])
        if status=="RESEARCH_SHADOW":
            st.info("BUY SHADOW terpicu dari model frozen. Ini hanya sinyal riset; "
                    "bukan izin entry, bukan pengganti konfirmasi SMC/ICT dan manajemen risiko.")
        elif status=="MODEL_ABSTAIN":
            st.write("**WAIT MODEL** · Score BUY atau filter trend_impulse "
                     "belum memenuhi aturan yang sudah dibekukan.")
        else:
            st.warning("**WAIT DATA** · "+row.get("reason","BELUM_TERBIT")
                       +". Jangan gunakan prediksi kedaluwarsa.")
        if row.get("score") is not None:
            st.caption(
                "Skor model BUY "+f'{row["score"]:.4f}'
                +" · ambang 0,5400 · trend_impulse "
                +("LOLOS" if row["gate_pass"] else "BELUM")
            )
        if row.get("target"):
            st.caption("Candle sumber: "+wib(row.get("closed"))
                       +" · target penutupan H4 berikutnya: "+wib(row["target"])
                       +" · diterbitkan: "+wib(row.get("issued")))
        elif row.get("expired_at"):
            st.caption("Prediksi terakhir kedaluwarsa: "+wib(row["expired_at"]))
        st.caption("R29.2 historis gabungan: 79/126 = 62,70% "
                   "(kebijakan 2024–2026 berbeda). "
                   "Konfigurasi frozen 2026: 14/23 = 60,87%. "
                   "Ini bukan akurasi forward yang sudah teruji.")
        st.caption("Model: Ridge Logistic · broad_context · threshold 0,54 "
                   "· gate trend_impulse. Hanya BUY; SELL belum lolos kriteria. "
                   "Tidak terhubung ke cBot LIVE atau tombol order.")
