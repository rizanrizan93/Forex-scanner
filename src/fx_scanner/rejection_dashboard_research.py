"""Isolated read-only XAU rejection panel; no execution authority."""
from datetime import UTC, datetime
import pandas as pd
import streamlit as st
from fx_scanner.rejection_v2_research import calculate

def render_rejection_panel():
    st.subheader("RIZAN Rejection Engine · Early BUY / SELL")
    st.caption("RESEARCH ONLY · no broker orders, no win-rate claim, no change to V1 / Manual R3")
    mode=st.radio("Sumber",["M1 feed read-only (Manual R3)","CSV M1 offline"],horizontal=True,
                  key="rejection_v2_mode")
    uploaded=None
    if mode=="CSV M1 offline":
        uploaded=st.file_uploader("CSV M1 UTC (timestamp OPEN, open/high/low/close)",type=["csv"],
                                  key="rejection_v2_m1_upload")
        st.caption("Offline evaluation uses the LAST closed M1 as-of, not current market time; no live entry-ready flag.")
    @st.fragment(run_every="10s")
    def panel():
        try:
            if mode=="M1 feed read-only (Manual R3)":
                from fx_scanner.manual_r3_feed import fetch_market
                @st.cache_data(ttl=5,show_spinner=False)
                def read_snapshot(bucket):
                    return fetch_market()
                now=datetime.now(UTC)
                src=read_snapshot(int(now.timestamp()//5))
                data=src['frame']
                outcome=calculate(data,now=now,bid=src.get('bid'),ask=src.get('ask'),
                                  quote_at=src.get('quote_as_of'))
                origin="cTrader market data read-only · Manual R3 public contract"
            else:
                if uploaded is None:
                    st.info("Upload CSV M1 historis untuk memeriksa zona; tidak ada harga yang dibuat-buat.")
                    return
                if uploaded.size>8_000_000:
                    raise ValueError("CSV lebih dari 8 MB")
                raw=pd.read_csv(uploaded)
                if 'timestamp' not in raw:
                    raise ValueError("CSV harus memiliki kolom timestamp")
                text=raw['timestamp'].astype(str)
                if not text.str.contains(r'(?:Z|[+-][0-9]{2}:[0-9]{2})$',regex=True).all():
                    raise ValueError("Semua timestamp CSV harus menyebut offset UTC eksplisit")
                raw.index=pd.to_datetime(raw.pop('timestamp'),utc=True,errors='raise')
                data=raw
                now=data.index[-1]+pd.Timedelta(minutes=1)
                outcome=calculate(data,now=now)
                origin="CSV M1 offline · tidak ada quote real-time"
        except (OSError,TimeoutError,ValueError,TypeError,KeyError,
                pd.errors.ParserError) as exc:
            st.error("WAIT DATA — sumber candle tidak lengkap, stale, atau tidak dapat diakses.")
            st.caption(str(exc))
            return
        st.caption(origin+" · M1 close "+outcome['last_closed_m1']+
                   " · M5 close "+outcome['last_closed_m5'])
        a,b,c,d=st.columns(4)
        a.metric("Bias utama H1/H4",outcome['bias'])
        b.metric("H1",outcome['h1_bias'])
        c.metric("H4",outcome['h4_bias'])
        d.metric("Harga referensi",f"{outcome['price']:,.2f}")
        if outcome['bias']=="WAIT":
            st.warning("Bias H1/H4 belum searah atau riwayat belum cukup. Zona tetap ditampilkan; ENTRY diblokir.")
        if not outcome['quote_valid']:
            st.caption("Quote live tidak tersedia/terlambat: tidak ada status EARLY ENTRY CANDIDATE.")
        st.markdown("#### Titik pantauan BUY dan SELL")
        st.caption("EMA20/50 M5, support/resistance M5, EMA20 H1, support/resistance H1; 3 zona terdekat PER SISI.")
        for side in ('BUY','SELL'):
            zones=[z for z in outcome['zones'] if z['side']==side]
            st.markdown("**"+side+"**")
            st.dataframe(pd.DataFrame([{
                "Titik":z['name'],"Harga":z['price'],
                "Zona":f"{z['low']:.2f}–{z['high']:.2f}",
                "Jarak ATR":z['distance_atr'],
                "Tahap":z['stage'],"Rencana":z['entry'],
                "Invalidasi referensi":z['invalidation'],
            } for z in zones]),hide_index=True,width="stretch")
        st.caption(f"ATR M5: {outcome['atr_m5']:.3f}. Early rejection memakai candle M1 yang sudah close; tidak menunggu retest wajib.")
        st.warning("Belum ada validasi probabilitas BUY/SELL atau backtest historis. LEVEL dan EARLY ENTRY adalah kandidat untuk analisis manual, bukan instruksi eksekusi.")
    panel()
