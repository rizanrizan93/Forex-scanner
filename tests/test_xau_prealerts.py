from copy import deepcopy
from datetime import timedelta
import json
import pandas as pd
import pytest
from fx_scanner.xau_prealerts import CONTRACT, view, build

NOW = pd.Timestamp('2026-01-23T10:35:10Z')


def plan(side='BUY'):
    d = 1 if side == 'BUY' else -1
    return dict(id=side, side=side, formed_at='2026-01-23T10:00:00Z',
                first_published_at='2026-01-23T10:00:10Z', expires_at='2026-01-23T14:00:00Z',
                price_observed_at='2026-01-23T10:35:00Z', touch_history_complete=True,
                low=3999., high=4001., entry=4000., sl=4000-d*15, tp=4000+d*25,
                sl_distance=15., tp_distance=25., execution_authority=False,
                execution_influence=False)


@pytest.mark.parametrize('side', ['BUY','SELL'])
def test_prealert_geometry_is_symmetric_but_never_a_broker_entry(side):
    q=view(plan(side),now=NOW)
    assert q['state']=='ABA_ABA' and q['entry_available'] is False
    assert q['execution_authority'] is False and q['execution_influence'] is False


def test_prepublication_touch_is_missed_not_a_new_entry():
    p=plan();p['first_observed_touch_at']='2026-01-23T10:00:00Z'
    assert view(p,now=NOW)['state']=='TERLEWAT'
    p['first_observed_touch_at']='2026-01-23T10:20:00Z'
    assert view(p,now=NOW)['state']=='TERSENTUH'
    p['first_presented_at']='2026-01-23T10:30:00Z'
    assert view(p,now=NOW)['state']=='TERLEWAT'


def test_cache_cannot_revive_expired_or_stale_or_incomplete_plans():
    p=plan()
    assert view(p,now=NOW+timedelta(hours=4))['state']=='KEDALUWARSA'
    assert view(p,now=NOW+timedelta(minutes=2))['state']=='DATA_BELUM_CUKUP'
    assert view(p,now=NOW,feed_fresh=False)['state']=='DATA_BELUM_CUKUP'
    p['touch_history_complete']=False
    assert view(p,now=NOW)['state']=='DATA_BELUM_CUKUP'


@pytest.mark.parametrize('change', [dict(execution_authority=True),dict(tp=4024),
    dict(sl=4001),dict(first_published_at='2026-01-24T00:00:00Z'),
    dict(first_observed_touch_at='2026-01-23T11:00:00Z')])
def test_invalid_contract_or_future_timestamps_fail_closed(change):
    assert view(dict(plan(),**change),now=NOW)['state']=='DATA_TIDAK_VALID'


def native():
    hour_end=NOW.floor('h')
    hours=pd.date_range(end=hour_end-pd.Timedelta(hours=1),periods=300,freq='h')
    h=[]
    for i,t in enumerate(hours):
        c=1000+i*.2;w=20 if i>=270 else .5
        h.append(dict(timestamp=t.isoformat(),open=c-.1,high=c+w,low=c-w,close=c))
    end=NOW.floor('15min');quarters=pd.date_range(end=end-pd.Timedelta(minutes=15),periods=120,freq='15min')
    q=[dict(timestamp=t.isoformat(),open=1050.,high=1051.,low=1049.,close=1050.) for t in quarters]
    q[-2].update(open=1050.,high=1071.,low=1049.,close=1070.)
    q[-1].update(open=1072.,high=1081.,low=1060.,close=1080.)
    m=[dict(timestamp=t.isoformat(),open=1070.,high=1071.,low=1069.,close=1070.)
       for t in pd.date_range(end=NOW.floor('min')-pd.Timedelta(minutes=1),periods=60,freq='min')]
    return dict(H1=h,M15=q,M1=m)


def test_builder_publishes_early_and_retains_original_geometry_and_clock():
    feed=native();a=build(feed,now=NOW,data_as_of=NOW)
    assert a['contract']==CONTRACT and a['plans']
    p=a['plans'][0];assert p['state']=='ABA_ABA'
    assert p['entry']==pytest.approx(1051.) and p['sl']==p['entry']-20
    assert p['tp']==p['entry']+25
    altered=deepcopy(feed);altered['M15'][-1]['close']=1080.01
    b=build(altered,now=NOW+pd.Timedelta(seconds=10),previous=a,data_as_of=NOW)
    assert b['plans'][0]['entry']==p['entry']
    assert b['plans'][0]['first_published_at']==p['first_published_at']


def test_publication_delay_does_not_complete_old_partial_candle():
    feed=native()
    feed['M15'].append(dict(timestamp=NOW.floor('15min').isoformat(),open=1050.,high=9999.,low=1049.,close=9998.))
    result=build(feed,now=NOW+pd.Timedelta(hours=1),data_as_of=NOW)
    assert all(pd.Timestamp(p['formed_at'])<=NOW for p in result['plans'])


def test_ui_shows_both_directions_without_promoting_missed_or_stale_entry():
    from streamlit.testing.v1 import AppTest
    p=plan();p['first_observed_touch_at']='2026-01-23T10:20:00Z'
    snap=dict(fresh=True,prealerts=dict(contract=CONTRACT,plans=[p]))
    code="from fx_scanner.xau_prealert_dashboard import render_prealerts\nimport json,pandas as pd\nrender_prealerts(json.loads("+repr(json.dumps(snap))+"),now=pd.Timestamp('2026-01-23T10:35:10Z'))"
    app=AppTest.from_string(code).run(timeout=15)
    assert not app.exception
    assert any('TERLEWAT' in x.value for x in app.markdown)
    assert any('SELL' in x.value for x in app.info)
    assert not app.metric and not app.button and not app.checkbox
