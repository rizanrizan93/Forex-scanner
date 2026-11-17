"""Independent mobile-friendly Range Reclaim R3 manual indicator panel."""
from datetime import UTC,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
from .manual_range_reclaim_r3 import evaluate_snapshot,context,levels,map_values
from .manual_r3_feed import fetch_market
WIB=ZoneInfo('Asia/Jakarta')
STATUS={'WAIT_DATA':'MENUNGGU DATA','WAIT_CHECKLIST':'MENUNGGU SYARAT','WAIT_SESSION':'DI LUAR SESI',
        'WAIT_NEWS':'JENDELA BERITA','WAIT_REGIME':'TUNGGU KONDISI RANGE','WATCH_ZONE':'PANTAU ZONA',
        'PREPARE_BUY':'BERSIAP BUY','PREPARE_SELL':'BERSIAP SELL','TRIGGER_BUY':'PEMICU BUY',
        'TRIGGER_SELL':'PEMICU SELL','EXPIRED_TIME':'WAKTU ENTRY HABIS','EXPIRED_PRICE':'HARGA SUDAH LEWAT'}

def _wib(v):
    try:return pd.Timestamp(v).tz_convert('Asia/Jakarta').strftime('%d/%m %H:%M:%S WIB')
    except (TypeError,ValueError):return '—'

def render_view(source=None,error=None,*,now=None):
    import streamlit as st
    now=now or datetime.now(UTC)
    st.subheader('Indikator Manual R3 · Range Reclaim')
    st.caption('XAUUSD · zona BUY dan SELL · pita Keltner M15 + kondisi H1 + pemicu M1')
    st.caption('Zona pantau belum memiliki peluang pantul 80% yang tervalidasi. Tunggu syarat dan pemicu; hasil riset zona dinilai terpisah dari strategi R3 yang sudah diuji.')
    if source is None:
        st.info('MENUNGGU DATA · riwayat M1, harga bid/ask dan kalender sedang diperbarui.')
        st.caption('Zona dan aturan strategi tetap tersedia di bawah; belum ada pemicu entry yang terverifikasi.')
        report={'status':'WAIT_DATA','checks':[],'plan':None}
    else:
        report=evaluate_snapshot(source['frame'],now=now,bid=source['bid'],ask=source['ask'],
              quote_as_of=source['quote_as_of'],news_events=source['news_events'],memory=st.session_state.get('_manual_r3_memory'))
        st.session_state['_manual_r3_memory']=report['memory']
        a,b,c=st.columns(3)
        a.metric('Status',STATUS.get(report['status'],report['status']))
        b.metric('Bias H1',report.get('bias','—'))
        c.metric('ADX14 H1',f"{report['h1_adx']:.1f}" if 'h1_adx' in report else '—')
        st.write(report.get('reason',''))
        st.caption('Candle M1 selesai '+_wib(report.get('last_closed_m1_utc'))+' · quote '+_wib(source.get('quote_as_of')))
        if report.get('zone_buy'):
            cols=st.columns(2)
            for col,key,label in [(cols[0],'zone_buy','Zona pantau BUY'),(cols[1],'zone_sell','Zona pantau SELL')]:
                z=report[key];col.metric(label,f"{z['low']:,.2f}–{z['high']:,.2f}")
                col.caption(f"Garis reclaim M1: {z['trigger_line']:,.2f}")
            d=source['frame'];ctx=context(d);upper,lower,_=levels(2,2,d,ctx)
            chart=d.tail(160).copy();chart.index+=pd.Timedelta(minutes=1)
            chart['upper']=map_values(upper,chart.index.asi8);chart['lower']=map_values(lower,chart.index.asi8)
            chart['time']=chart.index;chart['Waktu WIB']=chart.index.tz_convert('Asia/Jakarta').strftime('%d/%m %H:%M')
            import altair as alt
            base=alt.Chart(chart).encode(x=alt.X('time:T',title='Candle M1 selesai'),tooltip=['Waktu WIB','open:Q','high:Q','low:Q','close:Q'])
            color=alt.condition('datum.close >= datum.open',alt.value('#16a085'),alt.value('#d96c65'))
            pic=base.mark_rule().encode(y=alt.Y('low:Q',scale=alt.Scale(zero=False),title='XAUUSD'),y2='high:Q',color=color)
            pic+=base.mark_bar(size=4).encode(y='open:Q',y2='close:Q',color=color)
            for key in ['upper','lower']:pic+=base.mark_line(color='#5c90bb').encode(y=key+':Q')
            st.altair_chart(pic.properties(height=340),width='stretch')
        if report.get('checks'):
            st.markdown('**Checklist entry**')
            st.caption(f"{report['checklist_passed']}/{report['checklist_total']} syarat · kelengkapan checklist, bukan probabilitas menang")
            st.dataframe([{'Syarat':r['label'],'Status':'✅ Terpenuhi' if r['pass'] else '○ Menunggu','Rincian':r['value']} for r in report['checks']],hide_index=True,width='stretch')
        plan=report.get('plan')
        if plan:
            st.success(plan['side']+' · pemicu M1 selesai; entry tetap diputuskan manual')
            cols=st.columns(3)
            for col,title,key in zip(cols,['Entry referensi','SL','TP'],['entry_reference','sl','tp']):col.metric(title,f"{plan[key]:,.2f}")
            st.caption('Jendela entry sampai '+_wib(report['valid_until_utc'])+' · garis dan SL/TP terkunci untuk pemicu ini.')
            if report.get('alert_new'):st.toast(plan['side']+' · pemicu R3 baru')
        if report.get('status','').startswith('EXPIRED'):st.warning('Lewati entry ini. Tunggu setup baru.')
    with st.expander('Aturan strategi dan hasil replay',expanded=source is None):
        st.write('Senin–Rabu 14.00–00.00 WIB. ADX14 H1 <20 saat zona disentuh; arah mengikuti slope EMA20 H1 terhadap tiga candle sebelumnya.')
        st.write('BUY: sentuh pita bawah EMA20 M15 −2 ATR14 lalu close M1 kembali di atas garis. SELL: sentuh pita atas +2 ATR14 lalu close M1 kembali di bawah garis.')
        st.write('Reclaim maksimal lima candle M1; entry maksimal 60 detik dan jarak satu ATR M5 dari garis pemicu. SL tiga ATR M5, minimum dua spread; TP tiga kali jarak SL. Time exit empat jam atau 00.00 WIB.')
        st.write('Hindari ±30 menit CPI/PPI/NFP dan ±60 menit FOMC. Cek posisi sendiri: satu posisi, maksimal dua entry per hari; risiko model 0,5%.')
        st.dataframe([{'Periode':'2019–2024','Transaksi':249,'PF net-R':1.186},{'Periode':'2025','Transaksi':29,'PF net-R':1.519},{'Periode':'Gabungan','Transaksi':278,'PF net-R':1.220}],hide_index=True,width='stretch')
        st.caption('Eksperimental · 2019 merugi; stress biaya 1,5× + delay satu menit pada 2025 menghasilkan PF 0,94. Replay OHLC M1 dengan biaya sintetis; bukan pengujian tick FP Markets. Periode telah diamati dalam riset sebelumnya.')
    package=Path(__file__).resolve().parents[2]/'cbot_indicators/ManualRangeR3/releases/RizanManualRangeReclaimR3.algo'
    if package.exists():st.download_button('Unduh indikator cTrader (.algo)',package.read_bytes(),file_name=package.name,mime='application/octet-stream')
    st.caption('Custom indicator cTrader berjalan di Windows/Mac. Dari Android gunakan halaman ForexScanner ini.')


def render_manual_r3():
    import streamlit as st
    @st.cache_data(ttl=5,show_spinner=False)
    def load(slot):return fetch_market()
    @st.fragment(run_every='10s')
    def panel():
        try:source=load(int(datetime.now(UTC).timestamp()//5))
        except (OSError,ValueError,TypeError,KeyError,TimeoutError):source=None
        render_view(source,now=datetime.now(UTC))
    panel()
