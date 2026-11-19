"""Research-only rejection panel. User-provided CLOSED M5 data, no live execution."""
import pandas as pd
import streamlit as st
from fx_scanner.rejection_entry_research import plan_entry
from fx_scanner.rejection_watch_research import watch_zones

def render_rejection_panel():
    st.subheader("RIZAN Rejection Engine · BUY / SELL")
    st.caption("RESEARCH ONLY · bukan sinyal LIVE, bukan probabilitas terkalibrasi · tidak mengirim order")
    st.info("Unggah CSV candle M5 XAUUSD yang SUDAH CLOSE: timestamp (UTC), open, high, low, close. Candle berjalan tidak boleh disertakan.")
    uploaded = st.file_uploader("CSV XAUUSD M5 (UTC)", type=["csv"], key="rizan_rejection_csv")
    h1_file = st.file_uploader("Optional H1 CLOSED candles (UTC close timestamp)",type=["csv"],key="rizan_rejection_h1")
    h4_file = st.file_uploader("Optional H4 CLOSED candles (UTC close timestamp)",type=["csv"],key="rizan_rejection_h4")
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
        h1 = pd.read_csv(h1_file) if h1_file else None
        h4 = pd.read_csv(h4_file) if h4_file else None
        watch=watch_zones(data,h1,h4)
        result=plan_entry(data,lookback,direction)
    except (ValueError,TypeError,KeyError,pd.errors.ParserError) as exc:
        st.error("Data tidak valid: "+str(exc))
        return
    st.markdown("#### Bias utama dan zona yang dipantau")
    a,b,c=st.columns(3)
    a.metric("H1/H4 bias",watch.bias)
    b.metric("Nearest watch zone",watch.nearest_zone)
    c.metric("Watch price",f"{watch.zone_price:.2f}")
    st.caption(watch.bias_basis)
    st.write("**Early warning:**",watch.stage)
    st.write("**Entry timing:**",watch.entry_style)
    st.caption(watch.notes)
    st.markdown("#### Konfirmasi rejection dan rencana retest")
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
