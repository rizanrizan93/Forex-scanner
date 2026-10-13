"""Audited scanner research display; rejected models cannot emit trading zones."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CONTRACT='RIZAN_XAU_VOLATILITY_COST_REVERSAL_NET_V1'
RESULT=ROOT/'calibration/volatility_reversal_results.json'


def render_volatility_reversal_dashboard():
    import streamlit as st
    st.subheader('XAU · reversal utama harian · hasil penelitian')
    st.caption('Engine scanner terpisah. Strategy/execution cBots XAU/EUR tidak berubah.')
    try:result=json.loads(RESULT.read_text())
    except (OSError,ValueError):
        st.info('Hasil audit filter volatilitas/biaya belum tersedia. Tidak ada konfigurasi varian ini yang dipromosikan.')
        return
    if (result.get('contract')!=CONTRACT or result.get('execution_authority') is not False
            or result.get('execution_influence') is not False):
        st.error('Hasil penelitian tidak sesuai contract scanner read-only.')
        return
    qualified=[c for c in result.get('selected_by_side',[]) if c.get('qualified') and result.get('status')=='VALIDATED_2026']
    cols=st.columns(3)
    cols[0].metric('Kombinasi parameter',format(result.get('configurations_evaluated',0),',').replace(',','.'))
    cols[1].metric('Replay','2016–2025')
    cols[2].metric('Konfigurasi lolos',len(qualified))
    st.caption('Status: '+result.get('status','UNKNOWN'))
    if not qualified:
        st.warning('Belum ditemukan konfigurasi reversal utama yang lolos profit setelah biaya dan kestabilan antarperiode. Belum ada zona entry, TP, SL, atau jam terbaik yang dipromosikan dari penelitian ini.')
        if not result.get('selected_by_side'):
            st.caption('Tidak ada kandidat terkunci, sehingga tidak ada hasil trade kandidat Januari–September 2026 yang dapat diklaim sebagai validasi.')
    st.write('Rentang uji: stop berbasis ATR14 M5 dan ekstrem pola; target 1,5–6,6R, minimal 25% ADR20. Filter volatilitas dibanding spread model. Rentang ini bukan rekomendasi trading.')
    try:diagnostics=json.loads((ROOT/'calibration/volatility_reversal_diagnostics.json').read_text())
    except (OSError,ValueError):diagnostics={}
    if diagnostics.get('contract')==CONTRACT:
        with st.expander('Alasan penolakan dan contoh penelitian'):
            st.table([{'Syarat kumulatif':g['gate'],'Kombinasi tersisa':g['remaining_tuples']} for g in diagnostics.get('cumulative_gates',[])])
            rows=[]
            for e in diagnostics.get('diagnostic_examples',[]):
                cfg=e['config'];start=cfg['session_utc']
                rows.append({'Arah':'BUY' if cfg['side']==1 else 'SELL','Sumber':cfg['zone_source'],
                    'Sesi WIB':f'{(start+7)%24:02d}:00–{(start+13)%24:02d}:00',
                    'PF 2016–2021':round(e['train']['profit_factor'],3) if e['train']['profit_factor'] is not None else None,
                    'PF 2022–2025':round(e['validation']['profit_factor'],3) if e['validation']['profit_factor'] is not None else None,
                    'Mean net R training':round(e['train']['mean_net_r'],3),
                    'Mean net R validation':round(e['validation']['mean_net_r'],3)})
            if rows:st.table(rows)
            st.caption('Contoh dipilih untuk diagnosis setelah melihat validation. Jam ini bukan waktu reversal terbaik yang tervalidasi; konfigurasi lengkap dan alasan ditolak ada pada hasil audit.')
        st.caption('Tiga keluarga tambahan diuji masing-masing 10 juta tuple. Tuple dapat berbagi keputusan, bukan strategi independen.')
    for c in qualified:
        st.markdown('**'+('BUY' if c['config']['side']==1 else 'SELL')+' · Lolos pengujian Jan–Sep2026**')
        st.json({'config':c['config'],'test_2026':c.get('fresh_2026',{})})
    st.caption('Win rate net-positive berbeda dari target-hit rate. Synthetic spread/slippage bukan return akun, bukan backtest cBot, dan tidak menjamin reversal setiap hari.')

