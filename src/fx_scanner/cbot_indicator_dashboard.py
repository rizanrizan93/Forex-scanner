"""XAU indicator charts and a session-local manual trailing scenario."""
from datetime import UTC,datetime
from .cbot_manual import stamp,fresh
from .cbot_indicator import number,seed,advance

def render(c,p,*,now=None):
    import streamlit as st
    now=now or datetime.now(UTC);f=c.get('indicator')
    st.markdown('#### Indikator XAU · aturan entry cBot')
    if not p.get('fresh') or not isinstance(f,dict):
        st.info('Indikator menunggu data baru dari monitor. Belum ada aba-aba yang dapat diverifikasi.');return
    if (f.get('execution_authority') is not False or f.get('execution_influence') is not False or
        not fresh(f.get('at_utc'),now,360) or stamp(f.get('at_utc'))!=stamp(c.get('bar_at'))):
        st.warning('Data indikator belum valid atau terlambat.');return
    if not f.get('warm'):st.info('Pemanasan indikator belum mencapai 200 candle H1.');return
    hb,mb=f.get('h1_bias'),f.get('m15_bias');labels={1:'BUY',-1:'SELL',0:'NETRAL'}
    session=now.weekday()<5 and 12<=now.hour<17
    buy=f.get('buy_prior_eligible') and hb==1 and mb==1
    sell=number(f.get('sell_trigger_estimate')) and hb==-1 and mb==-1
    if not session:st.info('DI LUAR SESI · sinyal asli XAU 19:00–00:00 WIB, Senin–Jumat.')
    elif buy:st.info('ABA-ABA BUY · syarat candle sebelumnya tersedia; tunggu close M5 bullish di atas batas channel dan bias akhir tetap BUY.')
    elif sell:st.info('ABA-ABA SELL · sweep sudah terjadi; tunggu close M5 bearish melewati level konfirmasi sebelum setup habis.')
    else:st.info('MENUNGGU POLA · belum ada persiapan lengkap menurut aturan cBot.')
    st.caption('Bias H1 '+labels.get(hb,'—')+' · M15 '+labels.get(mb,'—')+' · aba-aba belum merupakan entry.')
    cols=st.columns(2)
    if number(f.get('buy_trigger_next')):cols[0].metric('BUY · batas close M5 berikutnya',f"{f['buy_trigger_next']:,.2f}")
    if number(f.get('sell_trigger_estimate')):
        cols[1].metric('SELL · estimasi konfirmasi',f"{f['sell_trigger_estimate']:,.2f}")
        from .cbot_manual_dashboard import wib
        st.caption('Setup SELL berakhir '+wib(f.get('sell_setup_expires'))+'. Estimasi berubah mengikuti ATR candle konfirmasi.')
    elif number(f.get('sell_sweep_next')):cols[1].metric('SELL · high untuk dipantau',f"{f['sell_sweep_next']:,.2f}")
    history=c.get('indicator_history') or []
    if history:
        import pandas as pd
        import altair as alt
        d=pd.DataFrame(history)
        if all(k in d for k in ['at_utc','open','high','low','close','signal_side']):
            d['time']=pd.to_datetime(d.at_utc,utc=True);d['Waktu WIB']=d.time.dt.tz_convert('Asia/Jakarta').dt.strftime('%d/%m %H:%M')
            base=alt.Chart(d).encode(x=alt.X('time:T',title='Waktu candle selesai'),tooltip=['Waktu WIB','open:Q','high:Q','low:Q','close:Q'])
            color=alt.condition('datum.close >= datum.open',alt.value('#22c55e'),alt.value('#ef4444'))
            chart=base.mark_rule().encode(y=alt.Y('low:Q',scale=alt.Scale(zero=False),title='XAUUSD'),y2='high:Q',color=color)
            chart+=base.mark_bar(size=4).encode(y='open:Q',y2='close:Q',color=color)
            for key,color in [('buy_trigger_next','#60a5fa'),('sell_trigger_estimate','#f59e0b')]:
                if key in d:chart+=base.mark_line(strokeDash=[4,4]).encode(y=alt.Y(key+':Q'),color=alt.value(color))
            chart+=base.transform_filter(alt.datum.signal_side!=0).mark_point(filled=True,size=90).encode(
                y='close:Q',shape=alt.condition('datum.signal_side == 1',alt.value('triangle-up'),alt.value('triangle-down')),
                color=alt.condition('datum.signal_side == 1',alt.value('#22c55e'),alt.value('#ef4444')))
            st.altair_chart(chart.properties(height=300),width='stretch')
            st.caption('Panah historis = konfirmasi teknis, belum memeriksa macro, news atau penerimaan order. Garis putus-putus adalah ambang indikator, bukan zona entry tetap.')
    mode=st.radio('Exit untuk trading manual',['Trailing manual','Acuan exit asli cBot'],key='cbot_indicator_exit',horizontal=True)
    if mode=='Acuan exit asli cBot':
        st.caption('SL awal: maksimum dari $0,50, 2,4 ATR M5, dan jarak anchor struktural. Target asli 5,5R; hold asli maksimal 8 jam. Tidak ada trailing pada aturan asli.');return
    st.caption('Skenario trailing tanpa TP tetap: aktif setelah +1R, jarak 1R. Stop hanya diperketat setelah M1 selesai. Nilai bawaan ini belum diuji sebagai strategi profitabel.')
    key='rizan_xau_manual_trailing'
    q=c.get('indicator_quote') or {};bid=q.get('BID') or {};ask=q.get('ASK') or {}
    quote_ok=all(number(v.get('price')) and fresh(v.get('at'),now,15) for v in [bid,ask]) and ask.get('price',0)>=bid.get('price',float('inf'))
    default=float(c.get('entry') or f.get('close') or 1.)
    initial=float(c.get('sl') or max(.01,default-2.4*(f.get('atr') or 1.)))
    with st.expander('Pantau trailing dari entry dan SL manual Anda'):
        st.caption('Isi harga posisi Anda. Tombol ini hanya membuat skenario di dashboard; SL broker harus Anda ubah sendiri. Pemantauan mulai sekarang, bukan replay sejak order lama.')
        with st.form('cbot_indicator_manual_form'):
            side=st.selectbox('Arah posisi',['BUY','SELL'])
            entry=st.number_input('Harga entry posisi',min_value=.01,value=default,step=.1,format='%.2f')
            stop=st.number_input('SL awal posisi',min_value=.01,value=initial,step=.1,format='%.2f')
            clicked=st.form_submit_button('Mulai skenario trailing',disabled=not quote_ok)
        if clicked:
            try:st.session_state[key]=seed(1 if side=='BUY' else -1,entry,stop,now.isoformat(),ask['price']-bid['price'])
            except ValueError as e:st.error(str(e))
    if key in st.session_state:
        try:
            s=advance(st.session_state[key],c.get('indicator_m1') or [],as_of=p.get('market_observed_at'),now=now)
            st.session_state[key]=s
            label='DATA TERPUTUS' if s['coverage_gap'] else 'STOP TERAMATI' if s['stopped'] else 'TRAIL AKTIF' if s['active'] else 'SL AWAL · MENUNGGU +1R'
            st.metric('Skenario trailing · '+label,f"{s['stop']:,.2f}")
            if s['stopped']:st.caption(f"Exit skenario {s['exit']:,.2f}; ini bukan konfirmasi exit broker.")
            st.caption('Spread SELL diasumsikan tetap sebesar spread saat mulai; ASK historis intramenit tidak tersedia. Menit entry yang belum lengkap dilewati. Skenario hilang jika sesi browser direset.')
        except ValueError as e:st.warning(str(e))
        if st.button('Hapus skenario trailing'):del st.session_state[key];st.rerun()
