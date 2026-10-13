"""Daily-anchor research display. No trading authority."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RESULT=ROOT/'calibration/daily_reversal_results.json'


def render_daily_reversal_dashboard():
    import streamlit as st
    st.subheader('XAU · reversal utama harian · sweep dan reclaim')
    st.caption('Penelitian scanner terpisah. Strategy/execution cBots XAU/EUR tidak berubah.')
    try:result=json.loads(RESULT.read_text())
    except (OSError,ValueError):
        st.info('Replay 2016–2025 sedang berjalan untuk 10 juta kombinasi baru: high/low D1, sesi UTC00–06/06–12, dan range H4. Belum ada konfigurasi baru yang dipromosikan.')
        st.write('Target diuji 25–100% ADR20; SL di luar ekstrem candle sweep. Parameter dikunci sebelum outcome kandidat Januari–September 2026 dihitung.')
        return
    qualified=[c for c in result.get('selected_by_side',[]) if c.get('qualified')]
    cols=st.columns(3)
    cols[0].metric('Kombinasi parameter',format(result.get('configurations_evaluated',0),',').replace(',','.'))
    cols[1].metric('Replay','2016–2025')
    cols[2].metric('Konfigurasi lolos',len(qualified))
    st.caption('Status: '+result.get('status','UNKNOWN'))
    if not qualified:
        st.warning('Keluarga pola ini belum menghasilkan konfigurasi yang memenuhi seluruh syarat profit setelah biaya dan kestabilan. Belum ada zona entry/TP/SL utama harian yang direkomendasikan.')
    for c in result.get('selected_by_side',[]):
        cfg=c['config'];m=c.get('fresh_2026',{})
        st.markdown('**'+('BUY' if cfg['side']==1 else 'SELL')+' · '+('Lolos pengujian Jan–Sep2026' if c.get('qualified') else 'Ditolak / penelitian saja')+'**')
        st.json({'config':cfg,'training':c.get('train',{}),'validation':c.get('validation',{}),'test_2026':m})
    st.caption('Win rate net-positive berbeda dari target-hit rate. Hasil synthetic spread/slippage bukan return akun, bukan backtest cBot, dan tidak menjamin reversal setiap hari.')

