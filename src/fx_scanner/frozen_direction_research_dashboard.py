"""Read-only historical benchmark viewer; not a live prediction model."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import pandas as pd
from .frozen_direction_context import TFS, context, horizon_plan, read_context_packet, session_closed
from .manual_reversal_dashboard import fetch_manual_map
from .manual_r3_feed import fetch_market, read_public, validate_market, stamp, URL
from .manual_direction_map import historical_benchmarks, timeframe_guidance, r2_tactical, direction_board_rows
from .predictive_zone_to_zone import build_zone_paths
from .zone_v05_dashboard import fetch as fetch_v05
from .entry_direction_r2.dashboard import fetch_snapshot as fetch_r2

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
    st.subheader("RIZAN XAU · Arah Candle Berikutnya")
    st.caption("BUY/SELL indikatif per timeframe (close-ke-close) saat feed segar. Sumber: lima bukti teknikal; bukan output model terlatih R28.1 dan bukan instruksi order.")
    lock=json.loads(LOCK.read_text())
    marks=historical_benchmarks(lock)
    # The history and model-admission disclaimer belong in the audit at the end,
    # not above the actionable current-direction observation dashboard.
    @st.cache_data(ttl=30,show_spinner=False)
    def read_sources(slot):
        return load_context_sources()
    @st.cache_data(ttl=30,show_spinner=False)
    def read_manual_sources(slot):
        try:
            v05=fetch_v05()
        except (OSError,ValueError,TypeError,KeyError,TimeoutError,OverflowError):
            v05=None
        try:
            r2=fetch_r2()
        except (OSError,ValueError,TypeError,KeyError,TimeoutError,ImportError,OverflowError):
            r2=None
        return v05,r2

    @st.fragment(run_every="30s")
    def panel():
        frames,reports,now=read_sources(int(datetime.now(UTC).timestamp()//30))
        v05_snapshot,r2_snapshot=read_manual_sources(int(datetime.now(UTC).timestamp()//30))
        try:
            v05_paths=build_zone_paths(v05_snapshot,now=now) if v05_snapshot is not None else {}
        except (ValueError,TypeError,KeyError,OverflowError):
            v05_paths={}
        guides={tf:timeframe_guidance(tf,reports[tf],frames.get(tf),reports,now=now,v05_paths=v05_paths) for tf in TFS}
        zones={tf:guides[tf]["watch_area"] for tf in TFS}
        st.markdown("### Prediksi arah indikatif · candle berikutnya")
        summary=direction_board_rows(guides)
        # Display forecasts before historical metrics or unrelated entry engines.
        st.dataframe([{k:v for k,v in x.items() if k in ("TF","Arah","Target close (WIB)","Sumber")} for x in summary],
                     hide_index=True, width="stretch")
        st.caption("BUY berarti perkiraan close candle berikutnya lebih tinggi; SELL lebih rendah. Lima indikator ini belum memiliki akurasi replay R28.1. WAIT jika data kedaluwarsa, pasar tutup atau bukti netral.")
        st.caption("Diperiksa "+pd.Timestamp(now).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M:%S WIB")+" · pembaruan otomatis 30 detik")
        if session_closed(now):
            st.warning("Pasar XAU tutup; arah historis tidak boleh dibaca sebagai sinyal saat ini.")
        elif not any(r["fresh"] for r in reports.values()):
            st.info("Belum ada candle segar untuk prediksi BUY/SELL; tunggu feed broker.")
        tactical=r2_tactical(r2_snapshot,now=now) if r2_snapshot is not None else {"state":"WAIT"}
        if tactical["state"]=="TRIGGER_SELL":
            st.warning("R2: Pemicu SELL manual teramati; model R2 berbeda dari prediksi close-ke-close dan tidak mengesahkan order.")
            x,y=st.columns(2)
            x.metric("Acuan R2",f"{tactical['reference']:,.2f}")
            y.metric("Level pola R2",f"{tactical['level']:,.2f}")
            st.caption("Kedaluwarsa "+pd.Timestamp(tactical["expires"]).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M:%S WIB"))
        st.caption("Area tiap timeframe adalah zona observasi, bukan entry terkonfirmasi. Tunggu rejection/reclaim dan BOS M5.")
        for tf in TFS:
            r=reports[tf]
            guide=guides[tf]
            zone=zones[tf]
            plan=horizon_plan(reports,tf)
            with st.container(border=True):
                st.markdown("**"+tf+" · arah candle berikutnya & area tunggu**")
                st.metric("Prediksi arah "+tf+" berikutnya · indikatif",guide["technical"])
                st.caption("Dihitung dari 5 bukti teknikal candle tertutup. Bukan inferensi model R28.1 atau probabilitas 80%.")
                if guide["target_at"]:
                    target=pd.Timestamp(guide["target_at"]).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M WIB")
                    st.caption("Target close teknikal: "+target+" · dibandingkan close "+tf+" sebelumnya")
                elif r["fresh"]:
                    st.caption("WAIT · indikator teknikal belum memberi arah BUY/SELL.")
                else:
                    st.caption("WAIT DATA · tidak tersedia candle tertutup yang cukup segar untuk timeframe ini.")
                if r.get("closed_at"):
                    st.caption("Candle sumber terakhir: "+pd.Timestamp(r["closed_at"]).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M WIB")+" · "+r.get("source",""))
                with st.expander("Audit indikator "+tf+" · historis jika data kedaluwarsa"):
                    a,b,c=st.columns(3)
                    a.metric("Bias indikator terakhir",r["last_bias"] or "DATA KURANG")
                    b.metric("BUY · skor bukti",f"{r['buy']}/5" if r["buy"] is not None else "—")
                    c.metric("SELL · skor bukti",f"{r['sell']}/5" if r["sell"] is not None else "—")
                    st.caption("Bukti di atas bukan prediksi aktif ketika data stale/WAIT; skor bukan peluang atau win rate.")
                st.caption(r["reason"])
                if plan["side"]!="WAIT":
                    st.write("**"+plan["setup"]+" · "+tf+"**")
                    if plan["phase"]=="POTENTIAL_REBOUND":st.caption(plan["timing_tf"]+" BUY: potensi rebound menuju zona SELL "+tf+". Tunggu rejection.")
                    elif plan["phase"]=="POTENTIAL_PULLBACK":st.caption(plan["timing_tf"]+" SELL: potensi pullback menuju zona BUY "+tf+". Tunggu reclaim.")
                    elif plan["phase"]=="ALIGNED_CONTINUATION":st.caption(plan["timing_tf"]+" searah: potensi continuation; jangan mengejar harga.")
                    else:st.caption("Timing belum terkonfirmasi. Pantau struktur lokal; bukan sinyal entry.")
                if zone is not None:
                    zc,dc=st.columns(2)
                    zc.metric("AREA TUNGGU · "+zone["side"],f"{zone['low']:,.2f}–{zone['high']:,.2f}")
                    dc.metric("Jarak ke zona (USD/oz)",f"{zone['distance']:,.2f}")
                    st.caption(zone["source"]+" · "+zone["position"])
                    st.caption("Invalidasi struktur: CLOSE "+tf+(" di bawah " if zone["side"]=="BUY" else " di atas ")+f"{zone['invalidation']:,.2f}"+". Bukan penempatan SL otomatis.")
                    st.caption("Syarat timing: "+guide["confirmation"])
                    if guide["state"]=="WAIT_OPPOSING_HIGHER_TF":
                        st.warning("WAIT KONFLIK: timeframe lebih tinggi yang segar mengarah berlawanan. Jangan gunakan zona ini sebagai setup searah tren besar.")
                    else:
                        st.info("WATCH · Hanya referensi observasi. Butuh sentuhan, reclaim/rejection dan break struktur; tidak ada angka probabilitas pantulan yang tervalidasi.")
                else:
                    st.info("WAIT AREA "+tf+" · tidak ada zona pantau aktif dengan arah teknikal dan data valid.")
                if r["checks"]:
                    with st.expander("Bukti teknikal "+tf):st.dataframe(r["checks"],hide_index=True)
        st.markdown("### Chart dan zona tunggu")
        tf=st.radio("Timeframe chart",list(TFS),horizontal=True,key="frozen_r281_chart_tf")
        bars=frames.get(tf);r=reports[tf];plan=horizon_plan(reports,tf);guide=guides[tf]
        st.caption("Horizon teknikal "+tf+" · "+plan["setup"]+" · timing "+str(plan["timing_tf"] or "lokal")+" "+str(plan["timing_side"] or "belum dievaluasi")+" · bukan hasil inferensi frozen")
        if bars is None or len(bars)<20:
            st.info("WAIT DATA · Data chart/level belum cukup.")
            return
        zone=zones[tf]
        # Chart and summary must show the same sample and price levels.
        if r.get("closed_at"):
            bars=bars.loc[bars.index<=pd.Timestamp(r["closed_at"])]
        chart=bars.tail(60).copy();chart["time"]=chart.index;chart["WIB"]=chart.index.tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M")
        if chart.empty:return
        value=float(chart.close.iloc[-1])
        st.metric("Close terakhir "+tf,f"{value:,.2f}")
        st.caption("Chart candle tertutup. Area berasal dari V05 WATCH atau kuartil 20 candle; belum lolos forward test sebagai level entry.")
        selected=[]
        if zone is not None:
            st.metric("AREA TUNGGU · "+guide["state"],f"{zone['low']:,.2f}–{zone['high']:,.2f}")
            st.caption("Batal jika close "+tf+(" di bawah " if zone["side"]=="BUY" else " di atas ")+f"{zone['invalidation']:,.2f}")
            if guide["state"]!="WATCH_ONLY":st.warning("Zona hanya referensi dengan konflik atau verifikasi belum lengkap; jangan anggap setup aktif.")
            selected=[{"lo":zone["low"],"hi":zone["high"],"zone":"Buy the dip" if zone["side"]=="BUY" else "Sell on rebound"}]
        else:st.info("WAIT · Belum ada arah atau level yang dapat dihitung.")
        base=alt.Chart(chart).encode(x=alt.X("time:T",title="Candle close UTC"),tooltip=["WIB","open:Q","high:Q","low:Q","close:Q"])
        color=alt.condition("datum.close >= datum.open",alt.value("#149c78"),alt.value("#d65c5c"))
        pic=base.mark_rule().encode(y=alt.Y("low:Q",scale=alt.Scale(zero=False),title="XAUUSD"),y2="high:Q",color=color)+base.mark_bar(size=4).encode(y="open:Q",y2="close:Q",color=color)
        if selected:
            shades=pd.DataFrame([{**z,"start":chart.index.min(),"end":chart.index.max()} for z in selected])
            rect=alt.Chart(shades).mark_rect(opacity=.12 if guide["state"]=="WATCH_ONLY" else .06).encode(x="start:T",x2="end:T",y=alt.Y("lo:Q",scale=alt.Scale(zero=False)),y2="hi:Q",color=alt.Color("zone:N",scale=alt.Scale(domain=["Buy the dip","Sell on rebound"],range=["#149c78","#d65c5c"]),legend=None))
            pic=rect+pic
        st.altair_chart(pic.properties(height=340),width="stretch")
        st.caption("Tidak ada izin entry/order; arah setiap timeframe adalah hipotesis teknikal, bukan model probabilitas.")
    panel()
    with st.expander("R28.1 · status model asli & hasil replay historis",expanded=False):
        st.warning("Model R11–R28.1 belum diekspor dan diuji parity untuk inferensi broker terkini. Prediksi BUY/SELL di atas berasal dari lima indikator teknikal, BUKAN dari fitted R28.1.")
        entries=lock["entries"]
        st.dataframe([{"TF":e["tf"],"Arah":e["side"],"Versi":e["version"],"Akurasi":f"{e['accuracy']:.2%}","n":e["n"]} for e in entries],hide_index=True)
        st.caption("Kandidat historis memiliki periode dan kebijakan yang berbeda-beda. Angkanya bukan probabilitas prediksi yang muncul pada dashboard saat ini.")
        st.download_button("Unduh benchmark JSON",LOCK.read_text(),file_name=LOCK.name,mime="application/json")
        st.markdown("[Handover R27](https://github.com/rizanrizan93/Forex-scanner/blob/research/r91-early-warning-m1-20261121/research/RIZAN_DIRECTION_HANDOVER_R27.md) · [Replay R28.1](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44970328847)")
