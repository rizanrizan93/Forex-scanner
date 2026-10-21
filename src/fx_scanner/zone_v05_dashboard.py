"""V05 research card, independent of cBot and legacy reversal filters."""
from datetime import UTC,datetime
from .manual_reversal_dashboard import read_json,latest_commit,wib,BASE,BRANCH
from .zone_v05 import validate
PATH='/runtime/zone_v05_snapshot.json'


def fetch():
    bucket=int(datetime.now(UTC).timestamp()//30)
    p=None
    try:
        p=validate(read_json(BASE+BRANCH+PATH+'?v05='+str(bucket)))
        age=(datetime.now(UTC)-datetime.fromisoformat(p.get('evaluated_close_at') or p['as_of'])).total_seconds()
        if p['fresh'] and age<=300:return p
    except (ValueError,OSError,KeyError,TypeError):pass
    try:
        return validate(read_json(BASE+latest_commit(bucket//3)+PATH))
    except (ValueError,OSError,KeyError,TypeError):
        if p is not None:return p
        raise ValueError('Snapshot unavailable')


def render_snapshot(snapshot):
    import streamlit as st
    p=validate(snapshot)
    st.subheader('Zona dinamis XAUUSD')
    if not p['fresh']:
        st.warning('WAIT · data V05 belum lengkap atau terlambat. Entry dan level harga disembunyikan.');return
    st.caption('Evaluasi close M5: '+wib(p['evaluated_close_at'])+' · berikutnya '+wib(p.get('next_evaluation_at')))
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


def _render():
    import streamlit as st
    load=st.cache_data(ttl=8,show_spinner=False)(fetch)
    try:render_snapshot(load())
    except Exception:
        st.subheader('Zona dinamis XAUUSD')
        st.warning('WAIT · snapshot V05 belum tersedia. Menunggu kolektor candle; tidak ada entry yang diterbitkan.')


def render_zone_v05():
    import streamlit as st
    st.fragment(run_every='10s')(_render)()
