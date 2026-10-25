from datetime import UTC,datetime,timedelta
from copy import deepcopy
from pathlib import Path
import json
import pytest
from fx_scanner.cbot_webview import build_view,safe_json

NOW=datetime(2026,10,21,12,0,10,tzinfo=UTC)
def fixture(side=1):
    at=NOW.replace(second=0).isoformat()
    f=dict(at_utc=at,open=4099,high=4103,low=4098,close=4101,
        h1_bias=side,m15_bias=side,warm=True,buy_prior_eligible=True,
        buy_trigger_next=4100,sell_sweep_next=4110,sell_trigger_estimate=4102 if side==-1 else None,
        signal_side=side,execution_authority=False,execution_influence=False)
    c=dict(symbol='XAUUSD',bar_at=at,status='ENTRY_MANUAL',target_r=5.5,
        indicator=f,indicator_history=[f],signal={'at':at,'side':'BUY' if side==1 else 'SELL'},
        valid_until=(NOW.replace(second=0)+timedelta(seconds=60)).isoformat(),
        quote_at=NOW.isoformat(),entry=4101,sl=4101-side*10,tp=4101+side*55,blockers=[],
        positions=[{'sensitive_position':'do-not-export'}],account_binding='private-test-binding')
    return dict(contract='RIZAN_CBOT_MANUAL_V1',source_commit='e357272fec03411a6e7c4d2397faf742d1a11047',source_release='V1.3.0',as_of=NOW.isoformat(),market_observed_at=NOW.isoformat(),native_observed_at=NOW.isoformat(),execution_authority=False,execution_influence=False,symbols=[c])

@pytest.mark.parametrize('side',[1,-1])
def test_native_markers_and_original_geometry_preserved(side):
    p=fixture(side);v=build_view(p,now=NOW)
    assert v['status']=='ENTRY_MANUAL' and v['entry']['side']==('BUY' if side==1 else 'SELL')
    assert v['history'][0]['signal_side']==side
    assert v['entry']['tp']==p['symbols'][0]['tp']
    assert v['hold_minutes']==480 and v['target_r']==5.5
    assert v['entry_until']==(NOW+timedelta(seconds=15)).isoformat()
    assert p['symbols'][0]['positions'] # inputs not mutated

def test_no_account_positions_credentials_in_export():
    p=fixture();p['api_key']='secret-test';p['symbols'][0]['indicator']['secret']='hidden'
    out=json.dumps(build_view(p,now=NOW))
    for token in ['do-not-export','private-test-binding','secret-test','hidden','api_key','positions']:assert token not in out

@pytest.mark.parametrize('change',['authority','source','future','stale','duplicate_symbol','history','geometry','block','wrong_side','expired','quote','native','warmup'])
def test_invalid_or_ineligible_inputs_never_export_entry(change):
    p=fixture();c=p['symbols'][0]
    if change=='authority':p['execution_authority']=True
    if change=='source':p['source_commit']='unknown'
    if change=='future':c['bar_at']=(NOW+timedelta(seconds=1)).isoformat()
    if change=='stale':p['as_of']=(NOW-timedelta(seconds=91)).isoformat()
    if change=='duplicate_symbol':p['symbols'].append(deepcopy(c))
    if change=='history':c['indicator_history']=[c['indicator'],c['indicator']]
    if change=='geometry':c['tp']=4102
    if change=='block':c['blockers']=['Macro menahan BUY'];c['status']='BLOCK'
    if change=='wrong_side':c['signal']['side']=''
    if change=='expired':c['valid_until']=NOW.isoformat()
    if change=='quote':c['quote_at']=(NOW-timedelta(seconds=16)).isoformat()
    if change=='native':p['native_observed_at']=(NOW-timedelta(seconds=91)).isoformat()
    if change=='warmup':c['indicator']['warm']=False
    assert build_view(p,now=NOW)['entry'] is None

def test_expired_signal_does_not_become_new_on_republication():
    p=fixture();later=NOW+timedelta(seconds=60)
    p['as_of']=p['market_observed_at']=p['native_observed_at']=later.isoformat()
    p['symbols'][0]['quote_at']=later.isoformat()
    assert build_view(p,now=later)['entry'] is None

def test_host_symbol_and_demo_cannot_create_wrong_live_signal():
    p=fixture()
    assert build_view(p,now=NOW,symbol='EURUSD')['status']=='SIMBOL_TIDAK_DIDUKUNG'
    v=build_view(p,now=NOW,demo=True);assert v['status']=='MODE_UJI' and v['entry'] is None

def test_script_payload_escapes_html_and_js_separator():
    out=safe_json({'reason':'</script><img src=x onerror=alert(1)>\u2028'})
    assert '</script>' not in out and '<img' not in out and '\\u2028' in out

def test_ui_export_has_no_sdk_or_trade_methods_and_no_signal_recalculation():
    root=Path(__file__).resolve().parents[1]
    js='\n'.join(p.read_text() for p in (root/'webview_app').glob('*.js'))
    for token in ['createNewOrder','modifyOrderProtection','closePosition','getAccountInformation','fetch(','WebSocket(']:assert token not in js
    assert 'signal_side' in js
    from fx_scanner.cbot_webview_dashboard import document,demo_view
    doc=document(build_view({},now=NOW),demo_view())
    assert 'MODE UJI' in doc and '__DATA__' not in doc and '__CODE__' not in doc

def test_route_uses_existing_host_and_lazy_read_only_view():
    root=Path(__file__).resolve().parents[1]
    text=(root/'main.py').read_text()
    assert 'url_path="cbot-plugin"' in text
    assert 'from fx_scanner.cbot_webview_dashboard import render_webview_plugin' in text
