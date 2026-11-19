"""Research-only rejection panel. User-provided CLOSED M5 data, no live execution."""
import pandas as pd
import streamlit as st
from fx_scanner.rejection_entry_research import plan_entry

def render_rejection_panel():
    st.subheader("RIZAN Rejection Engine · BUY / SELL")
    st.caption("RESEARCH ONLY · bukan sinyal LIVE, bukan probabilitas terkalibrasi · tidak mengirim order")
    st.info("Unggah CSV candle M5 XAUUSD yang SUDAH CLOSE: timestamp (UTC), open, high, low, close. Candle berjalan tidak boleh disertakan.")
    uploaded = st.file_uploader("CSV XAUUSD M5 (UTC)", type=["csv"], key="rizan_rejection_csv")
    left,right = st.columns(2)
    with left:
        lookback = st.slider("Liquidity lookback (M5 bars)",5,50,12,key="rizan_rejection_lookback")
    with right:
        macro = st.selectbox("DXY direction (optional)",["Unavailable","Falling","Flat","Rising"],key="rizan_rejection_dxy")
    if uploaded is None:
        st.warning("DATA BELUM TERSEDIA — panel tidak membuat angka harga atau sinyal sintetis.")
        return
    try:
        data=pd.read_csv(uploaded)
        direction={"Unavailable":None,"Falling":-1,"Flat":0,"Rising":1}[macro]
        result=plan_entry(data,lookback,direction)
    except (ValueError,TypeError,KeyError,pd.errors.ParserError) as exc:
        st.error("Data tidak valid: "+str(exc))
        return
    st.metric("Rejection",result.rejection)
    st.metric("Arah",result.side)
    st.metric("Keputusan entry",result.entry_status)
    if result.retest_low is not None:
        a,b,c=st.columns(3)
        a.metric("Retest lower",f"{result.retest_low:.2f}")
        b.metric("Retest upper",f"{result.retest_high:.2f}")
        c.metric("Invalidation",f"{result.invalidation:.2f}")
    st.write("Harga close terbaru:",f"{result.reference_price:.2f}")
    st.caption(result.explanation)
    st.warning("ENTRY READY hanya berarti harga berada di area retest. Periksa reaksi candle yang sudah close, spread, dan risk/reward sebelum keputusan manual.")
