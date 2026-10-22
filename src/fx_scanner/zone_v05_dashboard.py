"""V05 research card, independent of cBot and legacy reversal filters."""
from datetime import UTC,datetime
import base64
import json
import math
from functools import lru_cache
from .manual_reversal_dashboard import read_json,latest_commit,wib,BASE,BRANCH
from .zone_v05 import validate
PATH='/runtime/zone_v05_snapshot.json'


def decode_reference(raw,side):
    """URL references contain public zone geometry, never broker position state."""
    if not raw or len(raw)>2000:return None
    try:
        ref=json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        a=ref['source']
        if a['side']!=side or a['timeframe'] not in ('H1','H4'):return None
        if not all(isinstance(a[k],(int,float)) and math.isfinite(a[k]) for k in ('low','high')):return None
        if not 0<a['low']<a['high']:return None
        for value in (a['formed_at'],ref['saved_at']):datetime.fromisoformat(value)
        return ref
    except (ValueError,TypeError,KeyError,UnicodeError):return None


def save_reference(a):
    import streamlit as st
    source={k:a[k] for k in ('side','timeframe','low','high','formed_at')}
    ref=dict(source=source,saved_at=datetime.now(UTC).isoformat())
    st.query_params['ref_xau_'+a['side'].lower()]=base64.urlsafe_b64encode(json.dumps(ref).encode()).decode()


def clear_reference(side):
    import streamlit as st
    st.query_params.pop('ref_xau_'+side.lower(),None)


def render_references():
    import streamlit as st
    for side in ('BUY','SELL'):
        ref=decode_reference(st.query_params.get('ref_xau_'+side.lower()),side)
        if ref is None:continue
        a=ref['source'];buy=side=='BUY';distal=a['low'] if buy else a['high']
        st.markdown('#### 🔒 '+side+' · zona acuan terkunci')
        st.metric('Acuan tersimpan · '+a['timeframe'],f"{a['low']:,.2f}–{a['high']:,.2f}")
        st.caption('Terbentuk '+wib(a['formed_at'])+' · dikunci '+wib(ref['saved_at']))
        st.write(f"**Batas invalidasi tetap:** candle **{a['timeframe']} ditutup {'di bawah' if buy else 'di atas'} sekitar {distal:,.2f}**.")
        st.caption('Catatan manual, bukan sinyal ENTRY atau bukti posisi broker. Status valid/invalid zona tersimpan belum dipantau otomatis. SL posisi Anda tetap dikelola di cTrader.')
        st.caption('Tersimpan di tautan halaman ini: simpan tautan untuk membuka acuan yang sama setelah menutup browser. Zona pantauan terbaru di bawah dapat berganti tanpa mengubah acuan ini.')
        st.button('Lepaskan acuan '+side,key='release_ref_'+side,on_click=clear_reference,args=(side,))


def reference_button(a):
    import streamlit as st
    side=a['side'];locked=decode_reference(st.query_params.get('ref_xau_'+side.lower()),side)
    if locked:
        st.caption('Acuan '+side+' sudah terkunci di atas. Lepaskan dahulu jika ingin memilih zona lain.')
        return
    st.button('Kunci zona '+side+' sebagai acuan',key='lock_ref_'+side,on_click=save_reference,args=(a,))


@lru_cache(maxsize=2)
def _api_snapshot(bucket):
    """Minute-bounded fallback independent of cached raw URLs and branch refs."""
    meta=read_json('https://api.github.com/repos/rizanrizan93/Forex-scanner/contents'+PATH+'?ref='+BRANCH+'&rizan_minute='+str(bucket))
    if meta.get('encoding')!='base64':raise ValueError('Unsupported snapshot encoding')
    raw=base64.b64decode(meta['content'],validate=False)
    if len(raw)>900000:raise ValueError('Snapshot too large')
    return json.loads(raw)


def fetch():
    bucket=int(datetime.now(UTC).timestamp()//30)
    p=None
    try:
        p=validate(read_json(BASE+BRANCH+PATH+'?v05='+str(bucket)))
        age=(datetime.now(UTC)-datetime.fromisoformat(p.get('evaluated_close_at') or p['as_of'])).total_seconds()
        if p['fresh'] and age<=300 and 'watch_zones' in p:return p
    except (ValueError,OSError,KeyError,TypeError):pass
    try:
        alternate=validate(_api_snapshot(int(datetime.now(UTC).timestamp()//60)))
        if alternate['fresh'] or p is None:return alternate
        if p['fresh']:return p
        return max((p,alternate),key=lambda x:x.get('as_of',''))
    except (ValueError,OSError,KeyError,TypeError):
        if p is not None:return p
        raise ValueError('Snapshot unavailable')


def render_requirements(a,plan=None,observation=None):
    """Explain existing gates; observation is never promoted to an entry signal."""
    import streamlit as st
    buy=a['side']=='BUY';prox=a['high'] if buy else a['low'];distal=a['low'] if buy else a['high']
    tf=a['timeframe'];over='di atas' if buy else 'di bawah';broken='di bawah' if buy else 'di atas'
    st.write(f"**Zona invalid:** candle **{tf} ditutup {broken} batas zona sekitar {distal:,.2f}**.")
    st.caption('Wick melewati batas saja belum membatalkan struktur. Batas invalidasi zona berbeda dari SL transaksi.')
    values=plan if plan is not None else observation
    def status(key):
        if values is None:
            return 'Belum dinilai untuk entry'
        if values.get(key):
            return 'Teramati · ' + wib(values[key])
        issues = {
            'RIWAYAT_M1_BELUM_MENCAKUP_ZONA': 'M1 belum mencakup awal zona',
            'GAP_M1_SEBELUM_SENTUHAN': 'Gap M1 sebelum first touch',
            'GAP_M1_SAAT_MEMANTAU': 'Gap M1 belum terverifikasi',
            'RIWAYAT_M1_BELUM_LENGKAP': 'Riwayat M1 belum lengkap',
        }
        issue = issues.get(values.get('observation_status'))
        if issue:
            if key == 'first_touch_at' and values.get('observed_touch_at'):
                return 'Sentuhan terlihat · ' + wib(values['observed_touch_at']) + ' · first touch belum terbukti'
            return 'Belum dapat dipastikan · ' + issue
        return 'Menunggu'
    rows=[
        {'Syarat':'Zona terpilih engine EMA20 H1','Status':'Terpilih' if plan is not None else 'Belum menjadi kandidat ENTRY'},
        {'Syarat':f"Harga menguji zona {a['low']:,.2f}–{a['high']:,.2f}",'Status':status('first_touch_at')},
        {'Syarat':f"M15 {'bullish' if buy else 'bearish'} ditutup kembali {over} {prox:,.2f}",'Status':status('reclaim_m15_at')},
        {'Syarat':f"Sesudah reclaim M15: M5 {'bullish menembus high' if buy else 'bearish menembus low'} 3 candle M5 sebelumnya, close {over} {prox:,.2f}",'Status':status('confirmation_m5_at')},
    ]
    st.markdown('**Syarat konfirmasi:**')
    for row in rows:
        st.markdown('- '+row['Syarat']+' — **'+row['Status']+'**')
    if observation is not None:
        audit = observation.get('m1_audit') or {}
        if audit:
            st.caption('Audit M1 zona WATCH: ' + str(audit['m1_bars']) +
                       ' candle hingga titik pemeriksaan; ' +
                       str(audit['m1_missing_minutes']) + ' menit tanpa candle, ' +
                       str(audit['m5_excluded_missing_minutes']) +
                       ' menit dibuktikan tidak menyentuh zona oleh M5, ' +
                       str(audit['unverified_minutes']) + ' menit belum terverifikasi.')
            if audit.get('first_unverified_at'):
                st.caption('Gap pertama yang belum terbukti aman: ' +
                           wib(audit['first_unverified_at']) +
                           ' · awal zona: ' + wib(audit['required_from']) +
                           ' · M1 tersedia mulai: ' + wib(audit.get('first_m1_at')))
    st.caption('Konfirmasi teramati belum berarti semua pemeriksaan biaya, target, sesi, dan data lolos. Ikuti status serta alasan setup di atas.')
    if plan is None:
        st.caption('WATCH observasi: sentuhan/reclaim/BOS yang teramati di zona ini belum menjadikannya ENTRY V05. Engine harus memilih kandidat dan seluruh syarat entry harus lolos.')
        if values and values.get('observation_status')=='JENDELA_KONFIRMASI_SUDAH_LEWAT':st.warning('Jendela konfirmasi sudah lewat. Tanggal teramati merupakan riwayat, bukan entry baru.')


def render_snapshot(snapshot):
    import streamlit as st
    p=validate(snapshot)
    st.subheader('EMA V05 · perjalanan zona A → B')
    st.caption('A adalah zona sumber EMA20 H1; B adalah zona lawan yang dipilih sebagai tujuan. Setelah A → B selesai, C dan D menunggu setup baru. BUY/SELL tidak harus bergantian.')
    render_references()
    render_v05_details(p)


def render_v05_details(snapshot):
    import streamlit as st
    p=validate(snapshot)
    if not p['fresh']:
        st.caption('Candle terakhir: '+wib(p.get('evaluated_close_at'))+' · snapshot diterbitkan: '+wib(p.get('as_of')))
        st.warning('WAIT · data V05 belum lengkap atau terlambat. Entry dan level harga disembunyikan.');return
    st.caption('Evaluasi close M5: '+wib(p['evaluated_close_at'])+' · berikutnya '+wib(p.get('next_evaluation_at')))
    st.caption('ENTRY V05: first touch ≤24 jam; reclaim M15 → BOS M5 ≤120 menit setelah touch; entry referensi open M1 sesudah konfirmasi. Sesi 14.00–23.59 WIB; satu posisi referensi aktif.')
    st.caption('Target lawan harus tersedia dan belum tercapai/invalid; spread broker wajib tersedia; RR bersih ≥1,5; jarak SL ≥3× estimasi biaya; entry maksimal 0,75 ATR sumber dari batas dekat zona. Data M1 harus berurutan dan terbaru.')
    st.info('Konfirmasi M15 → M5 dapat menambah jeda beberapa hingga puluhan menit. Jika harga sudah terlalu jauh atau RR memburuk, setup dibatalkan. WATCH membantu persiapan lebih awal; aturan entry cepat belum diuji untuk menggantikan konfirmasi ini.')
    for row in p.get('decisions',[]):
        st.write('**'+row['side']+' · '+row['result']+'** — '+row['reason'].replace('_',' '))
    if not p.get('plans'):st.info('Belum ada setup ENTRY EMA V05. Menunggu kandidat zona A dan konfirmasi yang memenuhi syarat.')
    for x in p.get('plans',[]):
        a=x['source'];b=x.get('target')
        st.markdown('#### '+a['side']+' · '+x['state'])
        st.write(x['reason'].replace('_',' '))
        st.metric('Zona A · '+a['timeframe'],f"{a['low']:,.2f}–{a['high']:,.2f}")
        st.caption('Dibentuk '+wib(a['formed_at'])+' · zona dibekukan untuk setup ini')
        render_requirements(a,x)
        reference_button(a)
        if x.get('entry') is not None:st.metric('Entry referensi open M1',f"{x['entry']:,.2f}")
        if x.get('sl') is not None:st.metric('SL skenario',f"{x['sl']:,.2f}")
        if b:st.metric('Zona B · '+b['timeframe'],f"{b['low']:,.2f}–{b['high']:,.2f}")
        if x.get('tp') is not None:st.metric('TP sebelum zona B',f"{x['tp']:,.2f}")
        if x.get('planned_net_rr') is not None:st.caption(f"RR setelah proxy biaya: {x['planned_net_rr']:.2f}")
        for label,key in [('Sentuhan','first_touch_at'),('Reclaim M15','reclaim_m15_at'),('BOS M5','confirmation_m5_at')]:
            st.write(label+': '+wib(x.get(key)))
        st.caption('A → B adalah setup saat ini. B → C → D: WATCH bersyarat; arah berlawanan perlu zona dan konfirmasi baru. Tidak wajib bergantian BUY/SELL.')
    represented={x['source']['side'] for x in p.get('plans',[])}
    for a in p.get('watch_zones',[]):
        if a['side'] in represented:continue
        obs=p.get('watch_checks',{}).get(a['id'])
        st.markdown('#### '+a['side']+' · WATCH · belum kandidat ENTRY V05')
        st.metric('Zona pantauan · '+a['timeframe'],f"{a['low']:,.2f}–{a['high']:,.2f}")
        st.caption('Terbentuk '+wib(a['formed_at']))
        render_requirements(a,observation=obs)
        reference_button(a)
        if obs and obs.get('sl') is not None:
            st.metric('SL skenario observasi',f"{obs['sl']:,.2f}")
            st.caption('Batas distal zona ±0,2 ATR sumber. Ini skenario struktur, belum SL dari setup ENTRY V05 yang lolos.')
        for label,key in [('Sentuhan','first_touch_at'),('Reclaim M15','reclaim_m15_at'),('BOS M5','confirmation_m5_at')]:
            st.write(label+': '+(wib(obs.get(key)) if obs and obs.get(key) else 'Belum teramati / belum dapat dinilai'))


def _render():
    import streamlit as st
    load=st.cache_data(ttl=8,show_spinner=False)(fetch)
    try:render_snapshot(load())
    except Exception:
        st.subheader('EMA V05 · perjalanan zona A → B')
        render_references()
        st.warning('WAIT · snapshot V05 belum tersedia. Menunggu kolektor candle; tidak ada entry yang diterbitkan.')


def render_zone_v05():
    import streamlit as st
    st.fragment(run_every='10s')(_render)()
