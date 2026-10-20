"""Read-only manual reversal panel; no cBot state or execution imports."""
from datetime import UTC,datetime
from functools import lru_cache
import json,re
from urllib.request import Request,urlopen
from .manual_reversal_map import validate
from .manual_reversal_orderflow import summarize_plan_liquidity

BASE='https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/'
BRANCH='scanner-reversal-snapshots';PATH='/runtime/manual_reversal_snapshot.json'
PHASES={
 'MENUNGGU_HARGA':'Menunggu harga mendekati area',
 'MENUNGGU_RECLAIM_M15':'Menunggu rejection / reclaim M15',
 'MENUNGGU_BREAK_M5':'Reclaim M15 terlihat · menunggu break M5',
 'KONFIRMASI_STRUKTUR':'Konfirmasi M15 → M5 teramati',
 'KONFLIK_H1_H4':'Konflik demand dan supply H1/H4',
 'KONFLIK_STRUKTUR_H1_H2_H4':'Zona BUY/SELL H1/H2/H4 bertumpang tindih',
 'DATA_KONFIRMASI_BELUM_LENGKAP':'Candle konfirmasi belum lengkap / terlambat',
 'KONFIRMASI_LAMA':'Konfirmasi lama · tunggu pengujian ulang',
 'KONFIRMASI_BATAL':'Konfirmasi dibatalkan harga berikutnya',
 'RECLAIM_LAMA_TUNGGU_ULANG':'Reclaim lama · tunggu pengujian ulang',
 'GERAK_SUDAH_BERJALAN':'Harga sudah bergerak dari konfirmasi',
 'LEWATI_BATAS_SKENARIO':'Harga melewati batas skenario',
 'TEMBUS_SEMENTARA_TUNGGU_TF_ASAL':'Tembus sementara · tunggu penutupan candle asal dan reclaim M15',
 'ZONA_MELEMAH_TUNGGU_BASIS_BARU':'Zona sudah melemah · menunggu basis baru, bukan entry reversal',
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


def fetch_manual_orderflow():
    """Optional independent Bookmap/CME/crypto or broker DOM research sidecar.

    No collector is installed by this UI change. Missing files mean NO_DATA,
    not a synthetic Bookmap observation.
    """
    bucket=int(datetime.now(UTC).timestamp()//60)
    return read_json(BASE+BRANCH+'/runtime/manual_reversal_orderflow_snapshot.json?research_minute='+str(bucket))


def wib(value):
    import pandas as pd
    return pd.Timestamp(value).tz_convert('Asia/Jakarta').strftime('%d/%m %H:%M WIB') if value else '—'


def render_snapshot(snapshot, orderflow_sidecar=None):
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
                st.info('Belum ada acuan H1/H2/H4 yang aktif dan datanya cukup baru pada sisi harga ini.');continue
            plan=plans[side];z=plan['anchor'];phase=plan['phase'];label=PHASES.get(phase,'Menunggu pemeriksaan data')
            if phase=='KONFIRMASI_STRUKTUR':st.info(label+' · periksa ulang chart sebelum keputusan manual')
            elif phase in {'KONFLIK_H1_H4','KONFLIK_STRUKTUR_H1_H2_H4','LEWATI_BATAS_SKENARIO','KONFIRMASI_BATAL','TEMBUS_SEMENTARA_TUNGGU_TF_ASAL','ZONA_MELEMAH_TUNGGU_BASIS_BARU'}:st.warning(label)
            else:st.write('**'+label+'**')
            st.metric('Area acuan '+z['timeframe'],f"{z['low']:,.2f}–{z['high']:,.2f}")
            liquidity=summarize_plan_liquidity(
                plan, orderflow_sidecar, symbol=p.get('symbol','XAUUSD'))
            state=liquidity['state']
            source=liquidity.get('source') or 'belum ada feed'
            age_at=liquidity.get('evidence_at')
            ordinal=liquidity.get('support_index')
            ordinal_note=(' · indeks ordinal '+str(ordinal)+' (bukan probabilitas)' if ordinal is not None else '')
            st.caption('RLFE order flow [RISET]: '+state+
                       ' · '+source+ordinal_note+
                       ' · '+str(liquidity.get('reason'))+
                       (' · data '+wib(age_at) if age_at else '')+
                       ' · tidak mengubah WATCH/WAIT atau izin order')
            candidate=plan.get('candidate_a') or {}
            if candidate.get('model')=='CANDIDATE_A_TP1R_WATCH':
                state=candidate.get('state','WAIT')
                st.markdown('##### Kandidat A · TP 1R · riset manual')
                if state=='WATCH':
                    st.info('WATCH — filter D1 countertrend, first touch ≤12 jam, reclaim M15 dan BOS M5 ≤30 menit terpenuhi. **Ini bukan izin order.**')
                    st.caption('Level berikut adalah referensi dari close M5, bukan harga bid/ask fill broker.')
                    c1,c2,c3=st.columns(3)
                    c1.metric('M5 referensi',f"{candidate['entry_reference']:,.2f}")
                    c2.metric('SL skenario',f"{candidate['sl_reference']:,.2f}")
                    c3.metric('TP 1R skenario',f"{candidate['tp_1r_reference']:,.2f}")
                else:
                    st.caption('Kandidat A: WAIT · '+str(candidate.get('reason','DATA_TIDAK_TERSEDIA')).replace('_',' '))
                if candidate.get('first_touch_at'):
                    st.caption('First touch '+wib(candidate['first_touch_at'])+
                               ' · usia zona saat touch '+str(candidate.get('zone_age_at_first_touch_minutes'))+' menit')
                if candidate.get('d1_closed_at'):
                    st.caption('D1 EMA20/50 ('+str(candidate.get('d1_bias'))+
                               ') · candle selesai '+wib(candidate['d1_closed_at'])+
                               ' · EMA20 '+str(candidate.get('ema20'))+
                               ' / EMA50 '+str(candidate.get('ema50')))
                if candidate.get('confirmation_lag_minutes') is not None:
                    st.caption('Touch → close M5 '+str(candidate['confirmation_lag_minutes'])+' menit · batas 30 menit')
                st.caption('PF R satu-posisi TP1R historis ≈1,163 (2019–Mar 2026), bootstrap 95% 0,934–1,433. Belum terbukti edge live; tidak terhubung ke cBot.')
            st.caption('Terbentuk '+wib(z['available_at'])+' · '+('belum ada retest teramati' if z['touch_count']==0 else f"{z['touch_count']} episode retest teramati")
                       +' · sumber hitung '+str(z.get('touch_count_source') or 'SOURCE_TF'))
            if z.get('touch_count',0)==2:
                st.warning('Sudah 2 episode retest; zona ini bukan fresh. Konfirmasi M15/M5 diperlukan dan risiko breakdown meningkat.')
            if z.get('risk_state') == 'PENDING_PARENT_CLOSE':
                st.warning('Batas skenario ditembus sebelum penutupan candle timeframe asal; zona dikarantina sampai konfirmasi/reclaim.')
            elif z.get('lifecycle') == 'DEGRADED':
                st.warning('Zona sudah diuji berulang kali; perlakukan sebagai zona melemah, bukan fresh demand/supply.')
            st.write(f"Batas skenario: **{z['invalidation']:,.2f}**")
            if z['timeframe']=='H2':
                st.caption('H2 dipilih bila beririsan H1 searah, belum DEGRADED, dan tidak lebih jauh dari anchor H1 terdekat.')
            st.caption(plan['invalidation_rule']+' Batas ini bukan SL order yang telah dipasang.')
            target=plan.get('target_reference')
            if target is None:st.write('Level lawan H1/H2/H4 di depan harga: belum tersedia.')
            else:
                st.write(f"Level lawan H1/H2/H4: **{target:,.2f}**")
                st.caption(f"Jarak dari harga snapshot: ${plan['target_distance_usd']:,.2f} per ounce. Referensi tujuan, bukan jaminan TP tercapai.")
            context=plan.get('context_h4')
            if context and context['zone_id']!=z['zone_id']:
                st.caption(f"Konteks H4: {context['low']:,.2f}–{context['high']:,.2f}")
            for tf, ctx in (plan.get('contexts_htf') or {}).items():
                if tf == 'H4' or not ctx:
                    continue
                st.caption(f"Konteks {tf} {ctx['direction']}: {ctx['low']:,.2f}–{ctx['high']:,.2f} · bukan trigger entry")
            next_zones=sorted(
                (q for q in p.get('zones',[]) if q['direction']==side and
                 q['timeframe'] in {'H1','H2','H4'} and q['zone_id']!=z['zone_id'] and
                 q.get('eligible') and q.get('distance',0)>z.get('distance',0)),
                key=lambda q:q.get('distance',float('inf')))
            if next_zones:
                nxt=next_zones[0]
                st.caption(f"Zona berikutnya {nxt['timeframe']}: {nxt['low']:,.2f}–{nxt['high']:,.2f} · status {nxt.get('lifecycle','UNKNOWN')}; bukan target otomatis.")
            if z['overlap'] and not z['major_conflict']:st.caption('Ada irisan dengan zona mikro sisi lawan; arah mikro masih perlu dikonfirmasi.')
            if plan.get('rejection_m15_at'):st.write('Reclaim M15: '+wib(plan['rejection_m15_at']))
            if plan.get('confirmation_m5_at'):
                st.write('Break M5: '+wib(plan['confirmation_m5_at']))
                st.caption(f"Close konfirmasi {plan['confirmation_reference']:,.2f}; bukan harga entry saat ini.")
            for tf in ['M15','M5']:
                refs=[x for x in plan['refinements'] if x['timeframe']==tf]
                if refs:st.caption(tf+' refinement: '+', '.join(f"{x['low']:,.2f}–{x['high']:,.2f}" for x in refs[:2]))
    st.caption('Acuan H1/H2/H4 + WATCH Kandidat A: D1 EMA20/50 selesai dan countertrend, first touch ≤12 jam, reclaim M15 dan break M5 ≤30 menit dari first touch. H12/D1/W1 tetap konteks, bukan sinyal order.')
    with st.expander('Peta semua timeframe (H1/H2/H4/H12/D1/W1/M15/M5) dan usia data',expanded=False):
        rows=[{'TF':z['timeframe'],'Arah':z['direction'],'Bawah':round(z['low'],2),'Atas':round(z['high'],2),
            'Batas skenario':round(z['invalidation'],2),'Posisi':z['position'],'Lifecycle':z.get('lifecycle'),'Risiko break':z.get('risk_state'),
            'Sentuhan':z['touch_count'],'Sumber sentuhan':z.get('touch_count_source'),
            'BOS saat pembentukan':z['structural_bos'],'Konflik H1/H4':z['major_conflict'],'Terbentuk WIB':wib(z['available_at'])}
            for z in p.get('zones',[])]
        st.dataframe(rows,hide_index=True,width='stretch')
        for tf,at in p.get('timeframe_closed_at',{}).items():st.caption(tf+' · close '+wib(at)+' · '+('cukup baru' if p.get('timeframe_fresh',{}).get(tf) else 'belum lengkap / terlambat'))
        st.download_button('Unduh peta manual JSON',json.dumps(p,indent=2),file_name='RIZAN_XAU_Manual_Reversal.json',mime='application/json',key='manual_reversal_json')
    with st.expander('Audit PF historis — jangan disamakan dengan peluang reversal', expanded=False):
        st.caption('2019–Maret 2026 · Dukascopy BID M1 turunan tick, bukan tick native bid/ask FP Markets. Replay entry setelah reclaim M15 + break M5, TP 1,5R, stop distal, estimasi spread/komisi/slippage dan reopening gap.')
        st.dataframe([
            {'Zona': 'Gabungan H1/H2/H4', 'PF 2019–23': 0.842, 'PF 2024–25': 0.937, 'PF 2026 Q1': 1.489},
            {'Zona': 'H2 saja', 'PF 2019–23': 0.831, 'PF 2024–25': 0.941, 'PF 2026 Q1': 1.720},
        ], hide_index=True, width='stretch')
        st.warning('PF baseline train/validasi masih di bawah 1. Periode 2026 Q1 pendek; PF satu posisi gabungan saat itu hanya sekitar 1,03. Zona adalah referensi struktur, bukan sinyal yang edge trading-nya telah terbukti.')
        st.caption('PF berasal dari ledger kandidat terpisah, bukan order/portfolio live. Pencarian 6.242 filter memiliki risiko overfitting. Belum ada probabilitas yang terkalibrasi.')
        st.markdown('[Metodologi audit dan batas pengujian](https://github.com/rizanrizan93/Forex-scanner/blob/main/docs/research/manual_xau_confirmed_reversal_pf_2019_2026.md)')
    st.caption('Pemetaan struktural untuk keputusan manual. Probabilitas reversal dan keuntungan belum terkalibrasi; jarak gerak $10–$100 bukan target yang dijanjikan.')


def _render():
    import streamlit as st
    st.subheader('Titik reversal · acuan manual XAU')
    st.caption('H1/H2 anchor · H4/H12/D1/W1 konteks · M15 reclaim · M5 refinement · sepenuhnya terpisah dari order cBot')
    load=st.cache_data(ttl=60,show_spinner=False)(fetch_manual_map)
    if st.button('Perbarui tampilan',key='manual_reversal_refresh'):
        load.clear()
        latest_commit.cache_clear()
    try:
        try:
            sidecar=st.cache_data(ttl=60,show_spinner=False)(fetch_manual_orderflow)()
        except (ValueError,OSError,KeyError,TypeError):
            sidecar=None
        render_snapshot(load(), orderflow_sidecar=sidecar)
    except Exception:
        # A failed map must not abort the other dashboard tabs or expose credentials.
        st.warning('Peta manual belum dapat diperbarui. Level harga tidak ditampilkan; periksa kembali setelah pengambilan candle berikutnya.')


def render_manual_reversal_dashboard():
    import streamlit as st
    st.fragment(run_every='60s')(_render)()
