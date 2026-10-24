from datetime import UTC,datetime,timedelta
import json
import numpy as np,pandas as pd,pytest
from fx_scanner.manual_reversal_map import CONTRACT,detect,evaluate,project,validate

NOW=datetime(2026,10,14,0,45,tzinfo=UTC)

def bars():
    t=pd.date_range('2026-10-01',periods=100,freq='h',tz='UTC');out=[]
    for i,ts in enumerate(t):
        c=100. if i<30 else 104.
        out.append({'timestamp':ts.isoformat(),'open':c,'high':c+.2,'low':c-.2,'close':c})
    out[30].update(open=100.,low=99.9,high=104.2,close=104.)
    return out

def sample():
    return {'contract':CONTRACT,'symbol':'XAUUSD','as_of':NOW.isoformat(),'price':100.,'price_observed_at':NOW.isoformat(),
        'state':'MAP_AVAILABLE','execution_authority':False,'execution_influence':False,'zones':[]}

def test_base_zone_known_only_after_departure_closes():
    rows=bars();at=pd.Timestamp(rows[30]['timestamp']).to_pydatetime();before=detect(rows,'H1',at+timedelta(minutes=30));after=detect(rows,'H1',at+timedelta(hours=1))
    assert not before and after
    assert all(pd.Timestamp(x['available_at'])<=at+timedelta(hours=1) for x in after)

def test_future_data_does_not_change_known_zones_and_close_break_retires_zone():
    rows=bars();at=pd.Timestamp(rows[35]['timestamp']).to_pydatetime();a=detect(rows,'H1',at)
    changed=json.loads(json.dumps(rows))
    for x in changed[35:]:
        for k in ['open','high','low','close']:x[k]+=500
    assert detect(changed,'H1',at)==a
    rows[36].update(open=104.,high=104.2,low=97.,close=98.)
    remaining=detect(rows,'H1',pd.Timestamp(rows[38]['timestamp']).to_pydatetime())
    assert not any(x['zone_id']==a[0]['zone_id'] for x in remaining)

def test_fresh_publication_cannot_refresh_an_old_price_or_allow_execution():
    p=sample();p['price_observed_at']=(NOW-timedelta(days=4)).isoformat();assert not validate(p,now=NOW)['fresh']
    p['execution_authority']=True
    with pytest.raises(ValueError):validate(p,now=NOW)
    p=sample();p['as_of']=(NOW+timedelta(days=1)).isoformat();assert not validate(p,now=NOW)['fresh']

def test_structural_targets_do_not_point_into_overlapping_opposing_zones():
    def zone(tf,side,low,high):return {'timeframe':tf,'direction':side,'low':low,'high':high,'available_at':NOW.isoformat()}
    z=project([zone('H1','BUY',98,100),zone('M5','SELL',99,101),zone('H1','SELL',108,110)],102)
    demand=next(x for x in z if x['direction']=='BUY');assert demand['overlap'];assert demand['tp1_reference']==108 and demand['target_structural']==108

def test_m5_is_not_a_major_zone_and_probabilities_are_not_invented():
    rows=bars();now=pd.Timestamp(rows[34]['timestamp']).to_pydatetime();m1=[dict(rows[33],timestamp=(now-timedelta(minutes=1)).isoformat())]
    p=evaluate({'H1':rows,'M1':m1},now=now)
    assert p['execution_authority'] is False and p['execution_influence'] is False
    assert p['zones'] and all(x['probability'] is None for x in p['zones'])
    assert all(x['role']=='UTAMA' for x in p['zones'])
    micro=bars()
    for i,row in enumerate(micro):row['timestamp']=(datetime(2026,10,1,tzinfo=UTC)+timedelta(minutes=5*i)).isoformat()
    at=datetime(2026,10,1,2,50,tzinfo=UTC)
    micro_map=evaluate({'M5':micro,'M1':[dict(micro[33],timestamp=(at-timedelta(minutes=1)).isoformat())]},now=at)
    assert micro_map['zones'] and all(x['role']=='REAKSI / REFINEMENT' for x in micro_map['zones'])

def test_manual_reader_protocol_excludes_positions_orders_and_token_refresh():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'scripts/publish_reversal_snapshot.py';spec=importlib.util.spec_from_file_location('manual_reader',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    assert mod.READ_REQUESTS==frozenset({'ProtoOAApplicationAuthReq','ProtoOAGetAccountListByAccessTokenReq','ProtoOAAccountAuthReq','ProtoOASymbolsListReq','ProtoOAGetTrendbarsReq','ProtoOAGetTickDataReq'})
