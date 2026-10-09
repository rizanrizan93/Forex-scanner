"""Frozen core card across XAU tabs, backed by the existing hot transport."""
from .xau_frozen_dd50 import manifest, STRATEGY_ID, POLICY_HASH


def render_frozen_core():
    import streamlit as st
    from .xau_public_hot_v362 import fetch_public_hot_snapshot
    frozen = manifest()
    st.subheader('Inti XAUUSD · BUY + SELL · DD50 V1')
    st.caption('BUY: Regression Channel Reentry 48 · SELL: Sweep Candle Confirm 24 · konfirmasi H1 + M15 · DEMO')
    core, execution = {}, {}
    try:
        hot = fetch_public_hot_snapshot()
        for row in hot.get('heartbeats',[]):
            if row.get('worker_name')=='ctrader_demo_xau_sd_liquidity_v342':
                core = row.get('details',{}).get('evaluation',{}).get('frozen_core',{})
            elif row.get('worker_name')=='ctrader_demo_xau_v351_executor':
                execution = row.get('details',{})
        if core.get('policy_hash') != POLICY_HASH:
            core = {'state':'WAIT','reason':'MENUNGGU_RUNTIME_VERSI_BEKU'}
        if execution.get('policy_hash') != POLICY_HASH:
            execution = {}
    except Exception:
        core = {'state':'UNAVAILABLE','reason':'SNAPSHOT_RUNTIME_BELUM_TERSEDIA'}
    candidate = core.get('candidate') or {}
    cols = st.columns(4)
    cols[0].metric('Scanner',core.get('state','WAIT'))
    cols[1].metric('Arah',candidate.get('direction','—'))
    cols[2].metric('Executor DEMO',execution.get('state','MENUNGGU RUNTIME'))
    cols[3].metric('Layer rencana',execution.get('planned_children','—'))
    st.caption('Scanner: '+core.get('reason','NO_HEARTBEAT')+' · Executor: '+execution.get('reason','NO_FROZEN_HEARTBEAT'))
    if execution.get('entry') is not None:
        cols = st.columns(3)
        for col, field, label in zip(cols,('entry','sl','tp'),('Entry','SL','TP')):
            col.metric(label,f"{execution[field]:,.2f}")
    st.caption('Layer 0,01 lot per $100 saldo; dibatasi risiko 12,5% equity dan margin 50%. Satu setup aktif; entry 19:00–23:59 WIB; SL 2,65 ATR / struktur; TP 6,6R.')
    with st.expander('Konfigurasi beku dan bukti replay 10 tahun',expanded=False):
        st.caption('2016–2025 · modal awal $100 sekali · rata-rata 4,67 setup/bulan pada biaya cautious (layer bukan setup baru).')
        rows=[]
        for account in frozen['evidence']['accounts']:
            m=account['metrics']
            rows.append({'Biaya':account['scenario'],'Saldo akhir ($)':round(m['balance_usd'],2),
                'Max DD equity (%)':round(m['equity_m1_dd_percent'],2),'Setup':m['parent_setups'],
                'Target $10.000 & DD <50%':m['balance_usd']>=10000 and m['equity_m1_dd_percent']<50})
        st.dataframe(rows,hide_index=True,use_container_width=True)
        st.warning('Biaya stres gagal: DD 83,32%. Hasil ini dioptimasi pada periode replay, belum holdout; biaya sintetis dan makro harian revisi. DD50 adalah hasil replay, bukan batas kerugian forward.')
        st.caption(STRATEGY_ID+' · SHA256 '+POLICY_HASH)
        st.json(frozen['contract'])
        st.download_button('Unduh konfigurasi beku',data=__import__('json').dumps(frozen,indent=2),file_name='xauusd_buysell_dd50_v1.json',mime='application/json')
