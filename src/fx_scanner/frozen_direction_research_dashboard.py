"""Read-only historical benchmark viewer; not a live prediction model."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import json
import pandas as pd
from .frozen_direction_context import TFS, context, horizon_plan, next_candle_prediction, read_context_packet, session_closed, watch_zone
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
    st.subheader("RIZAN XAU · Prediksi Candle Berikutnya")
    st.caption("Prediksi close-ke-close H1 / H4 / D1 / W1, berbasis indikator teknikal READ-ONLY. Model frozen R28.1 belum berjalan sebagai prediktor live; tabel benchmark di bawah hanyalah hasil historis.")
    @st.cache_data(ttl=30,show_spinner=False)
    def read_sources(slot):
        return load_context_sources()
    @st.fragment(run_every="60s")
    def panel():
        frames,reports,now=read_sources(int(datetime.now(UTC).timestamp()//30))
        st.metric("Status pasar", "PASAR TUTUP" if session_closed(now) else "SESI PERDAGANGAN")
        st.caption("H1, H4, D1, W1 independen. Arah berbeda adalah konteks pullback/rebound potensial, bukan veto.")
        st.caption("Diperiksa "+pd.Timestamp(now).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M:%S WIB")+" · update 60 detik")
        if session_closed(now):st.warning("Pasar XAU umumnya tutup akhir pekan. WAIT; arah terakhir tidak berlaku sebagai sinyal live.")
        elif not any(r["fresh"] for r in reports.values()):st.info("Belum ada timeframe dengan data segar.")
        st.caption("Skor 0–5 = jumlah bukti teknikal, BUKAN probabilitas/akurasi. Hanya prediksi dengan data segar dan target candle yang belum berakhir dapat ditampilkan sebagai BUY/SELL; hipotesis teknikal ini belum diuji replay.")
        zones={tf:watch_zone(frames.get(tf),reports[tf]) for tf in TFS}
        for tf in TFS:
            r=reports[tf]
            zone=zones[tf]
            plan=horizon_plan(reports,tf)
            with st.container(border=True):
                st.markdown("**"+tf+" · arah close candle berikutnya**")
                prediction=next_candle_prediction(r,tf,now=now)
                st.metric("Prediksi "+tf+" ke depan",prediction["headline"])
                if prediction["target_at"]:
                    target=pd.Timestamp(prediction["target_at"]).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M WIB")
                    st.caption("Target close: "+target+" · arah dibandingkan close candle sebelumnya · hipotesis teknikal, bukan model frozen.")
                elif r["fresh"]:
                    st.caption("WAIT · indikator belum memberikan arah; target BUY/SELL tidak aktif.")
                else:
                    st.caption("WAIT DATA · belum ada candle tertutup yang valid dan cukup baru untuk memprediksi candle berikutnya.")
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
                    zc.metric(zone["label"]+" · "+zone["state"],f"{zone['low']:,.2f}–{zone['high']:,.2f}")
                    dc.metric("Jarak dari close "+tf,f"${zone['distance']:,.2f}")
                    st.caption(zone["position"]+" · close referensi "+f"{zone['reference_close']:,.2f}"+" · batas invalidasi "+f"{zone['invalidation']:,.2f}"+" (close "+tf+")")
                    st.caption("Zona kuartil rentang 20 candle; belum tervalidasi. "+("Tunggu konfirmasi lokal." if zone["active"] else "Historis saja; bukan area aktif."))
                else:
                    st.info("Zona "+tf+" belum tersedia: data kurang atau bias netral.")
                if r["checks"]:
                    with st.expander("Bukti teknikal "+tf):st.dataframe(r["checks"],hide_index=True)
        st.markdown("### Chart dan zona tunggu")
        tf=st.radio("Timeframe chart",list(TFS),horizontal=True,key="frozen_r281_chart_tf")
        bars=frames.get(tf);r=reports[tf];plan=horizon_plan(reports,tf)
        st.caption("Horizon acuan "+tf+" · "+plan["setup"]+" · timing "+str(plan["timing_tf"] or "lokal")+" "+str(plan["timing_side"] or "belum dievaluasi"))
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
        st.caption("Rentang 20 candle · kuartil bawah/atas, zona deskriptif, bukan zona yang sudah diuji.")
        selected=[]
        if zone is not None:
            st.metric(zone["label"]+" · "+zone["state"],f"{zone['low']:,.2f}–{zone['high']:,.2f}")
            st.caption("Batal jika close "+tf+(" di bawah " if zone["side"]=="BUY" else " di atas ")+f"{zone['invalidation']:,.2f}")
            if not zone["active"]:st.warning("Zona historis saja · tidak berlaku sebagai zona aktif.")
            selected=[{"lo":zone["low"],"hi":zone["high"],"zone":zone["label"]}]
        else:st.info("WAIT · Belum ada arah atau level yang dapat dihitung.")
        base=alt.Chart(chart).encode(x=alt.X("time:T",title="Candle close UTC"),tooltip=["WIB","open:Q","high:Q","low:Q","close:Q"])
        color=alt.condition("datum.close >= datum.open",alt.value("#149c78"),alt.value("#d65c5c"))
        pic=base.mark_rule().encode(y=alt.Y("low:Q",scale=alt.Scale(zero=False),title="XAUUSD"),y2="high:Q",color=color)+base.mark_bar(size=4).encode(y="open:Q",y2="close:Q",color=color)
        if selected:
            shades=pd.DataFrame([{**z,"start":chart.index.min(),"end":chart.index.max()} for z in selected])
            rect=alt.Chart(shades).mark_rect(opacity=.12 if zone["active"] else .06).encode(x="start:T",x2="end:T",y=alt.Y("lo:Q",scale=alt.Scale(zero=False)),y2="hi:Q",color=alt.Color("zone:N",scale=alt.Scale(domain=["Buy the dip","Sell on rebound"],range=["#149c78","#d65c5c"]),legend=None))
            pic=rect+pic
        st.altair_chart(pic.properties(height=340),width="stretch")
        st.caption("Tidak ada izin entry/order; arah setiap timeframe adalah hipotesis teknikal, bukan model probabilitas.")
    panel()
    lock=json.loads(LOCK.read_text())
    with st.expander("8 benchmark historis frozen R28.1",expanded=True):
        entries=lock["entries"]
        st.dataframe([{"TF":e["tf"],"Arah":e["side"],"Versi":e["version"],"Akurasi":f"{e['accuracy']:.2%}","n":e["n"]} for e in entries],hide_index=True)
        st.caption("Hasil berbeda kebijakan dan periode; bukan peluang BUY/SELL sekarang.")
        st.download_button("Unduh benchmark JSON",LOCK.read_text(),file_name=LOCK.name,mime="application/json")
        st.markdown("[Handover R27](https://github.com/rizanrizan93/Forex-scanner/blob/research/r91-early-warning-m1-20261121/research/RIZAN_DIRECTION_HANDOVER_R27.md) · [Replay R28.1](https://github.com/rizanrizan93/Forex-scanner/actions/runs/44970328847)")
