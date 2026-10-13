"""Scanner-only major reversal results; rejected research cannot emit a setup."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RESULT=ROOT/'calibration/major_reversal_results.json'
DIAGNOSTICS=ROOT/'calibration/major_reversal_diagnostics.json'


def render_major_reversal_dashboard():
    import streamlit as st
    st.subheader('XAU · riset reversal utama harian')
    st.caption('Engine scanner terpisah; tidak memengaruhi cBots XAU/EUR.')
    try:
        result=json.loads(RESULT.read_text())
    except (OSError,ValueError):
        st.info('Hasil riset reversal utama belum tersedia.')
        return
    cols=st.columns(3)
    cols[0].metric('Kombinasi parameter',format(result.get('configurations_evaluated',0),',').replace(',','.'))
    cols[1].metric('Replay historis','2016–2025')
    qualified=[c for c in result.get('selected_by_side',[]) if c.get('qualified')]
    cols[2].metric('Konfigurasi lolos',len(qualified))
    st.caption('Status: '+result.get('status','UNKNOWN'))
    if not qualified:
        st.warning('Belum ditemukan konfigurasi reversal utama yang lolos syarat profit setelah biaya dan kestabilan antarperiode. Belum ada zona entry, TP, SL, atau jam terbaik yang dipromosikan dari riset ini.')
        st.write('Target yang diuji: 1,5–6 ATR H1, minimal 25% ADR20; reward/risk net minimal 1,5. Angka ini adalah rentang penelitian, bukan rekomendasi trading.')
        try:diagnostics=json.loads(DIAGNOSTICS.read_text())
        except (OSError,ValueError):diagnostics={}
        gates=diagnostics.get('cumulative_gates',[])
        if gates:
            with st.expander('Mengapa konfigurasi ditolak'):
                st.table([{'Syarat kumulatif':g['gate'],'Kombinasi tersisa':g['remaining_tuples']} for g in gates])
                st.caption('Kombinasi parameter dapat menghasilkan keputusan yang sama; bukan 10 juta strategi independen.')
        st.caption('Tidak ada kandidat yang dikunci, sehingga belum ada hasil trading kandidat untuk pengujian Januari–September 2026.')
    else:
        for candidate in qualified:
            cfg=candidate['config']
            st.markdown('**'+('BUY' if cfg['side']==1 else 'SELL')+' · Lolos pengujian 2026**')
            st.json({'config':cfg,'test_2026':candidate.get('fresh_2026',{})})
    st.caption('Spread/slippage historis dimodelkan; hasil bukan return akun atau backtest cBot.')
