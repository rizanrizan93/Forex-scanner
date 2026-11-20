"""Isolated read-only XAU rejection panel; no execution authority."""
from datetime import UTC, datetime
import pandas as pd
import streamlit as st
from fx_scanner.rejection_v2_research import calculate
from research.fed_expectation_r1.macro_entry_alignment_r5 import align_macro_v4

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
                source_key="live-public-m1"
                if st.session_state.get("_rejection_event_source")!=source_key:
                    st.session_state["_rejection_event_source"]=source_key
                    st.session_state["_rejection_event_history"]=[]
                outcome=calculate(data,now=now,bid=src.get('bid'),ask=src.get('ask'),
                                  quote_at=src.get('quote_as_of'),
                                  prior_events=st.session_state["_rejection_event_history"])
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
                import hashlib
                source_key="offline-"+hashlib.sha256(uploaded.getvalue()).hexdigest()[:16]
                if st.session_state.get("_rejection_event_source")!=source_key:
                    st.session_state["_rejection_event_source"]=source_key
                    st.session_state["_rejection_event_history"]=[]
                outcome=calculate(data,now=now,
                                  prior_events=st.session_state["_rejection_event_history"])
                origin="CSV M1 offline · tidak ada quote real-time"
        except (OSError,TimeoutError,ValueError,TypeError,KeyError,
                pd.errors.ParserError) as exc:
            st.error("WAIT DATA — sumber candle tidak lengkap, stale, atau tidak dapat diakses.")
            st.caption(str(exc))
            return
        st.session_state["_rejection_event_history"]=outcome["rejection_events"]
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
        st.markdown("#### Status rejection yang sudah terdeteksi")
        events=outcome["rejection_events"]
        priority=[e for e in events if e["display_state"] in
                  ("BREAKOUT_RISK","REJECTION_INVALIDATED","BREAKOUT_CONFIRMED")]
        if priority:
            recent=priority[-1]
            st.error(recent["side"]+" "+recent["display_state"]+" · "+
                     recent["zone_name"]+" · "+recent["reason"])
            st.caption("Invalidasi dibekukan sejak sinyal: "+str(recent["invalidation"])+
                       " | sinyal "+recent["signal_at"]+
                       " | bukan instruksi menambah posisi")
        elif events:
            recent=events[-1]
            st.info(recent["side"]+" "+recent["display_state"]+
                    " · "+recent["zone_name"]+" · "+recent["reason"])
        else:
            st.caption("Belum ada event rejection yang tercatat dalam sesi panel ini.")
        if events:
            st.dataframe(pd.DataFrame([{
                "Sinyal UTC":e["signal_at"],"Arah":e["side"],
                "Titik":e["zone_name"],"Harga sinyal":e["level"],
                "Status":e["display_state"],"Batas invalidasi tetap":e["invalidation"],
                "Alasan":e["reason"],
            } for e in reversed(events[-8:])]),hide_index=True,width="stretch")
        st.caption("EARLY_REJECTION bukan VALID. REJECTION_CONFIRMED hanya konfirmasi M1, bukan jaminan H1/H4. BREAKOUT_RISK berasal dari quote; INVALIDATED memerlukan close M1, BREAKOUT_CONFIRMED memerlukan close M5.")
        st.markdown("#### R5 · Filter arah Fed → V4 (RESEARCH ONLY)")
        # Deliberately no fabricated live FOMC feed: R4 needs real
        # intraday OIS1Y + TIPS10Y + stock + DXY ingestion.
        # Until connected, both V4 directions must be BLOCKED.
        fed_gate=align_macro_v4(outcome["v4_setups"],None,None,evaluated_at=now)
        st.warning("R5 MACRO WAIT — belum ada feed intraday OIS/TIPS/S&P/DXY "
                   "dengan timestamp rilis & ingestion terverifikasi. "
                   "Tidak ada kandidat entry yang lolos filter arah makro.")
        st.dataframe(pd.DataFrame([{
            "Arah":v["side"],"Setup V4":v["setup_type"],
            "Kelayakan V4":v["original_v4_entry_status"],
            "Gate R5":v["macro_alignment_gate"],
        } for v in fed_gate["research_candidates"]]),hide_index=True,width="stretch")
        st.caption("Hasil V4 di bawah ini adalah kandidat TEKNIKAL saja. "
                   "R5 selalu memblokir order dan tidak mengklaim akurasi 80%. "
                   "R4 belum terhubung ke market feed live.")
        st.markdown("#### V4 · Trend Rejection dan Countertrend Reversal")
        st.caption("Dua jalur untuk BUY & SELL: searah H1/H4 atau reversal melawan tren dengan M1 sweep → reclaim → MSS. ENTRY_CANDIDATE tetap riset; bukan order.")
        for side in ("BUY","SELL"):
            xs=[x for x in outcome["v4_setups"] if x["side"]==side]
            for x in xs:
                title=side+" · "+x["setup_type"]+" · "+x["stage"]
                if x["entry_status"]=="ENTRY_CANDIDATE":
                    st.info(title+" — V4 TECHNICAL CANDIDATE ONLY; R5 MACRO BLOCKED")
                elif x["entry_status"].startswith("BLOCKED"):
                    st.warning(title+" — "+x["entry_status"])
                else:
                    st.write("**"+title+"** — "+x["entry_status"])
                st.caption("Watch "+str(x["watch_level"])+
                           " | Invalidation "+str(x["invalidation"])+
                           " | Room ATR "+str(x["room_atr"])+
                           " | "+("; ".join(x["reasons"]) if x["reasons"] else "Gates satisfied"))
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
        st.warning("Mode riset. Status reversal bukan rekomendasi entry dan tidak membatalkan kewajiban mengelola risiko posisi di cTrader. Rejection yang gagal tidak boleh dianggap masih valid.")
    panel()
