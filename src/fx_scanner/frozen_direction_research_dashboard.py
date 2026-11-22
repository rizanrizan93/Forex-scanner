"""Read-only historical benchmark viewer; not a live prediction model."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import pandas as pd
from .manual_r3_feed import fetch_market, read_public, validate_market, stamp, URL

ROOT=Path(__file__).resolve().parents[2]
LOCK=ROOT/"research/direction_benchmark_lock_r281_20261122.json"

def load_market():
    now=datetime.now(UTC)
    try:
        return fetch_market(now=now), False
    except (OSError,ValueError,TypeError,KeyError,TimeoutError):
        # Explicit historical-only fallback; never authorizes live action.
        try:
            p=read_public(URL)
            at=stamp(p.get("as_of"))
            if at is None or at>now:return None,True
            return validate_market(p,now=at),True
        except (OSError,ValueError,TypeError,KeyError,TimeoutError):
            return None,True

def reference_bars(frame, tf, cutoff):
    minutes={"H1":60,"H4":240}[tf]
    freq=f"{minutes}min"
    bars=frame.resample(freq,label="right",closed="left").agg(
        open=("open","first"),high=("high","max"),low=("low","min"),
        close=("close","last"),count=("close","count"))
    bars=bars[(bars.index<=cutoff)&(bars["count"]>=int(minutes*.83))].dropna()
    return bars

def render_frozen_direction_research():
    import streamlit as st
    import altair as alt
    st.subheader("RIZAN XAU · Frozen Direction R28.1")
    st.warning("WAIT · Delapan benchmark historis dikunci. Belum ada model inferensi LIVE tervalidasi. Akurasi historis bukan probabilitas sinyal sekarang.")
    lock=json.loads(LOCK.read_text())
    entries=lock["entries"]
    for tf in ("H1","H4","D1","W1"):
        st.markdown("**"+tf+" — prediksi close berikutnya**")
        cols=st.columns(2)
        for col,side in zip(cols,("BUY","SELL")):
            e=next(x for x in entries if x["tf"]==tf and x["side"]==side)
            col.metric(side+" · "+e["version"],f"{e['accuracy']:.2%}")
            col.caption(f"n={e['n']} · {e['lane']}")
    st.caption("BUY/SELL dari kebijakan dan periode pengujian berbeda; tidak boleh digabung menjadi klaim akurasi satu model. Tidak ada order, entry atau perubahan cBot.")
    with st.expander("Arsip benchmark dan konfigurasi penelitian"):
        st.dataframe([{"TF":e["tf"],"Arah":e["side"],"Versi":e["version"],"Akurasi":f"{e['accuracy']:.2%}","n":e["n"],"Catatan":e["notes"],"Replay":e["run_url"]} for e in entries],hide_index=True)
        st.download_button("Unduh benchmark JSON",LOCK.read_text(),file_name=LOCK.name,mime="application/json")
        st.markdown("[Handover R27](https://github.com/rizanrizan93/Forex-scanner/blob/research/r91-early-warning-m1-20261121/research/RIZAN_DIRECTION_HANDOVER_R27.md) · [Replay R28.1](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44970328847)")
    st.markdown("### Chart dan area pantau bersyarat")
    st.caption("Rentang 20 candle dengan cakupan minimum 83% terakhir; kuartil bawah = referensi buy the dip, kuartil atas = referensi sell on rebound. Bukan zona tujuan harga, target pantulan, probabilitas, ataupun sinyal entry dari model frozen.")
    tf=st.radio("Timeframe chart",["H1","H4"],horizontal=True,key="frozen_r281_chart_tf")
    @st.cache_data(ttl=30,show_spinner=False)
    def read_snapshot():
        return load_market()
    source,historical=read_snapshot()
    if source is None:
        st.info("WAIT DATA · Feed candle belum tersedia; tidak ada level harga yang dibuat-buat.")
        return
    bars=reference_bars(source["frame"],tf,source["as_of"])
    st.caption("Snapshot "+source["as_of"].isoformat()+" · UTC candle close · "+("HISTORIS/STALE, bukan level terkini" if historical else "feed read-only"))
    if len(bars)<20:
        st.info("WAIT DATA · Kurang dari 20 candle untuk rentang "+tf+".")
        return
    recent=bars.tail(20);lo=float(recent.low.min());hi=float(recent.high.max())
    if not hi>lo:
        st.info("WAIT DATA · Rentang harga tidak valid.");return
    q1=lo+(hi-lo)*.25;q3=lo+(hi-lo)*.75
    cols=st.columns(2)
    cols[0].metric("Buy the dip · referensi",f"{lo:,.2f}–{q1:,.2f}")
    cols[1].metric("Sell on rebound · referensi",f"{q3:,.2f}–{hi:,.2f}")
    cols[0].caption("Hanya dipertimbangkan jika arah bullish terkonfirmasi independen.")
    cols[1].caption("Hanya dipertimbangkan jika arah bearish terkonfirmasi independen.")
    chart=bars.tail(60).copy();chart["time"]=chart.index;chart["WIB"]=chart.index.tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M")
    shades=pd.DataFrame([{"start":chart.index.min(),"end":chart.index.max(),"lo":lo,"hi":q1,"zone":"Buy the dip"},{"start":chart.index.min(),"end":chart.index.max(),"lo":q3,"hi":hi,"zone":"Sell on rebound"}])
    rect=alt.Chart(shades).mark_rect(opacity=.12).encode(x="start:T",x2="end:T",y=alt.Y("lo:Q",scale=alt.Scale(zero=False)),y2="hi:Q",color=alt.Color("zone:N",scale=alt.Scale(domain=["Buy the dip","Sell on rebound"],range=["#149c78","#d65c5c"]),legend=None))
    base=alt.Chart(chart).encode(x=alt.X("time:T",title="Candle close UTC"),tooltip=["WIB","open:Q","high:Q","low:Q","close:Q"])
    color=alt.condition("datum.close >= datum.open",alt.value("#149c78"),alt.value("#d65c5c"))
    candles=base.mark_rule().encode(y=alt.Y("low:Q",scale=alt.Scale(zero=False),title="XAUUSD"),y2="high:Q",color=color)+base.mark_bar(size=4).encode(y="open:Q",y2="close:Q",color=color)
    st.altair_chart((rect+candles).properties(height=340),width="stretch")
    st.info("Keputusan engine: WAIT. Tidak ada izin entry; zona hanya deskriptif. D1/W1 memerlukan riwayat lebih panjang dan inferensi model tervalidasi.")
