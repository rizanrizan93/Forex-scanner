"""Net-profit research status. No speculative TP/SL or execution authority."""
import json
from pathlib import Path

RESULT=Path(__file__).resolve().parents[2]/'calibration/major_reversal_results.json'


def render_major_reversal_dashboard():
    import streamlit as st
    st.subheader('XAU · reversal utama harian · expectancy setelah biaya')
    st.caption('Engine scanner terpisah; tidak memengaruhi cBots XAU/EUR.')
    try:result=json.loads(RESULT.read_text())
    except (OSError,ValueError):
        st.info('Riset reversal utama sedang berjalan: target 1,5–6 ATR, minimal 25% ADR20, reward/risk net ≥1,5. Pengujian re-entry channel dan sweep-confirm M5 dengan konteks H1/M15; kandidat dikunci sebelum pengujian Januari–September 2026.')
        st.caption('Peta lama hanya mengukur pantulan kecil 0,5 ATR. TP/SL contoh lama tidak menjadi rekomendasi reversal utama.')
        return
    st.caption('Status: '+result['status'])
    for candidate in result.get('selected_by_side',[]):
        cfg=candidate['config'];metrics=candidate.get('fresh_2026',{})
        st.markdown('**'+('BUY' if cfg['side']==1 else 'SELL')+' · '+('Lolos pengujian 2026' if candidate.get('qualified') else 'RESEARCH ONLY')+'**')
        st.json({'config':cfg,'test_2026':metrics})
    if not any(w.get('qualified') for w in result.get('selected_by_side',[])):
        st.warning('Belum ada konfigurasi yang terbukti lolos seluruh kriteria profit setelah biaya. Tidak menampilkan entry/TP/SL sebagai setup profitable.')
