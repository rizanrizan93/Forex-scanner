from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace as NS
import pandas as pd
import pytest
from fx_scanner.eurusd_frozen_dd37 import (POLICY, POLICY_HASH, signal, layers, multiplier,
    features, advance_virtual, virtual_step)
from fx_scanner.execution.models import OrderIntent, OrderSide, OrderType
from fx_scanner.demo_eurusd_frozen_dd37 import DurableState, manage_exits, matching_positions

def test_frozen_parameters_and_risk_budgets():
    assert (POLICY.risk,POLICY.margin,POLICY.cap_at_100,POLICY.cap_exponent)==(.2725,.6,195,.0625)
    assert len(POLICY_HASH)==64
    for equity in (20,100,327.23,1000,12000):
        for distance in (.0005,.002,.006):
            for fast,slow in ((0,0),(-.6,0),(0,-.1),(-.6,-.1)):
                k=layers(equity,1.1,distance,fast,slow)
                scale=multiplier(fast,slow)
                assert k*1000*(distance+.00001)<=equity*.2725*scale+1e-8
                assert k*11<=equity*.6*scale+1e-8
                assert k<=195*(equity/100)**.0625
    assert multiplier(-.5,-.05)==1
    assert multiplier(-.50001,0)==.1
    assert multiplier(0,-.05001)==.625
    assert layers(100,1.1,.0005,0,0,free_margin=0)==0
    assert layers(100,1.1,.0005,0,0,margin_per_child=22)<layers(100,1.1,.0005,0,0)

def test_signal_context_body_and_session():
    at=pd.Timestamp('2026-10-09 07:00',tz='UTC')
    row=pd.Series(dict(open=1.1,high=1.101,low=1.098,close=1.1005,count=15,
        body=.5,prior_low=1.099,prior_high=1.102,atr=.0001,bias=0))
    assert signal(at,row)=={'at':at.isoformat(),'side':1,'distance':.0005}
    row['bias']=1;assert signal(at,row) is None
    row['bias']=0;assert signal(at.replace(hour=12),row) is None
    row['body']=.2;assert signal(at,row) is None
    row['body']=.5;row['count']=11;assert signal(at,row) is None

def test_virtual_stop_first_gap_and_timeout():
    at=pd.Timestamp('2026-10-09 07:00',tz='UTC')
    pending=dict(side=1,entry=1.1,distance=.001,at=at.isoformat(),last_at=at.isoformat(),last_close=1.1)
    net,exited=virtual_step(deepcopy(pending),at,NS(open=1.1,high=1.105,low=1.098,close=1.1))
    assert net==pytest.approx(-1.01)
    net,_=virtual_step(deepcopy(pending),at+pd.Timedelta(minutes=6),NS(open=1.095,high=1.1,low=1.09,close=1.099))
    assert net==pytest.approx(-5.01)
    timeout_pending={**pending,'last_at':(at+pd.Timedelta(minutes=239)).isoformat()}
    net,exited=virtual_step(timeout_pending,at+pd.Timedelta(minutes=240),NS(open=1.09,high=1.1,low=1.08,close=1.09))
    assert net==pytest.approx(-.01)
    assert pd.Timestamp(exited)==at+pd.Timedelta(minutes=239)

def test_closed_features_and_restart_ema_are_causal():
    ix=pd.date_range('2026-10-08',periods=24*60,freq='min',tz='UTC')
    raw=pd.DataFrame({'open':1.1,'high':1.1005,'low':1.0995,'close':1.1},index=ix)
    state={};f=features(raw.iloc[:700],state)
    assert f.index[-1]<=ix[699]+pd.Timedelta(minutes=1)
    records=deepcopy(state['h1_records'])
    f=features(raw.iloc[:700],state);assert state['h1_records']==records
    future=raw.copy();future.iloc[900:,future.columns.get_loc('close')]=1.1004
    a,b={},{};fa=features(raw,a);fb=features(future,b)
    pd.testing.assert_frame_equal(fa[fa.index<ix[900]],fb[fb.index<ix[900]])
    split={};features(raw.iloc[:900],split);features(raw,split)
    assert split['h1_records']==a['h1_records']

def test_virtual_result_cannot_size_same_minute_signal():
    at=pd.Timestamp('2026-10-09 07:00',tz='UTC')
    ix=pd.date_range(at,periods=2,freq='min')
    raw=pd.DataFrame({'open':1.1,'high':1.101,'low':1.099,'close':1.1},index=ix)
    f=pd.DataFrame([dict(open=1.1,high=1.101,low=1.098,close=1.1005,count=15,body=.5,
        prior_low=1.099,prior_high=1.102,atr=.0001,bias=0)],index=[at])
    state={'cursor':(at-pd.Timedelta(minutes=1)).isoformat(),'fast':0.,'slow':0.}
    advance_virtual(raw.iloc[:1],f,state)
    assert pd.Timestamp(state['virtual_exit'])==at
    old=deepcopy(state);advance_virtual(raw.iloc[:1],f,state);assert state==old

def test_high_risk_intent_is_pair_scoped():
    args=dict(signal_id='EU37:test:0',symbol='EURUSD',side=OrderSide.BUY,order_type=OrderType.MARKET,
        created_at=datetime.now(UTC),volume=.01,entry_price=1.1,stop_loss=1.09,take_profit=1.14,
        risk_pct=6,comment='DEMO_AUTO:EURUSD_DD37_FROZEN')
    OrderIntent(**args)
    with pytest.raises(Exception):OrderIntent(**{**args,'symbol':'XAUUSD'})
    with pytest.raises(Exception):OrderIntent(**{**args,'comment':'DEMO_AUTO:OTHER'})
    with pytest.raises(Exception):OrderIntent(**{**args,'risk_pct':27.26})

class FakeQuery:
    def __init__(self,db):self.db=db;self.filters={};self.update_data=None
    def select(self,*a):return self
    def eq(self,k,v):self.filters[k]=v;return self
    def insert(self,row):
        if row['worker_name'] in self.db:raise RuntimeError('duplicate')
        self.db[row['worker_name']]=deepcopy(row);return self
    def update(self,row):self.update_data=deepcopy(row);return self
    def execute(self):
        rows=[x for x in self.db.values() if all(x.get(k)==v for k,v in self.filters.items())]
        if self.update_data:
            for x in rows:x.update(self.update_data)
        return NS(data=deepcopy(rows))
class FakeClient:
    def __init__(self):self.db={}
    def table(self,*a):return FakeQuery(self.db)

def test_cas_state_lease_and_policy_hash_survive_restart():
    store=NS(client=FakeClient());now=datetime.now(UTC)
    a=DurableState(store,'123',now)
    with pytest.raises(RuntimeError,match='LEASE_BUSY'):DurableState(store,'123',now)
    a.data['fast']=-.7;a.save(release=True)
    b=DurableState(store,'123',datetime.now(UTC));assert b.data['fast']==-.7
    with pytest.raises(RuntimeError,match='CAS_CONFLICT'):a.save()
    b.data['policy_hash']='wrong';b.save(release=True)
    with pytest.raises(RuntimeError,match='HASH_MISMATCH'):DurableState(store,'123',datetime.now(UTC))

def test_position_manager_never_closes_xau_or_external_eurusd(monkeypatch):
    now=datetime.now(UTC)
    positions=[NS(positionId=1,tradeData=NS(symbolId=1,label='FXIS',openTimestamp=0,volume=100000)),
        NS(positionId=2,tradeData=NS(symbolId=2,label='MANUAL',openTimestamp=0,volume=100000)),
        NS(positionId=3,tradeData=NS(symbolId=2,label='RZEU37',openTimestamp=0,volume=100000))]
    eu=matching_positions(NS(position=positions),2);called=[]
    monkeypatch.setattr('fx_scanner.demo_eurusd_frozen_dd37._close_full_position',
        lambda session,**kw:(called.append(kw['position_id']) or ('CLOSED','ok')))
    manage_exits(None,eu,now,{'cursor':now.isoformat()})
    assert called==[3]
