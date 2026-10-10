"""Smartphone-readable frozen layering and observed broker state."""
from .frozen_layering import manifest


def render_layering(symbol, execution=None):
    import streamlit as st
    frozen=manifest(symbol);cfg=frozen['contract']['configuration']
    execution=execution or {};basket=execution.get('layering') or {}
    st.subheader(symbol+' · executor DEMO · layering sebelumnya')
    st.caption(f"Kandidat #{cfg['id']} · kapasitas equity {cfg['equity_capacity_multiplier']:g}× · tambahan berlaku {cfg['add_expiry_minutes']} menit · child 0,01 lot")
    if execution and execution.get('layering_policy_hash')!=frozen['policy_hash']:
        st.info('Konfigurasi baru sudah dibekukan; menunggu heartbeat runtime dengan versi layering ini.')
    rows=[]
    for i in range(cfg['stages']):
        depth=cfg['max_depth_r']*(i/(cfg['stages']-1))**cfg['spacing_exponent']
        observed=next((r for r in basket.get('stages',[]) if r['stage']==i),{})
        rows.append({'Tahap':'Entry awal' if i==0 else f'Layer {i}',
            'Kedalaman menuju SL (%)':round(depth*100,2),
            'Harga rencana':observed.get('entry'), 'Child rencana':observed.get('children')})
    st.dataframe(rows,hide_index=True,use_container_width=True)
    cols=st.columns(2)
    cols[0].metric('Child aktif',execution.get('active_children','—'))
    cols[1].metric('Limit menunggu',execution.get('pending_children','—'))
    st.caption('BUY ditambah lebih rendah; SELL lebih tinggi. SL/TP tetap sama. Limit dibatalkan saat basket selesai, invalid, budget menyusut, atau kedaluwarsa. Jumlah aktual mengikuti equity dan margin broker.')
    if basket.get('add_expires_at'):
        import pandas as pd
        st.caption('Batas tambahan: '+pd.Timestamp(basket['add_expires_at']).tz_convert('Asia/Jakarta').strftime('%d/%m/%Y %H:%M:%S WIB'))
    with st.expander('Konfigurasi & bukti layering 10 tahun',expanded=False):
        m=frozen['evidence']['selected_posthoc'];b=frozen['evidence']['baseline']
        st.dataframe([{'Mode':name,'Saldo akhir ($)':round(r['ending_balance_usd'],2),
            'DD M1 (%)':round(r['max_dd_m1_percent'],2),'PF':round(r['profit_factor'],3),
            'Setup/bulan':round(r['trades']/120,2)} for name,r in [('Baseline',b),('Layering beku',m)]],
            hide_index=True,use_container_width=True)
        st.caption('Replay 2016–2025, modal $100. Kandidat dipilih dari sejarah yang sudah terlihat; belum konsisten pada seluruh stress test. Eksekusi forward memakai quote/margin broker dan cadangan margin konservatif, sehingga jumlah/fill dapat berbeda.')
        st.json(frozen['contract'])
        import json
        st.download_button('Unduh konfigurasi layering '+symbol,data=json.dumps(frozen,indent=2),
            file_name=symbol.lower()+'_layering_1m_v1.json',mime='application/json',key='layering_download_'+symbol)
