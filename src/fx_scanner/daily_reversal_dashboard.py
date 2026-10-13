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
        st.caption('Tidak ada kandidat yang lolos seleksi 2016–2025, sehingga tidak ada kandidat terkunci untuk diuji pada 2026. Data 2026 tersedia, tetapi ini bukan hasil validasi 2026.')
    try:
        diagnostics=json.loads((ROOT/'calibration/daily_reversal_diagnostics.json').read_text())
    except (OSError,ValueError):
        diagnostics={}
    if diagnostics.get('contract')==result.get('contract'):
        examples=diagnostics.get('diagnostic_examples',[])
        if examples:
            with st.expander('Kandidat penelitian dan waktu WIB · belum layak digunakan'):
                st.caption('Dipilih untuk menjelaskan hasil penelitian. Jam ini bukan waktu reversal terbaik yang telah terverifikasi. PF >1 pada satu periode belum membuktikan kestabilan.')
                rows=[]
                for example in examples:
                    cfg=example['config'];start=cfg['session_utc']
                    rows.append({'Arah':'BUY' if cfg['side']==1 else 'SELL',
                        'Level zona':cfg['zone_source'],
                        'Jendela WIB':f'{(start+7)%24:02d}:00–{(start+13)%24:02d}:00',
                        'TP / ADR20':f"{cfg['target_adr_fraction']:.0%}",
                        'Buffer SL / ATR H1':cfg['stop_extension_atr'],
                        'PF 2016–2021':round(example['train']['profit_factor'],3),
                        'PF 2022–2025':round(example['validation']['profit_factor'],3),
                        'Expectancy train (R)':round(example['train']['mean_net_r'],3),
                        'Expectancy validation (R)':round(example['validation']['mean_net_r'],3),
                        'Status':'DITOLAK'})
                st.dataframe(rows,hide_index=True,use_container_width=True)
                st.caption('SL berada di luar ekstrem sweep ditambah buffer; target mengikuti ADR20 sebelum entry. Persentase peluang reversal belum tersedia untuk kandidat yang tervalidasi. Biaya yang diuji bersifat sintetis.')
    for c in result.get('selected_by_side',[]):
        cfg=c['config'];m=c.get('fresh_2026',{})
        st.markdown('**'+('BUY' if cfg['side']==1 else 'SELL')+' · '+('Lolos pengujian Jan–Sep2026' if c.get('qualified') else 'Ditolak / penelitian saja')+'**')
        st.json({'config':cfg,'training':c.get('train',{}),'validation':c.get('validation',{}),'test_2026':m})
    st.caption('Win rate net-positive berbeda dari target-hit rate. Hasil synthetic spread/slippage bukan return akun, bukan backtest cBot, dan tidak menjamin reversal setiap hari.')

