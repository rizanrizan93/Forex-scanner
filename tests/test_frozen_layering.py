from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import math
from types import SimpleNamespace as NS

import pytest
from fx_scanner import frozen_layering as layer
from fx_scanner.execution.models import OrderType
from test_ctrader_gateway_v04 import FakeSession, intent
from fx_scanner.execution.ctrader_gateway import CTraderExecutionGateway


def make_plan(symbol='XAUUSD',balance=1000,side=1,margin=None,scale=1):
    entry=2000 if symbol=='XAUUSD' else 1.1
    distance=2 if symbol=='XAUUSD' else .002
    margin=margin or (20 if symbol=='XAUUSD' else 11)
    units=1 if symbol=='XAUUSD' else 1000
    base=min(max(1,math.floor(balance/100)) if symbol=='XAUUSD' else math.floor(195*(balance/100)**.0625),
        math.floor(balance*(.125 if symbol=='XAUUSD' else .2725)*scale/(units*(distance+(.05 if symbol=='XAUUSD' else .00001)))),
        math.floor(balance*(.5 if symbol=='XAUUSD' else .6)*scale/margin))
    return layer.plan(symbol,balance=balance,equity=balance,free_margin=balance,baseline_children=base,
        entry=entry,stop=entry-side*distance,target=entry+side*distance*4,margin_child=margin,
        spread=.3 if symbol=='XAUUSD' else .00012,scale=scale,now=datetime.now(UTC),
        expires_at=(datetime.now(UTC)+timedelta(hours=4)).isoformat())


def test_frozen_configuration_identity_and_tamper(tmp_path):
    for symbol,identifier in [('XAUUSD',310303),('EURUSD',572811)]:
        value=layer.manifest(symbol)
        assert value['contract']['configuration']['id']==identifier
        value['contract']['configuration']['equity_capacity_multiplier']=99
        p=tmp_path/'tamper.json';p.write_text(json.dumps(value))
        with pytest.raises(RuntimeError,match='HASH_MISMATCH'):
            layer.manifest(symbol,p)


@pytest.mark.parametrize('symbol',['XAUUSD','EURUSD'])
@pytest.mark.parametrize('balance',[50,100,200,1000,10000])
@pytest.mark.parametrize('side',[1,-1])
def test_staged_geometry_integer_children_and_equity_caps(symbol,balance,side):
    basket=make_plan(symbol,balance,side)
    c=layer.manifest(symbol)['contract']
    assert basket['planned_risk_usd']<=balance*c['risk_cap']+1e-8
    assert basket['planned_margin_usd']<=balance*c['margin_cap']+1e-8
    assert all(isinstance(r['children'],int) and r['children']>=0 for r in basket['stages'])
    assert basket['total_children']==sum(r['children'] for r in basket['stages'])
    for r in basket['stages']:
        assert side*(r['entry']-basket['sl'])>0
        if r['stage']:
            assert side*(basket['entry']-r['entry'])>0
    if symbol=='EURUSD':
        assert basket['total_children']<=math.floor(195*(balance/100)**.0625)


def test_capacity_compounds_and_respects_broker_leverage():
    assert make_plan(balance=10000)['total_children']>make_plan(balance=1000)['total_children']
    assert make_plan(balance=1000,margin=65)['total_children']<make_plan(balance=1000,margin=20)['total_children']
    assert [r['depth_r'] for r in make_plan()['stages']]==pytest.approx([0,.325,.65])
    assert [r['depth_r'] for r in make_plan('EURUSD')['stages']]==pytest.approx([0,.1347150628,.1905158689,.2333333333])


def test_native_limit_expiry_and_protection_in_request():
    expiry=datetime.now(UTC)+timedelta(minutes=15)
    prepared=CTraderExecutionGateway(FakeSession()).preflight(replace(intent(OrderType.LIMIT),expires_at=expiry),{})
    assert prepared.accepted
    request=prepared.request.request
    assert request.timeInForce==1
    assert request.expirationTimestamp==int(expiry.timestamp()*1000)
    assert request.stopLoss==1.095 and request.takeProfit==1.11
    with pytest.raises(Exception,match='expires_at'):
        replace(intent(),expires_at=expiry)


class Durable:
    def __init__(self): self.saves=[]
    def save(self,**kwargs):self.saves.append(kwargs)


def owned(symbol_id=1,label='RZXA50',identifier=1):
    return NS(positionId=identifier,orderId=identifier,tradeData=NS(symbolId=symbol_id,label=label,volume=100),stopLoss=1998,takeProfit=2008)


@pytest.mark.parametrize('reason',['ttl','flat','invalid','budget','quarantine','control'])
def test_pending_cancellation_scoped_and_no_restart_submission(reason):
    basket=make_plan();basket['initial_accepted']=basket['initial_children']
    state={'layering_basket':basket,'quarantined':reason=='quarantine'}
    ours=owned();external=owned(2,'MANUAL',2)
    orders=[ours,external];positions=[] if reason=='flat' else [owned()]
    now=datetime.now(UTC)
    if reason=='ttl':basket['add_expires_at']=(now-timedelta(seconds=1)).isoformat()
    equity=1 if reason=='budget' else 1000
    quote=NS(bid=1997 if reason=='invalid' else 2000,ask=2000.3)
    canceled=[]
    def cancel(i):canceled.append(i);orders[:]=[o for o in orders if o.orderId!=i]
    session=NS(reconcile=lambda:NS(position=positions,order=orders),cancel_order=cancel)
    gateway=NS(market_quote=lambda s:quote,account_snapshot=lambda:NS(equity=equity))
    details={};durable=Durable()
    gate=NS(assert_orders_allowed=lambda *a:(_ for _ in ()).throw(RuntimeError('control blocked'))) if reason=='control' else None
    assert layer.monitor(state,durable,session,gateway,'XAUUSD','RZXA50',1,now,details,gate=gate)
    assert canceled==[1] and orders==[external]
    if reason=='flat':assert 'layering_basket' not in state


def test_active_plan_hash_change_is_quarantined():
    state={'layering_basket':make_plan(),'quarantined':False};state['layering_basket']['policy_hash']='bad'
    session=NS(reconcile=lambda:NS(position=[owned()],order=[]))
    with pytest.raises(RuntimeError,match='HASH_MISMATCH'):
        layer.monitor(state,Durable(),session,None,'XAUUSD','RZXA50',1,datetime.now(UTC),{})
    assert state['quarantined']


def test_unknown_pending_submit_is_reserved_before_broker(monkeypatch):
    from fx_scanner.execution.policy import load_execution_policy
    basket=make_plan(balance=10000);basket['initial_accepted']=1
    state={'layering_basket':basket,'attempts':{},'quarantined':False}
    calls=[]
    class Router:
        def __init__(self,*a,**kw):pass
        def execute(self,order):
            assert state['attempts'][order.signal_id]['outcome'] is None
            assert order.order_type==OrderType.LIMIT and order.expires_at
            assert order.stop_loss==basket['sl'] and order.take_profit==basket['tp']
            calls.append(order);raise TimeoutError('broker reply lost')
    monkeypatch.setattr(layer,'ExecutionRouter',Router)
    session=NS(reconcile=lambda:NS(position=[owned()],order=[]))
    gateway=NS(position_count=lambda:1,account_snapshot=lambda:NS(equity=10000,margin_free=10000),market_quote=lambda s:NS(bid=2000,ask=2000.3))
    with pytest.raises(TimeoutError):
        layer.submit_limits(state=state,durable=Durable(),session=session,gateway=gateway,store=None,
            base_policy=load_execution_policy(None),control=NS(refresh_once=lambda:None),gate=None,
            symbol='XAUUSD',label='RZXA50',symbol_id=1,at=datetime.now(UTC),details={})
    assert len(calls)==1 and state['quarantined']
    assert next(iter(state['attempts'].values()))['outcome'] is None


def test_eur_late_child_uses_initial_basket_expiry(monkeypatch):
    from fx_scanner.demo_eurusd_frozen_dd37 import manage_exits
    now=datetime(2026,10,10,11,0,tzinfo=UTC)
    late=NS(positionId=1,tradeData=NS(label='RZEU37',openTimestamp=int((now-timedelta(minutes=10)).timestamp()*1000),volume=100000),stopLoss=1.09,takeProfit=1.14)
    called=[]
    monkeypatch.setattr('fx_scanner.demo_eurusd_frozen_dd37._close_full_position',lambda session,**kw:(called.append(kw['position_id']) or ('CLOSED','ok')))
    manage_exits(None,[late],now,{'cursor':now.isoformat(),'layering_basket':{'expires_at':now.isoformat()}})
    assert called==[1]


def test_pending_acceptance_persists_stages_and_fixed_protection(monkeypatch):
    from fx_scanner.execution.policy import load_execution_policy
    basket=make_plan(balance=10000);basket['initial_accepted']=basket['initial_children']
    state={'layering_basket':basket,'attempts':{},'quarantined':False};orders=[];calls=[]
    class Router:
        def __init__(self,*a,**kw):pass
        def execute(self,intent):
            calls.append(intent)
            o=owned(identifier=len(calls));orders.append(o)
            return NS(accepted=True,broker_order_id=str(o.orderId))
    monkeypatch.setattr(layer,'ExecutionRouter',Router)
    session=NS(reconcile=lambda:NS(position=[owned()],order=orders))
    gateway=NS(position_count=lambda:1,account_snapshot=lambda:NS(equity=10000,margin_free=10000),market_quote=lambda s:NS(bid=2000,ask=2000.3))
    details={}
    layer.submit_limits(state=state,durable=Durable(),session=session,gateway=gateway,store=None,
        base_policy=load_execution_policy(None),control=NS(refresh_once=lambda:None),gate=None,
        symbol='XAUUSD',label='RZXA50',symbol_id=1,at=datetime.now(UTC),details=details)
    assert len(calls)==sum(r['children'] for r in basket['stages'][1:])>0
    assert basket['placement_complete'] and basket['pending_accepted']==len(calls)
    assert all(x.stop_loss==basket['sl'] and x.take_profit==basket['tp'] for x in calls)
    assert all(x['outcome']=='ACCEPTED' for x in state['attempts'].values())
