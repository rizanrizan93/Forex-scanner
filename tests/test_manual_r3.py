from datetime import UTC,datetime,timedelta
import json
from pathlib import Path
import pandas as pd
import pytest
from fx_scanner.manual_range_reclaim_r3 import evaluate_snapshot
from fx_scanner.manual_r3_feed import (CONTRACT,NEWS_CONTRACT,calendar_from_snapshot,validate_calendar,validate_market)
P=Path(__file__).parent/'fixtures/manual_r3'

@pytest.fixture
def case():
    info=json.loads((P/'case.json').read_text());now=pd.Timestamp(info['now'])
    frame=pd.read_csv(P/'m1.csv.gz',parse_dates=['timestamp']).set_index('timestamp')
    return info,now,frame

def report(case,**extra):
    info,now,frame=case
    args=dict(now=now,bid=info['bid'],ask=info['ask'],quote_as_of=now,news_events=[]);args.update(extra)
    return evaluate_snapshot(frame,**args)

def test_closed_m1_trigger_plan_frozen_and_alarm_once(case):
    first=report(case);assert first['status']==case[0]['expected'];assert first['alert_new']
    second=report(case,memory=first['memory'])
    assert not second['alert_new'] and second['plan']==first['plan']
    assert all(x['pass'] for x in first['checks'])
    assert first['execution_authority'] is False
    json.dumps(first,allow_nan=False)

@pytest.mark.parametrize('args',[{'news_events':None},{'bid':None,'ask':None}, {'quote_as_of':'2020-01-01T00:00:00Z'}])
def test_absent_calendar_or_quote_never_ready(case,args):
    assert not report(case,**args)['status'].startswith('TRIGGER')

def test_expired_price_and_time_rejected(case):
    out=report(case);level=out['frozen_trigger_line'];a=out['atr_m5']
    assert report(case,bid=level+3*a,ask=level+3*a+.3)['status']=='EXPIRED_PRICE'
    now=case[1]+pd.Timedelta(seconds=60)
    assert report(case,now=now,quote_as_of=now)['status']=='EXPIRED_TIME'

def test_forming_candle_cannot_repaint(case):
    info,now,frame=case;d=frame.copy();d.loc[now.floor('min')]=[9000,9001,8999,9000]
    a=report(case);b=evaluate_snapshot(d,now=now,bid=info['bid'],ask=info['ask'],quote_as_of=now,news_events=[])
    assert a['signal_id']==b['signal_id'] and a['plan']==b['plan']

def test_calendar_preserves_original_time_and_rejects_speech_as_fomc():
    now=datetime(2026,11,17,10,tzinfo=UTC)
    hb=dict(worker_name='ctrader_demo_xau_event_risk_v192',observed_at=now.isoformat(),healthy=True,details={'risk':{'upcoming_events':[
        {'category':'FED_SPEECH','event_component':'FOMC','title':'FOMC Member Speaks','scheduled_at':now.isoformat()},
        {'category':'CPI','title':'Core CPI','scheduled_at':now.isoformat()},
        {'category':'EMPLOYMENT','title':'Non-Farm Payrolls','scheduled_at':now.isoformat()}]}})
    snapshot=dict(contract='RIZAN_PRE_NEWS_SNAPSHOT_V1',execution_authority=False,heartbeats=[hb])
    c=calendar_from_snapshot(snapshot,now=now)
    assert c['observed_at']==now.isoformat()
    assert {x['event'] for x in c['events']}=={'CPI','NFP'}
    assert validate_calendar(c,now=now+timedelta(minutes=11)) is None

def test_feed_validates_contract_history_and_actual_quote_age(case):
    info,now,frame=case;d=frame[frame.index+pd.Timedelta(minutes=1)<=now]
    rows=d.reset_index();rows.timestamp=rows.timestamp.map(lambda x:x.isoformat())
    p=dict(contract=CONTRACT,source='CTRADER_MARKET_DATA_READ_ONLY',symbol='XAUUSD',as_of=now.isoformat(),
           execution_authority=False,execution_influence=False,m1=rows.to_dict('records'),
           quote=dict(bid=info['bid'],ask=info['ask'],at=now.isoformat()),
           calendar=dict(contract=NEWS_CONTRACT,execution_authority=False,observed_at=now.isoformat(),events=[]))
    valid=validate_market(p,now=now)
    assert len(valid['frame'])==12000 and valid['news_events']==[]
    p['quote']['at']=(now-timedelta(minutes=2)).isoformat()
    assert validate_market(p,now=now)['bid'] is None
    p['m1']=p['m1'][-512:]
    with pytest.raises(ValueError,match='HISTORY_INCOMPLETE'):validate_market(p,now=now)

def test_protocol_guard_has_no_order_or_rotation_requests():
    from scripts.collect_manual_r3 import Reader
    assert 'ProtoOAGetTickDataReq' in Reader.allowed
    assert not any('Order' in s or 'Reconcile' in s or 'RefreshToken' in s for s in Reader.allowed)
    with pytest.raises(RuntimeError,match='ORDER_DISABLED'):Reader.__new__(Reader).send_new_order()

def test_installer_is_isolated():
    from operations.manual_r3.install import BLOCK,UNIT,TIMER_UNIT
    assert 'manual-r3-news.json' in BLOCK and 'no-store' in BLOCK
    assert 'OnUnitInactiveSec=10' in TIMER_UNIT and '/var/lib/rizan-manual-r3' in UNIT

def test_reinstall_stops_only_manual_reader(monkeypatch):
    from types import SimpleNamespace
    from operations.manual_r3 import install
    calls=[]
    def fake_run(args,**kwargs):
        calls.append(args);return SimpleNamespace(stdout='loaded\n')
    monkeypatch.setattr(install,'run',fake_run)
    install.stop_previous_reader()
    assert [a for a in calls if a[1]=='stop']==[['systemctl','stop',install.TIMER],['systemctl','stop',install.SERVICE]]
    assert all(install.BRIDGE not in a for a in calls)

def test_dashboard_renders_wait_and_navigation_keeps_manual_page(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from fx_scanner import manual_r3_dashboard as dashboard
    monkeypatch.setattr(dashboard,'fetch_market',lambda **k:(_ for _ in ()).throw(OSError()))
    root=Path(__file__).resolve().parents[1]
    app=AppTest.from_file(str(root/'main.py'),default_timeout=20)
    app.session_state['rizan_xau_detail']='Manual R3';app.run()
    assert not app.exception
    assert any('Range Reclaim' in x.value for x in app.subheader)
    assert 'Manual R3' in app.radio[1].options and app.radio[1].value=='Manual R3'

def test_dashboard_renders_real_fixture_chart_and_plan():
    from streamlit.testing.v1 import AppTest
    root=Path(__file__).resolve().parents[1]
    source=f"""
import json,pandas as pd
from pathlib import Path
from fx_scanner.manual_r3_dashboard import render_view
p=Path({str(P)!r});info=json.loads((p/'case.json').read_text());now=pd.Timestamp(info['now'])
frame=pd.read_csv(p/'m1.csv.gz',parse_dates=['timestamp']).set_index('timestamp')
frame=frame[frame.index+pd.Timedelta(minutes=1)<=now]
render_view(dict(frame=frame,bid=info['bid'],ask=info['ask'],quote_as_of=now,news_events=[]),now=now)
"""
    app=AppTest.from_string(source,default_timeout=20).run()
    assert not app.exception
    assert any(x.label=='SL' for x in app.metric)
    assert any(x.label=='TP' for x in app.metric)
