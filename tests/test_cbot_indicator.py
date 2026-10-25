from datetime import UTC,datetime

AT=datetime(2026,10,21,12,tzinfo=UTC)
def test_source_files_remain_pinned_and_indicator_has_no_trading_calls():
    from pathlib import Path
    import json,hashlib
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'cbot_manual/SOURCE_MANIFEST.json').read_text())
    assert all(hashlib.sha256((root/'cbot_manual'/p).read_bytes()).hexdigest()==sha for p,sha in manifest['files'].items())
    path=root/'cbot_indicators/XauCbotIndicator/RizanXauCbotIndicator.cs'
    source=path.read_text()
    assert 'AccessRights=AccessRights.None' in source and ': Indicator' in source
    for token in ['TrackScenario','TrailLine','ManualTrailing','ActivationR','DistanceR','ExecuteMarketOrder','ModifyPosition','PlaceLimitOrder','ClosePosition','LocalStorage','WebSocket']:
        assert token not in source

def test_ui_preserves_original_exit_without_manual_setup():
    from streamlit.testing.v1 import AppTest
    at=AT.isoformat()
    frame=dict(at_utc=at,open=99,high=101,low=98,close=100,atr=2,h1_bias=1,m15_bias=1,
        warm=True,session_open=True,buy_trigger_next=101,buy_prior_eligible=True,
        sell_sweep_next=110,sell_trigger_estimate=None,signal_side=0,
        execution_authority=False,execution_influence=False)
    c=dict(symbol='XAUUSD',bar_at=at,indicator=frame,indicator_history=[frame])
    script="""import streamlit as st
from datetime import datetime,UTC
from fx_scanner.cbot_indicator_dashboard import render
render(st.session_state['c'],{'fresh':True},now=datetime(2026,10,21,12,tzinfo=UTC))
"""
    app=AppTest.from_string(script);app.session_state['c']=c;app.run(timeout=20)
    assert not app.exception
    assert any('ABA-ABA BUY' in t.value for t in app.info)
    assert any('batas close M5' in m.label for m in app.metric)
    assert not any('order' in b.label.lower() for b in app.button)

    assert not app.radio and not app.number_input and not app.get("form")
    assert any('TP 5,5R' in t.value for t in app.caption)
