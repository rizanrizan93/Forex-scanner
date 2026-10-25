from datetime import UTC,datetime,timedelta
from copy import deepcopy
import pytest
from fx_scanner.cbot_indicator import seed,advance

AT=datetime(2026,10,21,12,tzinfo=UTC)
def bar(at=AT,o=100,h=120,l=99,c=118):
    return dict(timestamp=at.isoformat(),open=o,high=h,low=l,close=c)
def step(s,rows,at=AT+timedelta(minutes=1)):
    return advance(s,rows,as_of=at.isoformat(),now=at)

def test_trail_uses_closed_minute_and_never_loosens():
    s=seed(1,100,90,AT.isoformat(),0);original=deepcopy(s)
    q=step(s,[bar()]);assert q['stop']==110 and q['active'] and s==original
    q=step(q,[bar(),bar(AT+timedelta(minutes=1),o=118,h=119,l=113,c=115)],AT+timedelta(minutes=2))
    assert q['stop']==110

def test_stop_first_and_adverse_gap_do_not_credit_high():
    s=seed(1,100,90,AT.isoformat(),0)
    q=step(s,[bar(h=140,l=89,c=130)]);assert q['stopped'] and q['exit']==90
    q=step(s,[bar()]);q=step(q,[bar(AT+timedelta(minutes=1),o=105,h=106,l=100,c=101)],AT+timedelta(minutes=2))
    assert q['stopped'] and q['exit']==105

def test_sell_uses_spread_proxy_and_stop_only_tightens():
    s=seed(-1,100,110,AT.isoformat(),1)
    q=step(s,[bar(o=100,h=101,l=80,c=82)]);assert q['stop']==91 and q['active']

def test_partial_entry_minute_future_candle_and_gap():
    s=seed(1,100,90,(AT+timedelta(seconds=10)).isoformat(),0)
    q=step(s,[bar()]);assert q['stop']==90 and not q['active']
    q=step(q,[bar(AT+timedelta(minutes=2))],AT+timedelta(minutes=3));assert q['coverage_gap']
    s=seed(1,100,90,AT.isoformat(),0)
    q=step(s,[bar(AT+timedelta(minutes=1))]);assert q['stop']==90

@pytest.mark.parametrize('side,entry,sl,spread',[(1,100,110,0),(-1,100,90,0),(1,float('nan'),90,0),(1,100,90,-1)])
def test_invalid_seed_is_rejected(side,entry,sl,spread):
    with pytest.raises(ValueError):seed(side,entry,sl,AT.isoformat(),spread)

def test_stale_future_and_tampered_state_fail_closed():
    s=seed(1,100,90,AT.isoformat(),0)
    with pytest.raises(ValueError):advance(s,[],as_of=AT.isoformat(),now=AT+timedelta(minutes=2))
    q=deepcopy(s);q['execution_authority']=True
    with pytest.raises(ValueError):step(q,[])
    q=deepcopy(s);q['stop']=80
    with pytest.raises(ValueError):step(q,[])

def test_source_files_remain_pinned_and_indicator_has_no_trading_calls():
    from pathlib import Path
    import json,hashlib
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'cbot_manual/SOURCE_MANIFEST.json').read_text())
    assert all(hashlib.sha256((root/'cbot_manual'/p).read_bytes()).hexdigest()==sha for p,sha in manifest['files'].items())
    path=root/'cbot_indicators/XauCbotIndicator/RizanXauCbotIndicator.cs'
    source=path.read_text()
    assert 'AccessRights=AccessRights.None' in source and ': Indicator' in source
    for token in ['ExecuteMarketOrder','ModifyPosition','PlaceLimitOrder','ClosePosition','LocalStorage','WebSocket']:
        assert token not in source

def test_ui_shows_preparation_chart_and_manual_only_scenario():
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
