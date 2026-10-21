"""V05 research card, independent of cBot and legacy reversal filters."""
from datetime import UTC,datetime
import json
from .manual_reversal_dashboard import read_json,latest_commit,wib,BASE,BRANCH
from .zone_v05 import validate
PATH='/runtime/zone_v05_snapshot.json'


def fetch():
    bucket=int(datetime.now(UTC).timestamp()//30)
    p=None
    for ref in (BRANCH,latest_commit(bucket//3)):
        try:
            p=validate(read_json(BASE+ref+PATH+'?v05='+str(bucket)))
            if p['fresh']:return p
        except (ValueError,OSError,KeyError,TypeError):pass
    if p is not None:return p
    raise ValueError('Snapshot unavailable')


def render_snapshot(snapshot):
    import streamlit as st
    p=validate(snapshot)
    st.subheader('V05 · Zona dinamis → konfirmasi → entry riset')
    st.caption('EMA20 H1 · reclaim M15 · BOS M5 · target lawan H1/H4. Kandidat riset; tidak mengirim order.')
    if not p['fresh']:
        st.warning('WAIT · data V05 belum lengkap atau terlambat. Entry dan level harga disembunyikan.');return
    st.caption('Evaluasi close M5: '+wib(p['evaluated_close_at'])+' · berikutnya '+wib(p.get('next_evaluation_at')))
    st.caption('Evaluasi setiap 5 menit, sekitar 1 menit setelah close agar open M1 referensi sudah tersedia. Tampilan mengecek setiap 30 detik; waktu pengambilan data dapat menambah jeda.')
    for row in p.get('decisions',[]):
        st.write('**'+row['side']+' · '+row['result']+'** — '+row['reason'].replace('_',' '))
    if not p.get('plans'):st.info('Tidak ada zona aktif yang memenuhi syarat awal. Menunggu close berikutnya.')
    for x in p.get('plans',[]):
        a=x['source'];b=x.get('target')
        st.markdown('#### '+a['side']+' · '+x['state'])
        st.write(x['reason'].replace('_',' '))
        st.metric('Zona A · '+a['timeframe'],f"{a['low']:,.2f}–{a['high']:,.2f}")
        st.caption('Dibentuk '+wib(a['formed_at'])+' · zona dibekukan untuk setup ini')
        if x.get('entry') is not None:st.metric('Entry referensi open M1',f"{x['entry']:,.2f}")
        if x.get('sl') is not None:st.metric('SL skenario',f"{x['sl']:,.2f}")
        if b:st.metric('Zona B · '+b['timeframe'],f"{b['low']:,.2f}–{b['high']:,.2f}")
        if x.get('tp') is not None:st.metric('TP sebelum zona B',f"{x['tp']:,.2f}")
        if x.get('planned_net_rr') is not None:st.caption(f"RR setelah proxy biaya: {x['planned_net_rr']:.2f}")
        for label,key in [('Sentuhan','first_touch_at'),('Reclaim M15','reclaim_m15_at'),('BOS M5','confirmation_m5_at')]:
            st.write(label+': '+wib(x.get(key)))
        st.caption('A → B adalah setup saat ini. B → C → D: WATCH bersyarat; arah berlawanan perlu zona dan konfirmasi baru. Tidak wajib bergantian BUY/SELL.')
    with st.expander('Evaluasi setup terakhir · bukan sinyal entry baru'):
        st.dataframe([{'Arah':x['source']['side'],'Status':x['state'],'Alasan':x['reason'],
            'Close M5 WIB':wib(x.get('confirmation_m5_at'))} for x in p.get('recent_events',[])],hide_index=True,width='stretch')
        for tf,at in p.get('timeframe_closed_at',{}).items():st.caption(tf+' close '+wib(at))
        st.download_button('Unduh evaluasi V05',json.dumps(p,indent=2),file_name='RIZAN_V05.json',mime='application/json',key='v05_download')
    st.caption('Kalibrasi 2019–2025: 216 transaksi, PF 1,34, biaya 2× PF 1,11. Q1 2026 hanya 6 transaksi; bukan holdout independen. Sesi V05 14:00–23:59 WIB. Feed native rolling belum diuji parity penuh dengan replay Dukascopy.')


def _render():
    import streamlit as st
    load=st.cache_data(ttl=25,show_spinner=False)(fetch)
    try:render_snapshot(load())
    except Exception:
        st.subheader('V05 · Zona dinamis')
        st.warning('WAIT · snapshot V05 belum tersedia. Menunggu kolektor candle; tidak ada entry yang diterbitkan.')


def render_zone_v05():
    import streamlit as st
    st.fragment(run_every='30s')(_render)()
