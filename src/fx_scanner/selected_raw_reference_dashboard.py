"""Phone-readable latest frozen references, independent of broker heartbeats."""
from .selected_raw_reference import reference, geometry


def render_selected_raw_reference(symbol):
    import json
    import streamlit as st
    r = reference(symbol); m = r['metrics']; cfg = r['layering']; p = r['policy']
    st.subheader(f"{symbol} · strategi RAW terpilih · 1:{r['leverage']}")
    st.caption('Acuan trading manual. Order otomatis live tidak diaktifkan. Status broker DEMO ditampilkan terpisah.')
    cols = st.columns(2)
    cols[0].metric('Saldo replay ($)', f"{m['ending_balance_usd']:,.2f}")
    cols[1].metric('DD floating M1 (%)', f"{m['max_dd_m1_percent']:.2f}")
    st.caption(f"2016–2025 · modal $100 · {m['trades']} basket · {m['trades']/120:.2f} trade/bulan · PF {m['profit_factor']:.3f}")
    rows = [{'Tahap': 'Entry awal' if i == 0 else f'Layer {i}', 'Kedalaman menuju SL (%)': round(d*100,2),
             'Syarat': 'Entry signal' if i == 0 else ('Konfirmasi reversal' if cfg['confirmed'] else 'Limit pada kedalaman')}
            for i,d in enumerate(cfg['depths_r'])]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    trigger = p['equity_dd_trigger']
    st.caption(f"Risk basket ≤{p['risk_ceiling']*100:g}% · margin ≤{p['margin_ceiling']*100:g}% · unit {r['child_lot']:.2f} lot · tambahan berlaku {cfg.get('add_expiry_minutes', cfg.get('expiry_minutes'))} menit.")
    st.caption(f"Entry awal {p['initial_fraction']*100:g}% dari unit dasar · kapasitas {p['capacity_multiplier']:g}× · bobot tahap {p['depth_weight_power']:g}. Jumlah unit mengikuti equity dan budget; jumlah tahap berbeda dari jumlah unit.")
    if trigger:
        st.caption(f"Saat DD yang sudah diketahui ≥{trigger*100:g}%, budget dan jumlah awal turun ke {p['dd_reduction_factor']*100:g}%.")
    with st.expander('Stress dan kontrak strategi RAW', expanded=False):
        cost_rows = []
        for key, label in [('raw_base','Dasar'),('base','Dasar'),('raw_spread_slip_x1_5','Biaya 1,5×'),('spread_slip_x1_5','Biaya 1,5×'),('raw_spread_slip_x2','Biaya 2×'),('spread_slip_x2','Biaya 2×'),('raw_spread_slip_x3','Biaya 3×'),('spread_slip_x3','Biaya 3×')]:
            if key in r['stress']:
                v = r['stress'][key]
                cost_rows.append({'Skenario':label,'Saldo ($)':round(v['ending_balance_usd'],2),'DD (%)':round(v['max_dd_m1_percent'],2)})
        st.dataframe(cost_rows,hide_index=True,use_container_width=True)
        st.caption('Spread RAW memakai referensi MT4 sebagai proxy cTrader; komisi per sisi masuk replay. Seleksi dilakukan pada sejarah yang sudah diamati. DD historis bukan batas kerugian ke depan.')
        st.json(r['frozen']['contract'])
        st.download_button('Unduh kontrak RAW '+symbol, json.dumps(r['frozen'],indent=2),
                           file_name=symbol.lower()+'_raw_selected.json',mime='application/json',key='raw_selected_download_'+symbol)
    with st.expander('Hitung level layer manual dari entry / SL / TP', expanded=False):
        with st.form('raw_geometry_'+symbol):
            digits = '%.2f' if symbol == 'XAUUSD' else '%.5f'
            entry = st.number_input('Entry',min_value=0.0,value=0.0,format=digits,key='raw_entry_'+symbol)
            stop = st.number_input('SL',min_value=0.0,value=0.0,format=digits,key='raw_sl_'+symbol)
            target = st.number_input('TP',min_value=0.0,value=0.0,format=digits,key='raw_tp_'+symbol)
            submitted = st.form_submit_button('Hitung level')
        if submitted:
            try:
                stages = geometry(symbol,entry,stop,target)
                st.dataframe([{'Tahap':x['stage'],'Level pemicu':x['trigger'],'SL':x['sl'],'TP':x['tp'],
                               'Konfirmasi wajib':x['requires_confirmation']} for x in stages],hide_index=True,use_container_width=True)
                st.caption('Level pemicu acuan manual, bukan harga fill terjamin. Semua layer berbagi SL/TP awal. Kalkulator ini tidak mengirim order.')
            except ValueError as exc:
                st.error(str(exc))
