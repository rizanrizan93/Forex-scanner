"""Read-only historical benchmark viewer; not a live prediction model."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import pandas as pd
from .frozen_direction_context import TFS, context, dominant, read_context_packet, session_closed
from .manual_reversal_dashboard import fetch_manual_map
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

def load_context_sources():
    now=datetime.now(UTC)
    source,historical=load_market()
    native={};native_at=None;market_fresh=False
    try:
        p=fetch_manual_map()
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
    st.subheader("RIZAN XAU · Frozen Direction R28.1")
    st.caption("Konteks prediksi candle berikutnya · read-only. Benchmark frozen dan prediksi teknikal sementara adalah dua hal berbeda.")
    @st.cache_data(ttl=30,show_spinner=False)
    def read_sources(slot):
        return load_context_sources()
    @st.fragment(run_every="60s")
    def panel():
        frames,reports,now=read_sources(int(datetime.now(UTC).timestamp()//30))
        side=dominant(reports)
        st.metric("Bias dominan · konteks aktual",side)
        st.caption("Diperiksa "+pd.Timestamp(now).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M:%S WIB")+" · update 60 detik")
        if session_closed(now):st.warning("Pasar XAU umumnya tutup akhir pekan. WAIT; arah terakhir tidak berlaku sebagai sinyal live.")
        elif side.startswith("WAIT"):st.info("Menunggu data segar atau keselarasan H1/H4/D1. W1 tidak boleh berlawanan jika segar.")
        st.caption("Skor 0–5 = jumlah bukti teknikal, bukan probabilitas. Prediksi frozen R28.1 asli belum terhubung; hipotesis teknikal ini belum diuji replay.")
        for tf in TFS:
            r=reports[tf]
            with st.container(border=True):
                st.markdown("**"+tf+" · prediksi close berikutnya**")
                a,b,c=st.columns(3)
                a.metric("Bias aktual",r["forecast"] if r["fresh"] else "WAIT")
                b.metric("BUY",f"{r['buy']}/5" if r["fresh"] and r["buy"] is not None else "—")
                c.metric("SELL",f"{r['sell']}/5" if r["fresh"] and r["sell"] is not None else "—")
                if r.get("closed_at"):
                    st.caption("Candle tertutup "+pd.Timestamp(r["closed_at"]).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M WIB")+" · "+r.get("source",""))
                if not r["fresh"] and r["last_bias"]:st.caption("Bias historis terakhir (bukan prediksi sekarang): "+r["last_bias"])
                st.caption(r["reason"])
                if r["checks"]:
                    with st.expander("Bukti teknikal "+tf):st.dataframe(r["checks"],hide_index=True)
        st.markdown("### Chart dan zona tunggu")
        tf=st.radio("Timeframe chart",list(TFS),horizontal=True,key="frozen_r281_chart_tf")
        bars=frames.get(tf);r=reports[tf]
        if bars is None or len(bars)<20:
            st.info("WAIT DATA · Data chart/level belum cukup.")
            return
        recent=bars.tail(20);lo=float(recent.low.min());hi=float(recent.high.max())
        if not hi>lo:return
        q1=lo+(hi-lo)*.25;q3=lo+(hi-lo)*.75
        chart=bars.tail(60).copy();chart["time"]=chart.index;chart["WIB"]=chart.index.tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M")
        value=float(chart.close.iloc[-1])
        st.metric("Close terakhir "+tf,f"{value:,.2f}")
        st.caption("Rentang 20 candle · kuartil bawah/atas, zona deskriptif, bukan zona yang sudah diuji.")
        selected=[]
        if not r["fresh"]:
            st.warning("Snapshot lama · chart historis; zona aktif disembunyikan.")
        elif r["forecast"]=="BUY" and lo<value and side=="BUY":
            st.metric("Buy the dip · area pantau",f"{lo:,.2f}–{q1:,.2f}")
            st.caption("Skenario bullish; tunggu konfirmasi reclaim. Batal jika close "+tf+" di bawah low rentang.")
            selected=[{"lo":lo,"hi":q1,"zone":"Buy the dip"}]
        elif r["forecast"]=="SELL" and hi>value and side=="SELL":
            st.metric("Sell on rebound · area pantau",f"{q3:,.2f}–{hi:,.2f}")
            st.caption("Skenario bearish; tunggu rejection. Batal jika close "+tf+" di atas high rentang.")
            selected=[{"lo":q3,"hi":hi,"zone":"Sell on rebound"}]
        else:st.info("WAIT · Belum ada arah atau level searah yang valid.")
        base=alt.Chart(chart).encode(x=alt.X("time:T",title="Candle close UTC"),tooltip=["WIB","open:Q","high:Q","low:Q","close:Q"])
        color=alt.condition("datum.close >= datum.open",alt.value("#149c78"),alt.value("#d65c5c"))
        pic=base.mark_rule().encode(y=alt.Y("low:Q",scale=alt.Scale(zero=False),title="XAUUSD"),y2="high:Q",color=color)+base.mark_bar(size=4).encode(y="open:Q",y2="close:Q",color=color)
        if selected:
            shades=pd.DataFrame([{**z,"start":chart.index.min(),"end":chart.index.max()} for z in selected])
            rect=alt.Chart(shades).mark_rect(opacity=.12).encode(x="start:T",x2="end:T",y=alt.Y("lo:Q",scale=alt.Scale(zero=False)),y2="hi:Q",color=alt.Color("zone:N",scale=alt.Scale(domain=["Buy the dip","Sell on rebound"],range=["#149c78","#d65c5c"]),legend=None))
            pic=rect+pic
        st.altair_chart(pic.properties(height=340),width="stretch")
        st.caption("Tidak ada izin entry/order; arah dominan bukan model probabilitas.")
    panel()
    lock=json.loads(LOCK.read_text())
    with st.expander("8 benchmark historis frozen R28.1",expanded=True):
        entries=lock["entries"]
        st.dataframe([{"TF":e["tf"],"Arah":e["side"],"Versi":e["version"],"Akurasi":f"{e['accuracy']:.2%}","n":e["n"]} for e in entries],hide_index=True)
        st.caption("Hasil berbeda kebijakan dan periode; bukan peluang BUY/SELL sekarang.")
        st.download_button("Unduh benchmark JSON",LOCK.read_text(),file_name=LOCK.name,mime="application/json")
        st.markdown("[Handover R27](https://github.com/rizanrizan93/Forex-scanner/blob/research/r91-early-warning-m1-20261121/research/RIZAN_DIRECTION_HANDOVER_R27.md) · [Replay R28.1](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44970328847)")
