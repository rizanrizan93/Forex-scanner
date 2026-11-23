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

def candidate_rows(lock):
    """Display all eight archived candidate outcomes without implying live inference."""
    by_key={(e.get("tf"),e.get("side")):e for e in lock.get("entries",[])}
    out=[]
    for tf in TFS:
        for side in ("BUY","SELL"):
            e=by_key.get((tf,side))
            if e is None:
                continue
            out.append({
                "TF":tf, "Kandidat":side, "Versi riset":e["version"],
                "Akurasi historis":f'{e["accuracy"]:.2%}',
                "Benar / sampel":f'{e["correct"]}/{e["n"]}',
                "Status":"BENCHMARK · BELUM LIVE",
                "Bukti replay":e.get("run_url",""),
            })
    return out

def candidate_summary(lock):
    """Historical performance beside each TF, never used to choose today's direction."""
    by_key={(e.get("tf"),e.get("side")):e for e in lock.get("entries",[])}
    def label(tf,side):
        e=by_key.get((tf,side))
        return f'{e["accuracy"]:.2%} · {e["version"]}' if e else "—"
    return {tf:{"BUY":label(tf,"BUY"),"SELL":label(tf,"SELL")} for tf in TFS}

def setup_watch_label(row):
    """Only active, unexpired research model snapshots can show a directional watch."""
    if row.get("state")!="RECONSTRUCTED_SHADOW":
        return "TUNGGU"
    return {"BUY":"PANTAU SETUP BUY","SELL":"PANTAU SETUP SELL"}.get(row.get("direction"),"TUNGGU")

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
    st.subheader("RIZAN XAU · Direction Multitimeframe R1–R28.1")
    st.caption("Panel arah untuk mencari setup manual: hanya snapshot model R28.1 yang masih valid memberi bias BUY/SELL. Delapan hasil R1–R28.1 di bawah adalah benchmark historis, bukan delapan sinyal live.")
    lock=json.loads(LOCK.read_text())
    candidates=candidate_rows(lock)
    summary=candidate_summary(lock)

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
        st.markdown("### Arah model sekarang · H1/H4/D1/W1")
        st.dataframe([
            {"TF":tf,
             "Arah R28.1":shadow[tf]["direction"],
             "Panduan setup":setup_watch_label(shadow[tf]),
             "Target close (WIB)":wib(shadow[tf]["target"]),
             "Diterbitkan (WIB)":wib(shadow[tf]["issued"]),
             "BUY terbaik (historis)":summary[tf]["BUY"],
             "SELL terbaik (historis)":summary[tf]["SELL"],
             "Status":("RESEARCH SHADOW" if shadow[tf]["state"]=="RECONSTRUCTED_SHADOW"
                       else "WAIT MODEL" if shadow[tf]["state"]=="MODEL_ABSTAIN" else "WAIT DATA"),
             "Keterangan":reason_text(shadow[tf]["reason"])}
            for tf in TFS],hide_index=True,width="stretch")
        st.caption("PANTAU SETUP BUY/SELL adalah bias arah candle berikutnya dari model riset (shadow), bukan instruksi entry. WAIT = jangan menyimpulkan arah dari angka akurasi historis.")
        st.markdown("### Semua 8 kandidat terbaik yang dibekukan · R1–R28.1")
        st.dataframe(candidates,hide_index=True,width="stretch",
                     column_config={"Bukti replay":st.column_config.LinkColumn("Bukti replay",display_text="GitHub Actions")})
        st.caption("Akurasi per sisi berasal dari sampel, periode, dan kebijakan yang berbeda; tidak boleh dirata-rata atau digabung sebagai confidence live. H1/H4 SELL R11 memiliki estimasi net P&L negatif; W1 BUY R27 hanya n=48. Tidak ada validasi forward independen.")
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
    with st.expander("Audit R1–R28.1 · arsip dan catatan riset",expanded=False):
        st.dataframe([{"TF":e["tf"],"Arah":e["side"],"Versi":e["version"],
                       "Akurasi":f"{e['accuracy']:.2%}","Benar/n":f"{e['correct']}/{e['n']}",
                       "Catatan":e.get("notes","")} for e in lock["entries"]],hide_index=True)
        st.caption("Hasil historis tidak digunakan sebagai probabilitas keberhasilan order saat ini. Untuk sinyal individual kedelapan kandidat diperlukan implementasi dan forward validation masing-masing model.")
        st.download_button("Unduh benchmark JSON",LOCK.read_text(),file_name=LOCK.name,mime="application/json")
