from datetime import timedelta
from copy import deepcopy
import math

from fx_scanner.dxy_broker_context import WEIGHTS, synthetic_points, evaluate_broker_dxy, select_dxy
from test_pre_news_expectation import NOW


def basket():
    levels={'EURUSD':1.1,'USDJPY':150,'GBPUSD':1.3,'USDCAD':1.35,'USDSEK':10.2,'USDCHF':.85}
    return {key:[{'observed_at':NOW-timedelta(minutes=m),'value':value*(1.002 if key=='EURUSD' and m==0 else 1)}
                 for m in [120,60,0]] for key,value in levels.items()}


def test_formula_uses_complete_basket_and_correct_inverse_direction():
    data=basket()
    rows=synthetic_points(data,now=NOW)
    expected=50.14348112*math.prod(data[key][0]['value']**weight for key,weight in WEIGHTS.items())
    assert abs(rows[0]['value']-expected)<1e-10
    assert rows[-1]['value']<rows[0]['value']
    view=evaluate_broker_dxy(now=NOW,basket=data)
    assert view['source']=='CTRADER_SYNTHETIC_USDX_6FX'
    assert view['state']=='DXY_DOWN'
    assert view['component_count']==6
    assert view['execution_authority'] is False
    assert view['execution_influence'] is False


def test_missing_stale_future_invalid_and_unsynchronized_components_abstain():
    for issue in ['missing','unsynchronized','stale','invalid','future']:
        data=basket()
        if issue=='missing': data.pop('USDSEK')
        if issue=='unsynchronized':
            for p in data['USDCHF']:p['observed_at']+=timedelta(minutes=1)
        if issue=='stale':
            for series in data.values():
                for p in series:p['observed_at']-=timedelta(hours=4)
        if issue=='invalid':
            for p in data['GBPUSD']:p['value']=float('nan')
        if issue=='future':
            for series in data.values():
                for p in series:p['observed_at']+=timedelta(days=1)
        assert not evaluate_broker_dxy(now=NOW,basket=data)['available'],issue


def test_direct_broker_symbol_preferred_and_broad_usd_proxy_not_accepted():
    direct=[{'observed_at':NOW-timedelta(minutes=m),'value':100+(120-m)*.002} for m in [120,60,0]]
    out=evaluate_broker_dxy(now=NOW,direct=direct,symbol='DXY',basket=basket())
    assert out['source']=='CTRADER_DXY_CFD_PROXY'
    assert out['state']=='DXY_UP'
    assert evaluate_broker_dxy(now=NOW,direct=direct,symbol='USDOLLAR')['available'] is False


def test_fallback_selection_preserves_primary_and_rejects_stale_or_authoritative():
    broker=evaluate_broker_dxy(now=NOW,basket=basket())
    assert select_dxy({},broker,now=NOW)['source']=='CTRADER_SYNTHETIC_USDX_6FX'
    primary={'available':True,'freshness':'FRESH','current_at':NOW.isoformat(),'source':'YAHOO'}
    assert select_dxy(primary,broker,now=NOW)==primary
    for changes in [{'current_at':(NOW-timedelta(minutes=16)).isoformat()},{'execution_authority':True},{'source':'UNRECOGNIZED'}]:
        bad=broker|changes
        assert select_dxy({},bad,now=NOW)=={}


def test_protocol_reader_has_no_order_or_position_messages():
    import ast
    from pathlib import Path
    p=Path(__file__).resolve().parents[1]/'scripts/collect_broker_dxy.py'
    tree=ast.parse(p.read_text())
    requests={node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='request' and node.args}
    assert requests=={'ProtoOAApplicationAuthReq','ProtoOAGetAccountListByAccessTokenReq','ProtoOAAccountAuthReq','ProtoOASymbolsListReq','ProtoOAGetTrendbarsReq'}
