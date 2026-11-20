"""Independent R6 read-only entry-area panel, no cTrader order interface."""
from __future__ import annotations
from datetime import UTC, datetime
import json
from .fed_r6_manual_entry_areas import evaluate_areas
from .manual_r3_feed import fetch_market
from .fed_r61_operational_macro_direction import assess_market_direction
from .pre_news_transport import fetch_pre_news_snapshot


def _fmt(value):
    return "—" if value is None else f"{float(value):,.2f}"


def _wib(value):
    if not value:
        return "—"
    import pandas as pd
    return pd.Timestamp(value).tz_convert("Asia/Jakarta").strftime("%d/%m %H:%M:%S WIB")


def render_view(source=None, macro_snapshot=None, *, now=None):
    import streamlit as st
    now = now or datetime.now(UTC)
    st.subheader("Fed R6 · Peta Area Entry XAUUSD")
    st.caption(
        "SMC/ICT research · swing M5 terkonfirmasi 2 kiri + 2 kanan, "
        "retest zona, close M1 reclaim, H1/H4 dan bias Fed. "
        "Zona aktual dihitung dari data cTrader hanya bila segar."
    )
    st.info(
        "Mode keputusan **manual / read-only**. Replay FOMC 2019–2026 "
        "belum membuktikan akurasi entry 80% untuk BUY dan SELL. "
        "Tidak ada limit order, market order, atau perubahan Frozen V1."
    )
    market_context=assess_market_direction(macro_snapshot,now=now)
    if source is None:
        report = {
            "status":"WAIT","reason":"FEED_XAU_UNAVAILABLE",
            "macro_direction":"WAIT","macro_reason":"NO_VERIFIED_R4_REALTIME_FEED",
            "bias_h1":"UNKNOWN","bias_h4":"UNKNOWN",
            "price":None,"atr_m5":None,"quote_at":None,
            "last_closed_m1":None,"zones":[],
            "entry_allowed":False,"authority_to_send_orders":False,
            "market_context":market_context,
        }
    else:
        report = evaluate_areas(
            source["frame"],now=now,bid=source.get("bid"),ask=source.get("ask"),
            quote_at=source.get("quote_as_of"),
            news_events=source.get("news_events"),
            # No live OIS1Y + intraday TIPS10Y + SP500 + DXY R4
            # first-ingestion record is wired. Never invent it from FRED
            # daily or the historical retrospective FOMC replay.
            macro=None,market_context=market_context,
        )
    a,b,c,d = st.columns(4)
    a.metric("Bias pasar XAU",market_context["direction"])
    st.caption(
        "Kekuatan: "+market_context["strength"]+
        " · Fed R4 asli: "+report["macro_direction"]+
        " · sumber makro: "+_wib(market_context.get("source_observed_at"))
    )
    b.metric("Harga referensi",_fmt(report["price"]))
    c.metric("Struktur H1 / H4",report["bias_h1"]+" / "+report["bias_h4"])
    d.metric("ATR M5",_fmt(report["atr_m5"]))
    st.caption(
        "M1 terakhir selesai: "+_wib(report.get("last_closed_m1"))+
        " · quote bid/ask: "+_wib(report.get("quote_at"))+
        " · status: "+str(report["status"])
    )
    if market_context["direction"] in ("BUY","SELL"):
        st.info(
            "Arah "+market_context["direction"]+" untuk **pantauan manual**, "
            "berdasarkan yield Treasury harian dan konfirmasi DXY/yield "
            "intraday bila segar. Status "+market_context["strength"]+
            ". Ini bukan perintah entry atau hasil FOMC R4."
        )
    else:
        st.warning(
            "BIAS PASAR WAIT · "+market_context["reason"].replace("_"," ")+
            ". Data dolar/yield mungkin tidak lengkap atau saling bertentangan."
        )
    with st.expander("Audit arah pasar · sumber, timestamp dan pembatasan",expanded=False):
        cols=[]
        for name,v in market_context.get("daily_yields",{}).items():
            cols.append({"Indikator":name,
                         "Nilai":v.get("yield_pct"),
                         "Perubahan":v.get("daily_delta_bps"),
                         "Sumber":v.get("provider"),
                         "Waktu WIB":_wib(v.get("observed_at")),
                         "Segar":v.get("valid_official_daily")})
        dxy=market_context.get("dxy",{})
        cols.append({"Indikator":"DXY (proksi)",
                     "Nilai":dxy.get("current"),
                     "Perubahan":dxy.get("change_pct"),
                     "Sumber":dxy.get("source"),
                     "Waktu WIB":_wib(dxy.get("observed_at")),
                     "Segar":dxy.get("fresh")})
        intra=market_context.get("intraday_yield",{})
        cols.append({"Indikator":"Treasury intraday",
                     "Nilai":intra.get("futures_price"),
                     "Perubahan":intra.get("pressure"),
                     "Sumber":intra.get("basis"),
                     "Waktu WIB":_wib(intra.get("observed_at")),
                     "Segar":intra.get("available_for_direction")})
        st.dataframe(cols,hide_index=True,width="stretch")
        st.caption(
            "Treasury resmi harian bukan intraday. ZN futures hanya proksi "
            "tekanan yield. DXY Yahoo bukan ICE resmi. Kualitas engine asal: "+
            market_context["quality_state"]+" / "+market_context["quality_screened_bias"]+
            ". BUY/SELL belum terkalibrasi sebagai probabilitas menang."
        )

    if report["macro_direction"]=="WAIT":
        st.warning(
            "MACRO WAIT · sumber intraday R4 (OIS 1Y, real yield TIPS, "
            "S&P 500 dan DXY dengan timestamp) belum terhubung/terverifikasi. "
            "Seluruh titik di bawah adalah **area pantauan**, bukan izin entry."
        )
    if not report["zones"]:
        st.warning(
            "Belum ada area R6 yang dapat dipublikasikan dari M5 segar. "
            "Alasan: "+str(report["reason"]).replace("_"," ")+". "
            "Harga, SL dan TP tidak dibuat dari data lama."
        )
    else:
        st.markdown("#### Titik pantauan BUY dan SELL")
        st.caption(
            "Entry referensi = tepi dalam pita retest, **bukan harga fill**. "
            "Konfirmasi perlu sentuhan zona lalu close M1 kembali melampaui "
            "garis trigger. SL dan TP berikut adalah skenario geometris, "
            "bukan order atau target profit tervalidasi."
        )
        for side,column in zip(("BUY","SELL"),st.columns(2)):
            with column:
                rows=[z for z in report["zones"] if z["side"]==side]
                st.markdown("**"+side+" · "+(
                    "buy the dip" if side=="BUY" else "sell on rebound")+"**")
                if not rows:
                    st.caption("Tidak ada swing M5 terkonfirmasi yang layak dipantau di sisi ini.")
                for idx,z in enumerate(rows,1):
                    with st.container(border=True):
                        state=("FRESH · belum retest" if z["fresh_first_touch"]
                               else "RETESTED · bukan fresh")
                        st.markdown("**Area "+str(idx)+" · "+state+"**")
                        st.metric("Zona "+side,_fmt(z["low"])+" – "+_fmt(z["high"]))
                        st.caption(
                            "Pivot "+_wib(z["formed_at"])+
                            " · konfirmasi M5 "+_wib(z["confirmed_at"])+
                            " · jarak "+str(z["atr_distance"])+" ATR dari harga"
                        )
                        e,sl=st.columns(2)
                        e.metric("Entry pantau",_fmt(z["entry_reference"]))
                        sl.metric("Invalidasi / SL skenario",_fmt(z["sl_scenario"]))
                        t1,t2=st.columns(2)
                        t1.metric("TP1 skenario · 1,5R",_fmt(z["tp1_scenario"]))
                        t2.metric("TP2 skenario · 2R",_fmt(z["tp2_scenario"]))
                        st.caption(
                            "Trigger close M1 "+("di atas " if side=="BUY" else "di bawah ")+
                            _fmt(z["trigger_line"])+" sesudah sentuh zona · "
                            "swing lawan "+_fmt(z["opposing_swing"])+
                            " · ruang "+(_fmt(z["room_rr"])+"R" if z["room_rr"] is not None else "belum valid")
                        )
                        st.caption(
                            "Konfirmasi M1: "+("teramati" if z["trigger_confirmed"] else "belum")+
                            " · macro alignment: "+z["macro_alignment"]+
                            " · bias pasar: "+z["market_context_alignment"]
                        )
                        with st.expander("Checklist syarat · "+side+" "+str(idx), expanded=False):
                            st.dataframe(
                                [{"Syarat":k.replace("_"," "),
                                  "Status":"✅" if passed else "○ Menunggu"}
                                 for k,passed in z["checks"].items()],
                                hide_index=True,width="stretch"
                            )
                        if z["entry_eligible"]:
                            st.info("Semua syarat analitik teramati. Tetap keputusan manual, bukan izin order.")
                        else:
                            st.caption("WAIT · masih ada syarat yang belum terpenuhi; jangan mengejar harga.")
        with st.expander("Grafik zona R6 · M1 terakhir",expanded=False):
            import altair as alt
            import pandas as pd
            d=source["frame"].tail(180).copy()
            d=d.reset_index().rename(columns={"timestamp":"time","index":"time"})
            if "time" not in d.columns:
                d=d.rename(columns={d.columns[0]:"time"})
            d["time"]=pd.to_datetime(d["time"],utc=True)
            d["time"]=d["time"]+pd.Timedelta(minutes=1)
            chart=alt.Chart(d).mark_line(color="#8da9c5").encode(
                x=alt.X("time:T",title="Waktu (UTC)"),y=alt.Y(
                    "close:Q",scale=alt.Scale(zero=False),title="XAUUSD"))
            for z in report["zones"]:
                level=(float(z["low"])+float(z["high"]))/2
                color="#46ccb9" if z["side"]=="BUY" else "#e98a8d"
                chart+=alt.Chart(pd.DataFrame({"level":[level]})).mark_rule(
                    color=color,strokeDash=[5,3]).encode(y="level:Q")
            st.altair_chart(chart.properties(height=300),width="stretch")
        st.download_button(
            "Unduh audit level & checklist R6 (JSON)",
            json.dumps(report,indent=2,default=str),
            file_name="RIZAN_XAU_R6_Area_Entry_READONLY.json",
            mime="application/json",key="r6_manual_area_export"
        )
    st.caption(
        "Tidak ada prediksi 80% yang sudah diverifikasi. Data FOMC ex-post "
        "tidak boleh diperlakukan sebagai sinyal LIVE. "
        "R6 tidak mengontrol order cBot, posisi, bridge, atau ukuran lot."
    )


def render_fed_r6_manual_areas():
    import streamlit as st
    @st.cache_data(ttl=8,show_spinner=False)
    def load(slot):
        return fetch_market()
    @st.fragment(run_every="15s")
    def panel():
        now=datetime.now(UTC)
        try:
            source=load(int(now.timestamp()//8))
        except (OSError,ValueError,TypeError,KeyError,TimeoutError):
            source=None
        render_view(source,now=now)
    panel()
