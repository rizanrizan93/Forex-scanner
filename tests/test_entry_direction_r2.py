from datetime import UTC,datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
import pytest
from fx_scanner.entry_direction_r2 import runtime
from fx_scanner.entry_direction_r2.features import build_frames
from fx_scanner.entry_direction_r2.runtime_contract import validate_snapshot,CONTRACT
ROOT=Path(__file__).resolve().parents[1]

def test_frozen_ensemble_matches_research_scores():
 case=json.loads((ROOT/'tests/fixtures/entry_r2/feature_cases.json').read_text());x=pd.DataFrame(case['rows'],columns=case['columns']);scores=runtime.score(x,runtime.load_model())
 assert np.allclose(scores,case['scores'],rtol=0,atol=1e-11)
 assert runtime.manifest()['rule']['rule_id']==670 and runtime.manifest()['side']=='SELL'
 assert runtime.manifest()['metrics'][2]['accuracy']==28/65

def frame(n=16000):
 index=pd.date_range('2026-09-01',periods=n,freq='min',tz='UTC');c=100+np.sin(np.arange(n)/37)*2+np.arange(n)*.0001
 return pd.DataFrame({'open':c,'high':c+.1,'low':c-.1,'close':c+.02,'spread':.4},index=index)

def test_features_ignore_forming_high_low_close_and_future_data():
 d=frame();t=d.index[-1];events=pd.DataFrame([dict(event_i=0,style=7,entry_i=len(d)-1,side=-1,atr=2.,level=100.,trend=3,touch=len(d)-2,t=t.value//60_000_000_000,dow=t.dayofweek,minute=t.hour*60+t.minute)])
 a,_=build_frames(d,d[['close']],events);changed=d.copy();changed.loc[t,['high','low','close']]=[9000,.1,5000]
 future=d.tail(50).copy();future.index=pd.date_range(t+pd.Timedelta(minutes=1),periods=50,freq='min');changed=pd.concat([changed,future])
 b,_=build_frames(changed,changed[['close']],events)
 assert list(a)==runtime.manifest()['features'];assert np.allclose(a,b,rtol=0,atol=1e-6,equal_nan=True)

@pytest.fixture
def source(monkeypatch):
 now=pd.Timestamp('2026-11-17T09:00:10Z');idx=pd.date_range(end=now.floor('min'),periods=60001,freq='min',tz='UTC');d=pd.DataFrame({'open':100.,'high':100.1,'low':99.9,'close':100.,'spread':.4},index=idx)
 def events(frame):return np.array([(len(frame)-1,len(frame)-2,7,-1,5.,100.,3)],dtype=runtime.setups.ED)
 monkeypatch.setattr(runtime.setups,'generate',events);monkeypatch.setattr(runtime,'build_frames',lambda d,e,events:(pd.DataFrame({'value':[1.]}),events));monkeypatch.setattr(runtime,'score',lambda x,b:np.array([.7]))
 return now,d,d.tail(1000),{'bid':100.,'ask':100.4,'at':now.isoformat()}

def test_signal_is_frozen_and_not_selected_twice(source):
 now,d,e,q=source;a=runtime.evaluate(d,e,q,now=now,bundles={'test':True});assert a['status']=='TRIGGER_SELL' and a['signals_today']==1
 b=runtime.evaluate(d,e,q,now=now+pd.Timedelta(seconds=10),memory=a['memory'],bundles={'test':True});assert b['status']=='TRIGGER_SELL' and b['signals_today']==1 and a['signal']==b['signal']
 assert b['execution_authority'] is False;json.dumps(b,allow_nan=False)

def test_missing_spread_or_quote_never_triggers(source):
 now,d,e,q=source;d.loc[now.floor('min')-pd.Timedelta(minutes=1),'spread']=np.nan
 assert runtime.evaluate(d,e,q,now=now,bundles={'test':True})['status']=='WARMUP'
 q['at']=(now-pd.Timedelta(minutes=2)).isoformat();assert runtime.evaluate(d,e,q,now=now,bundles={'test':True})['status']=='WAIT_DATA'

def test_daily_limit_stays_waiting(source):
 now,d,e,q=source;p=runtime.evaluate(d,e,q,now=now,memory={'day':'2026-11-17','count':2},bundles={'test':True});assert p['status']=='WAIT_LIMIT'

def test_public_snapshot_rejects_stale_and_expired_trigger(source):
 now,d,e,q=source;p=runtime.evaluate(d,e,q,now=now,bundles={'test':True});p.pop('memory')
 assert validate_snapshot(p,now=now.to_pydatetime())['status']=='TRIGGER_SELL'
 assert validate_snapshot(p,now=(now+pd.Timedelta(seconds=55)).to_pydatetime())['direction']=='WAIT'
 with pytest.raises(ValueError,match='STALE'):validate_snapshot(p,now=(now+pd.Timedelta(minutes=3)).to_pydatetime())
 p['execution_authority']=True
 with pytest.raises(ValueError,match='CONTRACT'):validate_snapshot(p,now=now.to_pydatetime())

def test_reader_guard_and_tick_delta_decode():
 from scripts.collect_entry_direction_r2 import Reader,decode_ticks
 assert not any('Order' in n or 'RefreshToken' in n or 'Reconcile' in n for n in Reader.allowed)
 with pytest.raises(RuntimeError,match='ORDER_DISABLED'):Reader.__new__(Reader).send_new_order()
 q=[SimpleNamespace(timestamp=1700000000000,tick=200000000),SimpleNamespace(timestamp=-250,tick=199999000),SimpleNamespace(timestamp=100,tick=199998000)]
 assert decode_ticks(q)==[(1700000000000,2000.),(1699999999750,1999.99),(1699999999650,1999.98)]

def test_installer_is_resource_isolated_and_preserves_bridge():
 from operations.entry_direction_r2.install import UNIT,TIMER,BLOCK
 assert 'MemoryMax=768M' in UNIT and 'CPUQuota=30%' in UNIT and 'OnUnitInactiveSec=20' in TIMER
 assert 'alias /var/lib/rizan-entry-r2/snapshot.json' in BLOCK and 'no-store' in BLOCK
 assert 'rizan-bootstrap125-bridge.service' not in UNIT

def test_reinstall_stops_only_the_old_independent_reader(monkeypatch):
 from operations.entry_direction_r2 import install
 calls=[]
 def fake_run(args,**kwargs):
  calls.append(args)
  return SimpleNamespace(stdout='loaded\n')
 monkeypatch.setattr(install,'run',fake_run)
 install.stop_previous_reader()
 assert [args for args in calls if args[1]=='stop']==[
  ['systemctl','stop','rizan-entry-r2.timer'],
  ['systemctl','stop','rizan-entry-r2.service']]
 assert all(install.BRIDGE not in args for args in calls)

def test_dashboard_wait_has_honest_metrics_and_no_old_panels():
 from streamlit.testing.v1 import AppTest
 app=AppTest.from_string('from fx_scanner.entry_direction_r2.dashboard import render_view\nrender_view()').run()
 assert not app.exception
 assert any('63,6%' in x.value and '43,1%' in x.value for x in app.warning)
 assert any('Arah Entry R2' in x.value for x in app.subheader)

def test_legacy_navigation_routes_to_entry_without_duplicates(monkeypatch):
 import runpy
 import streamlit as st
 from streamlit.testing.v1 import AppTest
 monkeypatch.setattr(runpy,'run_path',lambda path,**kwargs:st.write('PAGE '+Path(path).name))
 app=AppTest.from_file(str(ROOT/'main.py'));app.session_state['rizan_xau_detail']='Analisis Terpadu';app.run()
 assert not app.exception;assert app.radio(key='rizan_xau_detail').value=='Arah Entry'
 for old in ['Analisis Terpadu','Checklist','Teknikal','Manual R3','Keputusan']:assert old not in app.radio(key='rizan_xau_detail').options
 assert app.radio(key='rizan_pair').options==['XAUUSD','EURUSD','Frozen V1','cBots']
 assert any('8_XAU_Entry_Direction_R2.py' in x.value for x in app.markdown)
