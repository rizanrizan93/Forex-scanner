from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
import pytest
from fx_scanner.xau_frozen_dd50 import (manifest, POLICY_HASH, frame_from_bars,
    raw_signals, macro_observation, blocked_event, geometry, layers, features)
from fx_scanner.demo_xau_frozen_dd50 import candidate_from_heartbeat


def test_frozen_identity_and_tamper(tmp_path):
    data=manifest()
    assert data['policy_hash']==POLICY_HASH
    data['contract']['sizing']['risk_cap']=.15
    p=tmp_path/'policy.json';p.write_text(json.dumps(data))
    with pytest.raises(RuntimeError,match='HASH_MISMATCH'):
        manifest(p)


def test_completed_bar_open_to_end_and_future_exclusion():
    now=datetime(2026,10,9,12,5,2,tzinfo=UTC)
    rows=[SimpleNamespace(timestamp=now.replace(minute=i,second=0),open=1,high=2,low=.5,close=1.5) for i in (0,5)]
    f=frame_from_bars(rows,5,now)
    assert len(f)==1 and f.index[-1]==pd.Timestamp('2026-10-09T12:05Z')


def test_raw_signal_parity_with_independent_replay_fixture():
    d=pd.read_json(Path(__file__).parent/'fixtures/xau_dd50_replay_2025.json.gz')
    d['timestamp']=pd.to_datetime(d.timestamp,utc=True);d=d.set_index('timestamp')
    actual=raw_signals(d)
    for key in ('buy','sell'):
        np.testing.assert_array_equal(actual[key],d['expected_'+key])
        assert actual[key].sum()>0
        np.testing.assert_allclose(actual.loc[actual[key],key+'_anchor'],d.loc[actual[key],'expected_'+key+'_anchor'],rtol=1e-10)


def test_macro_two_federal_business_days_holiday_and_staleness():
    f=pd.DataFrame({'DATE':['2026-07-01','2026-07-02'], 'DGS10':[4.1,4.2]})
    # Friday July 3 is observed Independence Day; Jul 2 +2 business days = Jul 7.
    with pytest.raises(RuntimeError,match='STALE_OR_MISSING'):
        macro_observation(f,'DGS10',pd.Timestamp('2026-07-07T03:59Z'))
    value=macro_observation(f,'DGS10',pd.Timestamp('2026-07-07T04:00Z'))
    assert value['delta']==pytest.approx(.1)
    assert value['available_at']=='2026-07-07T04:00:00+00:00'
    with pytest.raises(RuntimeError,match='STALE'):
        macro_observation(f,'DGS10',pd.Timestamp('2026-07-15T04:00Z'))


def test_news_guard_uses_full_planned_hold_not_short_actual_trade():
    at=pd.Timestamp('2026-10-09T12:00Z')
    event=SimpleNamespace(category='CPI',scheduled_at=at+pd.Timedelta(hours=7))
    assert blocked_event([event],at) is event
    event.scheduled_at=at+pd.Timedelta(minutes=496)
    assert blocked_event([event],at) is None
    event.category='PPI';event.scheduled_at=at-pd.Timedelta(minutes=30)
    assert blocked_event([event],at) is event


@pytest.mark.parametrize('side,anchor,expected',[(1,90,(100.5,90.,169.8,10.5)),(-1,110,(100.,110.5,30.7,10.5))])
def test_bid_ask_structural_stop_and_target(side,anchor,expected):
    assert geometry({'side':side,'anchor':anchor,'atr':1},100,100.5)==pytest.approx(expected)


def test_spread_and_sizing_actual_broker_margin():
    with pytest.raises(RuntimeError,match='SPREAD'):
        geometry({'side':1,'anchor':90,'atr':1},100,102)
    assert layers(10000,10000,10,40,10000)==100
    assert layers(10000,10000,100,40,10000)==12
    assert layers(10000,10000,10,140,10000)==35
    assert layers(100,100,20,40,100)==0
    assert layers(10000,10000,10,40,10000,4900)==2
    assert layers(100,100,1,40,float('nan'))==0


def test_higher_timeframe_availability_is_backward_only():
    index=pd.date_range('2026-10-01',periods=300,freq='h',tz='UTC')
    h=pd.DataFrame({'open':np.arange(300)+100,'high':np.arange(300)+102,'low':np.arange(300)+99,'close':np.arange(300)+101},index=index)
    m5=h.copy();m15=h.copy()
    first=features(m5,h,m15)
    h2=h.copy();h2.loc[index[-1]+pd.Timedelta(hours=1)]=[1,2,0,1]
    pd.testing.assert_series_equal(first.h1strict,features(m5,h2,m15).h1strict)


class Query:
    def __init__(self,rows): self.rows=rows
    def table(self,*a): return self
    def select(self,*a): return self
    def eq(self,*a): return self
    def execute(self): return SimpleNamespace(data=self.rows)


def test_executor_rejects_old_engine_and_stale_source():
    now=datetime.now(UTC)
    row={'healthy':True,'observed_at':now.isoformat(),'details':{'evaluation':{}}}
    store=SimpleNamespace(client=Query([row]))
    with pytest.raises(RuntimeError,match='IDENTITY'):
        candidate_from_heartbeat(store,now)
    row['observed_at']=(now-timedelta(seconds=61)).isoformat()
    with pytest.raises(RuntimeError,match='STALE'):
        candidate_from_heartbeat(store,now)


def test_frozen_high_risk_child_is_exact_pair_and_tag_scoped():
    from fx_scanner.execution.models import OrderIntent, OrderSide, OrderType
    args=dict(signal_id='XA50:test',symbol='XAUUSD',side=OrderSide.BUY,order_type=OrderType.MARKET,
        created_at=datetime.now(UTC),volume=.01,entry_price=100,stop_loss=90,take_profit=166,
        risk_pct=12.5,comment='DEMO_AUTO:XAU_DD50_FROZEN')
    OrderIntent(**args)
    for change in ({'symbol':'EURUSD'},{'comment':'DEMO_AUTO:OTHER'},{'risk_pct':12.50001}):
        with pytest.raises(Exception):
            OrderIntent(**{**args,**change})


def test_unknown_broker_outcome_is_reserved_and_never_retried(monkeypatch):
    from fx_scanner import demo_xau_frozen_dd50 as ex
    from fx_scanner.execution.policy import load_execution_policy
    now=datetime.now(UTC)
    candidate={'at':now.isoformat(),'side':1,'direction':'BUY','atr':1,'anchor':90,
        'reference_bid':100,'expires_at':(now+timedelta(hours=2)).isoformat()}
    state={'policy_hash':POLICY_HASH,'daily_counts':{},'attempts':{},'quarantined':False,'activated_at':now.isoformat()}
    saves=[];calls=[]
    class State:
        def __init__(self,*a): self.data=state
        def save(self,release=False):
            from copy import deepcopy
            saves.append(deepcopy(state))
    class Router:
        def __init__(self,*a,**kw): pass
        def execute(self,intent):
            assert saves[-1]['attempts'][intent.signal_id]['outcome'] is None
            calls.append(intent)
            raise TimeoutError('uncertain after submit')
    monkeypatch.setattr(ex,'DurableState',State)
    monkeypatch.setattr(ex,'ExecutionRouter',Router)
    monkeypatch.setattr(ex,'usd_contract',lambda s:SimpleNamespace(symbolId=1))
    monkeypatch.setattr(ex,'candidate_from_heartbeat',lambda *a:{'state':'READY','reason':'SIGNAL','candidate':candidate})
    session=SimpleNamespace(account_id=1,reconcile=lambda:SimpleNamespace(position=[],order=[]),
        expected_margin=lambda *a:SimpleNamespace(margin=[SimpleNamespace(buyMargin=100,sellMargin=100)],moneyDigits=2))
    gateway=SimpleNamespace(account_snapshot=lambda:SimpleNamespace(equity=100.,balance=100.,margin_free=100.),
        market_quote=lambda s:SimpleNamespace(bid=100.,ask=100.5),position_count=lambda:0)
    gate=SimpleNamespace(assert_orders_allowed=lambda *a:None)
    control=SimpleNamespace(refresh_once=lambda:None)
    store=SimpleNamespace()
    with pytest.raises(TimeoutError):
        ex.cycle(store,gateway,session,load_execution_policy(None),control,gate,now)
    assert state['quarantined'] and len(calls)==1
    assert state['last_signal']==now.isoformat()
    assert state['attempts'][calls[0].signal_id]['outcome'] is None
    result=ex.cycle(store,gateway,session,load_execution_policy(None),control,gate,now)
    assert result['reason']=='UNCERTAIN_ATTEMPT_QUARANTINE' and len(calls)==1
