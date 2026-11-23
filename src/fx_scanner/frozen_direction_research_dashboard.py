"""R28.1 research model forecasts and raw closed-candle chart."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import pandas as pd
from .frozen_direction_context import TFS, context, read_context_packet, session_closed
from .manual_reversal_dashboard import fetch_manual_map
from .manual_r3_feed import fetch_market, read_public, validate_market, stamp, URL
from .r281_shadow_feed import fetch as fetch_r281, blank as blank_r281, reason_text

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
    # No partial H1/H4 aggregation: 50/60 minutes is NOT a closed H1 candle.
    bars=bars[(bars.index<=cutoff)&(bars["count"]==minutes)].dropna()
    return bars

def load_context_sources():
    source,historical=load_market()
    now=datetime.now(UTC)
    native={};native_at=None;market_fresh=False
    try:
        p=fetch_manual_map()
        now=datetime.now(UTC)
        native,native_at=read_context_packet(p.get("direction_context"),now)
        market_fresh=bool(p.get("fresh"))
    except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
        pass
    frames={};reports={}
    for tf in TFS:
        choices=[]
        if tf in native:choices.append((native[tf],native_at,market_fresh,"Native cTrader"))
        if source is not None and tf in ("H1","H4"):
            b=reference_bars(source["frame"],tf,source["as_of"])
            last_m1=source["frame"].index[-1]+pd.Timedelta(minutes=1)
            fresh=(not historical and 0<=(pd.Timestamp(now)-last_m1).total_seconds()<=120)
            if len(b):choices.append((b,source["as_of"],fresh,"M1 cTrader teragregasi UTC"))
        assessed=[(b,context(b,tf,now=now,observed_at=at,market_fresh=ok),label,at) for b,at,ok,label in choices]
        if assessed:
            b,r,label,at=max(assessed,key=lambda item:(item[1]["fresh"],item[1]["last_bias"] is not None,pd.Timestamp(item[3])))
            frames[tf]=b;reports[tf]={**r,"source":label,"snapshot_at":pd.Timestamp(at).isoformat()}
        else:reports[tf]=context(None,tf,now=now,observed_at=now,market_fresh=False)
    return frames,reports,now

def render_frozen_direction_research():
    import streamlit as st
    import altair as alt
    st.subheader("RIZAN XAU · Prediksi R28.1")
    st.caption("Arah H1, H4, D1, dan W1 berasal hanya dari model riset R28.1. BUY: close berikutnya lebih tinggi; SELL: lebih rendah dibanding close terakhir.")

    @st.cache_data(ttl=30,show_spinner=False)
    def read_r281(slot):
        return fetch_r281()

    @st.cache_data(ttl=30,show_spinner=False)
    def read_chart(slot):
        return load_context_sources()

    def wib(value):
        return pd.Timestamp(value).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M WIB") if value else "—"

    @st.fragment(run_every="30s")
    def panel():
        now=datetime.now(UTC)
        try:
            shadow=read_r281(int(now.timestamp()//30))
        except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
            shadow={tf:blank_r281("MODEL_SNAPSHOT_UNAVAILABLE") for tf in TFS}
        st.dataframe([
            {"TF":tf,
             "Arah R28.1":shadow[tf]["direction"],
             "Target close (WIB)":wib(shadow[tf]["target"]),
             "Diterbitkan (WIB)":wib(shadow[tf]["issued"]),
             "Status":("RESEARCH SHADOW" if shadow[tf]["state"]=="RECONSTRUCTED_SHADOW"
                       else "WAIT MODEL" if shadow[tf]["state"]=="MODEL_ABSTAIN" else "WAIT DATA"),
             "Keterangan":reason_text(shadow[tf]["reason"])}
            for tf in TFS],hide_index=True,width="stretch")
        st.caption("Diperiksa "+wib(now)+" · tampilan diperbarui 30 detik; waktu penerbitan menunjukkan pembaruan model sebenarnya.")
        st.caption("WAIT MODEL: syarat skor riset belum terpenuhi atau kedua arah bertentangan. WAIT DATA: input/model belum tersedia atau target prediksi sudah berakhir.")
        if session_closed(now):
            st.warning("Pasar XAU tutup; tunggu pembaruan model saat pasar buka.")
        for tf in TFS:
            row=shadow[tf]
            with st.container(border=True):
                st.metric(tf+" · R28.1",row["direction"])
                st.caption(reason_text(row["reason"]))
                if row["closed"]:
                    st.caption("Close acuan: "+wib(row["closed"])+" · target: "+wib(row["target"])+" · diterbitkan: "+wib(row["issued"]))
        st.caption("Model direkonstruksi dari konfigurasi replay R28.1. Replay parity 2025 lulus; akurasi forward 2026 belum tervalidasi independen.")
        with st.expander("Chart candle sumber",expanded=False):
            if not st.toggle("Tampilkan chart",key="r281_show_chart"):
                return
            tf=st.radio("Timeframe chart",list(TFS),horizontal=True,key="frozen_r281_chart_tf")
            frames,reports,_=read_chart(int(now.timestamp()//30))
            bars=frames.get(tf)
            if bars is None or bars.empty:
                st.info("Data chart belum tersedia.")
                return
            r=reports[tf]
            if r.get("closed_at"):
                bars=bars.loc[bars.index<=pd.Timestamp(r["closed_at"])]
            chart=bars.tail(60).copy()
            if chart.empty:return
            chart["time"]=chart.index
            chart["WIB"]=chart.index.tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M")
            st.caption("Candle sumber untuk referensi visual. Arah prediksi pada tabel berasal dari model R28.1.")
            base=alt.Chart(chart).encode(x=alt.X("time:T",title="Candle close UTC"),tooltip=["WIB","open:Q","high:Q","low:Q","close:Q"])
            color=alt.condition("datum.close >= datum.open",alt.value("#149c78"),alt.value("#d65c5c"))
            pic=base.mark_rule().encode(y=alt.Y("low:Q",scale=alt.Scale(zero=False),title="XAUUSD"),y2="high:Q",color=color)+base.mark_bar(size=4).encode(y="open:Q",y2="close:Q",color=color)
            st.altair_chart(pic.properties(height=340),width="stretch")
    panel()
    with st.expander("R28.1 · hasil replay historis",expanded=False):
        lock=json.loads(LOCK.read_text())
        entries=lock["entries"]
        st.dataframe([{"TF":e["tf"],"Arah":e["side"],"Versi":e["version"],"Akurasi":f"{e['accuracy']:.2%}","n":e["n"]} for e in entries],hide_index=True)
        st.caption("Benchmark historis berasal dari berbagai kebijakan/sampel, bukan probabilitas prediksi saat ini.")
        st.download_button("Unduh benchmark JSON",LOCK.read_text(),file_name=LOCK.name,mime="application/json")
