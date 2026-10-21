from datetime import UTC,datetime,timedelta
from types import SimpleNamespace as N
import pandas as pd
import pytest
from fx_scanner.zone_v05 import confirmation,build_plan,blank,validate,MIN,HOUR,INF
from fx_scanner.zone_v05_quotes import spread_asof
T=pd.Timestamp('2026-01-23T09:00:00Z').value

def frames():
    m=pd.DataFrame({'timestamp':pd.to_datetime([T+i*MIN for i in range(41)],utc=True),'open':102.,'high':103.,'low':101.,'close':102.});m.loc[0,'low']=99.5
    five=pd.DataFrame({'closed_ns':[T+(i+1)*5*MIN for i in range(8)],'open':101.,'high':103.,'low':100.,'close':102.});five.loc[3,['close','high']]=[104.,104.5]
    fifteen=pd.DataFrame({'closed_ns':[T+15*MIN,T+30*MIN],'open':[100.,101.],'close':[102.,104.]})
    a=N(family=5,tf=60,lookback=20,direction=1,formed_ns=T-HOUR,low=99.,high=101.,atr=10.,strength=1.,touch_i=0,dead=INF)
    z=pd.DataFrame([dict(family=6,tf=60,direction=-1,formed_ns=T-HOUR,low=120.,high=121.,atr=10.,dead=INF)])
    return a,z,m,five,fifteen

def test_reclaim_is_not_entry_until_subsequent_m5_bos():
    a,z,m,five,fifteen=frames()
    assert confirmation(five,fifteen,T,T+15*MIN,1,101.)==(T+15*MIN,None)
    assert confirmation(five,fifteen,T,T+20*MIN,1,101.)==(T+15*MIN,T+20*MIN)

def test_entry_uses_next_open_and_old_signal_becomes_active_reference():
    a,z,m,five,fifteen=frames();en=pd.Timestamp(T+20*MIN,tz='UTC').isoformat()
    p=build_plan(a,z,m.iloc[:22],five,fifteen,T+22*MIN,{en:.3})
    assert p['state']=='ENTRY' and p['entry']==102. and p['planned_net_rr']>=1.5
    assert p['target']['low']==120. and p['tp']==119.75
    assert build_plan(a,z,m,five,fifteen,T+40*MIN,{en:.3})['state']=='AKTIF_REFERENSI'

def test_missing_spread_blocks_and_spent_target_cancels():
    a,z,m,five,fifteen=frames()
    assert build_plan(a,z,m,five,fifteen,T+22*MIN,{})['state']=='BLOCK'
    m.loc[12,'high']=121.
    assert build_plan(a,z,m,five,fifteen,T+22*MIN,{})['reason']=='TARGET_SUDAH_TERCAPAI'

def test_both_sides_same_minute_stop_first():
    a,z,m,five,fifteen=frames();en=pd.Timestamp(T+20*MIN,tz='UTC').isoformat();m.loc[21,['low','high']]=[90.,125.]
    p=build_plan(a,z,m,five,fifteen,T+22*MIN,{en:.3})
    assert p['state']=='SELESAI' and p['reason']=='SL_TERSENTUH'

def test_stale_snapshot_hides_entry_and_execution_guard():
    now=datetime.now(UTC);p=blank(now);p.update(evaluated_close_at=(now-timedelta(minutes=8)).isoformat(),plans=[{'state':'ENTRY'}])
    q=validate(p,now=now);assert not q['fresh'] and q['plans']==[]
    p['execution_authority']=True
    with pytest.raises(ValueError):validate(p,now=now)

def test_asof_quotes_reject_future_stale_crossed_truncated():
    def r(t,p,more=False):return N(tickData=[N(timestamp=t,tick=int(p*100000))],hasMore=more)
    assert spread_asof(r(9990,4000),r(9995,4000.3),10000)==pytest.approx(.3)
    assert spread_asof(r(10001,4000),r(9995,4000.3),10000) is None
    assert spread_asof(r(1,4000),r(1,4000.3),30000) is None
    assert spread_asof(r(9990,4001),r(9995,4000.3),10000) is None
    assert spread_asof(r(9990,4000,True),r(9995,4000.3),10000) is None

def test_forming_native_candle_is_excluded():
    from fx_scanner.zone_v05 import completed
    rows=[dict(timestamp='2026-01-23T09:00:00Z',open=100,high=101,low=99,close=100),dict(timestamp='2026-01-23T09:05:00Z',open=100,high=9999,low=1,close=9999)]
    assert len(completed(rows,'M5',pd.Timestamp('2026-01-23T09:06:00Z')))==1

def test_registry_preserves_formed_geometry_when_rolling_feed_changes():
    from fx_scanner.zone_v05 import preserve_registry,CONTRACT
    row=dict(formed_ns=T,direction=1,tf=60,family=5,style=0,lookback=20,low=99.,high=101.,atr=10.,strength=1.,base_ns=T,origin_eligible=True)
    prior=dict(contract=CONTRACT,node_registry=[row]);new=dict(row,low=99.01,high=101.01)
    z=preserve_registry(pd.DataFrame([new]),prior,T-HOUR)
    assert len(z)==1 and z.low.iloc[0]==99. and z.high.iloc[0]==101.


def test_sell_confirmation_requires_lower_break():
    five=pd.DataFrame({'closed_ns':[T+(i+1)*5*MIN for i in range(4)],'open':100.,'high':101.,'low':98.,'close':99.})
    five.loc[3,'close']=97.
    fifteen=pd.DataFrame({'closed_ns':[T+15*MIN],'open':[101.],'close':[99.]})
    assert confirmation(five,fifteen,T,T+20*MIN,-1,100.)==(T+15*MIN,T+20*MIN)


def test_panel_renders_watch_and_entry_as_research_without_orders():
    import json
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    now=pd.Timestamp.now(tz='UTC');a,z,m,five,fifteen=frames();en=pd.Timestamp(T+20*MIN,tz='UTC').isoformat()
    plan=build_plan(a,z,m.iloc[:22],five,fifteen,T+22*MIN,{en:.3})
    plan['confirmation_m5_at']=(now-pd.Timedelta(minutes=1)).isoformat()
    p=blank(now);p.update(evaluated_close_at=now.floor('5min').isoformat(),plans=[plan],decisions=[dict(side='BUY',result='ENTRY',reason='SYARAT_TERPENUHI')])
    source='from fx_scanner.zone_v05_dashboard import render_snapshot\nimport json\nrender_snapshot(json.loads('+repr(json.dumps(p))+'))'
    app=AppTest.from_string(source).run(timeout=15)
    assert not app.exception
    assert any('BUY · ENTRY' in x.value for x in app.markdown)
    assert any(x.label=='TP sebelum zona B' for x in app.metric)
    assert not app.button and not app.checkbox


def test_old_confirmation_is_not_presented_as_current_cost_block():
    a,z,m,five,fifteen=frames()
    p=build_plan(a,z,m,five,fifteen,T+25*HOUR,{})
    assert p['state']=='BATAL' and p['reason']=='KONFIRMASI_LAMA_LEBIH_24_JAM'


def test_fresh_direct_snapshot_does_not_require_github_api():
    from unittest.mock import patch
    from fx_scanner import zone_v05_dashboard as panel
    now=pd.Timestamp.now(tz='UTC');p=blank(now);p['evaluated_close_at']=now.floor('5min').isoformat()
    with patch.object(panel,'read_json',return_value=p),patch.object(panel,'latest_commit',side_effect=OSError('API unavailable')) as commit:
        assert panel.fetch()['fresh']
        commit.assert_not_called()


def test_consumer_expires_entry_even_when_cached_snapshot_is_within_grace():
    now=pd.Timestamp.now(tz='UTC');a,z,m,five,fifteen=frames();en=pd.Timestamp(T+20*MIN,tz='UTC').isoformat()
    plan=build_plan(a,z,m.iloc[:22],five,fifteen,T+22*MIN,{en:.3});plan['confirmation_m5_at']=(now-pd.Timedelta(minutes=6)).isoformat()
    p=blank(now);p.update(state='ENTRY',evaluated_close_at=(now-pd.Timedelta(minutes=6)).isoformat(),plans=[plan],decisions=[dict(side='BUY',result='ENTRY',reason='OK')])
    q=validate(p,now=now)
    assert q['fresh'] and q['plans'][0]['state']=='AKTIF_REFERENSI' and q['decisions'][0]['result']=='TIDAK_ENTRY'


def test_entry_open_uses_first_tick_and_only_ask_known_at_that_tick():
    from fx_scanner.zone_v05_quotes import entry_open_quote
    # Reverse-chronological delta encoding: first bid is 4000 at10005ms.
    b=N(tickData=[N(timestamp=10020,tick=400100000),N(timestamp=-15,tick=-100000)],hasMore=False)
    a=N(tickData=[N(timestamp=10015,tick=400120000),N(timestamp=-12,tick=-100000)],hasMore=False)
    p=entry_open_quote(b,a,10000,10030)
    assert p['price']==4000 and p['observed_ms']==10005 and p['spread']==pytest.approx(.2)
    b.hasMore=True
    assert entry_open_quote(b,a,10000,10030) is None


def test_missing_next_m1_requests_observed_open_quote_instead_of_waiting_one_minute():
    a,z,m,five,fifteen=frames()
    p=build_plan(a,z,m.iloc[:20],five,fifteen,T+20*MIN+5_000_000_000,{})
    assert p['state']=='WATCH' and p['open_quote_anchor']==pd.Timestamp(T+20*MIN,tz='UTC').isoformat()
