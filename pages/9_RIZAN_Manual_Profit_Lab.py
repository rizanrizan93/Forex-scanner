"""RIZAN manual trade planning panel (RESEARCH ONLY; no broker execution).
Uses user-entered prices and checklist; no forecasts or live signals.
"""
import math
import streamlit as st

st.set_page_config(page_title="RIZAN Manual Profit Lab",page_icon="🧪",layout="wide")
st.title("RIZAN — Manual Profit Lab")
st.caption("RESEARCH / PLANNING ONLY • Tidak terkoneksi ke broker, tidak mengirim order.")
st.warning("R12 BELUM LULUS VALIDASI: kandidat BUY dan SELL sama-sama negatif pada evaluasi 2026. Kalkulator ini bukan sinyal trading LIVE.")
st.markdown("[Bukti replay R12](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44916167164)")
st.markdown("### Perencanaan transaksi hipotetis")
c1,c2,c3=st.columns(3)
with c1:
    equity=st.number_input("Equity (USD)",min_value=1.0,value=100.0,step=10.0)
    side=st.selectbox("Rencana arah",["BUY","SELL"])
    entry=st.number_input("Harga entry XAUUSD",min_value=0.0,value=0.0,step=1.0,format="%.2f")
with c2:
    stop=st.number_input("Stop loss (harga)",min_value=0.0,value=0.0,step=1.0,format="%.2f")
    target=st.number_input("Take profit (harga)",min_value=0.0,value=0.0,step=1.0,format="%.2f")
    risk_limit_pct=st.slider("Batas risiko per trade (%)",min_value=0.25,max_value=1.0,value=0.5,step=0.25)
with c3:
    minimum_lot=st.number_input("Lot minimum broker",min_value=0.001,value=0.01,step=0.01,format="%.3f")
    lot_increment=st.number_input("Increment lot broker",min_value=0.001,value=0.01,step=0.01,format="%.3f")
    ounces_per_lot=st.number_input("Kontrak emas (oz/lot) sesuai cTrader",min_value=1.0,value=100.0,step=10.0)
    roundtrip_cost_oz=st.number_input("Asumsi spread + komisi + slippage (USD/oz)",min_value=0.0,value=0.7,step=0.1)
valid_price=(entry>0 and stop>0 and target>0)
valid_side=valid_price and ((stop<entry<target) if side=="BUY" else (target<entry<stop))
budget=equity*risk_limit_pct/100
if not valid_price:
    st.info("Isi harga entry, SL, TP untuk menghitung risiko; halaman tidak menggunakan harga otomatis.")
elif not valid_side:
    st.error("SL/TP tidak valid. BUY: SL < entry < TP. SELL: TP < entry < SL.")
else:
    gross_stop=abs(entry-stop)
    gross_reward=abs(target-entry)
    stop_loss_lot=(gross_stop+roundtrip_cost_oz)*ounces_per_lot
    potential_profit_lot=(gross_reward-roundtrip_cost_oz)*ounces_per_lot
    units=math.floor((budget/stop_loss_lot+1e-10)/lot_increment)
    max_lot=round(units*lot_increment,6)
    contract_allows=max_lot+1e-10>=minimum_lot
    display_lot=max_lot if contract_allows else 0.0
    cash_risk=display_lot*stop_loss_lot
    cash_reward=display_lot*potential_profit_lot
    net_rr=max(0.0,potential_profit_lot)/max(1e-10,stop_loss_lot)
    a,b,c,d=st.columns(4)
    a.metric("Anggaran risiko",f"USD {budget:,.2f}")
    b.metric("Lot maksimal hipotetis",f"{display_lot:.3f}")
    c.metric("Kerugian jika SL",f"USD {cash_risk:,.2f}")
    d.metric("R:R setelah biaya",f"{net_rr:.2f}R")
    st.caption(f"Estimasi laba jika TP: USD {cash_reward:,.2f}. Ini kalkulator posisi, bukan prediksi peluang TP.")
    if not contract_allows:
        st.error("WAIT — risiko lot minimum broker melebihi anggaran risiko.")
    elif net_rr<1.5:
        st.warning("WAIT — R:R setelah biaya kurang dari 1,5R.")
st.divider()
st.markdown("### Checklist manual: berdasarkan chart yang Anda periksa")
st.caption("Checklist ini tidak dapat memvalidasi data broker; jangan centang sebelum memeriksa chart aktual.")
p1,p2=st.columns(2)
with p1:
    h4=st.checkbox("H4: arah dominan terkonfirmasi, bukan sekadar EMA cross")
    h1=st.checkbox("H1: zona likuiditas/pullback belum invalid")
    m5=st.checkbox("M5: MSS/BOS atau displacement sesuai arah telah selesai")
with p2:
    spread=st.checkbox("Spread dan slippage saat ini diperiksa")
    macro=st.checkbox("Tidak ada event risiko tinggi yang belum diputuskan")
    fresh=st.checkbox("Harga segar, simbol dan jam WIB terverifikasi")
allcheck=all((h4,h1,m5,spread,macro,fresh))
if valid_side and allcheck and contract_allows and net_rr>=1.5:
    st.info("PREPARE — checklist dan kalkulator terpenuhi. R12 BELUM terverifikasi; panel tidak memberi perintah entry.")
else:
    st.warning("WAIT — setup belum memenuhi seluruh syarat atau harga belum valid.")
st.markdown("### Status penelitian")
st.markdown(
    "R12 menguji 1.152 konfigurasi empat keluarga setup pada H4/H1. Evaluasi 2024–2026 menggunakan entry OPEN candle H1 berikutnya; "
    "SL/TP memakai urutan intrabar konservatif. Tahun 2026 expectancy BUY dan SELL negatif. "
    "M5, data makro point-in-time, biaya aktual broker, serta forward holdout baru belum divalidasi."
)
st.caption("Halaman ini tidak memuat broker login, token, transaksi, modifikasi cBot, atau otomasi order.")
