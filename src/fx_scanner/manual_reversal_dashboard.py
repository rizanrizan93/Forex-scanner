"""Read-only manual reversal panel; no cBot state or execution imports."""
from datetime import UTC,datetime
from functools import lru_cache
import json,re
from urllib.request import Request,urlopen
from .manual_reversal_map import validate

BASE='https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/'
BRANCH='scanner-reversal-snapshots';PATH='/runtime/manual_reversal_snapshot.json'
PHASES={
 'MENUNGGU_HARGA':'Menunggu harga mendekati area',
 'MENUNGGU_RECLAIM_M15':'Menunggu rejection / reclaim M15',
 'MENUNGGU_BREAK_M5':'Reclaim M15 terlihat · menunggu break M5',
 'KONFIRMASI_STRUKTUR':'Konfirmasi M15 → M5 teramati',
 'KONFLIK_H1_H4':'Konflik demand dan supply H1/H4',
 'DATA_KONFIRMASI_BELUM_LENGKAP':'Candle konfirmasi belum lengkap / terlambat',
 'KONFIRMASI_LAMA':'Konfirmasi lama · tunggu pengujian ulang',
 'KONFIRMASI_BATAL':'Konfirmasi dibatalkan harga berikutnya',
 'RECLAIM_LAMA_TUNGGU_ULANG':'Reclaim lama · tunggu pengujian ulang',
 'GERAK_SUDAH_BERJALAN':'Harga sudah bergerak dari konfirmasi',
 'LEWATI_BATAS_SKENARIO':'Harga melewati batas skenario',
}

def read_json(url):
    req=Request(url,headers={'Cache-Control':'no-cache','User-Agent':'RIZAN-Manual-Reversal'})
    with urlopen(req,timeout=8) as response:raw=response.read(1_000_001)
    if len(raw)>1_000_000:raise ValueError('Snapshot terlalu besar')
    return json.loads(raw)

@lru_cache(maxsize=2)
def latest_commit(bucket):
    ref=read_json('https://api.github.com/repos/rizanrizan93/Forex-scanner/git/ref/heads/'+BRANCH)
    sha=str(ref.get('object',{}).get('sha',''))
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Referensi snapshot tidak valid')
    return sha

def fetch_manual_map():
    bucket=int(datetime.now(UTC).timestamp()//60)
    try:
        p=validate(read_json(BASE+BRANCH+PATH+"?rizan_minute="+str(bucket)))
        if p['fresh']:return p
    except (ValueError,OSError,KeyError,TypeError):p=None
    try:return validate(read_json(BASE+latest_commit(int(datetime.now(UTC).timestamp()//90))+PATH))
    except (ValueError,OSError,KeyError,TypeError):
        if p is not None:return p
        raise


def wib(value):
    import pandas as pd
    return pd.Timestamp(value).tz_convert('Asia/Jakarta').strftime('%d/%m %H:%M WIB') if value else '—'


def render_snapshot(snapshot):
    import streamlit as st
    p=validate(snapshot)
    if not p['fresh']:
        st.warning('Data reversal belum tersedia atau sudah kedaluwarsa. Level harga disembunyikan sampai snapshot baru tersedia.')
        st.caption('Candle terakhir: '+wib(p.get('price_observed_at')))
        st.caption('Snapshot diterbitkan: '+wib(p.get('as_of')))
        if p.get('age_seconds') is not None:
            st.caption(f"Usia candle {max(0,p['age_seconds'])/60:,.0f} menit · menunggu pembaruan kolektor.")
        return
    price=p['price'];st.caption(f"Harga snapshot {price:,.2f} · candle {wib(p['price_observed_at'])} · bukan bid/ask live")
    st.caption('Tampilan mengecek ulang setiap 60 detik; kolektor candle setiap 5 menit. Cocokkan harga dan candle terakhir dengan chart cTrader Anda.')
    plans={x['direction']:x for x in p.get('plans',[])}
    for side,col in zip(['BUY','SELL'],st.columns(2)):
        with col:
            st.markdown('#### '+('Kandidat demand · BUY' if side=='BUY' else 'Kandidat supply · SELL'))
            if side not in plans:
                st.info('Belum ada acuan H1/H4 yang aktif dan datanya cukup baru pada sisi harga ini.');continue
            plan=plans[side];z=plan['anchor'];phase=plan['phase'];label=PHASES.get(phase,'Menunggu pemeriksaan data')
            if phase=='KONFIRMASI_STRUKTUR':st.info(label+' · periksa ulang chart sebelum keputusan manual')
            elif phase in {'KONFLIK_H1_H4','LEWATI_BATAS_SKENARIO','KONFIRMASI_BATAL'}:st.warning(label)
            else:st.write('**'+label+'**')
            st.metric('Area acuan '+z['timeframe'],f"{z['low']:,.2f}–{z['high']:,.2f}")
            st.caption('Terbentuk '+wib(z['available_at'])+' · '+('belum retest pada TF asal' if z['touch_count']==0 else f"{z['touch_count']} episode retest TF asal"))
            st.write(f"Batas skenario: **{z['invalidation']:,.2f}**")
            st.caption(plan['invalidation_rule']+' Batas ini bukan SL order yang telah dipasang.')
            target=plan.get('target_reference')
            if target is None:st.write('Level lawan H1/H4 di depan harga: belum tersedia.')
            else:
                st.write(f"Level lawan H1/H4: **{target:,.2f}**")
                st.caption(f"Jarak dari harga snapshot: ${plan['target_distance_usd']:,.2f} per ounce. Referensi tujuan, bukan jaminan TP tercapai.")
            context=plan.get('context_h4')
            if context and context['zone_id']!=z['zone_id']:
                st.caption(f"Konteks H4: {context['low']:,.2f}–{context['high']:,.2f}")
            if z['overlap'] and not z['major_conflict']:st.caption('Ada irisan dengan zona mikro sisi lawan; arah mikro masih perlu dikonfirmasi.')
            if plan.get('rejection_m15_at'):st.write('Reclaim M15: '+wib(plan['rejection_m15_at']))
            if plan.get('confirmation_m5_at'):
                st.write('Break M5: '+wib(plan['confirmation_m5_at']))
                st.caption(f"Close konfirmasi {plan['confirmation_reference']:,.2f}; bukan harga entry saat ini.")
            for tf in ['M15','M5']:
                refs=[x for x in plan['refinements'] if x['timeframe']==tf]
                if refs:st.caption(tf+' refinement: '+', '.join(f"{x['low']:,.2f}–{x['high']:,.2f}" for x in refs[:2]))
    st.caption('H1 adalah acuan terdekat, H4 konteks lebih besar; keduanya bukan label probabilitas. M15 memvalidasi reaksi, M5 memeriksa perubahan struktur lokal setelah M15 selesai.')
    with st.expander('Peta semua timeframe dan usia data',expanded=False):
        rows=[{'TF':z['timeframe'],'Arah':z['direction'],'Bawah':round(z['low'],2),'Atas':round(z['high'],2),
            'Batas skenario':round(z['invalidation'],2),'Posisi':z['position'],'Sentuhan TF':z['touch_count'],
            'BOS saat pembentukan':z['structural_bos'],'Konflik H1/H4':z['major_conflict'],'Terbentuk WIB':wib(z['available_at'])}
            for z in p.get('zones',[])]
        st.dataframe(rows,hide_index=True,width='stretch')
        for tf,at in p.get('timeframe_closed_at',{}).items():st.caption(tf+' · close '+wib(at)+' · '+('cukup baru' if p.get('timeframe_fresh',{}).get(tf) else 'belum lengkap / terlambat'))
        st.download_button('Unduh peta manual JSON',json.dumps(p,indent=2),file_name='RIZAN_XAU_Manual_Reversal.json',mime='application/json',key='manual_reversal_json')
    st.caption('Pemetaan struktural untuk keputusan manual. Probabilitas reversal dan keuntungan belum terkalibrasi; jarak gerak $10–$100 bukan target yang dijanjikan.')


def _render():
    import streamlit as st
    st.subheader('Titik reversal · acuan manual XAU')
    st.caption('Peta H4/H1 → reaksi M15 → konfirmasi M5 · terpisah dari strategi dan order cBot')
    load=st.cache_data(ttl=60,show_spinner=False)(fetch_manual_map)
    if st.button('Perbarui tampilan',key='manual_reversal_refresh'):
        load.clear()
        latest_commit.cache_clear()
    try:render_snapshot(load())
    except Exception:
        # A failed map must not abort the other dashboard tabs or expose credentials.
        st.warning('Peta manual belum dapat diperbarui. Level harga tidak ditampilkan; periksa kembali setelah pengambilan candle berikutnya.')


def render_manual_reversal_dashboard():
    import streamlit as st
    st.fragment(run_every='60s')(_render)()
