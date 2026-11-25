"""R17 historical reference; does not replace R13 or authorize entries."""
from __future__ import annotations

SPLITS=(
    ("2019–2022",336,164.24724637623876,1.2128235131737626,.47023809523809523),
    ("2023–2024",146,75.70011740457267,1.1773558429895505,.5342465753424658),
    ("2025–31 Mar 2026",171,461.92192293703556,1.3684055104987274,.5964912280701754),
)
EVIDENCE="https://github.com/rizanrizan93/Forex-scanner/blob/research/r9-r10-100b-local-20261125/research/r9_r10_local/R17_MANUAL_REPLAY_EVIDENCE.json"

def render_r17_reference(st):
    with st.container(border=True):
        st.markdown("### R17 · H4 Intermarket Ensemble")
        st.warning("RESEARCH ONLY · NO LIVE SIGNAL")
        st.caption("Hasil screening historis XAUUSD/EURUSD, 1 ons, biaya model 2×. Dipilih setelah melihat evaluasi; bukan holdout independen.")
        a,b=st.columns(2)
        a.metric("Net historis / ons",f"${sum(r[2] for r in SPLITS):,.2f}")
        b.metric("Transaksi historis",sum(r[1] for r in SPLITS))
        a,b=st.columns(2)
        a.metric("Win rate evaluasi terbaru","59.65%")
        b.metric("PF evaluasi terbaru","1.37")
        st.caption("Belum memenuhi target win rate 80% / PF 1.5. Win rate transaksi bukan akurasi prediksi H4.")
        st.dataframe([{"Periode":p,"N":n,"Net USD/oz":round(net,2),"PF":round(pf,3),"Win %":round(win*100,2)} for p,n,net,pf,win in SPLITS],hide_index=True)
        with st.expander("Konfigurasi ensemble historis dan kebutuhan data"):
            st.write("BUY: reclaim EMA4 M15, H4 di atas EMA40, sesi tetap 13–21 UTC; TP $10, SL 1 ATR H4 (minimum $2), holding 120 menit, trailing berbasis close 0.8R.")
            st.write("SELL: rejection EMA8 M15, H4 di bawah EMA40, semua sesi; TP $30, SL 1 ATR H4 (minimum $2), holding 240 menit, breakeven setelah progress close 0.6R.")
            st.write("Keduanya: ATR14 H4 >= $3, ATR relatif terhadap median 60 bar sebelumnya >= 1.15; return EURUSD 60 menit dibagi rolling std 96 return sebelumnya <= -0.5 (nilai mentah, kedua sisi, sesuai ensemble.py). Maksimum satu posisi pada replay; BUY mendapat prioritas jika bersamaan.")
            st.caption("Angka ini merupakan parameter penelitian, bukan level entry/SL/TP sekarang. Inferensi membutuhkan seri EURUSD dan XAUUSD sinkron, riwayat H4 lengkap untuk ATR/EMA dan median 60 bar, serta verifikasi parity terhadap replay.")
            st.markdown("[Bukti replay R17]("+EVIDENCE+")")
        st.info("WAIT DATA / CALIBRATION · R17 belum dihubungkan ke feed EURUSD sinkron yang tervalidasi. Arah, area tunggu, dan R13 tetap memakai engine yang sudah ada.")
