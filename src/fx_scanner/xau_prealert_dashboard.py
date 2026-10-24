"""Display early research plans without importing execution components."""
from datetime import UTC, datetime
from .xau_prealerts import CONTRACT, view
from .manual_reversal_dashboard import wib


def render_prealerts(snapshot, *, now=None):
    import streamlit as st
    now = now or datetime.now(UTC)
    st.subheader('Aba-aba zona · TP harga $25')
    st.caption('Rencana ditampilkan sebelum sentuhan jika data tersedia tepat waktu. '
               'Level tetap sampai kedaluwarsa; sentuhan yang sudah lewat tidak menjadi entry baru.')
    group = snapshot.get('prealerts') or {}
    if group.get('contract') != CONTRACT:
        st.info('Aba-aba SL kecil belum diterbitkan kolektor. Status ENTRY V05 di detail bawah memakai konfirmasi lama.')
        return
    st.caption('Riset SL kecil · hasil historis masih eksploratif. Publikasi data sekitar 5 menit; '
               'refresh layar 10 detik tidak mempercepat sumber harga.')
    seen = st.session_state.setdefault('rizan_prealert_first_seen', {})
    shown = []
    for plan in group.get('plans', []):
        key = plan.get('id')
        if not key:
            continue
        first_seen = seen.setdefault(key, now.isoformat())
        shown.append(dict(plan, first_presented_at=first_seen))
    if len(seen) > 100:
        active = {p['id'] for p in shown}
        st.session_state['rizan_prealert_first_seen'] = {k:v for k,v in seen.items() if k in active}
    for side in ('BUY', 'SELL'):
        cards = [view(p, now=now, feed_fresh=snapshot.get('fresh', False))
                 for p in shown if p.get('side') == side]
        if not cards:
            st.info(side + (' · konfigurasi SELL belum lolos saringan riset; belum ada rencana entry.'
                           if side == 'SELL' else ' · belum ada zona yang memenuhi konfigurasi SL kecil.'))
            continue
        p = cards[0]
        labels = {'ABA_ABA':'ABA-ABA · rencana pending', 'MENUNGGU_SESI':'ABA-ABA · menunggu sesi',
                  'TERLEWAT':'TERLEWAT · jangan mengejar harga', 'TERSENTUH':'ZONA SUDAH TERSENTUH · bukan entry baru',
                  'KEDALUWARSA':'KEDALUWARSA', 'DATA_BELUM_CUKUP':'DATA HARGA PERLU DIPERBARUI',
                  'DATA_TIDAK_VALID':'DATA TIDAK VALID'}
        st.markdown('#### '+side+' · '+labels[p['state']])
        st.caption('Zona terbentuk '+wib(p.get('formed_at'))+' · rencana disusun '+wib(p.get('first_published_at'))+
                   ' · tampil pertama '+wib(p.get('first_presented_at')))
        if p['state'] in ('DATA_BELUM_CUKUP','DATA_TIDAK_VALID'):
            st.warning('Aba-aba harga disembunyikan sampai harga dan riwayat sentuhan dapat diperiksa kembali.')
            continue
        if p['state'] in ('TERLEWAT','TERSENTUH','KEDALUWARSA'):
            st.caption('Rencana historis · tidak ada entry baru. Sentuhan teramati '+wib(p.get('first_observed_touch_at')))
            continue
        st.metric('Zona rencana', f"{p['low']:,.2f}–{p['high']:,.2f}")
        st.metric('Entry rencana · '+side+' LIMIT', f"{p['entry']:,.2f}")
        c1, c2 = st.columns(2)
        c1.metric('SL · jarak $'+f"{p['sl_distance']:g}",f"{p['sl']:,.2f}")
        c2.metric('TP · jarak $25', f"{p['tp']:,.2f}")
        st.caption('Pending berlaku sampai '+wib(p.get('expires_at'))+' · harga terakhir '+wib(p.get('price_observed_at')))
        st.write('Periksa spread dan quote cTrader sebelum memasang pending. Sentuhan pada scanner bukan konfirmasi posisi broker.')
